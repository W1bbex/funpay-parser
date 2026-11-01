import os
import json
import sys
from loguru import logger

# Настройка единого логгера для всех скриптов
logger.remove() # Удаляем стандартный обработчик
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)
os.makedirs("logs", exist_ok=True)
logger.add("logs/parser.log", rotation="10 MB", retention="7 days", compression="zip")

def load_proxies(base_dir=None):
    """Загружает и форматирует прокси из файлов proxies.txt и good_proxies.txt с сохранением порядка."""
    if not base_dir:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    good_path = os.path.join(base_dir, "good_proxies.txt")
    if os.path.exists(good_path) and os.path.getsize(good_path) > 0:
        target_file = good_path
    else:
        target_file = os.path.join(base_dir, "proxies.txt")
        
    seen = set()
    raw_proxies = []
    if os.path.exists(target_file):
        with open(target_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and line not in seen:
                    seen.add(line)
                    raw_proxies.append(line)
        
    formatted_proxies = []
    for p in raw_proxies:
        if not p.startswith("http") and not p.startswith("socks"):
            parts = p.split(":")
            if len(parts) == 4:
                formatted_proxies.append(f"socks5://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}")
            else:
                formatted_proxies.append(f"http://{p}")
        else:
            formatted_proxies.append(p)
            
    return formatted_proxies

def get_browser_for_proxy(proxy_url: str) -> str:
    """Возвращает фиксированный отпечаток браузера для конкретного прокси на основе его URL."""
    IMPERSONATES = ["chrome110", "chrome116", "chrome120", "edge101", "safari15_5"]
    if not proxy_url:
        return "chrome120"
    # Простой детерминированный хэш
    hash_val = sum(ord(c) for c in proxy_url)
    return IMPERSONATES[hash_val % len(IMPERSONATES)]

def hide_proxy_credentials(url: str) -> str:
    """Удаляет логин, пароль и протокол из строки прокси для безопасного вывода в лог."""
    if not url:
        return "None"
    if '@' in url:
        return url.split('@')[-1]
    parts = url.split(':')
    if len(parts) == 4 and not url.startswith(('http://', 'https://', 'socks')):
        return f"{parts[0]}:{parts[1]}"
    if '://' in url:
        clean = url.split('://')[-1]
        if '@' in clean:
            return clean.split('@')[-1]
        return clean
    return url

def atomic_write_json(filepath: str, data: dict):
    """Атомарно сохраняет JSON в файл, предотвращая потерю данных при прерывании процесса."""
    tmp_path = filepath + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_path, filepath)
    except Exception as e:
        logger.error(f"Ошибка при атомарном сохранении файла {filepath}: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def atomic_write_lines(filepath: str, lines: list):
    """Атомарно сохраняет список строк в файл."""
    tmp_path = filepath + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            for line in lines:
                f.write(line + "\n")
        os.replace(tmp_path, filepath)
    except Exception as e:
        logger.error(f"Ошибка при атомарном сохранении файла {filepath}: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
