import email
import email.policy
import os
import re
from decimal import Decimal, ROUND_HALF_UP
from bs4 import BeautifulSoup

from funpay_analytics.storage.db import get_db
from funpay_analytics.storage.raw_lake import save_raw_snapshot

def parse_mhtml(file_path):
    with open(file_path, 'rb') as f:
        file_bytes = f.read()

    msg = email.message_from_bytes(file_bytes, policy=email.policy.default)

    html_part = None
    for part in msg.walk():
        if part.get_content_type() == 'text/html':
            payload = part.get_payload(decode=True)
            if isinstance(payload, (bytes, bytearray)):
                raw_bytes = bytes(payload)
                charset = part.get_content_charset() or 'utf-8'
                try:
                    html_part = raw_bytes.decode(charset)
                except (LookupError, UnicodeDecodeError):
                    html_part = raw_bytes.decode('utf-8', errors='replace')
                break

    if not html_part:
        # Fallback: support plain .html files
        try:
            decoded = file_bytes.decode('utf-8', errors='replace')
            if '<a class="tc-item"' in decoded or '<html' in decoded.lower():
                html_part = decoded
        except Exception:
            pass

    if not html_part:
        raise ValueError("В MHTML не найдена HTML часть")

    ext = "mhtml" if str(file_path).lower().endswith(".mhtml") else "html"
    content_sha256, compressed_path = save_raw_snapshot('own_orders', file_bytes, ext)

    soup = BeautifulSoup(html_part, 'html.parser')
    return soup, content_sha256, compressed_path

_SUPPORTED_CURRENCIES = {
    "rub": "RUB",
    "rur": "RUB",
    "руб": "RUB",
    "р": "RUB",
    "usd": "USD",
    "eur": "EUR",
}

_CURRENCY_SYMBOLS = {
    "₽": "RUB",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "₴": "UAH",
    "₸": "KZT",
}


def _detect_currency(raw_text: str) -> tuple[str | None, str | None]:
    """Detect a single supported currency code or return an error description."""
    found: set[str] = set()
    for sym, code in _CURRENCY_SYMBOLS.items():
        if sym in raw_text:
            found.add(code)
    for token in re.findall(r"[a-zA-Zа-яА-ЯёЁ]+", raw_text):
        low = token.lower()
        found.add(_SUPPORTED_CURRENCIES.get(low, token.upper()))
    if not found:
        return None, "валюта не указана"
    if len(found) > 1:
        return None, f"неоднозначная валюта: {', '.join(sorted(found))}"
    code = next(iter(found))
    if code not in ("RUB", "USD", "EUR"):
        return None, f"неподдерживаемая валюта: {code}"
    return code, None


