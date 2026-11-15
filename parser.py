import asyncio
import json
import random
import os
# Base directory resolved dynamically
import sys
import time
# from pathlib import Path
from decimal import Decimal
from urllib.parse import urlparse, parse_qs

from funpayparsers.parsers.reviews_parser import ReviewsParser
from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import math

from utils import (
    load_proxies,
    atomic_write_json,
    atomic_write_lines,
    logger,
    get_browser_for_proxy,
    hide_proxy_credentials,
    parse_price,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FUNPAY_COOKIES = {'cy': 'rub', 'locale': 'ru'}

def get_smart_delay(is_proxy=False):
    chance = random.random()
    if is_proxy:
        if chance < 0.1:
            return random.uniform(1.5, 2.5)
        else:
            return random.uniform(0.5, 1.5)
    else:
        if chance < 0.1:
            return random.uniform(4.0, 6.0)
        else:
            return random.uniform(2.0, 4.0)

def get_review_interval(price: float) -> tuple[Decimal, Decimal] | None:
    if price <= 0:
        return None
    if price % 1000 == 0 and price >= 2000:
        p = Decimal(str(price))
        return (p - Decimal('500'), p + Decimal('500'))
    elif price == 1000:
        return (Decimal('950'), Decimal('1500'))
    elif price == 100:
        return (Decimal('95'), Decimal('150'))
    elif price % 100 == 0 and price < 1000:
        p = Decimal(str(price))
        return (p - Decimal('50'), p + Decimal('50'))
    elif price % 10 == 0 and price < 100:
        p = Decimal(str(price))
        return (p - Decimal('5'), p + Decimal('5'))
    return None

def is_candidate(lot_price: float, lower: Decimal, upper: Decimal) -> bool:
    if lot_price <= 0:
        return False
    lp = Decimal(str(lot_price))
    q_min = max(Decimal('1'), math.ceil(lower / lp))
    return (lp * q_min) < upper

def parse_lot_price(price_div) -> float:
    if not price_div:
        return 0.0
    text = getattr(price_div, "text", str(price_div))
    return parse_price(text)

def extract_profile_lots(soup: BeautifulSoup, user_id: str) -> list[dict]:
    """Извлекает активные лоты продавца со страницы профиля."""
    active_lots = []
    for mb20 in soup.find_all('div', class_='mb20'):
        for offer in mb20.find_all('div', class_='offer'):
            title_div = offer.find('div', class_='offer-list-title')
            if not title_div:
                continue
            section_name = title_div.text.strip().replace('\n', ' ')

            for a in offer.find_all('a', class_='tc-item'):
                href = a.get('href', '')
                parsed_url = urlparse(href)
                qs = parse_qs(parsed_url.query)
                lot_id = qs.get('id', [''])[0]
                if not lot_id.isdigit():
                    m = re.search(r'id=(\d+)', href)
                    lot_id = m.group(1) if m else ""

                if not lot_id:
                    logger.warning(f"[ID {user_id}] Пропущен лот без ID (href: {href})")
                    continue

                price_div = a.find('div', class_='tc-price')
                price = parse_lot_price(price_div)

                if price <= 0:
                    logger.warning(f"[ID {user_id}] Пропущен лот с некорректной ценой (ID: {lot_id})")
                    continue

                title_elem = a.find('div', class_='tc-desc')
                title = title_elem.text.strip() if title_elem else "Лот"

                amount_div = a.find('div', class_='tc-amount')
                stock = None
                if amount_div:
                    amount_str = re.sub(r'[^\d]', '', amount_div.text)
                    if amount_str:
                        stock = int(amount_str)

                active_lots.append({
                    'id': lot_id,
                    'section': section_name,
                    'text': title,
                    'price': price,
                    'stock': stock
                })
    return active_lots


async def fetch_seller_reviews(client: requests.AsyncSession, user_id: str, actual_user_id: str,
                               initial_batch, headers: dict, proxy: str = None,
                               max_reviews: int = None) -> tuple[dict, int] | None:
    """Выполняет пагинацию и сбор отзывов продавца."""
    total_reviews = 0
    categories_reviews = {}

    def process_batch(batch_reviews):
        nonlocal total_reviews
        count = 0
        for review in batch_reviews:
            if max_reviews is not None and total_reviews >= max_reviews:
                break
            date = (review.date_text or "").strip()
            category = review.category_str or "Неизвестно"
            price_val = float(review.order_total.value) if review.order_total else 0.0

            if category not in categories_reviews:
                categories_reviews[category] = []

            categories_reviews[category].append({
                'price': price_val,
                'rating': review.rating,
                'text': review.text or "",
                'reply': review.reply,
                'date': date
            })
            total_reviews += 1
            count += 1
        return count

    process_batch(initial_batch.reviews)
    next_id = initial_batch.next_review_id
    page = 2

    while next_id:
        if max_reviews is not None and total_reviews >= max_reviews:
            logger.info(f"[ID {user_id}] Достигнут запрошенный лимит {max_reviews:,} отзывов. Завершаем сбор.")
            break

        post_data = {
            'user_id': actual_user_id,
            'continue': next_id,
            'filter': ''
        }

        post_headers = headers.copy()
        post_headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'

        success = False
        for attempt in range(4):
            await asyncio.sleep(get_smart_delay(bool(proxy)))
            try:
                r2 = await client.post('https://funpay.com/users/reviews', data=post_data, headers=post_headers, cookies=FUNPAY_COOKIES)
                if r2.status_code == 429:
                    raise Exception("429 Too Many Requests")
                r2.raise_for_status()
                html_text2 = r2.text
                success = True
                break
            except Exception as e:
                if "429" in str(e):
                    if attempt < 3:
                        delay = (attempt + 1) * 15
                        logger.warning(f"[ID {user_id}] Блок 429 на стр {page}. Ждем {delay}с (Попытка {attempt+1}/4)...")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"[ID {user_id}] Исчерпаны попытки пагинации на стр {page} (429): {e}")
                        break
                else:
                    if attempt < 3:
                        delay = (attempt + 1) * 2
                        logger.warning(f"[ID {user_id}] Временная ошибка пагинации на стр {page} (попытка {attempt+1}/4): {e}. Повтор через {delay}с...")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"[ID {user_id}] Исчерпаны попытки пагинации на стр {page}: {e}")
                        break

        if not success:
            logger.error(f"[ID {user_id}] Не удалось пройти страницу {page} после 4 попыток. Отменяем.")
            return None

        try:
            next_batch = ReviewsParser(html_text2).parse()
        except Exception as e:
            logger.error(f"[ID {user_id}] Ошибка разбора структуры отзывов на стр {page}: {e}")
            return None
        added = process_batch(next_batch.reviews)

        if page % 5 == 0 or (max_reviews is not None and total_reviews >= max_reviews):
            logger.info(f"[ID {user_id}] Собрано {total_reviews:,} отзывов (страница {page})...")

        if added == 0 or (max_reviews is not None and total_reviews >= max_reviews):
            break

        next_id = next_batch.next_review_id
        page += 1

    return categories_reviews, total_reviews


