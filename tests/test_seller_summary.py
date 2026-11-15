import json
from io import StringIO
from rich.console import Console

import show_seller
from funpay_analytics.models import SellerSummary
from funpay_analytics.storage.db import get_db, init_db


def test_seller_summary_from_dict():
    raw_data = {
        "seller_id": 12345,
        "username": "TestSeller",
        "total_reviews": 10,
        "categories": {
            "Steam": {
                "reviews": [
                    {"price": "100.00 ₽", "rating": 5},
                    {"price": "250.00 ₽", "rating": 5},
                ],
                "candidate_lots": [{"id": 1, "text": "Item 1", "price": "100.00"}],
            },
            "Discord": {
                "reviews": [
                    {"price": "500.00 ₽", "rating": 5},
                ],
                "candidate_lots": [],
            },
        },
    }

    summary = SellerSummary.from_dict(raw_data)
    assert summary.seller_id == 12345
    assert summary.username == "TestSeller"
    assert summary.total_reviews == 10
    assert summary.source == "json"
    assert len(summary.categories) == 2

    # Should be sorted descending by total_rub: Discord (500) > Steam (350)
    assert summary.categories[0].name == "Discord"
    assert summary.categories[0].total_rub == 500.0
    assert summary.categories[0].review_count == 1
    assert summary.categories[0].lot_count == 0

    assert summary.categories[1].name == "Steam"
    assert summary.categories[1].total_rub == 350.0
    assert summary.categories[1].review_count == 2
    assert summary.categories[1].lot_count == 1


def test_seller_summary_from_db_aggregates_categories():
    init_db()

    with get_db() as conn:
        cursor = conn.cursor()
        # 1. Insert seller
        cursor.execute(
            "INSERT INTO sellers (id, name, rating, reviews_count) VALUES (?, ?, ?, ?)",
            (777, "DbMerchant", 4.95, 3),
        )

        # 2. Insert raw snapshot
        cursor.execute(
            """
            INSERT INTO raw_snapshots (id, source_type, seller_id, external_id, content_sha256)
            VALUES (?, ?, ?, ?, ?)
            """,
            (10, "seller_snapshot_v2", 777, "777", "dummy_sha_10"),
        )

        # 3. Insert reviews across categories
        cursor.execute(
            """
            INSERT INTO reviews (raw_snapshot_id, review_index, seller_id, category_text, price_minor, rating)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (10, 0, 777, "Telegram", 15000, 5),  # 150.00 RUB
        )
        cursor.execute(
            """
            INSERT INTO reviews (raw_snapshot_id, review_index, seller_id, category_text, price_minor, rating)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (10, 1, 777, "Telegram", 5000, 5),   # 50.00 RUB
        )
        cursor.execute(
            """
            INSERT INTO reviews (raw_snapshot_id, review_index, seller_id, category_text, price_minor, rating)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (10, 2, 777, "Genshin", 30000, 5),   # 300.00 RUB
        )

        # 4. Insert candidate lots
        cursor.execute("INSERT INTO lots (id, seller_id, category_id) VALUES (?, ?, ?)", (101, 777, "Telegram"))
        cursor.execute("INSERT INTO lots (id, seller_id, category_id) VALUES (?, ?, ?)", (102, 777, "Telegram"))
        cursor.execute(
            "INSERT INTO snapshot_candidate_lots (raw_snapshot_id, category_text, lot_id) VALUES (?, ?, ?)",
            (10, "Telegram", 101),
        )
        cursor.execute(
            "INSERT INTO snapshot_candidate_lots (raw_snapshot_id, category_text, lot_id) VALUES (?, ?, ?)",
            (10, "Telegram", 102),
        )
        conn.commit()

        summary = SellerSummary.from_db(conn, 777)

    assert summary is not None
    assert summary.seller_id == 777
    assert summary.username == "DbMerchant"
    assert summary.rating == 4.95
    assert summary.total_reviews == 3
    assert summary.source == "sqlite"
    assert len(summary.categories) == 2

    # Genshin: 300.00 RUB > Telegram: 200.00 RUB
    assert summary.categories[0].name == "Genshin"
    assert summary.categories[0].total_rub == 300.0
    assert summary.categories[0].review_count == 1
    assert summary.categories[0].lot_count == 0

    assert summary.categories[1].name == "Telegram"
    assert summary.categories[1].total_rub == 200.0
    assert summary.categories[1].review_count == 2
    assert summary.categories[1].lot_count == 2


def test_seller_summary_from_db_returns_none_for_missing_seller():
    init_db()
    with get_db() as conn:
        summary = SellerSummary.from_db(conn, 99999999)
    assert summary is None


def test_show_seller_main_pulls_directly_from_sqlite(monkeypatch):
    init_db()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO sellers (id, name, rating, reviews_count) VALUES (?, ?, ?, ?)",
            (888, "SqliteDirectUser", 5.0, 1),
        )
        cursor.execute(
            """
            INSERT OR REPLACE INTO raw_snapshots (id, source_type, seller_id, external_id, content_sha256)
            VALUES (?, ?, ?, ?, ?)
            """,
            (20, "seller_snapshot_v2", 888, "888", "sha_888"),
        )
        cursor.execute(
            """
            INSERT OR REPLACE INTO reviews (raw_snapshot_id, review_index, seller_id, category_text, price_minor, rating)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (20, 0, 888, "Valorant", 85000, 5),  # 850.00 RUB
        )
        conn.commit()

    monkeypatch.setattr(show_seller.time, "sleep", lambda *_: None)
    output = StringIO()
    monkeypatch.setattr(show_seller, "console", Console(file=output))
    monkeypatch.setattr("sys.argv", ["show_seller.py", "888"])

    show_seller.main()
    rendered = output.getvalue()

    assert "SqliteDirectUser" in rendered
    assert "888" in rendered
    assert "Valorant" in rendered
    assert "850.00 RUB" in rendered
    assert "SQLite (analytics.sqlite3)" in rendered
    assert "Данные получены напрямую из SQLite базы данных" in rendered


def test_show_seller_main_falls_back_to_json_report(tmp_path, monkeypatch):
    report_file = tmp_path / "reports_v2" / "seller_555.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(
        json.dumps({
            "seller_id": 555,
            "username": "JsonFallbackUser",
            "total_reviews": 4,
            "categories": {
                "Roblox": {
                    "reviews": [{"price": "120.00 ₽", "rating": 5}],
                    "candidate_lots": [],
                }
            },
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(show_seller, "BASE_DIR", tmp_path)
    monkeypatch.setattr(show_seller.time, "sleep", lambda *_: None)
    output = StringIO()
    monkeypatch.setattr(show_seller, "console", Console(file=output))
    monkeypatch.setattr("sys.argv", ["show_seller.py", "555"])

    show_seller.main()
    rendered = output.getvalue()

    assert "JsonFallbackUser" in rendered
    assert "555" in rendered
    assert "Roblox" in rendered
    assert "120.00 RUB" in rendered
    assert "seller_555.json" in rendered
