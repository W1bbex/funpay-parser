from __future__ import annotations

import asyncio
import os
import random
import sys
from typing import Any

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
    mass_parse as _core_mass_parse,
    parse_worker as _core_parse_worker,
    run_pipeline as _core_run_pipeline,
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
    parse_profile as _core_parse_profile,
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


async def parse_profile(
    client: Any,
    user_id: str,
    proxy: str | None = None,
    user_agent: str | None = None,
    max_reviews: int | None = None,
    reviews_parser_cls: Any = None,
) -> dict[str, Any] | None:
    """Facade for parse_profile forwarding mockable ReviewsParser downward."""
    mod = sys.modules.get(__name__)
    if reviews_parser_cls is None:
        reviews_parser_cls = getattr(mod, "ReviewsParser", ReviewsParser)
    return await _core_parse_profile(
        client=client,
        user_id=user_id,
        proxy=proxy,
        user_agent=user_agent,
        max_reviews=max_reviews,
        reviews_parser_cls=reviews_parser_cls,
    )


async def parse_worker(
    worker_id: int,
    ip_name: str,
    proxy_url: str | None,
    queue: asyncio.Queue[str],
    results: list[dict[str, Any]] | list[Any],
    library: dict[str, Any],
    stats: dict[str, Any],
    retry_map: dict[str, int] | None = None,
    active_workers: list[int] | None = None,
    base_dir: str | None = None,
    profile_parser: Any = None,
    session_cls: Any = None,
    atomic_writer: Any = None,
    sleep_fn: Any = None,
) -> None:
    """Facade for parse_worker injecting top-level mockable dependencies."""
    mod = sys.modules.get(__name__)
    if base_dir is None:
        base_dir = getattr(mod, "BASE_DIR", BASE_DIR)
    if profile_parser is None:
        profile_parser = getattr(mod, "parse_profile", parse_profile)
    if session_cls is None:
        req_mod = getattr(mod, "requests", requests)
        session_cls = getattr(req_mod, "AsyncSession", getattr(requests, "AsyncSession", None))
    if atomic_writer is None:
        atomic_writer = getattr(mod, "atomic_write_json", atomic_write_json)
    if sleep_fn is None:
        asyncio_mod = getattr(mod, "asyncio", asyncio)
        sleep_fn = getattr(asyncio_mod, "sleep", asyncio.sleep)

    return await _core_parse_worker(
        worker_id,
        ip_name,
        proxy_url,
        queue,
        results,
        library,
        stats,
        retry_map=retry_map,
        active_workers=active_workers,
        base_dir=base_dir,
        profile_parser=profile_parser,
        session_cls=session_cls,
        atomic_writer=atomic_writer,
        sleep_fn=sleep_fn,
    )


async def mass_parse(
    library: dict[str, Any],
    stats: dict[str, Any],
    base_dir: str | None = None,
    worker_fn: Any = None,
    ranker: Any = None,
    proxy_loader: Any = None,
) -> list[Any] | None:
    """Facade for mass_parse injecting top-level mockable dependencies."""
    mod = sys.modules.get(__name__)
    if base_dir is None:
        base_dir = getattr(mod, "BASE_DIR", BASE_DIR)
    if worker_fn is None:
        worker_fn = getattr(mod, "parse_worker", parse_worker)
    if ranker is None:
        ranker = getattr(mod, "ping_and_rank", ping_and_rank)
    if proxy_loader is None:
        proxy_loader = getattr(mod, "load_proxies", load_proxies)

    return await _core_mass_parse(
        library=library,
        stats=stats,
        base_dir=base_dir,
        worker_fn=worker_fn,
        ranker=ranker,
        proxy_loader=proxy_loader,
    )


async def run_pipeline(
    base_dir: str | None = None,
    mass_parser: Any = None,
) -> bool:
    """Facade for run_pipeline injecting top-level mockable mass_parser."""
    mod = sys.modules.get(__name__)
    if base_dir is None:
        base_dir = getattr(mod, "BASE_DIR", BASE_DIR)
    if mass_parser is None:
        mass_parser = getattr(mod, "mass_parse", mass_parse)

    return await _core_run_pipeline(
        base_dir=base_dir,
        mass_parser=mass_parser,
    )


async def main_async() -> bool:
    """Entry point for running the market scraping pipeline."""
    mod = sys.modules.get(__name__)
    cur_base_dir = getattr(mod, "BASE_DIR", BASE_DIR)
    pipeline_fn = getattr(mod, "run_pipeline", run_pipeline)
    return await pipeline_fn(base_dir=cur_base_dir)


def main() -> None:
    """CLI runner executing main_async on the asyncio event loop."""
    success = asyncio.run(main_async())
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
