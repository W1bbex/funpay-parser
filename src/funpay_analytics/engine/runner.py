from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time
from typing import Any

from curl_cffi import requests
from utils import (
    atomic_write_json,
    atomic_write_lines,
    get_browser_for_proxy,
    hide_proxy_credentials,
    load_proxies,
    logger,
)

from funpay_analytics.scraper.client import (
    FUNPAY_COOKIES,
    parse_profile as default_parse_profile,
)
from funpay_analytics.scraper.proxy_pool import ping_and_rank as default_ping_and_rank


def _resolve_base_dir(base_dir: str | None = None) -> str:
    if base_dir:
        return base_dir
    parser_mod = sys.modules.get("parser")
    if parser_mod and hasattr(parser_mod, "BASE_DIR"):
        return str(parser_mod.BASE_DIR)
    return os.path.dirname(os.path.abspath(__file__))


def _get_parse_profile():
    parser_mod = sys.modules.get("parser")
    if parser_mod and hasattr(parser_mod, "parse_profile"):
        return parser_mod.parse_profile
    return default_parse_profile


def _get_async_session():
    parser_mod = sys.modules.get("parser")
    if parser_mod and hasattr(parser_mod, "requests"):
        return parser_mod.requests.AsyncSession
    return requests.AsyncSession


def _get_load_proxies():
    parser_mod = sys.modules.get("parser")
    if parser_mod and hasattr(parser_mod, "load_proxies"):
        return parser_mod.load_proxies
    return load_proxies


def _get_ping_and_rank():
    parser_mod = sys.modules.get("parser")
    if parser_mod and hasattr(parser_mod, "ping_and_rank"):
        return parser_mod.ping_and_rank
    return default_ping_and_rank


def _get_parse_worker():
    parser_mod = sys.modules.get("parser")
    if parser_mod and hasattr(parser_mod, "parse_worker"):
        return parser_mod.parse_worker
    return parse_worker


def _get_atomic_write_json():
    parser_mod = sys.modules.get("parser")
    if parser_mod and hasattr(parser_mod, "atomic_write_json"):
        return parser_mod.atomic_write_json
    return atomic_write_json


def _get_random():
    parser_mod = sys.modules.get("parser")
    if parser_mod and hasattr(parser_mod, "random"):
        return parser_mod.random
    return random


def _get_mass_parse():
    parser_mod = sys.modules.get("parser")
    if parser_mod and hasattr(parser_mod, "mass_parse"):
        return parser_mod.mass_parse
    return mass_parse


async def _async_sleep(seconds: float) -> None:
    parser_mod = sys.modules.get("parser")
    if parser_mod and hasattr(parser_mod, "asyncio"):
        await parser_mod.asyncio.sleep(seconds)
    else:
        await asyncio.sleep(seconds)


