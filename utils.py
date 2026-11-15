"""Backward-compatibility facade for utilities now hosted in funpay_analytics.core."""
from __future__ import annotations

import os

from funpay_analytics.core import (
    IMPERSONATES,
    atomic_write_json,
    atomic_write_lines,
    extract_user_id,
    get_browser_for_proxy,
    hide_proxy_credentials,
    is_running_under_pytest,
    load_proxies,
    logger,
    normalize_proxy,
    parse_price,
    setup_file_logging,
)

__all__ = [
    "IMPERSONATES",
    "atomic_write_json",
    "atomic_write_lines",
    "extract_user_id",
    "get_browser_for_proxy",
    "hide_proxy_credentials",
    "is_running_under_pytest",
    "load_proxies",
    "logger",
    "normalize_proxy",
    "os",
    "parse_price",
    "setup_file_logging",
]