def extract_orders(soup):
    orders = []
    items = soup.find_all("a", class_="tc-item")

    for item in items:
        # Парсим ID заказа
        order_div = item.find("div", class_="tc-order")
        order_id = None
        if order_div:
            match = re.search(r'#([A-Z0-9]+)', order_div.text)
            if match:
                order_id = match.group(1)

        # Парсим реальную цену продавца через Decimal с поддержкой валют и разделителей
        price_div = item.find("div", class_="tc-seller-sum")
        real_price_minor = None
        currency = None
        currency_error = None
        if price_div:
            raw_text = price_div.text.replace('\xa0', ' ').strip()
            currency, currency_error = _detect_currency(raw_text)
            raw_num = re.sub(r'[a-zA-Zа-яА-ЯёЁ]+\.?\s*', '', raw_text).strip()
            s_cleaned = re.sub(r'[^\d.,]', '', raw_num).strip('.,')
            if s_cleaned:
                if ',' in s_cleaned and '.' in s_cleaned:
                    if s_cleaned.rfind('.') > s_cleaned.rfind(','):
                        s_cleaned = s_cleaned.replace(',', '')
                    else:
                        s_cleaned = s_cleaned.replace('.', '').replace(',', '.')
                elif ',' in s_cleaned:
                    if re.search(r"^\d{1,3}(?:,\d{3})+$", s_cleaned):
                        s_cleaned = s_cleaned.replace(',', '')
                    else:
                        s_cleaned = s_cleaned.replace(',', '.')
                elif '.' in s_cleaned:
                    if s_cleaned.count('.') > 1:
                        s_cleaned = s_cleaned.replace('.', '')
                match = re.search(r'([\d.]+)', s_cleaned)
                if match:
                    try:
                        price_val = Decimal(match.group(1))
                        real_price_minor = int((price_val * Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                    except Exception:
                        pass

        # Парсим название лота и категорию
        title = None
        category = None
        desc_div = item.find("div", class_="order-desc")
        if desc_div:
            divs = desc_div.find_all("div", recursive=False)
            if len(divs) >= 1:
                title = divs[0].text.strip()
            if len(divs) >= 2:
                category = divs[1].text.strip()

        orders.append({
            "order_id": order_id,
            "title_raw": title,
            "seller_total_minor": real_price_minor,
            "currency": currency,
            "currency_error": currency_error,
            "category_text": category
        })

    return orders

def validate_orders(orders):
    errors = []
    valid = []
    for idx, o in enumerate(orders):
        if not o.get('title_raw'):
            continue

        missing = []
        if not o.get('order_id'):
            missing.append('order_id')
        if o.get('seller_total_minor') is None:
            missing.append('seller_total_minor')
        if not o.get('category_text'):
            missing.append('category_text')

        if missing:
            errors.append(f"Заказ #{o.get('order_id', idx)}: отсутствуют обязательные поля {missing}")
        elif o.get('currency_error') or ('currency' in o and not o.get('currency')):
            reason = o.get('currency_error') or 'валюта не определена'
            errors.append(f"Заказ #{o.get('order_id', idx)}: ошибка валюты ({reason})")
        else:
            valid.append(o)

    return valid, errors

def import_orders(file_path, allow_partial=False):
    """Единая транзакция импорта. Возвращает количество добавленных записей."""
    soup, content_sha256, compressed_path = parse_mhtml(file_path)
    orders = extract_orders(soup)
    valid_orders, errors = validate_orders(orders)

    if errors and not allow_partial:
        raise ValueError(f"Найдено {len(errors)} ошибок валидации:\n" + "\n".join(errors[:10]) + ("\n..." if len(errors) > 10 else ""))

    if not valid_orders:
        return 0

    with get_db() as conn:
        try:
            cursor = conn.cursor()
            # 1. Запись в Raw Layer
            cursor.execute('''
                INSERT INTO raw_snapshots (source_type, external_id, content_sha256, compressed_path, parser_status, parser_version)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_type, external_id, content_sha256) DO UPDATE SET
                parser_status='success', compressed_path=excluded.compressed_path
            ''', ('own_orders', 'file', content_sha256, compressed_path, 'success', 'v1'))

            cursor.execute('''
                SELECT id FROM raw_snapshots
                WHERE source_type=? AND external_id=? AND content_sha256=?
            ''', ('own_orders', 'file', content_sha256))
            snapshot_row = cursor.fetchone()
            if not snapshot_row:
                raise Exception("Не удалось получить ID raw_snapshot")
            snapshot_id = snapshot_row[0]

            # 2. Запись заказов с привязкой к snapshot_id
            inserted = 0
            for order in valid_orders:
                cursor.execute('''
                    INSERT INTO own_orders (
                        order_id, seller_id, title_raw, category_text, seller_total_minor, currency, raw_snapshot_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(order_id) DO UPDATE SET
                        title_raw=excluded.title_raw,
                        category_text=excluded.category_text,
                        seller_total_minor=excluded.seller_total_minor,
                        currency=excluded.currency,
                        raw_snapshot_id=excluded.raw_snapshot_id
                ''', (
                    order['order_id'],
                    None,
                    order['title_raw'],
                    order['category_text'],
                    order['seller_total_minor'],
                    order.get('currency') or 'RUB',
                    snapshot_id
                ))
                inserted += 1

            conn.commit()
            return inserted

        except Exception as e:
            conn.rollback()
            raise e

def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Импорт собственных заказов FunPay")
    parser.add_argument("path", help="Путь к файлу .html или .mhtml")
    parser.add_argument("--allow-partial", action="store_true", help="Пропускать невалидные строки вместо срыва всей транзакции")
    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"Файл не найден: {args.path}")
        sys.exit(1)

    try:
        inserted = import_orders(args.path, allow_partial=args.allow_partial)
        print(f"Успешно импортировано {inserted} заказов.")
    except Exception as e:
        print(f"Критическая ошибка импорта: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
