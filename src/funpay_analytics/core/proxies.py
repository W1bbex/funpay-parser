from __future__ import annotations

import os
import re
from pathlib import Path

IMPERSONATES = ["chrome110", "chrome116", "chrome120", "edge101", "chrome124"]

BROWSER_HEADERS_PROFILES: dict[str, dict[str, str]] = {
    "chrome110": {
        "windows": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
        ),
        "macos": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
        ),
        "sec_ch_ua": '"Chromium";v="110", "Not A(Brand";v="24", "Google Chrome";v="110"',
    },
    "chrome116": {
        "windows": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
        ),
        "macos": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
        ),
        "sec_ch_ua": '"Chromium";v="116", "Not)A;Brand";v="24", "Google Chrome";v="116"',
    },
    "chrome120": {
        "windows": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "macos": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "sec_ch_ua": '"Not.A/Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    },
    "edge101": {
        "windows": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.64 Safari/537.36 Edg/101.0.1210.53"
        ),
        "macos": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.64 Safari/537.36 Edg/101.0.1210.53"
        ),
        "sec_ch_ua": '" Not A;Brand";v="99", "Chromium";v="101", "Microsoft Edge";v="101"',
    },
    "chrome124": {
        "windows": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "macos": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "sec_ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    },
}


def _get_default_base_dir() -> str:
    """Returns project root directory or test-monkeypatched directory."""
    d = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(d) == "core":
        return os.path.abspath(os.path.join(d, "..", "..", ".."))
    return d


def normalize_proxy(line: str) -> str:
    """Normalizes raw proxy string into standard URL format (e.g. socks5://user:pass@ip:port)."""
    p = line.strip()
    if not p or p.startswith("#"):
        return ""

    proto = "socks5"
    clean = p
    if p.startswith(("http://", "https://", "socks5://", "socks4://")):
        proto, clean = p.split("://", 1)

    if "@" in clean:
        return f"{proto}://{clean}" if not p.startswith(("http://", "https://", "socks")) else p

    parts = clean.split(":")
    if len(parts) == 4:
        if parts[3].isdigit() and ("." in parts[2] or "." not in parts[0]):
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
        return f"{proto}://{user}:{pwd}@{ip}:{port}"
    elif len(parts) == 2 and not p.startswith(("http://", "https://", "socks")):
        return f"http://{p}"
    return p


def load_proxies(base_dir: str | Path | None = None) -> list[str]:
    """Loads and formats proxies from good_proxies.txt and proxies.txt with deduplication after normalization."""
    if not base_dir:
        base_dir_path = Path(_get_default_base_dir())
    else:
        base_dir_path = Path(base_dir)

    candidate_files: list[Path] = []
    good_path = base_dir_path / "good_proxies.txt"
    if good_path.exists() and good_path.stat().st_size > 0:
        candidate_files.append(good_path)

    proxy_path = base_dir_path / "proxies.txt"
    if proxy_path.exists() and proxy_path.stat().st_size > 0:
        candidate_files.append(proxy_path)

    seen: set[str] = set()
    formatted_proxies: list[str] = []
    for target_file in candidate_files:
        with open(target_file, encoding="utf-8") as f:
            for line in f:
                norm = normalize_proxy(line)
                if norm and norm not in seen:
                    seen.add(norm)
                    formatted_proxies.append(norm)

    return formatted_proxies


def get_browser_for_proxy(proxy_url: str | None) -> str:
    """Returns deterministic browser fingerprint for a specific proxy based on its URL hash."""
    if not proxy_url:
        return "chrome120"
    hash_val = sum(ord(c) for c in proxy_url)
    return IMPERSONATES[hash_val % len(IMPERSONATES)]


def get_user_agent_for_browser(browser: str | None, platform: str = "Windows") -> str:
    """Returns a User-Agent matching the selected curl_cffi impersonate profile."""
    profile = BROWSER_HEADERS_PROFILES.get(browser or "chrome120", BROWSER_HEADERS_PROFILES["chrome120"])
    key = "macos" if platform.lower().startswith("mac") else "windows"
    return profile[key]


def get_sec_ch_ua(user_agent: str | None = None, browser: str | None = None) -> str:
    """Returns a Sec-Ch-Ua header consistent with the given User-Agent or browser profile."""
    if browser and browser in BROWSER_HEADERS_PROFILES and not user_agent:
        return BROWSER_HEADERS_PROFILES[browser]["sec_ch_ua"]
    if user_agent:
        edge_match = re.search(r"Edg/(\d+)", user_agent)
        if edge_match:
            ver = edge_match.group(1)
            return f'" Not A;Brand";v="99", "Chromium";v="{ver}", "Microsoft Edge";v="{ver}"'
        chrome_match = re.search(r"Chrome/(\d+)", user_agent)
        if chrome_match:
            ver = chrome_match.group(1)
            for prof in BROWSER_HEADERS_PROFILES.values():
                if f'v="{ver}"' in prof["sec_ch_ua"] and "Microsoft Edge" not in prof["sec_ch_ua"]:
                    return prof["sec_ch_ua"]
            return f'"Chromium";v="{ver}", "Google Chrome";v="{ver}", "Not-A.Brand";v="99"'
    return BROWSER_HEADERS_PROFILES["chrome120"]["sec_ch_ua"]


def hide_proxy_credentials(url: str | None) -> str:
    """Strips username, password, and protocol from proxy URL for sanitized logging."""
    if not url:
        return "None"
    clean = url.split("://")[-1]
    if "@" in clean:
        return clean.split("@")[-1]
    parts = clean.split(":")
    if len(parts) == 4:
        if parts[3].isdigit() and ("." in parts[2] or "." not in parts[0]):
            return f"{parts[2]}:{parts[3]}"
        elif parts[1].isdigit():
            return f"{parts[0]}:{parts[1]}"
        elif parts[3].isdigit():
            return f"{parts[2]}:{parts[3]}"
    return clean


def extract_user_id(val: str | None) -> str | None:
    """Extracts FunPay seller numeric ID from input string, profile URL, or file path."""
    if not val:
        return None
    clean = val.strip()
    if clean.isdigit():
        return clean
    m = re.search(r"users/(\d+)", clean)
    if m:
        return m.group(1)
    m_file = re.search(r"seller_(\d+)\.json", clean)
    if m_file:
        return m_file.group(1)
    return None


__all__ = [
    "BROWSER_HEADERS_PROFILES",
    "IMPERSONATES",
    "extract_user_id",
    "get_browser_for_proxy",
    "get_sec_ch_ua",
    "get_user_agent_for_browser",
    "hide_proxy_credentials",
    "load_proxies",
    "normalize_proxy",
]
