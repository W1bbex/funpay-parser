import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from funpay_analytics.models import CandidateLotDict
from funpay_analytics.storage.db import get_db
from funpay_analytics.storage.raw_lake import save_raw_snapshot

def _to_price_minor(price_val) -> int:
    """Безопасно переводит цену (число или строку с валютой) в минорные единицы (копейки)."""
    if price_val is None:
        raise ValueError("Цена не может быть None")
    if isinstance(price_val, (int, float)):
        val = Decimal(str(price_val))
        return int((val * Decimal('100')).to_integral_value())
    s = str(price_val).replace('\xa0', ' ').strip()
    # Отсекаем текстовые обозначения валют и единиц с возможной точкой (руб., коп., usd.)
    s = re.sub(r'[a-zA-Zа-яА-ЯёЁ]+\.?\s*', '', s).strip()
    s_cleaned = re.sub(r'[^\d.,]', '', s).strip('.,')
    if not s_cleaned:
        raise ValueError(f"Некорректная цена: {price_val}")
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
    if not match:
        raise ValueError(f"Некорректная цена: {price_val}")
    try:
        val = Decimal(match.group(1))
        return int((val * Decimal('100')).to_integral_value())
    except (InvalidOperation, TypeError, ValueError) as e:
        raise ValueError(f"Невозможно преобразовать цену {price_val} в Decimal: {e}") from e