async def parse_worker(
    worker_id: int,
    ip_name: str,
    proxy_url: str | None,
    queue: asyncio.Queue,
    results: list[Any],
    library: dict[str, Any],
    stats: dict[str, Any],
    retry_map: dict[str, int] | None = None,
    active_workers: list[int] | None = None,
    base_dir: str | None = None,
) -> None:
    """Async worker processing sellers from the queue with retry tracking and atomic storage."""
    effective_base_dir = _resolve_base_dir(base_dir)
    if retry_map is None:
        retry_map = {}
    if active_workers is None:
        active_workers = [0]
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]
    ua = random.choice(user_agents)

    proxies: Any = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    consecutive_errors = 0
    browser: Any = get_browser_for_proxy(proxy_url) if proxy_url else "chrome120"

    session_cls = _get_async_session()
    profile_parser = _get_parse_profile()

    async with session_cls(proxies=proxies, impersonate=browser, timeout=25.0, cookies=FUNPAY_COOKIES) as client:
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
                res = await profile_parser(client, user_id, proxy=proxy_url, user_agent=ua)
            except Exception as e:
                logger.error(f"[Воркер {worker_id} | IP: {ip_name}] Неожиданная ошибка при парсинге {user_id}: {e}")
                res = None
            elapsed = time.time() - start_time

            written = False
            if res:
                reviews = res.get("total_reviews", 0)
                rps = reviews / elapsed if elapsed > 0 else 0
                logger.info(f"[ID {user_id}] ⚡ Скорость: {rps:.1f} о/с (Всего: {elapsed:.1f} с)")

                reports_dir = os.path.join(effective_base_dir, "reports_v2")
                await asyncio.to_thread(os.makedirs, reports_dir, exist_ok=True)
                report_path = os.path.join(reports_dir, f"seller_{user_id}.json")
                writer = _get_atomic_write_json()
                written = bool(await asyncio.to_thread(writer, report_path, res))
                if written:
                    library[user_id] = {
                        "status": "completed",
                        "reviews": reviews,
                    }
                    consecutive_errors = 0
                    stats["parsed_count"] = stats.get("parsed_count", 0) + 1
                    stats["total_reviews"] = stats.get("total_reviews", 0) + reviews
                    p_url = proxy_url if proxy_url else "Локальный IP"
                    proxy_success = stats.setdefault("proxy_success", {})
                    proxy_success[p_url] = proxy_success.get(p_url, 0) + 1
                else:
                    logger.error(
                        f"[Воркер {worker_id} | IP: {ip_name}] Ошибка записи файла отчета reports_v2/seller_{user_id}.json"
                    )

            if not res or not written:
                consecutive_errors += 1
                retries = retry_map.get(user_id, 0) + 1
                retry_map[user_id] = retries
                if retries < 3:
                    logger.warning(
                        f"[Воркер {worker_id} | IP: {ip_name}] Ошибка (попытка {retries}/3). "
                        f"Возвращаем продавца {user_id} в очередь."
                    )
                    queue.put_nowait(user_id)
                else:
                    logger.error(
                        f"[Воркер {worker_id} | IP: {ip_name}] Продавец {user_id} превысил лимит попыток ({retries}). Пропускаем."
                    )
                    library[user_id] = {"status": "failed", "error": "max_retries_exceeded"}
                    stats["failed_count"] = stats.get("failed_count", 0) + 1
                stats["errors"] = stats.get("errors", 0) + 1

            active_workers[0] -= 1
            queue.task_done()

            if consecutive_errors >= 3:
                masked_proxy = hide_proxy_credentials(proxy_url) if proxy_url else "Direct"
                logger.error(
                    f"[Воркер {worker_id} | IP: {masked_proxy}] Слишком много ошибок подряд (3). "
                    f"Воркер отключается. (Осталось в очереди: {queue.qsize()})"
                )
                break

            if not queue.empty():
                rnd = _get_random()
                if proxy_url:
                    await _async_sleep(rnd.uniform(1.0, 2.0))
                else:
                    await _async_sleep(rnd.uniform(3.0, 5.0))


async def background_library_saver(library: dict[str, Any], lock: asyncio.Lock | None = None, base_dir: str | None = None) -> None:
    """Background task periodically saving library_v2.json to disk."""
    effective_base_dir = _resolve_base_dir(base_dir)
    target_path = os.path.join(effective_base_dir, "library_v2.json")
    while True:
        await asyncio.sleep(30)
        if lock:
            async with lock:
                lib_copy = library.copy()
        else:
            lib_copy = library.copy()
        saved = await asyncio.to_thread(atomic_write_json, target_path, lib_copy)
        if saved:
            logger.debug("Фоновое сохранение library_v2.json выполнено.")
        else:
            logger.warning("Фоновое сохранение library_v2.json не удалось.")