def match_and_filter_lots(all_active_lots: list[dict], categories_reviews: dict) -> dict:
    """Сопоставляет активные лоты с категориями отзывов и выполняет ценовую фильтрацию."""
    categories = {}
    known_review_categories = list(categories_reviews.keys())

    for cat in known_review_categories:
        categories[cat] = {'reviews': categories_reviews[cat], 'candidate_lots': []}

    def normalize_cat(c):
        return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', '', c)).casefold().strip()

    for lot in all_active_lots:
        sec_norm = normalize_cat(lot['section'])
        matches = []
        for rc in known_review_categories:
            norm_rc = normalize_cat(rc)
            if norm_rc:
                if norm_rc in sec_norm:
                    matches.append(rc)
            elif rc.strip() and rc.strip().casefold() in lot['section'].casefold():
                matches.append(rc)

        if matches:
            matched_cat = max(matches, key=len)
            categories[matched_cat]['candidate_lots'].append(lot)

    for cat_name, data in categories.items():
        reviews = data['reviews']
        lots = data['candidate_lots']
        filtered_lots = []

        intervals = []
        disable_filtering = False

        for r in reviews:
            iv = get_review_interval(r['price'])
            if iv is None:
                disable_filtering = True
                break
            intervals.append(iv)

        if disable_filtering:
            filtered_lots = lots.copy()
        else:
            for lot in lots:
                is_valid = False
                for lower, upper in intervals:
                    if is_candidate(lot['price'], lower, upper):
                        is_valid = True
                        break
                if is_valid:
                    filtered_lots.append(lot)

        data['candidate_lots'] = filtered_lots

    return categories


