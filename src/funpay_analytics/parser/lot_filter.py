from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from funpay_analytics.core import logger, parse_price


def get_review_interval(price: float) -> tuple[Decimal, Decimal] | None:
    """Calculates estimation price window for a completed order review."""
    if price <= 0:
        return None
    if price % 1000 == 0 and price >= 2000:
        p = Decimal(str(price))
        return (p - Decimal("500"), p + Decimal("500"))
    elif price == 1000:
        return (Decimal("950"), Decimal("1500"))
    elif price == 100:
        return (Decimal("95"), Decimal("150"))
    elif price % 100 == 0 and price < 1000:
        p = Decimal(str(price))
        return (p - Decimal("50"), p + Decimal("50"))
    elif price % 10 == 0 and price < 100:
        p = Decimal(str(price))
        return (p - Decimal("5"), p + Decimal("5"))
    return None


def is_candidate(lot_price: float, lower: Decimal, upper: Decimal) -> bool:
    """Checks whether lot unit price could fulfill an order within [lower, upper]."""
    if lot_price <= 0:
        return False
    lp = Decimal(str(lot_price))
    q_min = max(Decimal("1"), Decimal(str(math.ceil(lower / lp))))
    return (lp * q_min) < upper


def parse_lot_price(price_div: Any) -> float:
    """Extracts numeric price from lot price element."""
    if not price_div:
        return 0.0
    text = getattr(price_div, "text", str(price_div))
    return parse_price(text)


def extract_profile_lots(soup: BeautifulSoup, user_id: str) -> list[dict[str, Any]]:
    """Extracts active seller lots from profile HTML soup."""
    active_lots: list[dict[str, Any]] = []
    for mb20 in soup.find_all("div", class_="mb20"):
        for offer in mb20.find_all("div", class_="offer"):
            title_div = offer.find("div", class_="offer-list-title")
            if not title_div:
                continue
            section_name = title_div.text.strip().replace("\n", " ")

            for a in offer.find_all("a", class_="tc-item"):
                href = str(a.get("href") or "")
                parsed_url = urlparse(href)
                qs = parse_qs(parsed_url.query)
                lot_id = qs.get("id", [""])[0]
                if not lot_id.isdigit():
                    m = re.search(r"id=(\d+)", href)
                    lot_id = m.group(1) if m else ""

                if not lot_id:
                    logger.warning(f"[ID {user_id}] Пропущен лот без ID (href: {href})")
                    continue

                price_div = a.find("div", class_="tc-price")
                price = parse_lot_price(price_div)

                if price <= 0:
                    logger.warning(f"[ID {user_id}] Пропущен лот с некорректной ценой (ID: {lot_id})")
                    continue

                title_elem = a.find("div", class_="tc-desc")
                title = title_elem.text.strip() if title_elem else "Лот"

                amount_div = a.find("div", class_="tc-amount")
                stock = None
                if amount_div:
                    amount_str = re.sub(r"[^\d]", "", amount_div.text)
                    if amount_str:
                        stock = int(amount_str)

                active_lots.append({
                    "id": lot_id,
                    "section": section_name,
                    "text": title,
                    "price": price,
                    "stock": stock,
                })
    return active_lots


def match_and_filter_lots(all_active_lots: list[dict[str, Any]], categories_reviews: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Matches active lots with review categories and performs price window filtering."""
    categories: dict[str, Any] = {}
    known_review_categories = list(categories_reviews.keys())

    for cat in known_review_categories:
        categories[cat] = {"reviews": categories_reviews[cat], "candidate_lots": []}

    def normalize_cat(c: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", c)).casefold().strip()

    for lot in all_active_lots:
        sec_norm = normalize_cat(lot["section"])
        matches = []
        for rc in known_review_categories:
            norm_rc = normalize_cat(rc)
            if norm_rc:
                if norm_rc in sec_norm:
                    matches.append(rc)
            elif rc.strip() and rc.strip().casefold() in lot["section"].casefold():
                matches.append(rc)

        if matches:
            matched_cat = max(matches, key=len)
            categories[matched_cat]["candidate_lots"].append(lot)

    for cat_name, data in categories.items():
        reviews = data["reviews"]
        lots = data["candidate_lots"]
        filtered_lots = []

        intervals = []
        disable_filtering = False

        for r in reviews:
            iv = get_review_interval(r["price"])
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
                    if is_candidate(lot["price"], lower, upper):
                        is_valid = True
                        break
                if is_valid:
                    filtered_lots.append(lot)

        data["candidate_lots"] = filtered_lots

    return categories