async def mass_parse(library: dict[str, Any], stats: dict[str, Any], base_dir: str | None = None) -> list[Any] | None:
    """Orchestrates pool of async workers to drain queue.txt."""
    effective_base_dir = _resolve_base_dir(base_dir)
    queue_path = os.path.join(effective_base_dir, "queue.txt")
    if not os.path.exists(queue_path):
        logger.error("Файл queue.txt не найден! Сначала запустите fetch_ids.py")
        return None

    all_sellers_dict: dict[str, int] = {}
    with open(queue_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(":")
            uid = parts[0].strip()
            if not uid.isdigit():
                continue
            count = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip().isdigit() else 0
            all_sellers_dict[uid] = count

    all_sellers = [{"uid": u, "count": c} for u, c in all_sellers_dict.items()]
    atomic_write_lines(queue_path, [f"{s['uid']}:{s['count']}" for s in all_sellers])

    logger.info(f"Загружено {len(all_sellers)} продавцов из очереди.")
    top_ids = [s for s in all_sellers if library.get(str(s["uid"]), {}).get("status") != "completed"]
    logger.info(f"К парсингу (осталось): {len(top_ids)} чел.")

    if not top_ids:
        logger.info("Все продавцы из очереди уже успешно спарсены!")
        return []

    top_ids.sort(key=lambda x: int(str(x["count"])), reverse=True)
    logger.info("Топ 10 следующих к парсингу:")
    for s in top_ids[:10]:
        logger.info(f"  ID {s['uid']} - {s['count']} отзывов")

    results: list[Any] = []
    proxy_loader = _get_load_proxies()
    proxy_list = proxy_loader()

    ranker = _get_ping_and_rank()
    available_ips = await ranker(proxy_list)

    logger.info("[Этап 2] Умное распределение задач...")
    queue: asyncio.Queue = asyncio.Queue()
    for s in top_ids:
        queue.put_nowait(s["uid"])

    save_lock = asyncio.Lock()
    saver_task = asyncio.create_task(background_library_saver(library, lock=save_lock, base_dir=effective_base_dir))

    retry_map: dict[str, int] = {}
    active_workers = [0]
    workers = []
    worker_fn = _get_parse_worker()

    for i, ip_info in enumerate(available_ips):
        if queue.empty():
            break

        worker_task = asyncio.create_task(
            worker_fn(
                i + 1,
                ip_info["name"],
                ip_info["url"],
                queue,
                results,
                library,
                stats,
                retry_map,
                active_workers,
            )
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
            await asyncio.to_thread(
                atomic_write_json, os.path.join(effective_base_dir, "library_v2.json"), lib_final
            )

    if not queue.empty():
        unprocessed = queue.qsize()
        stats["unprocessed_count"] = unprocessed
        logger.error(
            f"[ОШИБКА ОЧЕРЕДИ] Все воркеры отключились из-за ошибок, в очереди осталось {unprocessed} "
            "необработанных задач! Парсинг не завершён."
        )
    else:
        stats["unprocessed_count"] = 0

    return results


async def run_pipeline(base_dir: str | None = None) -> bool:
    """Main execution pipeline: loads library, runs mass_parse, and generates market summaries."""
    effective_base_dir = _resolve_base_dir(base_dir)
    logger.info("=== ЗАПУСК МАССОВОГО ПАРСЕРА ===")

    library_path = os.path.join(effective_base_dir, "library_v2.json")
    library: dict[str, Any] = {}
    if os.path.exists(library_path):
        try:
            with open(library_path, encoding="utf-8") as f:
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

    stats: dict[str, Any] = {
        "parsed_count": 0,
        "total_reviews": 0,
        "errors": 0,
        "failed_count": 0,
        "proxy_success": {},
    }
    global_start = time.time()
    interrupted = False

    try:
        mass_parser = _get_mass_parse()
        await mass_parser(library, stats, base_dir=effective_base_dir)
    except (KeyboardInterrupt, asyncio.CancelledError):
        interrupted = True
        logger.warning("Парсинг прерван пользователем (Ctrl+C). Прогресс сохранен.")
        await asyncio.to_thread(atomic_write_json, library_path, library)
    finally:
        global_elapsed = time.time() - global_start
        cat_counts: dict[str, int] = {}

        reports_dir = os.path.join(effective_base_dir, "reports_v2")
        if os.path.exists(reports_dir):
            summary = []
            files = await asyncio.to_thread(os.listdir, reports_dir)
            for file in files:
                if file.endswith(".json"):
                    try:
                        with open(os.path.join(reports_dir, file), encoding="utf-8") as f:
                            res = json.load(f)
                            if isinstance(res, dict):
                                for cat, data in (res.get("categories") or {}).items():
                                    cat_c = len((data or {}).get("reviews", []))
                                    cat_counts[cat] = cat_counts.get(cat, 0) + cat_c
                                summary.append(res)
                    except Exception as e:
                        logger.error(f"Ошибка чтения отчета {file}: {e}")

            summary.sort(key=lambda x: (x.get("total_reviews") or 0), reverse=True)
            await asyncio.to_thread(
                atomic_write_json, os.path.join(effective_base_dir, "market_report_v2.json"), summary
            )
            await asyncio.to_thread(
                atomic_write_json, os.path.join(effective_base_dir, "market_report.json"), summary
            )

        mins = int(global_elapsed // 60)
        secs = int(global_elapsed % 60)
        avg_speed = stats["total_reviews"] / global_elapsed if global_elapsed > 0 else 0

        best_proxy = "Нет данных"
        if stats.get("proxy_success"):
            best_proxy = max(stats["proxy_success"].items(), key=lambda x: x[1])[0]

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
        if stats.get("unprocessed_count", 0) > 0:
            logger.error(f"Необработанных продавцов (сбой воркеров): {stats['unprocessed_count']}")
        logger.info("========================================")

    if interrupted:
        return False
    if stats.get("unprocessed_count", 0) > 0:
        return False
    if stats.get("failed_count", 0) > 0 and stats.get("parsed_count", 0) == 0:
        return False
    return True