async def parse_profile(client: requests.AsyncSession, user_id: str, proxy: str = None, user_agent: str = None, max_reviews: int = None) -> dict:
    if not user_agent:
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    url = f"https://funpay.com/users/{user_id}/"
    headers = {
        'User-Agent': user_agent,
        'X-Requested-With': 'XMLHttpRequest',
        'Sec-Ch-Ua': '"Not.A/Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8'
    }

    masked_p = hide_proxy_credentials(proxy) if proxy else None
    proxy_info = f" (через прокси {masked_p})" if masked_p else " (напрямую без прокси)"
    logger.info(f"[ID {user_id}] Начинаем парсинг{proxy_info}...")

    html_text = None
    for attempt in range(2):
        try:
            response = await client.get(url, headers=headers, cookies=FUNPAY_COOKIES)
            if response.status_code == 429:
                raise Exception("429 Too Many Requests")
            response.raise_for_status()
            html_text = response.text
            break
        except Exception as e:
            err_msg = str(e)
            if "curl: (35)" in err_msg or "TLS connect error" in err_msg:
                logger.error(f"[ID {user_id}] Ошибка TLS (35): Соединение с FunPay сброшено/заблокировано (ТСПУ / Cloudflare). Требуется рабочий прокси.")
                return None
            if "429" in err_msg and attempt < 1:
                logger.warning(f"[ID {user_id}] Блок 429 на профиле. Пауза 5с перед повтором...")
                await asyncio.sleep(5.0)
                continue
            logger.error(f"[ID {user_id}] Ошибка доступа: {e}")
            return None

    if not html_text:
        return None

    soup = BeautifulSoup(html_text, 'html.parser')
    username_elem = soup.find('span', class_='mr4')
    if not username_elem:
        logger.error(f"[ID {user_id}] Ошибка парсинга: не удалось извлечь никнейм пользователя.")
        return None
    username = username_elem.text.strip()

    all_active_lots = extract_profile_lots(soup, user_id)
    try:
        batch = ReviewsParser(html_text).parse()
    except Exception as e:
        logger.error(f"[ID {user_id}] Ошибка разбора структуры профиля: {e}")
        return None
    actual_user_id = batch.user_id if batch.user_id else user_id

    review_res = await fetch_seller_reviews(client, user_id, actual_user_id, batch, headers, proxy=proxy, max_reviews=max_reviews)
    if review_res is None:
        return None
    categories_reviews, total_reviews = review_res

    categories = match_and_filter_lots(all_active_lots, categories_reviews)

    logger.success(f"[ID {user_id}] Готово! Собрано отзывов: {total_reviews}.")

    return {
        'schema_version': 2,
        'seller_id': user_id,
        'username': username,
        'currency': 'RUB',
        'total_reviews': total_reviews,
        'categories': categories
    }

async def ping_proxy_curl(proxy_url: str, sem: asyncio.Semaphore) -> dict:
    """Пингует прокси с использованием curl_cffi."""
    try:
        async with sem:
            proxies = {"http": proxy_url, "https": proxy_url}
            browser = get_browser_for_proxy(proxy_url)
            start = time.time()
            async with requests.AsyncSession(proxies=proxies, impersonate=browser, timeout=10.0) as session:
                resp = await session.get("https://funpay.com", cookies=FUNPAY_COOKIES)
                if resp.status_code == 200:
                    return {'url': proxy_url, 'ping': time.time() - start, 'name': hide_proxy_credentials(proxy_url)}
    except (asyncio.CancelledError, KeyboardInterrupt):
        raise
    except Exception:
        pass
    return None

