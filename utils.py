import os
import json
import sys
import re
from typing import Any
from loguru import logger

# Настройка единого логгера для всех скриптов
logger.remove() # Удаляем стандартный обработчик
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)
if not os.environ.get("PYTEST_CURRENT_TEST"):
    _LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(_LOG_DIR, exist_ok=True)
    logger.add(os.path.join(_LOG_DIR, "parser.log"), rotation="10 MB", retention="7 days", compression="zip")

def parse_price(val) -> float:
    """Безопасно извлекает числовую цену из float, int или строки с валютой/разделителями."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    raw = str(val).replace("\xa0", " ").strip()
    if not raw:
        return 0.0
    # Отсекаем текстовые обозначения валют и единиц с возможной точкой (руб., коп., usd.)
    raw = re.sub(r'[a-zA-Zа-яА-ЯёЁ]+\.?\s*', '', raw).strip().strip('.,')
    if not raw:
        return 0.0

    # Если присутствуют оба знака (точка и запятая)
    if "," in raw and "." in raw:
        if raw.rfind(".") > raw.rfind(","):
            # Формат 1,500.50 -> запятая разделитель тысяч
            raw = raw.replace(",", "")
        else:
            # Формат 1.500,50 -> точка разделитель тысяч, запятая - десятичный
            raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        # Только запятая: проверяем, разделитель тысяч (10,000) или десятичная дробь (150,50)
        digits_and_comma = re.sub(r"[^\d,]", "", raw)
        if re.search(r"^\d{1,3}(?:,\d{3})+$", digits_and_comma):
            raw = raw.replace(",", "")
        else:
            raw = raw.replace(",", ".")
    elif "." in raw:
        # Несколько точек: 1.000.000 или 1.250.00
        digits_and_dot = re.sub(r"[^\d.]", "", raw)
        if digits_and_dot.count(".") > 1:
            parts = digits_and_dot.split(".")
            if len(parts[-1]) == 2:
                raw = "".join(parts[:-1]) + "." + parts[-1]
            else:
                raw = "".join(parts)

    cleaned = re.sub(r"[^\d.]", "", raw)
    if not cleaned:
        return 0.0
    if cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def load_proxies(base_dir=None):
    """Загружает и форматирует прокси из файлов good_proxies.txt и proxies.txt с сохранением порядка."""
    if not base_dir:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    candidate_files = []
    good_path = os.path.join(base_dir, "good_proxies.txt")
    if os.path.exists(good_path) and os.path.getsize(good_path) > 0:
        candidate_files.append(good_path)

    proxy_path = os.path.join(base_dir, "proxies.txt")
    if os.path.exists(proxy_path) and os.path.getsize(proxy_path) > 0:
        candidate_files.append(proxy_path)

    seen = set()
    raw_proxies = []
    for target_file in candidate_files:
        with open(target_file, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and line not in seen:
                    seen.add(line)
                    raw_proxies.append(line)

    formatted_proxies = []
    for p in raw_proxies:
        proto = "socks5"
        clean = p
        if p.startswith(("http://", "https://", "socks5://", "socks4://")):
            proto, clean = p.split("://", 1)

        if "@" in clean:
            formatted_proxies.append(f"{proto}://{clean}" if not p.startswith(("http://", "https://", "socks")) else p)
            continue

        parts = clean.split(":")
        if len(parts) == 4:
            if parts[3].isdigit() and ('.' in parts[2] or '.' not in parts[0]):
                # user:pass:ip:port
                user, pwd, ip, port = parts[0], parts[1], parts[2], parts[3]
            elif parts[1].isdigit():
                # ip:port:user:pass
                ip, port, user, pwd = parts[0], parts[1], parts[2], parts[3]
            elif parts[3].isdigit():
                # user:pass:ip:port
                user, pwd, ip, port = parts[0], parts[1], parts[2], parts[3]
            else:
                ip, port, user, pwd = parts[0], parts[1], parts[2], parts[3]
            formatted_proxies.append(f"{proto}://{user}:{pwd}@{ip}:{port}")
        elif len(parts) == 2 and not p.startswith(("http://", "https://", "socks")):
            formatted_proxies.append(f"http://{p}")
        else:
            formatted_proxies.append(p)

    return formatted_proxies

def get_browser_for_proxy(proxy_url: str) -> str:
    """Возвращает фиксированный отпечаток браузера для конкретного прокси на основе его URL."""
    IMPERSONATES = ["chrome110", "chrome116", "chrome120", "edge101", "chrome124"]
    if not proxy_url:
        return "chrome120"
    # Простой детерминированный хэш
    hash_val = sum(ord(c) for c in proxy_url)
    return IMPERSONATES[hash_val % len(IMPERSONATES)]

def hide_proxy_credentials(url: str) -> str:
    """Удаляет логин, пароль и протокол из строки прокси для безопасного вывода в лог."""
    if not url:
        return "None"
    clean = url.split("://")[-1]
    if "@" in clean:
        return clean.split("@")[-1]
    parts = clean.split(":")
    if len(parts) == 4:
        if parts[3].isdigit() and ('.' in parts[2] or '.' not in parts[0]):
            # user:pass:ip:port -> ip:port
            return f"{parts[2]}:{parts[3]}"
        elif parts[1].isdigit():
            # ip:port:user:pass -> ip:port
            return f"{parts[0]}:{parts[1]}"
        elif parts[3].isdigit():
            # user:pass:ip:port -> ip:port
            return f"{parts[2]}:{parts[3]}"
    return clean

def atomic_write_json(filepath: str, data: Any) -> bool:
    """Атомарно сохраняет JSON в файл с уникальным временным файлом, предотвращая гонки на Windows."""
    import secrets
    tmp_path = f"{filepath}.tmp.{secrets.token_hex(4)}"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_path, filepath)
        return True
    except Exception as e:
        logger.error(f"Ошибка при атомарном сохранении файла {filepath}: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False

def atomic_write_lines(filepath: str, lines: list) -> bool:
    """Атомарно сохраняет список строк в файл с уникальным временным файлом."""
    import secrets
    tmp_path = f"{filepath}.tmp.{secrets.token_hex(4)}"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            for line in lines:
                f.write(line + "\n")
        os.replace(tmp_path, filepath)
        return True
    except Exception as e:
        logger.error(f"Ошибка при атомарном сохранении файла {filepath}: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False

def extract_user_id(val: str) -> str | None:
    """Извлекает ID пользователя FunPay из ввода: числовой ID, ссылка или алиас."""
    if not val:
        return None
    clean = val.strip()
    if clean.isdigit():
        return clean
    m = re.search(r'users/(\d+)', clean)
    if m:
        return m.group(1)
    return None
