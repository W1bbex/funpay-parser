import os
import asyncio
import math
import random
import re
from bs4 import BeautifulSoup
from curl_cffi import requests
from utils import logger, atomic_write_lines, load_proxies, get_browser_for_proxy

def get_rmthub_proxies(all_proxies, base_dir):
    good_path = os.path.join(base_dir, "good_rmthub.txt")
    bad_path = os.path.join(base_dir, "bad_rmthub.txt")
    good_proxies = set()
    bad_proxies = set()
    if os.path.exists(good_path):
        with open(good_path, encoding="utf-8") as f:
            good_proxies.update(line.strip() for line in f if line.strip())
    if os.path.exists(bad_path):
        with open(bad_path, encoding="utf-8") as f:
            bad_proxies.update(line.strip() for line in f if line.strip())

    good_proxies = {p for p in good_proxies if p in all_proxies}
    pool = [p for p in all_proxies if p not in bad_proxies]
    return pool, good_proxies, bad_proxies

def mark_proxy(proxy, status, base_dir, good_proxies, bad_proxies, pool, proxy_errors=None, permanent=False):
    if not proxy:
        return
    if status == 'good':
        was_bad = proxy in bad_proxies
        bad_path = os.path.join(base_dir, "bad_rmthub.txt")
        good_path = os.path.join(base_dir, "good_rmthub.txt")
        if was_bad:
            updated_bad = sorted(bad_proxies - {proxy})
            if atomic_write_lines(bad_path, updated_bad):
                bad_proxies.discard(proxy)
        if proxy not in good_proxies:
            updated_good = sorted(good_proxies | {proxy})
            if atomic_write_lines(good_path, updated_good):
                good_proxies.add(proxy)
        if proxy_errors is not None:
            proxy_errors.pop(proxy, None)
    elif status == 'bad':
        good_proxies.discard(proxy)
        if proxy_errors is not None:
            err_count = proxy_errors.get(proxy, 0) + 1
            proxy_errors[proxy] = err_count
            should_ban = permanent or err_count >= 3
        else:
            should_ban = True

        if should_ban:
            if proxy in pool:
                try:
                    pool.remove(proxy)
                except ValueError:
                    pass
            if proxy not in bad_proxies:
                bad_path = os.path.join(base_dir, "bad_rmthub.txt")
                updated_bad = sorted(bad_proxies | {proxy})
                if atomic_write_lines(bad_path, updated_bad):
                    bad_proxies.add(proxy)

async def fetch_page(page: int, pool: list, good_proxies: set, bad_proxies: set, base_dir: str, sem: asyncio.Semaphore = None, proxy_errors: dict = None) -> list:
    url = f"https://rmthub.com/ru/funpay?category=top_sellers&filter=all_time&page={page}"

    for attempt in range(1, 4):
        proxy_url = None
        if good_proxies:
            available_good = [p for p in good_proxies if p in pool]
            if available_good:
                proxy_url = random.choice(available_good)
        if not proxy_url and pool:
            proxy_url = random.choice(pool)

        browser = get_browser_for_proxy(proxy_url) if proxy_url else "chrome120"
        proxies_dict = {"http": proxy_url, "https": proxy_url} if proxy_url else None

        try:
            async with requests.AsyncSession(proxies=proxies_dict, impersonate=browser, timeout=8.0) as session:
                resp = await session.get(url)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    links = soup.find_all('a', href=re.compile(r'^/ru/funpay/\d+$'))
                    if not links:
                        logger.warning(f"Страница {page} вернула 200 OK, но не содержит ссылок продавцов (капча/Cloudflare). Попытка {attempt}/3...")
                        if proxy_url:
                            await asyncio.to_thread(mark_proxy, proxy_url, 'bad', base_dir, good_proxies, bad_proxies, pool, proxy_errors, False)
                        await asyncio.sleep(0.5)
                        continue

                    if proxy_url:
                        await asyncio.to_thread(mark_proxy, proxy_url, 'good', base_dir, good_proxies, bad_proxies, pool, proxy_errors, False)

                    user_ids = []
                    for a in links:
                        uid = a['href'].split('/')[-1]
                        chips = a.find_all('span', class_=re.compile(r'MuiChip-label'))
                        val = 0
                        if chips:
                            val_str = chips[-1].text
                            val_clean = re.sub(r'\D', '', val_str)
                            if val_clean:
                                val = int(val_clean)
                        user_ids.append((uid, val))

                    logger.info(f"Страница {page} успешно загружена (Найдено {len(user_ids)} чел)")
                    return user_ids
                elif resp.status_code == 403:
                    if proxy_url:
                        await asyncio.to_thread(mark_proxy, proxy_url, 'bad', base_dir, good_proxies, bad_proxies, pool, proxy_errors, True)
                    logger.warning(f"Страница {page} заблокирована {resp.status_code} (Попытка {attempt}/3)")
                elif resp.status_code == 429:
                    if proxy_url:
                        await asyncio.to_thread(mark_proxy, proxy_url, 'bad', base_dir, good_proxies, bad_proxies, pool, proxy_errors, False)
                    logger.warning(f"Страница {page} заблокирована 429 Too Many Requests (Попытка {attempt}/3)")
                else:
                    if proxy_url:
                        await asyncio.to_thread(mark_proxy, proxy_url, 'bad', base_dir, good_proxies, bad_proxies, pool, proxy_errors, False)
                    logger.warning(f"Страница {page} получила статус {resp.status_code} (Попытка {attempt}/3)")
        except Exception as e:
            if proxy_url:
                await asyncio.to_thread(mark_proxy, proxy_url, 'bad', base_dir, good_proxies, bad_proxies, pool, proxy_errors, False)
            logger.debug(f"Ошибка при загрузке страницы {page} (попытка {attempt}/3): {e}")

        await asyncio.sleep(0.5)

    logger.error(f"❌ Страница {page} не загрузилась после 3 попыток.")
    return []