async def ping_and_rank(proxy_list: list) -> list:
    logger.info("[Этап 1] Калибровка прокси-серверов...")
    sem = asyncio.Semaphore(150)
    tasks = [asyncio.create_task(ping_proxy_curl(p, sem)) for p in proxy_list]
    try:
        results = await asyncio.gather(*tasks)
    except (asyncio.CancelledError, KeyboardInterrupt):
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    valid = [r for r in results if r is not None and r['ping'] <= 10.0]
    valid.sort(key=lambda x: x['ping'])
    valid.append({'url': None, 'ping': 999.0, 'name': 'Родной IP'})

    logger.info(f"Отбор прошли {len(valid)-1} прокси.")
    for i, v in enumerate(valid):
        ping_str = f"{v['ping']:.2f}c" if v['ping'] < 900 else "N/A"
        logger.info(f"  {i+1}. {v['name']} - Пинг: {ping_str}")

    return valid

async def parse_worker(worker_id: int, ip_name: str, proxy_url: str, queue: asyncio.Queue, results: list, library: dict, stats: dict, retry_map: dict = None, active_workers: list = None):
    if retry_map is None:
        retry_map = {}
    if active_workers is None:
        active_workers = [0]
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]
    ua = random.choice(user_agents)

    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    consecutive_errors = 0

    browser = get_browser_for_proxy(proxy_url)

    async with requests.AsyncSession(proxies=proxies, impersonate=browser, timeout=25.0, cookies=FUNPAY_COOKIES) as client:
        while True:
            try:
                user_id = queue.get_nowait()
            except asyncio.QueueEmpty:
                if active_workers[0] == 0:
                    break
                try:
                    user_id = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    if active_workers[0] == 0 and queue.empty():
                        break
                    continue

            active_workers[0] += 1
            logger.debug(f"[Воркер {worker_id} | IP: {ip_name}] Взял в работу продавца {user_id}")
            start_time = time.time()
            try:
                res = await parse_profile(client, user_id, proxy=proxy_url, user_agent=ua)
            except Exception as e:
                logger.error(f"[Воркер {worker_id} | IP: {ip_name}] Неожиданная ошибка при парсинге {user_id}: {e}")
                res = None
            elapsed = time.time() - start_time

            written = False
            if res:
                reviews = res.get('total_reviews', 0)
                rps = reviews / elapsed if elapsed > 0 else 0
                logger.info(f"[ID {user_id}] ⚡ Скорость: {rps:.1f} о/с (Всего: {elapsed:.1f} с)")

                reports_dir = os.path.join(BASE_DIR, 'reports_v2')
                await asyncio.to_thread(os.makedirs, reports_dir, exist_ok=True)
                report_path = os.path.join(reports_dir, f'seller_{user_id}.json')
                written = bool(await asyncio.to_thread(atomic_write_json, report_path, res))
                if written:
                    library[user_id] = {
                        'status': 'completed',
                        'reviews': reviews
                    }
                    consecutive_errors = 0
                    stats['parsed_count'] += 1
                    stats['total_reviews'] += reviews
                    p_url = proxy_url if proxy_url else 'Локальный IP'
                    stats['proxy_success'][p_url] = stats['proxy_success'].get(p_url, 0) + 1
                else:
                    logger.error(f"[Воркер {worker_id} | IP: {ip_name}] Ошибка записи файла отчета reports_v2/seller_{user_id}.json")

            if not res or not written:
                consecutive_errors += 1
                retries = retry_map.get(user_id, 0) + 1
                retry_map[user_id] = retries
                if retries < 3:
                    logger.warning(f"[Воркер {worker_id} | IP: {ip_name}] Ошибка (попытка {retries}/3). Возвращаем продавца {user_id} в очередь.")
                    queue.put_nowait(user_id)
                else:
                    logger.error(f"[Воркер {worker_id} | IP: {ip_name}] Продавец {user_id} превысил лимит попыток ({retries}). Пропускаем.")
                    library[user_id] = {'status': 'failed', 'error': 'max_retries_exceeded'}
                    stats['failed_count'] = stats.get('failed_count', 0) + 1
                stats['errors'] += 1

            active_workers[0] -= 1
            queue.task_done()

            if consecutive_errors >= 3:
                logger.error(f"[Воркер {worker_id} | IP: {hide_proxy_credentials(proxy_url)}] Слишком много ошибок подряд (3). Воркер отключается. (Осталось в очереди: {queue.qsize()})")
                break

            if not queue.empty():
                if proxy_url:
                    await asyncio.sleep(random.uniform(1.0, 2.0))
                else:
                    await asyncio.sleep(random.uniform(3.0, 5.0))