def import_seller_json(file_path):
    with open(file_path, 'rb') as f:
        file_bytes = f.read()

    data = json.loads(file_bytes.decode('utf-8'))

    if not isinstance(data, dict):
        raise ValueError("Ожидается JSON объект продавца (dict)")

    # 1. Валидация в памяти
    if "schema_version" in data and data["schema_version"] != 2:
        raise ValueError("Ожидается schema_version == 2")

    seller_id = data.get("seller_id")
    if not seller_id:
        raise ValueError("Отсутствует seller_id")
    try:
        seller_id = int(seller_id)
    except (TypeError, ValueError):
        raise ValueError(f"Некорректный seller_id: {seller_id}")

    username = data.get("username")
    if not username:
        raise ValueError("Отсутствует username")

    currency = data.get("currency")
    if not currency:
        raise ValueError("Отсутствует currency")

    categories = data.get("categories")
    if not categories or not isinstance(categories, dict):
        raise ValueError("Отсутствует или некорректен объект categories")

    collected_at = data.get("collected_at")
    if not collected_at:
        collected_at = datetime.now(timezone.utc).isoformat()

    # Валидация и сбор лотов
    # Один lot_id может прийти из разных категорий.
    # Нужно убедиться, что он идентичен (section, text, price, stock).
    parsed_lots: dict[int, CandidateLotDict] = {} # lot_id -> dict
    candidate_links = [] # list of (category_text, lot_id)

    parsed_reviews = []

    for cat_name, cat_data in categories.items():
        if not isinstance(cat_data, dict):
            continue
        candidate_lots = cat_data.get("candidate_lots") or []
        for lot in candidate_lots:
            lot_id = lot.get("id")
            section = lot.get("section")
            title = lot.get("text")
            price_val = lot.get("price")
            stock_val = lot.get("stock") # Can be absent or None

            if lot_id is None or title is None or price_val is None:
                raise ValueError(f"Некорректный формат лота: {lot}")

            try:
                lot_id = int(lot_id)
            except (TypeError, ValueError):
                raise ValueError(f"Некорректный ID лота: {lot_id}")

            price_minor = _to_price_minor(price_val)

            lot_dict: CandidateLotDict = {
                "id": lot_id,
                "section": section,
                "title": title,
                "price_minor": price_minor,
                "stock": stock_val,
            }

            if lot_id in parsed_lots:
                if parsed_lots[lot_id] != lot_dict:
                    raise ValueError(f"Конфликт данных для лота {lot_id} в разных категориях: {parsed_lots[lot_id]} != {lot_dict}")
            else:
                parsed_lots[lot_id] = lot_dict

            candidate_links.append((cat_name, lot_id))

        reviews = cat_data.get("reviews") or []
        for review in reviews:
            price_val = review.get("price")
            rating = review.get("rating")
            text_content = review.get("text")
            date_text_raw = review.get("date")

            if price_val is None or text_content is None or date_text_raw is None:
                raise ValueError(f"Отсутствуют обязательные поля в отзыве: {review}")
            if "rating" not in review:
                raise ValueError(f"Отсутствует поле rating в отзыве: {review}")

            price_minor = _to_price_minor(price_val)

            parsed_reviews.append({
                "rating": rating,
                "text_content": text_content,
                "seller_reply": review.get("reply"),
                "date_text_raw": date_text_raw,
                "category_text": cat_name,
                "price_minor": price_minor
            })

    # Все валидации пройдены, теперь сохраняем на диск
    content_sha256, compressed_path = save_raw_snapshot('seller_snapshot_v2', str(seller_id), file_bytes, 'json')

    with get_db() as conn:
        try:
            cursor = conn.cursor()

            # Запись в raw_snapshots
            metadata = json.dumps({"currency": currency, "collected_at": collected_at})
            cursor.execute('''
                INSERT INTO raw_snapshots (source_type, external_id, seller_id, content_sha256, compressed_path, parser_status, parser_version, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_type, external_id, content_sha256) DO UPDATE SET
                parser_status='success', compressed_path=excluded.compressed_path
            ''', ('seller_snapshot_v2', str(seller_id), seller_id, content_sha256, compressed_path, 'success', 'v2', metadata))

            cursor.execute('''
                SELECT id FROM raw_snapshots
                WHERE source_type=? AND external_id=? AND content_sha256=?
            ''', ('seller_snapshot_v2', str(seller_id), content_sha256))
            snapshot_row = cursor.fetchone()
            if not snapshot_row:
                raise Exception("Не удалось получить ID raw_snapshot")
            snapshot_id = snapshot_row[0]

            # Обновление продавца
            cursor.execute('''
                INSERT INTO sellers (id, name, last_seen_at)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, last_seen_at=excluded.last_seen_at
            ''', (seller_id, username, collected_at))

            # Вставка лотов (уникальных)
            for lot_id, lot_data in parsed_lots.items():
                cursor.execute('SELECT seller_id FROM lots WHERE id=?', (lot_id,))
                existing_lot = cursor.fetchone()
                if existing_lot and existing_lot[0] is not None and str(existing_lot[0]) != str(seller_id):
                    raise ValueError(f"Конфликт владельца: лот {lot_id} уже принадлежит продавцу {existing_lot[0]}")

                cursor.execute('''
                    INSERT INTO lots (id, seller_id, is_active)
                    VALUES (?, ?, 1)
                    ON CONFLICT(id) DO UPDATE SET is_active=1, seller_id=excluded.seller_id
                ''', (lot_id, seller_id))

                cursor.execute('''
                    INSERT INTO lot_snapshots (
                        lot_id, seller_id, native_section_name,
                        title_raw, visible_price_minor, stock, raw_snapshot_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(raw_snapshot_id, lot_id) DO UPDATE SET
                    native_section_name=excluded.native_section_name,
                    title_raw=excluded.title_raw,
                    visible_price_minor=excluded.visible_price_minor,
                    stock=excluded.stock
                ''', (lot_id, seller_id, lot_data['section'], lot_data['title'], lot_data['price_minor'], lot_data['stock'], snapshot_id))

            # Связи snapshot_candidate_lots
            for cat_name, lot_id in candidate_links:
                cursor.execute('''
                    INSERT INTO snapshot_candidate_lots (
                        raw_snapshot_id, category_text, lot_id
                    ) VALUES (?, ?, ?)
                    ON CONFLICT(raw_snapshot_id, category_text, lot_id) DO NOTHING
                ''', (snapshot_id, cat_name, lot_id))

            # Вставка отзывов
            for index, rev in enumerate(parsed_reviews):
                cursor.execute('''
                    INSERT INTO reviews (
                        raw_snapshot_id, review_index, seller_id,
                        rating, text_content, seller_reply, date_text_raw, category_text, price_minor
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(raw_snapshot_id, review_index) DO UPDATE SET
                    rating=excluded.rating, text_content=excluded.text_content,
                    seller_reply=excluded.seller_reply, date_text_raw=excluded.date_text_raw,
                    category_text=excluded.category_text, price_minor=excluded.price_minor
                ''', (
                    snapshot_id, index, seller_id,
                    rev['rating'], rev['text_content'], rev['seller_reply'], rev['date_text_raw'], rev['category_text'], rev['price_minor']
                ))

            conn.commit()
            return snapshot_id

        except Exception as e:
            conn.rollback()
            raise e
