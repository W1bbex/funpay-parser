from __future__ import annotations

import asyncio
import time
from typing import Any

from curl_cffi import requests
from utils import get_browser_for_proxy, hide_proxy_credentials, logger

from funpay_analytics.scraper.client import FUNPAY_COOKIES


async def ping_proxy_curl(proxy_url: str, sem: asyncio.Semaphore) -> dict[str, Any] | None:
    """Pings a proxy server with curl_cffi against funpay.com."""
    try:
        async with sem:
            proxies: Any = {"http": proxy_url, "https": proxy_url}
            browser: Any = get_browser_for_proxy(proxy_url)
            start = time.time()
            async with requests.AsyncSession(proxies=proxies, impersonate=browser, timeout=10.0) as session:
                resp = await session.get("https://funpay.com", cookies=FUNPAY_COOKIES)
                if resp.status_code == 200:
                    return {
                        "url": proxy_url,
                        "ping": time.time() - start,
                        "name": hide_proxy_credentials(proxy_url),
                    }
    except (asyncio.CancelledError, KeyboardInterrupt):
        raise
    except Exception:
        pass
    return None


async def ping_and_rank(proxy_list: list[str]) -> list[dict[str, Any]]:
    """Calibrates and ranks proxy list by ping latency."""
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

    valid = [r for r in results if r is not None and r["ping"] <= 10.0]
    valid.sort(key=lambda x: x["ping"])
    valid.append({"url": None, "ping": 999.0, "name": "Родной IP"})

    logger.info(f"Отбор прошли {len(valid)-1} прокси.")
    for i, v in enumerate(valid):
        ping_str = f"{v['ping']:.2f}c" if v["ping"] < 900 else "N/A"
        logger.info(f"  {i+1}. {v['name']} - Пинг: {ping_str}")

    return valid