async def background_library_saver(library: dict, lock: asyncio.Lock = None):
    """Фоновая задача для периодического сохранения library_v2.json"""
    while True:
        await asyncio.sleep(30)
        if lock:
            async with lock:
                lib_copy = library.copy()
        else:
            lib_copy = library.copy()
        saved = await asyncio.to_thread(atomic_write_json, os.path.join(BASE_DIR, 'library_v2.json'), lib_copy)
        if saved:
            logger.debug("Фоновое сохранение library_v2.json выполнено.")
        else:
            logger.warning("Фоновое сохранение library_v2.json не удалось.")

async def mass_parse(library: dict, stats: dict):
    queue_path = os.path.join(BASE_DIR, "queue.txt")
    if not os.path.exists(queue_path):
        logger.error("Файл queue.txt не найден! Сначала запустите fetch_ids.py")
        return

    all_sellers_dict = {}
    with open(queue_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(':')
            uid = parts[0].strip()
            if not uid.isdigit():
                continue
            count = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip().isdigit() else 0
            all_sellers_dict[uid] = count

    all_sellers = [{'uid': u, 'count': c} for u, c in all_sellers_dict.items()]

    atomic_write_lines(queue_path, [f"{s['uid']}:{s['count']}" for s in all_sellers])

    logger.info(f"Загружено {len(all_sellers)} продавцов из очереди.")

    top_ids = [s for s in all_sellers if library.get(s['uid'], {}).get('status') != 'completed']
    logger.info(f"К парсингу (осталось): {len(top_ids)} чел.")

    if not top_ids:
        logger.info("Все продавцы из очереди уже успешно спарсены!")
        return

    top_ids.sort(key=lambda x: x['count'], reverse=True)
    logger.info("Топ 10 следующих к парсингу:")
    for s in top_ids[:10]:
        logger.info(f"  ID {s['uid']} - {s['count']} отзывов")

    results = []
    proxy_list = load_proxies()

    available_ips = await ping_and_rank(proxy_list)

    logger.info("[Этап 2] Умное распределение задач...")
    queue = asyncio.Queue()
    for s in top_ids:
        queue.put_nowait(s['uid'])

    save_lock = asyncio.Lock()
    saver_task = asyncio.create_task(background_library_saver(library, lock=save_lock))

    retry_map = {}
    active_workers = [0]
    workers = []
    for i, ip_info in enumerate(available_ips):
        if queue.empty():
            break

        worker_task = asyncio.create_task(
            parse_worker(i+1, ip_info['name'], ip_info['url'], queue, results, library, stats, retry_map, active_workers)
        )
        workers.append(worker_task)

    try:
        await asyncio.gather(*workers)
    except (asyncio.CancelledError, KeyboardInterrupt):
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise
    finally:
        saver_task.cancel()
        try:
            await saver_task
        except asyncio.CancelledError:
            pass
        async with save_lock:
            lib_final = library.copy()
            await asyncio.to_thread(atomic_write_json, os.path.join(BASE_DIR, 'library_v2.json'), lib_final)

    if not queue.empty():
        unprocessed = queue.qsize()
        stats['unprocessed_count'] = unprocessed
        logger.error(f"[ОШИБКА ОЧЕРЕДИ] Все воркеры отключились из-за ошибок, в очереди осталось {unprocessed} необработанных задач! Парсинг не завершён.")
    else:
        stats['unprocessed_count'] = 0

    return results

async def main_async():
    logger.info("=== ЗАПУСК МАССОВОГО ПАРСЕРА ===")

    library_path = os.path.join(BASE_DIR, 'library_v2.json')
    library = {}
    if os.path.exists(library_path):
        try:
            with open(library_path, encoding='utf-8') as f:
                loaded = json.load(f)
                if not isinstance(loaded, dict):
                    raise ValueError(f"Ожидается словарь (dict), получен {type(loaded).__name__}")
                library = loaded
        except json.decoder.JSONDecodeError as e:
            logger.error(f"Ошибка загрузки library_v2.json: {e}. Создается бэкап и начинается новая база.")
            os.replace(library_path, library_path + ".bak")
            library = {}
        except Exception as e:
            logger.error(f"Не удалось безопасно прочитать {library_path}: {e}. Операция остановлена во избежание потери данных.")
            return False

    stats = {'parsed_count': 0, 'total_reviews': 0, 'errors': 0, 'failed_count': 0, 'proxy_success': {}}
    global_start = time.time()
    interrupted = False

    try:
        await mass_parse(library, stats)
    except (KeyboardInterrupt, asyncio.CancelledError):
        interrupted = True
        logger.warning("Парсинг прерван пользователем (Ctrl+C). Прогресс сохранен.")
        await asyncio.to_thread(atomic_write_json, library_path, library)
    finally:
        global_elapsed = time.time() - global_start
        cat_counts = {}

        reports_dir = os.path.join(BASE_DIR, 'reports_v2')
        if os.path.exists(reports_dir):
            summary = []
            files = await asyncio.to_thread(os.listdir, reports_dir)
            for file in files:
                if file.endswith('.json'):
                    try:
                        with open(os.path.join(reports_dir, file), encoding='utf-8') as f:
                            res = json.load(f)
                            if isinstance(res, dict):
                                for cat, data in (res.get('categories') or {}).items():
                                    cat_c = len((data or {}).get('reviews', []))
                                    cat_counts[cat] = cat_counts.get(cat, 0) + cat_c
                                summary.append(res)
                    except Exception as e:
                        logger.error(f"Ошибка чтения отчета {file}: {e}")

            summary.sort(key=lambda x: (x.get('total_reviews') or 0), reverse=True)
            await asyncio.to_thread(atomic_write_json, os.path.join(BASE_DIR, 'market_report_v2.json'), summary)
            await asyncio.to_thread(atomic_write_json, os.path.join(BASE_DIR, 'market_report.json'), summary)

        mins = int(global_elapsed // 60)
        secs = int(global_elapsed % 60)
        avg_speed = stats['total_reviews'] / global_elapsed if global_elapsed > 0 else 0

        best_proxy = "Нет данных"
        if stats.get('proxy_success'):
            best_proxy = max(stats['proxy_success'].items(), key=lambda x: x[1])[0]

        best_cat_count = "Нет данных"
        if cat_counts:
            b_cat_c = max(cat_counts.items(), key=lambda x: x[1])
            best_cat_count = f"{b_cat_c[0]} ({b_cat_c[1]} отз.)"

        logger.info("========================================")
        logger.info("=== ИТОГОВАЯ СТАТИСТИКА ПАРСИНГА ===")
        logger.info("========================================")
        logger.info(f"Время сессии:                  {mins}м {secs}с")
        logger.info(f"Пропарсено продавцов:          {stats['parsed_count']}")
        logger.info(f"Собрано отзывов:               {stats['total_reviews']}")
        logger.info(f"Количество ошибок:             {stats['errors']}")
        logger.info(f"Средняя скорость:              {avg_speed:.1f} о/с")
        logger.info(f"Самая отзывчивая категория:    {best_cat_count}")
        logger.info(f"Самый стабильный прокси:       {hide_proxy_credentials(best_proxy)}")
        if stats.get('unprocessed_count', 0) > 0:
            logger.error(f"Необработанных продавцов (сбой воркеров): {stats['unprocessed_count']}")
        logger.info("========================================")
    if interrupted:
        return False
    if stats.get('unprocessed_count', 0) > 0:
        return False
    if stats.get('failed_count', 0) > 0 and stats.get('parsed_count', 0) == 0:
        return False
    return True

def main():
    success = asyncio.run(main_async())
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