async def worker(queue: asyncio.Queue, pool: list, good_proxies: set, bad_proxies: set, base_dir: str, results: list, failed_pages: list, proxy_errors: dict):
    while True:
        try:
            page = queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        ids = await fetch_page(page, pool, good_proxies, bad_proxies, base_dir, proxy_errors=proxy_errors)
        if ids:
            results.append(ids)
        else:
            failed_pages.append(page)

        queue.task_done()

async def main(target_count: int = None, use_failed_only: bool = False):
    logger.info("=== ЗАПУСК ПАРСИНГА ОЧЕРЕДИ С RMTHUB ===")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    failed_file = os.path.join(base_dir, "failed_pages.txt")

    pages_to_load = []

    if os.path.exists(failed_file) and (target_count is None or use_failed_only):
        with open(failed_file, encoding="utf-8") as f:
            saved_fails = [int(line.strip()) for line in f if line.strip().isdigit()]
        if saved_fails and use_failed_only:
            pages_to_load = saved_fails
            logger.info(f"Будут перепаршены только пропущенные страницы: {pages_to_load}")

    if not pages_to_load:
        if target_count is None:
            try:
                ans = await asyncio.to_thread(input, "Сколько топ-продавцов вы хотите собрать с RMTHub? (Например: 200): ")
                target_count = int(ans) if ans.strip().isdigit() else 200
            except Exception:
                target_count = 200

        pages_to_fetch = max(1, math.ceil(target_count / 20))
        pages_to_load = list(range(1, pages_to_fetch + 1))
        logger.info(f"Стягиваем {pages_to_fetch} страниц (Топ-{target_count}) в пуле воркеров...")

    all_proxies = load_proxies()
    pool, good_proxies, bad_proxies = get_rmthub_proxies(all_proxies, base_dir)

    if not pool and not good_proxies:
        logger.warning("Внимание: рабочие прокси не найдены, используем локальный IP.")
    else:
        logger.info(f"Загружено {len(pool) + len(good_proxies)} прокси ({len(good_proxies)} проверенных для RMTHub). Начинаем сбор...")

    queue_path = os.path.join(base_dir, "queue.txt")

    all_ids = {}
    if os.path.exists(queue_path):
        with open(queue_path, encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str and not line_str.startswith('#'):
                    parts = line_str.split(':')
                    uid = parts[0].strip()
                    if uid.isdigit():
                        count = int(parts[1].strip()) if len(parts) == 2 and parts[1].strip().isdigit() else 0
                        all_ids[uid] = count

    queue = asyncio.Queue()
    for page in pages_to_load:
        queue.put_nowait(page)

    results = []
    failed_pages = []
    proxy_errors = {}

    num_workers = min(15, len(pool) + len(good_proxies) if (pool or good_proxies) else 5)
    workers = [asyncio.create_task(worker(queue, pool, good_proxies, bad_proxies, base_dir, results, failed_pages, proxy_errors)) for _ in range(num_workers)]

    await asyncio.gather(*workers)

    for ids in results:
        for uid, count in ids:
            all_ids[uid] = count

    logger.info(f"Собрано уникальных продавцов в очереди: {len(all_ids)}")

    if failed_pages:
        logger.warning(f"Неудачные страницы: {len(failed_pages)} шт.")
        if atomic_write_lines(failed_file, [str(p) for p in failed_pages]):
            logger.info(f"Неудачные страницы сохранены в failed_pages.txt ({len(failed_pages)} шт).")
        else:
            logger.error("Не удалось записать failed_pages.txt!")
    else:
        logger.success("Все запрошенные страницы успешно обработаны!")
        if os.path.exists(failed_file):
            try:
                os.remove(failed_file)
            except OSError:
                pass

    lines_to_write = [f"{uid}:{count}" for uid, count in sorted(all_ids.items(), key=lambda x: x[1], reverse=True)]
    if atomic_write_lines(queue_path, lines_to_write):
        logger.success(f"Сохранено в queue.txt ({len(all_ids)} продавцов)!")
    else:
        logger.error(f"Не удалось сохранить очередь в {queue_path}!")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
