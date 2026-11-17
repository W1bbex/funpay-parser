"""An empty successful snapshot must replace, rather than merge with, history."""

import json

import pytest

from funpay_analytics.harvest.json_importer import import_seller_json
from funpay_analytics.models import SellerSummary
from funpay_analytics.storage.db import get_db, init_db


def import_snapshot(tmp_path, name, *, reviews, lots):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({
        "schema_version": 2, "seller_id": 777, "username": "Seller", "currency": "RUB",
        "categories": {"Steam": {"reviews": reviews, "candidate_lots": lots}},
    }), encoding="utf-8")
    return import_seller_json(path)


@pytest.mark.parametrize("empty_reviews", [False, True])
def test_latest_successful_json_keeps_empty_candidate_result(tmp_path, empty_reviews):
    init_db()
    review = {"price": 100, "rating": 5, "text": "First", "date": "yesterday"}
    lot = {"id": 101, "section": "Steam", "text": "Lot", "price": 100}
    import_snapshot(tmp_path, "before", reviews=[review], lots=[lot])
    after_reviews = [] if empty_reviews else [{**review, "price": 200, "date": "today"}]
    import_snapshot(tmp_path, "after", reviews=after_reviews, lots=[])
    with get_db() as conn:
        summary = SellerSummary.from_db(conn, 777)
    assert summary is not None
    assert sum(c.lot_count for c in summary.categories) == 0
    assert sum(c.review_count for c in summary.categories) == len(after_reviews)
    assert sum(c.total_rub for c in summary.categories) == (0 if empty_reviews else 200)


def test_empty_json_does_not_borrow_profile_lots(tmp_path):
    init_db()
    with get_db() as conn:
        conn.execute("INSERT INTO sellers (id, name) VALUES (777, 'Seller')")
        conn.execute("INSERT INTO raw_snapshots (id, source_type, seller_id, parser_status) VALUES (1, 'profile', 777, 'success')")
        conn.execute("INSERT INTO lots (id, seller_id) VALUES (101, 777)")
        conn.execute("INSERT INTO lot_snapshots (lot_id, seller_id, native_section_name, raw_snapshot_id) VALUES (101, 777, 'Steam', 1)")
        conn.commit()
    import_snapshot(tmp_path, "empty", reviews=[], lots=[])
    with get_db() as conn:
        summary = SellerSummary.from_db(conn, 777)
    assert summary is not None
    assert summary.categories == []


def test_failed_json_does_not_replace_successful_snapshot(tmp_path):
    init_db()
    import_snapshot(tmp_path, "valid", reviews=[{"price": 100, "rating": 5, "text": "Good", "date": "today"}], lots=[])
    with get_db() as conn:
        conn.execute("INSERT INTO raw_snapshots (source_type, seller_id, parser_status) VALUES ('seller_snapshot_v2', 777, 'failed')")
        conn.commit()
        summary = SellerSummary.from_db(conn, 777)
    assert summary is not None
    assert summary.categories[0].total_rub == 100


def test_empty_latest_profile_replaces_historical_profile_lots():
    init_db()
    with get_db() as conn:
        conn.execute("INSERT INTO sellers (id, name) VALUES (777, 'Seller')")
        conn.execute("INSERT INTO raw_snapshots (id, source_type, seller_id, parser_status) VALUES (1, 'profile', 777, 'success')")
        conn.execute("INSERT INTO lots (id, seller_id) VALUES (101, 777)")
        conn.execute("INSERT INTO lot_snapshots (lot_id, seller_id, native_section_name, raw_snapshot_id) VALUES (101, 777, 'Steam', 1)")
        conn.execute("INSERT INTO raw_snapshots (id, source_type, seller_id, parser_status) VALUES (2, 'profile', 777, 'success')")
        conn.commit()
        summary = SellerSummary.from_db(conn, 777)
    assert summary is not None
    assert summary.categories == []
