from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


def _clean_price_string(val: str) -> str:
    """Cleans currency strings, strips per-unit tails and normalizes decimal delimiters."""
    raw = str(val).replace("\xa0", " ").strip()
    if not raw:
        return ""

    # If there is a per-unit tail like "10 руб. / 1 шт.", take only the price part
    if "/" in raw:
        raw = raw.split("/", 1)[0].strip()

    # Strip currency words, symbols and abbreviations with optional trailing dots
    raw = re.sub(r"[a-zA-Zа-яА-ЯёЁ₽$€¥]+\.?\s*", "", raw).strip().strip(".,")
    if not raw:
        return ""

    # Both comma and dot present
    if "," in raw and "." in raw:
        if raw.rfind(".") > raw.rfind(","):
            # Format 1,500.50 -> comma is thousands separator
            raw = raw.replace(",", "")
        else:
            # Format 1.500,50 -> dot is thousands separator, comma is decimal
            raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        digits_and_comma = re.sub(r"[^\d,]", "", raw)
        if re.search(r"^\d{1,3}(?:,\d{3})+$", digits_and_comma):
            raw = raw.replace(",", "")
        else:
            raw = raw.replace(",", ".")
    elif "." in raw:
        digits_and_dot = re.sub(r"[^\d.]", "", raw)
        if digits_and_dot.count(".") > 1:
            parts = digits_and_dot.split(".")
            # If last component is 2 digits (kopecks/cents), keep last dot as decimal separator
            if len(parts[-1]) == 2:
                raw = "".join(parts[:-1]) + "." + parts[-1]
            else:
                raw = "".join(parts)

    cleaned = re.sub(r"[^\d.]", "", raw)
    if not cleaned:
        return ""
    if cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    return cleaned


def to_price_minor(price_val: Any) -> int:
    """Safely converts price value (number or formatted currency string) into minor units (kopecks/cents)."""
    if price_val is None:
        raise ValueError("Цена не может быть None")
    if isinstance(price_val, bool):
        raise ValueError("Цена не может быть boolean")
    if isinstance(price_val, (int, float, Decimal)):
        val = Decimal(str(price_val))
        return int((val * Decimal("100")).to_integral_value())

    cleaned = _clean_price_string(str(price_val))
    if not cleaned:
        raise ValueError(f"Некорректная цена: {price_val}")

    match = re.search(r"([\d.]+)", cleaned)
    if not match:
        raise ValueError(f"Некорректная цена: {price_val}")
    try:
        val = Decimal(match.group(1))
        return int((val * Decimal("100")).to_integral_value())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Невозможно преобразовать цену {price_val} в Decimal: {exc}") from exc


def parse_price(val: Any) -> float:
    """Safely extracts numeric float price from float, int, or currency string."""
    if val is None or isinstance(val, bool):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)

    cleaned = _clean_price_string(str(val))
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


__all__ = ["parse_price", "to_price_minor"]
