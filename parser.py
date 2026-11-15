from __future__ import annotations

import asyncio
import os
import random
import sys

from curl_cffi import requests
from funpayparsers.parsers.reviews_parser import ReviewsParser
from utils import (
    atomic_write_json,
    atomic_write_lines,
    get_browser_for_proxy,
    hide_proxy_credentials,
    load_proxies,
    logger,
    parse_price,
)

from funpay_analytics.engine.runner import (
    background_library_saver,
    mass_parse,
    parse_worker,
    run_pipeline,
)
from funpay_analytics.parser.lot_filter import (
    extract_profile_lots,
    get_review_interval,
    is_candidate,
    match_and_filter_lots,
    parse_lot_price,
)
from funpay_analytics.scraper.client import (
    FUNPAY_COOKIES,
    fetch_seller_reviews,
    get_smart_delay,
    parse_profile,
)
from funpay_analytics.scraper.proxy_pool import (
    ping_and_rank,
    ping_proxy_curl,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

__all__ = [
    "BASE_DIR",
    "FUNPAY_COOKIES",
    "get_smart_delay",
    "get_review_interval",
    "is_candidate",
    "parse_lot_price",
    "extract_profile_lots",
    "fetch_seller_reviews",
    "match_and_filter_lots",
    "parse_profile",
    "ping_proxy_curl",
    "ping_and_rank",
    "parse_worker",
    "background_library_saver",
    "mass_parse",
    "run_pipeline",
    "main_async",
    "main",
    "requests",
    "load_proxies",
    "atomic_write_json",
    "atomic_write_lines",
    "logger",
    "get_browser_for_proxy",
    "hide_proxy_credentials",
    "parse_price",
    "random",
    "ReviewsParser",
]


async def main_async() -> bool:
    """Entry point for running the market scraping pipeline."""
    return await run_pipeline(base_dir=BASE_DIR)


def main() -> None:
    """CLI runner executing main_async on the asyncio event loop."""
    success = asyncio.run(main_async())
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
