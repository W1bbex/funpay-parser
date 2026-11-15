from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

if sys.version_info >= (3, 11):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict


class CandidateLotDict(TypedDict, total=False):
    id: int | str
    section: str | None
    text: str | None
    title: str | None
    price: float | str | None
    price_minor: int | None
    stock: int | None


class ReviewDict(TypedDict, total=False):
    rating: int | None
    text: str | None
    reply: str | None
    date: str | None
    price: float | str | None
    price_minor: int | None
    category: str | None
    order_id: str | None
    buyer_id: int | None
    buyer_name: str | None


class CategoryDataDict(TypedDict, total=False):
    reviews: list[ReviewDict]
    candidate_lots: list[CandidateLotDict]


class SellerReportDict(TypedDict, total=False):
    schema_version: int
    seller_id: int | str
    username: str
    currency: str
    total_reviews: int
    collected_at: str
    categories: dict[str, CategoryDataDict]


@dataclass
class CategorySummary:
    name: str
    review_count: int = 0
    total_rub: float = 0.0
    lot_count: int = 0


@dataclass
class SellerSummary:
    seller_id: int
    username: str
    total_reviews: int = 0
    rating: float | None = None
    source: str = "sqlite"
    categories: list[CategorySummary] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SellerSummary:
        """Constructs a SellerSummary from a report dict (e.g. from JSON)."""
        from utils import parse_price

        raw_id = data.get("seller_id", 0)
        try:
            seller_id = int(raw_id)
        except (TypeError, ValueError):
            seller_id = 0

        username = str(data.get("username", "Unknown"))
        total_reviews = int(data.get("total_reviews", 0) or 0)
        raw_cats = data.get("categories") or {}

        categories: list[CategorySummary] = []
        if isinstance(raw_cats, dict):
            for cat_name, cat_val in raw_cats.items():
                if not isinstance(cat_val, dict):
                    continue
                revs = cat_val.get("reviews") or []
                lots = cat_val.get("candidate_lots") or []
                rev_count = len(revs) if isinstance(revs, list) else 0
                lot_count = len(lots) if isinstance(lots, list) else 0
                total_sum = 0.0
                if isinstance(revs, list):
                    for r in revs:
                        if isinstance(r, dict):
                            total_sum += parse_price(r.get("price"))
                categories.append(
                    CategorySummary(
                        name=str(cat_name),
                        review_count=rev_count,
                        total_rub=total_sum,
                        lot_count=lot_count,
                    )
                )

        if not total_reviews and categories:
            total_reviews = sum(c.review_count for c in categories)

        categories.sort(key=lambda c: c.total_rub, reverse=True)
        return cls(
            seller_id=seller_id,
            username=username,
            total_reviews=total_reviews,
            source="json",
            categories=categories,
        )

    @classmethod
    def from_db(cls, conn: Any, seller_id: int) -> SellerSummary | None:
        """Loads seller summary and category breakdown directly from SQLite."""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, rating, reviews_count FROM sellers WHERE id = ?",
            (seller_id,),
        )
        seller_row = cursor.fetchone()
        if not seller_row:
            return None

        username = seller_row[1] or f"User_{seller_id}"
        rating = float(seller_row[2]) if seller_row[2] is not None else None
        total_reviews = int(seller_row[3]) if seller_row[3] is not None else 0

        cursor.execute(
            """
            SELECT category_text, COUNT(*) as rev_c, COALESCE(SUM(price_minor), 0) as sum_minor
            FROM reviews
            WHERE seller_id = ? AND category_text IS NOT NULL
            GROUP BY category_text
            """,
            (seller_id,),
        )
        cat_stats = {
            row[0]: {"review_count": int(row[1]), "total_rub": float(row[2]) / 100.0}
            for row in cursor.fetchall()
        }

        cursor.execute(
            """
            SELECT scl.category_text, COUNT(DISTINCT scl.lot_id) as lot_c
            FROM snapshot_candidate_lots scl
            JOIN raw_snapshots rs ON scl.raw_snapshot_id = rs.id
            WHERE rs.seller_id = ?
            GROUP BY scl.category_text
            """,
            (seller_id,),
        )
        lot_counts = {row[0]: int(row[1]) for row in cursor.fetchall()}

        all_cat_names = set(cat_stats.keys()) | set(lot_counts.keys())
        categories: list[CategorySummary] = []
        for cat_name in all_cat_names:
            c_stat = cat_stats.get(cat_name, {"review_count": 0, "total_rub": 0.0})
            l_count = lot_counts.get(cat_name, 0)
            categories.append(
                CategorySummary(
                    name=str(cat_name),
                    review_count=int(c_stat["review_count"]),
                    total_rub=float(c_stat["total_rub"]),
                    lot_count=l_count,
                )
            )

        if not total_reviews and categories:
            total_reviews = sum(c.review_count for c in categories)

        categories.sort(key=lambda c: c.total_rub, reverse=True)
        return cls(
            seller_id=seller_id,
            username=username,
            total_reviews=total_reviews,
            rating=rating,
            source="sqlite",
            categories=categories,
        )
