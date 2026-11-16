import asyncio
import json
import os
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bs4 import BeautifulSoup
from rich.console import Console

import main

from funpay_analytics.harvest.json_importer import import_seller_json
from funpay_analytics.harvest.profile_harvester import parse_profile
from funpay_analytics.normalize.extract_own_orders import (
    extract_orders,
    parse_mhtml,
    save_raw_snapshot,
    validate_orders,
)
from funpay_analytics.storage.db import get_connection
import funpay_analytics.storage.db as db_mod
from parser import FUNPAY_COOKIES, get_review_interval, parse_lot_price
from utils import (
    atomic_write_json,
    atomic_write_lines,
    extract_user_id,
    hide_proxy_credentials,
    load_proxies,
    parse_price,
)
from fetch_ids import mark_proxy


# 1. Non-breaking space (\xa0) in extract_own_orders
def test_extract_own_orders_nbsp_price():
    html = """
    <a class="tc-item" href="https://funpay.com/orders/TEST1234/">
        <div class="tc-order">#TEST1234</div>
        <div class="order-desc">
            <div>Steam Gift 1500 RUB</div>
            <div class="text-muted">Steam, Keys</div>
        </div>
        <div class="tc-price tc-seller-sum"> 1\xa0500.00 <span class="unit">rub</span></div>
    </a>
    """
    soup = BeautifulSoup(html, "html.parser")
    orders = extract_orders(soup)
    assert len(orders) == 1
    assert orders[0]["seller_total_minor"] == 150000
    assert orders[0]["order_id"] == "TEST1234"


# 2. Plain HTML file import in extract_own_orders
def test_parse_plain_html(tmp_path, monkeypatch):
    monkeypatch.setenv("FUNPAY_DATA_DIR", str(tmp_path))
    plain_html = b"""<!DOCTYPE html>
    <html><body>
    <a class="tc-item" href="https://funpay.com/orders/PLN1234/">
        <div class="tc-order">#PLN1234</div>
        <div class="order-desc"><div>Item</div><div>Category</div></div>
        <div class="tc-price tc-seller-sum"> 100.00 <span class="unit">rub</span></div>
    </a>
    </body></html>"""
    test_file = tmp_path / "plain_orders.html"
    test_file.write_bytes(plain_html)

    soup, sha, path = parse_mhtml(str(test_file))
    assert soup is not None
    assert len(soup.find_all("a", class_="tc-item")) == 1


# 3. Lot price parser robustness (thousands separators, dots, commas)
def test_parser_lot_price():
    cases = [
        ("1.250.00 \u20bd", 1250.0),
        ("1 250,50 \u20bd", 1250.5),
        ("1.250,50 \u20bd", 1250.5),
        ("500 \u20bd", 500.0),
        ("0.50 \u20bd", 0.5),
        ("invalid", 0.0),
        ("", 0.0),
    ]
    for text, expected in cases:
        html = f"<div class='tc-price'>{text}</div>"
        soup = BeautifulSoup(html, "html.parser")
        elem = soup.find("div", class_="tc-price")
        assert parse_lot_price(elem) == expected


def test_parse_lot_price_formats():
    class MockTag:
        def __init__(self, text):
            self.text = text

    assert parse_lot_price(MockTag("1,250.50 \u20bd")) == 1250.50
    assert parse_lot_price(MockTag("1.250,50 \u20bd")) == 1250.50
    assert parse_lot_price(MockTag("99.90 \u20bd")) == 99.90
    assert parse_lot_price(MockTag("500 \u20bd")) == 500.0


# 4. Proxy credential masking
def test_hide_proxy_credentials():
    assert hide_proxy_credentials("1.2.3.4:8080:myuser:mypass") == "1.2.3.4:8080"
    assert hide_proxy_credentials("socks5://myuser:mypass@1.2.3.4:8080") == "1.2.3.4:8080"
    assert hide_proxy_credentials("http://user:pass@1.2.3.4:8080") == "1.2.3.4:8080"
    assert hide_proxy_credentials("http://1.2.3.4:8080") == "1.2.3.4:8080"
    assert hide_proxy_credentials("") == "None"


def test_hide_proxy_credentials_formats():
    assert hide_proxy_credentials("http://user:secret@1.2.3.4:8000") == "1.2.3.4:8000"
    assert hide_proxy_credentials("1.2.3.4:8000:myuser:mypass") == "1.2.3.4:8000"


# 5. Load proxies skips comment lines
def test_load_proxies_comments(tmp_path, monkeypatch):
    proxies_content = "# \u0424\u043e\u0440\u043c\u0430\u0442: ip:port:user:pass\n1.2.3.4:8080:u:p\n# \u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439\n"
    p_file = tmp_path / "proxies.txt"
    p_file.write_text(proxies_content, encoding="utf-8")

    monkeypatch.setattr(os.path, "dirname", lambda x: str(tmp_path))
    proxies = load_proxies()
    assert len(proxies) == 1
    assert "socks5://u:p@1.2.3.4:8080" in proxies
    assert not any("#" in p for p in proxies)


# 6. mark_proxy removes bad proxy from good_proxies
def test_mark_proxy_hygiene(tmp_path):
    good_set = {"1.1.1.1:8080"}
    bad_set = set()
    pool = ["1.1.1.1:8080", "2.2.2.2:8080"]

    mark_proxy("1.1.1.1:8080", "bad", str(tmp_path), good_set, bad_set, pool)
    assert "1.1.1.1:8080" not in good_set
    assert "1.1.1.1:8080" in bad_set
    assert "1.1.1.1:8080" not in pool


# Nullable prices must be handled by the actual analytics screen.
def test_market_analytics_sums_nullable_review_prices(tmp_path, monkeypatch):
    revs = [
        {"price": 100.0},
        {"price": None},
        {"price": 50.0},
        {"other": 10.0},
    ]
    report = [{"total_reviews": 4, "categories": {"Keys": {"reviews": revs}}}]
    (tmp_path / "market_report_v2.json").write_text(json.dumps(report), encoding="utf-8")
    output = StringIO()
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    monkeypatch.setattr(main, "console", Console(file=output, width=120, color_system=None))
    monkeypatch.setattr("builtins.input", lambda *_: "")

    main.show_market_analytics()

    rendered = output.getvalue()
    assert "Keys" in rendered
    assert rendered.count("150.00 RUB") == 2


# 8. db get_connection when DB_PATH has no directory component
def test_db_dirname_empty_safety(tmp_path, monkeypatch):
    test_db = tmp_path / "test_local.sqlite3"
    monkeypatch.delenv("FUNPAY_DB_PATH", raising=False)
    monkeypatch.setattr(db_mod, "DB_PATH", str(test_db.name))
    monkeypatch.chdir(tmp_path)

    conn = db_mod.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1;")
        assert cursor.fetchone()[0] == 1
    finally:
        conn.close()


# 9. load_proxies preserves sorted order
def test_load_proxies_preserves_order(tmp_path):
    p_file = tmp_path / "good_proxies.txt"
    p_file.write_text("socks5://1.1.1.1:1080\nsocks5://2.2.2.2:1080\nsocks5://3.3.3.3:1080\n", encoding="utf-8")
    proxies = load_proxies(base_dir=str(tmp_path))
    assert proxies == ["socks5://1.1.1.1:1080", "socks5://2.2.2.2:1080", "socks5://3.3.3.3:1080"]


# 10. get_review_interval handles zero and negative prices
def test_get_review_interval_zero_negative():
    assert get_review_interval(0.0) is None
    assert get_review_interval(-50.0) is None
    assert get_review_interval(-1.0) is None


# 11. Chips currency regex in profile parser
@patch("funpay_analytics.harvest.profile_harvester.ProfilePageParser")
def test_profile_harvester_chips_regex(mock_parser):
    mock_parser.return_value.parse.return_value = MagicMock()
    html = """
    <div class="offer-list-title">
        <a href="https://funpay.com/chips/123/">Path of Exile \u0412\u0430\u043b\u044e\u0442\u0430</a>
    </div>
    """
    _, category_names = parse_profile(html)
    assert 123 in category_names
    assert category_names[123] == "Path of Exile \u0412\u0430\u043b\u044e\u0442\u0430"


# 12. Extract user ID from URL or raw digits
def test_extract_user_id_from_url_or_raw():
    assert extract_user_id("14273448") == "14273448"
    assert extract_user_id("https://funpay.com/users/14273448/") == "14273448"
    assert extract_user_id("https://funpay.com/users/14273448") == "14273448"
    assert extract_user_id("funpay.com/users/14273448/") == "14273448"
    assert extract_user_id("   https://funpay.com/ru/users/3/  ") == "3"
    assert extract_user_id("w1bbex") is None
    assert extract_user_id("W1bbex") is None
    assert extract_user_id("Dipper") is None
    assert extract_user_id("not-a-valid-input") is None
    assert extract_user_id("") is None


# 13. FUNPAY_COOKIES guarantees cy=rub and locale=ru
def test_funpay_cookies_currency_rub():
    assert FUNPAY_COOKIES.get("cy") == "rub"
    assert FUNPAY_COOKIES.get("locale") == "ru"


# 14. JSON importer rejects non-dict
def test_json_importer_rejects_non_dict(tmp_path):
    report_file = tmp_path / "bad_report.json"
    report_file.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="\u041e\u0436\u0438\u0434\u0430\u0435\u0442\u0441\u044f JSON \u043e\u0431\u044a\u0435\u043a\u0442 \u043f\u0440\u043e\u0434\u0430\u0432\u0446\u0430"):
        import_seller_json(str(report_file))


# 15. Dynamic DB connection env
def test_db_get_connection_dynamic_env(tmp_path, monkeypatch):
    custom_db = tmp_path / "custom_dynamic.sqlite3"
    monkeypatch.setenv("FUNPAY_DB_PATH", str(custom_db))

    conn = get_connection()
    try:
        assert custom_db.exists()
    finally:
        conn.close()


# 16. MHTML charset windows-1251 decoding
def test_extract_own_orders_charset_windows_1251(tmp_path, monkeypatch):
    monkeypatch.setenv("FUNPAY_DATA_DIR", str(tmp_path))
    cyrillic_text = bytes.fromhex("d2e5f1f2eefbe9").decode("windows-1251")
    html_content = f"""
    <html><body>
    <a class="tc-item" href="https://funpay.com/orders/TEST1234/">
        <div class="tc-order">#TEST1234</div>
        <div class="tc-title">{cyrillic_text}</div>
        <div class="tc-price">1 500 rub</div>
        <div class="tc-status text-success">OK</div>
    </a>
    </body></html>
    """

    mhtml_body = f"""From: <Saved by Blink>
Snapshot-Content-Location: https://funpay.com/orders/trade
Subject: FunPay
MIME-Version: 1.0
Content-Type: multipart/related;
\ttype="text/html";
\tboundary="----=_NextPart_000_TEST"

------=_NextPart_000_TEST
Content-Type: text/html; charset="windows-1251"
Content-Transfer-Encoding: 8bit

{html_content}
------=_NextPart_000_TEST--
"""
    mhtml_file = tmp_path / "orders.mhtml"
    mhtml_file.write_bytes(mhtml_body.encode("windows-1251"))

    soup, sha256, compressed = parse_mhtml(str(mhtml_file))
    assert cyrillic_text in str(soup)
    assert "TEST1234" in str(soup)


def test_atomic_write_json_replaces_from_distinct_temporary_files(tmp_path, monkeypatch):
    """The previous JSON remains readable until each complete replacement is ready."""
    target = tmp_path / "data.json"
    target.write_text('{"version": 0}', encoding="utf-8")
    replace = os.replace
    temporary_paths = []

    def observe_replace(source, destination):
        source = Path(source)
        assert Path(destination) == target
        assert source != target
        assert source.parent == target.parent
        assert json.loads(target.read_text(encoding="utf-8")) == {"version": len(temporary_paths)}
        assert json.loads(source.read_text(encoding="utf-8")) == {"version": len(temporary_paths) + 1}
        temporary_paths.append(source)
        replace(source, destination)

    monkeypatch.setattr("utils.os.replace", observe_replace)
    atomic_write_json(str(target), {"version": 1})
    atomic_write_json(str(target), {"version": 2})

    assert len(temporary_paths) == len(set(temporary_paths)) == 2
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 2}
    assert set(tmp_path.iterdir()) == {target}


def test_atomic_write_json_preserves_old_file_and_cleans_temp_on_replace_error(tmp_path, monkeypatch):
    target = tmp_path / "data.json"
    original = '{"version": 0}\n'
    target.write_text(original, encoding="utf-8")
    replace = MagicMock(side_effect=OSError("replacement denied"))
    monkeypatch.setattr("utils.os.replace", replace)

    atomic_write_json(str(target), {"version": 1})

    replace.assert_called_once()
    assert target.read_text(encoding="utf-8") == original
    assert set(tmp_path.iterdir()) == {target}


# 18. FUNPAY_DATA_DIR physical path synchronization
def test_funpay_data_dir_sync(tmp_path, monkeypatch):
    custom_dir = tmp_path / "custom_data"
    monkeypatch.setenv("FUNPAY_DATA_DIR", str(custom_dir))

    sha256, path_rel = save_raw_snapshot("unit_test", b"hello funpay data", "html")
    expected_file = custom_dir / "raw" / "unit_test" / f"{sha256}.html.gz"

    assert expected_file.exists()
    assert os.path.normpath(path_rel) == os.path.normpath(str(expected_file))


# 20. Orders validation skips missing title safely
def test_orders_validation_skips_without_title():
    sample_orders = [
        {"order_id": "1", "title_raw": "Valid Order", "seller_total_minor": 1000, "category_text": "Steam"},
        {"order_id": "2", "title_raw": "", "seller_total_minor": 500, "category_text": "Discord"},
        {"order_id": "3", "title_raw": "Another Valid", "seller_total_minor": 2000, "category_text": "Keys"},
    ]

    valid, errors = validate_orders(sample_orders)
    assert len(valid) == 2
    assert len(errors) == 0
    assert [o["order_id"] for o in valid] == ["1", "3"]


def test_parse_price_formats():
    assert parse_price(150) == 150.0
    assert parse_price(150.75) == 150.75
    assert parse_price(None) == 0.0
    assert parse_price("") == 0.0
    assert parse_price("1 250,50 RUB") == 1250.50
    assert parse_price("99.99 ₽") == 99.99
    assert parse_price("abc") == 0.0


def test_atomic_write_lines_unique_tmp(tmp_path, monkeypatch):
    target = tmp_path / "test.txt"
    lines = ["line1", "line2"]
    created_tmps = []
    real_replace = os.replace

    def tracked_replace(src, dst):
        created_tmps.append(str(src))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", tracked_replace)
    atomic_write_lines(str(target), lines)

    assert target.exists()
    assert target.read_text(encoding="utf-8").splitlines() == lines
    assert len(created_tmps) == 1
    assert created_tmps[0].startswith(str(target) + ".tmp.")
    assert not os.path.exists(created_tmps[0])


def test_load_proxies_merges_good_and_regular_proxies(tmp_path):
    (tmp_path / "good_proxies.txt").write_text("1.1.1.1:8080\n", encoding="utf-8")
    (tmp_path / "proxies.txt").write_text("1.1.1.1:8080\n2.2.2.2:8080\n", encoding="utf-8")
    loaded = load_proxies(base_dir=str(tmp_path))
    assert loaded == ["http://1.1.1.1:8080", "http://2.2.2.2:8080"]


def test_show_seller_main_handles_missing_report(tmp_path, monkeypatch):
    import show_seller
    from io import StringIO
    from rich.console import Console

    monkeypatch.setattr(show_seller, "BASE_DIR", tmp_path)
    monkeypatch.setattr(show_seller.time, "sleep", lambda *_: None)
    output = StringIO()
    monkeypatch.setattr(show_seller, "console", Console(file=output))
    monkeypatch.setattr("sys.argv", ["show_seller.py", "9999999999"])
    show_seller.main()
    rendered = output.getvalue()
    assert "не найден" in rendered or "Файл отчета" in rendered


def test_init_db_transactional_migration_and_duplicate_column_idempotency(tmp_path, monkeypatch):
    db_file = tmp_path / "test_migrations.sqlite3"
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "001_init.sql").write_text(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);\n"
        "ALTER TABLE items ADD COLUMN extra TEXT;\n"
        "ALTER TABLE items ADD COLUMN extra TEXT;\n",
        encoding="utf-8",
    )
    (mig_dir / "002_broken.sql").write_text(
        "ALTER TABLE items ADD COLUMN temp_col TEXT;\n"
        "INSERT INTO non_existent_table VALUES (1);\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FUNPAY_DB_PATH", str(db_file))
    monkeypatch.setattr(db_mod, "MIGRATIONS_DIR", str(mig_dir))

    with pytest.raises(Exception, match="Migration failed 002_broken.sql"):
        db_mod.init_db()

    with db_mod.get_db() as conn:
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()]
        assert versions == [1]
        cols = [r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()]
        assert "extra" in cols
        assert "temp_col" not in cols


def test_parse_price_handles_thousands_separators_and_currency_formats():
    from utils import parse_price

    assert parse_price("1,500.50 RUB") == 1500.50
    assert parse_price("1.500,50 ₽") == 1500.50
    assert parse_price("10,000") == 10000.0
    assert parse_price("10,000 ₽") == 10000.0
    assert parse_price("150,50 ₽") == 150.50
    assert parse_price("150.50") == 150.50
    assert parse_price("10 000 ₽") == 10000.0
    assert parse_price("10\xa0000,50 ₽") == 10000.50
    assert parse_price(1500) == 1500.0
    assert parse_price(1500.75) == 1500.75
    assert parse_price(None) == 0.0
    assert parse_price("") == 0.0
    assert parse_price("invalid") == 0.0


def test_atomic_write_lines_boolean_contract(tmp_path, monkeypatch):
    from utils import atomic_write_lines

    target = tmp_path / "test_lines.txt"
    assert atomic_write_lines(str(target), ["line1", "line2"]) is True
    assert target.read_text(encoding="utf-8").splitlines() == ["line1", "line2"]

    monkeypatch.setattr("utils.os.replace", lambda s, d: (_ for _ in ()).throw(OSError("disk full")))
    assert atomic_write_lines(str(target), ["fail"]) is False


def test_hide_proxy_credentials_variations():
    from utils import hide_proxy_credentials

    assert hide_proxy_credentials("socks5://user:pass@1.2.3.4:1080") == "1.2.3.4:1080"
    assert hide_proxy_credentials("http://user:pass@1.2.3.4:8080") == "1.2.3.4:8080"
    assert hide_proxy_credentials("1.2.3.4:8080:user:pass") == "1.2.3.4:8080"
    assert hide_proxy_credentials("user:pass:1.2.3.4:8080") == "1.2.3.4:8080"
    assert hide_proxy_credentials("http://1.2.3.4:8080") == "1.2.3.4:8080"
    assert hide_proxy_credentials(None) == "None"


def test_get_browser_for_proxy_impersonations():
    from utils import get_browser_for_proxy

    allowed = {"chrome110", "chrome116", "chrome120", "edge101", "chrome124"}
    for p in ["http://p1:8080", "socks5://p2:1080", "http://p3:3128", None]:
        browser = get_browser_for_proxy(p)
        assert browser in allowed
        assert "safari" not in browser


def test_json_importer_handles_currency_strings_and_missing_reply(tmp_path, monkeypatch):
    from funpay_analytics.harvest.json_importer import import_seller_json
    from funpay_analytics.storage.db import init_db, get_db

    db_path = str(tmp_path / "importer_test.sqlite3")
    monkeypatch.setenv("FUNPAY_DB_PATH", db_path)
    monkeypatch.setenv("FUNPAY_DATA_DIR", str(tmp_path / "data"))
    init_db()

    payload = {
        "schema_version": 2,
        "seller_id": "99901",
        "username": "SuperSeller",
        "currency": "RUB",
        "categories": {
            "Gems": {
                "candidate_lots": [
                    {"id": "111", "section": "Gems", "text": "100 Gems", "price": "150 ₽", "stock": 5}
                ],
                "reviews": [
                    {"rating": 5, "price": "150,00 ₽", "text": "Great!", "date": "10 мая"}
                ]
            }
        }
    }
    json_file = tmp_path / "seller.json"
    json_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    import_seller_json(str(json_file))

    with get_db() as conn:
        lot = conn.execute("SELECT id, seller_id, is_active FROM lots WHERE id=111").fetchone()
        assert lot[0] == 111
        assert lot[1] == 99901
        review = conn.execute("SELECT rating, price_minor, seller_reply FROM reviews WHERE seller_id=99901").fetchone()
        assert review[0] == 5
        assert review[1] == 15000
        assert review[2] is None


def test_json_importer_null_seller_id_conflict_avoidance(tmp_path, monkeypatch):
    from funpay_analytics.harvest.json_importer import import_seller_json
    from funpay_analytics.storage.db import init_db, get_db

    db_path = str(tmp_path / "null_conflict.sqlite3")
    monkeypatch.setenv("FUNPAY_DB_PATH", db_path)
    monkeypatch.setenv("FUNPAY_DATA_DIR", str(tmp_path / "data"))
    init_db()

    with get_db() as conn:
        conn.execute("INSERT INTO lots (id, seller_id, is_active) VALUES (222, NULL, 1)")
        conn.commit()

    payload = {
        "schema_version": 2,
        "seller_id": "88802",
        "username": "OwnerSeller",
        "currency": "RUB",
        "categories": {
            "Coins": {
                "candidate_lots": [
                    {"id": "222", "section": "Coins", "text": "Gold Coin", "price": 50.0}
                ],
                "reviews": []
            }
        }
    }
    json_file = tmp_path / "seller_claim.json"
    json_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    import_seller_json(str(json_file))

    with get_db() as conn:
        lot = conn.execute("SELECT id, seller_id FROM lots WHERE id=222").fetchone()
        assert lot[1] == 88802


def test_extract_profile_lots_and_matching():
    from parser import extract_profile_lots, match_and_filter_lots

    html = """
    <div class="mb20">
        <div class="offer">
            <div class="offer-list-title">Telegram Premium</div>
            <a class="tc-item" href="https://funpay.com/lots/offer?id=777123">
                <div class="tc-desc">Premium 1 Year</div>
                <div class="tc-price">1 000 ₽</div>
                <div class="tc-amount">10 шт.</div>
            </a>
        </div>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    lots = extract_profile_lots(soup, "12345")
    assert len(lots) == 1
    assert lots[0]["id"] == "777123"
    assert lots[0]["price"] == 1000.0
    assert lots[0]["stock"] == 10

    categories_reviews = {
        "Telegram": [{"price": 1000.0, "rating": 5, "text": "ok", "reply": None, "date": "1 мая"}]
    }
    categories = match_and_filter_lots(lots, categories_reviews)
    assert "Telegram" in categories
    assert len(categories["Telegram"]["candidate_lots"]) >= 1


def test_parse_worker_single_bad_seller_does_not_abort_subsequent_queue(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    import parser as fp_parser
    from parser import parse_worker

    monkeypatch.setattr(fp_parser, "BASE_DIR", str(tmp_path))

    async def _run():
        queue = asyncio.Queue()
        queue.put_nowait("bad_seller")
        queue.put_nowait("good_seller")

        library = {}
        stats = {"parsed_count": 0, "total_reviews": 0, "errors": 0, "proxy_success": {}, "failed_count": 0}
        retry_map = {}

        async def fake_parse_profile(client, uid, *args, **kwargs):
            if uid == "bad_seller":
                return None
            return {"total_reviews": 5, "categories": {}}

        with patch("parser.parse_profile", side_effect=fake_parse_profile):
            with patch("parser.requests.AsyncSession") as mock_session_cls:
                mock_session = AsyncMock()
                mock_session.__aenter__.return_value = mock_session
                mock_session_cls.return_value = mock_session
                with patch("parser.atomic_write_json", return_value=True):
                    with patch("parser.asyncio.sleep", new=AsyncMock()):
                        await parse_worker(1, "test-ip", "http://fake-proxy:8080", queue, [], library, stats, retry_map)

        assert library["bad_seller"]["status"] == "failed"
        assert library["good_seller"]["status"] == "completed"
        assert stats["parsed_count"] == 1
        assert queue.empty()

    asyncio.run(_run())


def test_fetch_ids_bad_rmthub_file_cleansed_on_recovery(tmp_path):
    from fetch_ids import mark_proxy

    base_dir = str(tmp_path)
    good_proxies = set()
    bad_proxies = {"http://recovered-proxy:8080", "http://still-bad:8080"}
    pool = ["http://recovered-proxy:8080"]

    (tmp_path / "bad_rmthub.txt").write_text("http://recovered-proxy:8080\nhttp://still-bad:8080\n", encoding="utf-8")

    mark_proxy("http://recovered-proxy:8080", "good", base_dir, good_proxies, bad_proxies, pool)

    assert "http://recovered-proxy:8080" in good_proxies
    assert "http://recovered-proxy:8080" not in bad_proxies
    bad_lines = (tmp_path / "bad_rmthub.txt").read_text(encoding="utf-8").splitlines()
    assert "http://recovered-proxy:8080" not in bad_lines
    assert "http://still-bad:8080" in bad_lines


def test_price_minor_currency_abbreviation_with_dot():
    from funpay_analytics.harvest.json_importer import _to_price_minor
    from utils import parse_price

    assert _to_price_minor("50,25 руб.") == 5025
    assert _to_price_minor("50.25 руб.") == 5025
    assert _to_price_minor("1,500.50 руб.") == 150050
    assert _to_price_minor("10,000 руб.") == 1000000
    assert _to_price_minor("50,25 р.") == 5025
    assert _to_price_minor("10.50 руб.") == 1050

    assert parse_price("50,25 руб.") == 50.25
    assert parse_price("50.25 руб.") == 50.25
    assert parse_price("1,500.50 руб.") == 1500.50
    assert parse_price("10,000 руб.") == 10000.0


def test_profile_harvester_data_s_prefers_tc_price_over_tc_amount(tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch
    import funpay_analytics.storage.db as db_module
    from funpay_analytics.harvest.profile_harvester import import_profile_from_file

    test_db = str(tmp_path / "test_data_s.sqlite3")
    test_data = str(tmp_path / "test_data_s_dir")
    monkeypatch.setenv("FUNPAY_DB_PATH", test_db)
    monkeypatch.setenv("FUNPAY_DATA_DIR", test_data)
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    db_module.init_db()

    mock_profile = MagicMock()
    mock_profile.user_id = 771122
    mock_profile.username = "TestSeller"
    mock_profile.status_text = "Online"
    mock_profile.registration_date_text = "1 января 2024"
    mock_profile.rating = None

    mock_offer = MagicMock()
    mock_offer.id = "8888"
    mock_offer.title = "1000 Gold"
    mock_offer.price = MagicMock(value=0.5)
    mock_offer.raw_source = '<a class="tc-item"><div class="tc-amount" data-s="50000">50,000 шт.</div><div class="tc-price" data-s="0.5">0.50 ₽</div></a>'
    mock_offer.auto_delivery = False

    mock_profile.offers = {"chips": {777: [mock_offer]}}

    html_file = tmp_path / "profile_chips.html"
    html_file.write_text("<html><body></body></html>", encoding="utf-8")

    with patch("funpay_analytics.harvest.profile_harvester.ProfilePageParser") as mock_parser_cls:
        mock_parser = MagicMock()
        mock_parser.parse.return_value = mock_profile
        mock_parser_cls.return_value = mock_parser

        seller_id, count = import_profile_from_file(str(html_file))
        assert seller_id == 771122
        assert count == 1

    with db_module.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data_s_decimal FROM lot_snapshots WHERE lot_id=8888")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "0.5"


def test_markup_escape_prevents_rich_errors(tmp_path, monkeypatch):
    import show_seller
    from io import StringIO
    from rich.console import Console

    test_console = Console(file=StringIO(), force_terminal=False)
    monkeypatch.setattr(show_seller, "console", test_console)

    untrusted_strings = [
        "[/bold]",
        "[bold red]error[/bold red]",
        "User[123]",
        "[/a][/b]",
        "{'key': [1, 2, 3]}",
    ]

    for idx, s in enumerate(untrusted_strings, 1):
        report_file = tmp_path / f"seller_{idx}.json"
        report_file.write_text(
            json.dumps({"username": s, "total_reviews": 1, "categories": {}, "source": "json"}),
            encoding="utf-8",
        )
        monkeypatch.setattr("sys.argv", ["show_seller.py", str(report_file)])
        show_seller.main()


def test_mark_proxy_atomic_write_failure_preserves_state(tmp_path, monkeypatch):
    import fetch_ids

    monkeypatch.setattr(fetch_ids, "atomic_write_lines", lambda *args, **kwargs: False)
    good_proxies = {"http://p1:8080"}
    bad_proxies = {"http://p2:8080"}
    pool = ["http://p1:8080"]

    # Trying to mark p2 as good when disk write fails must not discard it from memory
    fetch_ids.mark_proxy("http://p2:8080", "good", str(tmp_path), good_proxies, bad_proxies, pool)
    assert "http://p2:8080" in bad_proxies
    assert "http://p2:8080" not in good_proxies


def test_library_read_error_aborts_without_overwriting(tmp_path, monkeypatch):
    import parser as fp_parser

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fp_parser, "BASE_DIR", str(tmp_path))
    lib_file = tmp_path / "library_v2.json"
    original_content = '["not", "a", "dict"]'
    lib_file.write_text(original_content, encoding="utf-8")

    success = asyncio.run(fp_parser.main_async())
    assert success is False
    assert lib_file.read_text(encoding="utf-8") == original_content


def test_main_async_returns_false_on_interruption(tmp_path, monkeypatch):
    import parser as fp_parser

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fp_parser, "BASE_DIR", str(tmp_path))

    async def raise_interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(fp_parser, "mass_parse", raise_interrupt)
    success = asyncio.run(fp_parser.main_async())
    assert success is False


def test_parse_worker_waits_for_peer_reenqueued_tasks(tmp_path, monkeypatch):
    import parser as fp_parser
    from unittest.mock import AsyncMock, patch

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fp_parser, "BASE_DIR", str(tmp_path))

    async def _run():
        queue = asyncio.Queue()
        library = {}
        stats = {"parsed_count": 0, "total_reviews": 0, "errors": 0, "proxy_success": {}, "failed_count": 0}
        retry_map = {}
        active_workers = [1]  # Simulate peer worker currently in-flight

        async def fake_parse_profile(client, uid, *args, **kwargs):
            return {"total_reviews": 10, "categories": {}}

        async def peer_simulator():
            await asyncio.sleep(0.05)
            queue.put_nowait("seller_delayed")
            active_workers[0] = 0

        with patch("parser.parse_profile", side_effect=fake_parse_profile):
            with patch("parser.requests.AsyncSession") as mock_session_cls:
                mock_session = AsyncMock()
                mock_session.__aenter__.return_value = mock_session
                mock_session_cls.return_value = mock_session
                with patch("parser.atomic_write_json", return_value=True):
                    with patch("parser.asyncio.sleep", new=AsyncMock()):
                        worker_task = asyncio.create_task(
                            fp_parser.parse_worker(1, "test-ip", None, queue, [], library, stats, retry_map, active_workers)
                        )
                        await peer_simulator()
                        await worker_task

        assert "seller_delayed" in library
        assert library["seller_delayed"]["status"] == "completed"

    asyncio.run(_run())


def test_fetch_page_retries_on_empty_200_ok(tmp_path, monkeypatch):
    import fetch_ids
    from unittest.mock import AsyncMock, patch

    call_count = 0

    class MockResp:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.text = text

    async def fake_get(url):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # 200 OK challenge page with no seller links
            return MockResp(200, "<html><body><div>Verification required</div></body></html>")
        # 200 OK real page
        return MockResp(200, '<html><body><a href="/ru/funpay/99999"><span class="MuiChip-label">50</span></a></body></html>')

    async def _run():
        sem = asyncio.Semaphore(1)
        good_proxies = set()
        bad_proxies = set()
        pool = ["http://p1:8080"]

        mock_session = AsyncMock()
        mock_session.get.side_effect = fake_get
        mock_session.__aenter__.return_value = mock_session

        with patch("fetch_ids.requests.AsyncSession", return_value=mock_session):
            with patch("fetch_ids.asyncio.sleep", new=AsyncMock()):
                with patch("fetch_ids.atomic_write_lines", return_value=True):
                    res = await fetch_ids.fetch_page(1, pool, good_proxies, bad_proxies, str(tmp_path), sem)

        assert res == [("99999", 50)]
        assert call_count == 2

    asyncio.run(_run())


def test_parse_profile_handles_malformed_reviews_markup():
    from unittest.mock import patch, MagicMock, AsyncMock
    import parser as fp_parser

    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '<html><body><span class="mr4">TestSeller</span></body></html>'
    mock_client.get.return_value = mock_resp

    with patch("parser.ReviewsParser") as mock_reviews_cls:
        mock_parser = MagicMock()
        mock_parser.parse.side_effect = IndexError("Malformed review node list")
        mock_reviews_cls.return_value = mock_parser

        res = asyncio.run(fp_parser.parse_profile(mock_client, "123456"))
        assert res is None


def test_proxy_credentials_numeric_password_preserves_ip_and_port(tmp_path):
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("user:123456:1.2.3.4:8080\n", encoding="utf-8")
    loaded = load_proxies(base_dir=str(tmp_path))
    assert loaded == ["socks5://user:123456@1.2.3.4:8080"]
    hidden = hide_proxy_credentials(loaded[0])
    assert hidden == "1.2.3.4:8080"
    assert "123456" not in hidden


def test_init_db_immediate_transaction(tmp_path, monkeypatch):
    test_db = tmp_path / "test_init_db.sqlite3"
    monkeypatch.setenv("FUNPAY_DB_PATH", str(test_db))
    db_mod.init_db()
    with db_mod.get_connection() as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "schema_migrations" in tables
        assert "sellers" in tables
        assert "lots" in tables
        assert "raw_snapshots" in tables


def test_raw_lake_save_snapshot_deduplication(tmp_path, monkeypatch):
    from funpay_analytics.storage.raw_lake import save_raw_snapshot
    import gzip

    monkeypatch.setenv("FUNPAY_DATA_DIR", str(tmp_path))
    content = b"sample raw test payload"
    sha1, path1 = save_raw_snapshot("test_source", content, "json")
    sha2, path2 = save_raw_snapshot("test_source", content, "json")

    assert sha1 == sha2
    assert path1 == path2
    file_path = tmp_path / "raw" / "test_source" / f"{sha1}.json.gz"
    assert file_path.exists()
    assert gzip.decompress(file_path.read_bytes()) == content


def test_json_importer_null_reviews_and_string_lot_id(tmp_path, monkeypatch):
    test_db = tmp_path / "test_json.sqlite3"
    monkeypatch.setenv("FUNPAY_DB_PATH", str(test_db))
    monkeypatch.setenv("FUNPAY_DATA_DIR", str(tmp_path))
    db_mod.init_db()

    payload = {
        "schema_version": 2,
        "seller_id": "777888",
        "username": "SellerNullTest",
        "currency": "RUB",
        "categories": {
            "Telegram": {
                "candidate_lots": [
                    {
                        "id": "100500",
                        "section": "Telegram",
                        "text": "Telegram Premium",
                        "price": "250,50 руб."
                    }
                ],
                "reviews": None
            }
        }
    }
    json_file = tmp_path / "seller_null.json"
    json_file.write_text(json.dumps(payload), encoding="utf-8")

    snapshot_id = import_seller_json(str(json_file))
    assert snapshot_id > 0

    with db_mod.get_connection() as conn:
        lot = conn.execute("SELECT id, seller_id FROM lots WHERE id=100500").fetchone()
        assert lot is not None
        assert lot["id"] == 100500
        assert lot["seller_id"] == 777888


def test_extract_own_orders_mixed_separators_and_title_validation():
    from bs4 import BeautifulSoup
    from funpay_analytics.normalize.extract_own_orders import extract_orders, validate_orders

    html = """
    <a class="tc-item" href="https://funpay.com/orders/TESTCOMMAS/">
        <div class="tc-order">#TESTCOMMAS</div>
        <div class="order-desc">
            <div>Discord Nitro 1 Year</div>
            <div class="text-muted">Discord</div>
        </div>
        <div class="tc-price tc-seller-sum"> 1,234.56 <span class="unit">rub</span></div>
    </a>
    <a class="tc-item" href="https://funpay.com/orders/TESTNOTITLE/">
        <div class="tc-order">#TESTNOTITLE</div>
        <div class="order-desc">
            <div></div>
            <div class="text-muted">Empty</div>
        </div>
        <div class="tc-price tc-seller-sum"> 50.00 <span class="unit">rub</span></div>
    </a>
    """
    soup = BeautifulSoup(html, "html.parser")
    orders = extract_orders(soup)
    assert len(orders) == 2
    assert orders[0]["seller_total_minor"] == 123456

    valid, errors = validate_orders(orders)
    assert len(valid) == 1
    assert valid[0]["order_id"] == "TESTCOMMAS"
    assert len(errors) == 0


def test_mark_proxy_error_threshold_retries(tmp_path):
    import fetch_ids

    good_proxies = set()
    bad_proxies = set()
    pool = ["http://proxy1:8080"]
    proxy_errors = {}

    fetch_ids.mark_proxy("http://proxy1:8080", "bad", str(tmp_path), good_proxies, bad_proxies, pool, proxy_errors, permanent=False)
    assert "http://proxy1:8080" not in bad_proxies
    assert proxy_errors["http://proxy1:8080"] == 1

    fetch_ids.mark_proxy("http://proxy1:8080", "bad", str(tmp_path), good_proxies, bad_proxies, pool, proxy_errors, permanent=False)
    assert "http://proxy1:8080" not in bad_proxies
    assert proxy_errors["http://proxy1:8080"] == 2

    fetch_ids.mark_proxy("http://proxy1:8080", "bad", str(tmp_path), good_proxies, bad_proxies, pool, proxy_errors, permanent=False)
    assert "http://proxy1:8080" in bad_proxies


def test_match_and_filter_lots_special_chars_category_does_not_match_all():
    from parser import match_and_filter_lots

    lots = [
        {"section": "Steam Keys", "price": 100.0, "title": "Game key"},
        {"section": "Discord Nitro", "price": 200.0, "title": "Nitro subscription"},
    ]
    categories_reviews = {
        "***": [{"price": 100.0, "date": "1 day ago"}],
    }

    filtered = match_and_filter_lots(lots, categories_reviews)
    assert "***" in filtered
    assert len(filtered["***"]["candidate_lots"]) == 0


def test_core_package_exports_and_imports():
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

    assert len(IMPERSONATES) > 0
    assert callable(get_browser_for_proxy)
    assert callable(hide_proxy_credentials)
    assert logger is not None
    assert callable(normalize_proxy)
    assert callable(setup_file_logging)
    assert callable(parse_price)
    assert callable(load_proxies)
    assert callable(atomic_write_json)
    assert callable(atomic_write_lines)
    assert is_running_under_pytest() is True
    assert extract_user_id("seller_12345.json") == "12345"


def test_load_proxies_deduplicates_raw_and_normalized(tmp_path):
    p_file = tmp_path / "proxies.txt"
    p_file.write_text("1.2.3.4:8080:user:pass\n", encoding="utf-8")
    g_file = tmp_path / "good_proxies.txt"
    g_file.write_text("socks5://user:pass@1.2.3.4:8080\n", encoding="utf-8")

    proxies = load_proxies(base_dir=str(tmp_path))
    assert len(proxies) == 1
    assert proxies[0] == "socks5://user:pass@1.2.3.4:8080"


def test_logging_setup_file_logging_skips_under_pytest(tmp_path):
    from funpay_analytics.core.logging import setup_file_logging

    log_dir = tmp_path / "test_logs"
    setup_file_logging(log_dir)
    assert not (log_dir / "parser.log").exists()


def test_price_minor_and_parse_price_units_and_formats():
    from funpay_analytics.core import parse_price, to_price_minor

    # Units with slash
    assert to_price_minor("10 руб. / 1 шт.") == 1000
    assert parse_price("10 руб. / 1 шт.") == 10.0

    # Multiple dots (European format)
    assert to_price_minor("1.500.50") == 150050
    assert parse_price("1.500.50") == 1500.50

    # Boolean protection
    with pytest.raises(ValueError, match="boolean"):
        to_price_minor(True)
    with pytest.raises(ValueError, match="boolean"):
        to_price_minor(False)
    assert parse_price(True) == 0.0
    assert parse_price(False) == 0.0

    # Normal prices
    assert to_price_minor("250.00 ₽") == 25000
    assert parse_price("250.00 ₽") == 250.0


def test_seller_summary_from_db_deduplicates_multiple_historical_snapshots():
    from funpay_analytics.models import SellerSummary
    from funpay_analytics.storage.db import get_db, init_db

    init_db()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sellers (id, name, rating, reviews_count) VALUES (901, 'MultiSnap', 5.0, 2)")

        # Snapshot 1
        cursor.execute(
            "INSERT INTO raw_snapshots (id, source_type, seller_id, external_id, content_sha256) VALUES (91, 'seller_snapshot_v2', 901, '901', 'sha_snap_91')"
        )
        cursor.execute(
            "INSERT INTO reviews (raw_snapshot_id, review_index, seller_id, category_text, price_minor, rating) VALUES (91, 0, 901, 'Keys', 10000, 5)"
        )

        # Snapshot 2 (updated reviews for the same seller)
        cursor.execute(
            "INSERT INTO raw_snapshots (id, source_type, seller_id, external_id, content_sha256) VALUES (92, 'seller_snapshot_v2', 901, '901', 'sha_snap_92')"
        )
        cursor.execute(
            "INSERT INTO reviews (raw_snapshot_id, review_index, seller_id, category_text, price_minor, rating) VALUES (92, 0, 901, 'Keys', 15000, 5)"
        )
        cursor.execute(
            "INSERT INTO reviews (raw_snapshot_id, review_index, seller_id, category_text, price_minor, rating) VALUES (92, 1, 901, 'Keys', 25000, 5)"
        )
        conn.commit()

        summary = SellerSummary.from_db(conn, 901)
        assert summary is not None
        assert len(summary.categories) == 1
        # Only snapshot 92 should be counted: 150 + 250 = 400.0 RUB (2 reviews), NOT 100 + 150 + 250 = 500.0 RUB (3 reviews)
        assert summary.categories[0].review_count == 2
        assert summary.categories[0].total_rub == 400.0


def test_seller_summary_from_db_html_profile_fallback_for_lots():
    from funpay_analytics.models import SellerSummary
    from funpay_analytics.storage.db import get_db, init_db

    init_db()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sellers (id, name, rating, reviews_count) VALUES (902, 'HtmlSeller', 4.8, 0)")
        cursor.execute(
            "INSERT INTO raw_snapshots (id, source_type, seller_id, external_id, content_sha256) VALUES (93, 'profile', 902, '902', 'sha_snap_93')"
        )
        cursor.execute("INSERT INTO lots (id, seller_id, category_id) VALUES (5001, 902, '10')")
        cursor.execute("INSERT INTO lots (id, seller_id, category_id) VALUES (5002, 902, '10')")
        cursor.execute(
            """
            INSERT INTO lot_snapshots (lot_id, seller_id, native_section_name, title_raw, visible_price_minor, raw_snapshot_id)
            VALUES (5001, 902, 'Steam Gifts', 'Gift 1', 5000, 93)
            """
        )
        cursor.execute(
            """
            INSERT INTO lot_snapshots (lot_id, seller_id, native_section_name, title_raw, visible_price_minor, raw_snapshot_id)
            VALUES (5002, 902, 'Steam Gifts', 'Gift 2', 8000, 93)
            """
        )
        conn.commit()

        summary = SellerSummary.from_db(conn, 902)
        assert summary is not None
        assert len(summary.categories) == 1
        assert summary.categories[0].name == "Steam Gifts"
        assert summary.categories[0].lot_count == 2


def test_seller_summary_from_dict_preserves_rating():
    from funpay_analytics.models import SellerSummary

    data = {
        "seller_id": "4444",
        "username": "RatedSeller",
        "rating": 4.85,
        "categories": {},
    }
    summary = SellerSummary.from_dict(data)
    assert summary.rating == 4.85


def test_profile_harvester_conflict_owner_raises_error(tmp_path, monkeypatch):
    from unittest.mock import patch
    from funpay_analytics.storage.db import get_db, init_db
    from funpay_analytics.harvest.profile_harvester import import_profile_from_file

    init_db()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sellers (id, name) VALUES (111, 'Owner1')")
        cursor.execute("INSERT INTO sellers (id, name) VALUES (222, 'Owner2')")
        cursor.execute("INSERT INTO lots (id, seller_id, is_active) VALUES (77777, 111, 1)")
        conn.commit()

    html_file = tmp_path / "profile_conflict.html"
    html_file.write_text("<html><body><div class='offer-list-title'><a>Games</a></div></body></html>", encoding="utf-8")

    from types import SimpleNamespace
    mock_offer = SimpleNamespace(
        id="77777",
        title="Conflict Item",
        price=SimpleNamespace(value=100),
        raw_source=None,
        auto_delivery=False,
    )
    mock_parsed = SimpleNamespace(
        user_id=222,  # Different seller attempting to claim lot 77777
        username="Owner2",
        status_text="Online",
        registration_date_text="Today",
        rating=None,
        offers={"game": {1: [mock_offer]}},
    )

    with patch("funpay_analytics.harvest.profile_harvester.ProfilePageParser") as mock_parser_cls:
        mock_parser_instance = mock_parser_cls.return_value
        mock_parser_instance.parse.return_value = mock_parsed

        with pytest.raises(ValueError, match="Конфликт владельца: лот 77777 уже принадлежит продавцу 111"):
            import_profile_from_file(str(html_file))


def test_raw_lake_save_snapshot_string_content_signature_a():
    from funpay_analytics.storage.raw_lake import save_raw_snapshot

    sha256, path_rel = save_raw_snapshot("seller_snapshot_v2", "888", '{"status": "ok", "items": [1, 2, 3]}', "json")
    assert len(sha256) == 64
    assert path_rel.endswith(".json.gz")


def test_raw_lake_path_traversal_sanitization():
    from funpay_analytics.storage.raw_lake import save_raw_snapshot

    sha256, path_rel = save_raw_snapshot("../../evil_dir", b"clean payload", "../../bad.ext")
    assert len(sha256) == 64
    assert "evil_dir" in path_rel
    assert ".." not in path_rel
    assert path_rel.endswith(".badext.gz")


def test_fetch_ids_mark_proxy_cleans_good_rmthub_file(tmp_path):
    from fetch_ids import mark_proxy

    good_file = tmp_path / "good_rmthub.txt"
    bad_file = tmp_path / "bad_rmthub.txt"
    good_file.write_text("http://p1:8080\nhttp://p2:8080\n", encoding="utf-8")

    good_proxies = {"http://p1:8080", "http://p2:8080"}
    bad_proxies = set()
    pool = ["http://p1:8080", "http://p2:8080"]

    mark_proxy("http://p1:8080", "bad", str(tmp_path), good_proxies, bad_proxies, pool, permanent=True)

    assert "http://p1:8080" not in good_proxies
    assert "http://p1:8080" in bad_proxies
    assert "http://p1:8080" not in good_file.read_text(encoding="utf-8")
    assert "http://p1:8080" in bad_file.read_text(encoding="utf-8")


def test_fetch_ids_reset_queue_ignores_existing_queue_file(tmp_path):
    import fetch_ids

    q_file = tmp_path / "queue.txt"
    q_file.write_text("999999:10\n", encoding="utf-8")

    async def _test():
        with patch("fetch_ids.load_proxies", return_value=[]):
            with patch("fetch_ids.fetch_page", new=AsyncMock(return_value=[("12345", 50)])):
                await fetch_ids.main(target_count=20, reset_queue=True)

    with patch("fetch_ids.os.path.dirname", return_value=str(tmp_path)):
        asyncio.run(_test())

    content = q_file.read_text(encoding="utf-8")
    assert "12345:50" in content
    assert "999999" not in content


def test_runner_parse_worker_guarantees_cleanup_on_cancel():
    from funpay_analytics.engine.runner import parse_worker

    queue = asyncio.Queue()
    queue.put_nowait("111")
    active_workers = [0]

    async def cancelled_parser(*args, **kwargs):
        raise asyncio.CancelledError()

    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session_cls = MagicMock(return_value=mock_session)

    async def _run():
        task = asyncio.create_task(
            parse_worker(
                1,
                "Direct",
                None,
                queue,
                [],
                {},
                {},
                active_workers=active_workers,
                profile_parser=cancelled_parser,
                session_cls=mock_session_cls,
            )
        )
        await asyncio.sleep(0.01)
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
    assert active_workers[0] == 0


def test_runner_mass_parse_propagates_base_dir_to_worker(tmp_path):
    from funpay_analytics.engine.runner import mass_parse

    q_file = tmp_path / "queue.txt"
    q_file.write_text("222:1\n", encoding="utf-8")

    passed_base_dirs = []

    async def mock_worker(*args, **kwargs):
        passed_base_dirs.append(args[9] if len(args) > 9 else kwargs.get("base_dir"))
        queue = args[3]
        queue.get_nowait()
        queue.task_done()

    async def _run():
        await mass_parse(
            {},
            {},
            base_dir=str(tmp_path),
            worker_fn=mock_worker,
            ranker=AsyncMock(return_value=[{"name": "Local", "url": None}]),
            proxy_loader=lambda: [],
        )

    asyncio.run(_run())
    assert len(passed_base_dirs) == 1
    assert passed_base_dirs[0] == str(tmp_path)


def test_client_parse_profile_retries_on_transient_network_error():
    from funpay_analytics.scraper.client import parse_profile

    mock_client = AsyncMock()
    call_count = [0]

    async def mock_get(url, *args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("curl: (28) Connection timeout")
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "<html><span class='mr4'>TestUser</span></html>"
        return resp

    mock_client.get = mock_get

    async def _run():
        mock_p = MagicMock()
        mock_p.return_value.parse.return_value = MagicMock(user_id=123)
        with patch("funpay_analytics.scraper.client.asyncio.sleep", new=AsyncMock()):
            with patch("funpay_analytics.scraper.client.extract_profile_lots", return_value=[]):
                with patch("funpay_analytics.scraper.client.fetch_seller_reviews", return_value=({}, 0)):
                    return await parse_profile(mock_client, "123", reviews_parser_cls=mock_p)

    res = asyncio.run(_run())
    assert res is not None
    assert res["username"] == "TestUser"
    assert call_count[0] == 2


def test_client_sec_ch_ua_platform_matches_user_agent():
    from funpay_analytics.scraper.client import parse_profile

    captured_headers = []
    mock_client = AsyncMock()

    async def mock_get(url, *args, **kwargs):
        captured_headers.append(kwargs.get("headers", {}))
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "<html><span class='mr4'>MacUser</span></html>"
        return resp

    mock_client.get = mock_get

    async def _run():
        mac_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        mock_p = MagicMock()
        mock_p.return_value.parse.return_value = MagicMock(user_id=123)
        with patch("funpay_analytics.scraper.client.extract_profile_lots", return_value=[]):
            with patch("funpay_analytics.scraper.client.fetch_seller_reviews", return_value=({}, 0)):
                await parse_profile(mock_client, "123", user_agent=mac_ua, reviews_parser_cls=mock_p)

    asyncio.run(_run())
    assert len(captured_headers) == 1
    assert captured_headers[0]["Sec-Ch-Ua-Platform"] == '"macOS"'


def test_client_parse_profile_does_not_treat_port_40400_as_http_404():
    from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError
    from funpay_analytics.scraper.client import parse_profile

    mock_client = AsyncMock()
    attempts = [0]

    async def mock_get(url, *args, **kwargs):
        attempts[0] += 1
        if attempts[0] == 1:
            raise CurlConnectionError("Failed to connect to 127.0.0.1 port 40400", code=7)
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "<html><span class='mr4'>RecoveredUser</span></html>"
        return resp

    mock_client.get = mock_get

    async def _run():
        mock_p = MagicMock()
        mock_p.return_value.parse.return_value = MagicMock(user_id=123)
        with patch("funpay_analytics.scraper.client.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            with patch("funpay_analytics.scraper.client.extract_profile_lots", return_value=[]):
                with patch("funpay_analytics.scraper.client.fetch_seller_reviews", return_value=({}, 0)):
                    res = await parse_profile(mock_client, "123", reviews_parser_cls=mock_p)
                    return res, mock_sleep.call_count

    res, sleep_calls = asyncio.run(_run())
    assert res is not None
    assert res["username"] == "RecoveredUser"
    assert attempts[0] == 2
    assert sleep_calls == 1


def test_client_parse_profile_404_does_not_retry_and_429_backs_off():
    from funpay_analytics.scraper.client import parse_profile

    mock_client = AsyncMock()
    calls_404 = [0]

    async def mock_get_404(url, *args, **kwargs):
        calls_404[0] += 1
        resp = MagicMock()
        resp.status_code = 404
        return resp

    mock_client.get = mock_get_404
    res_404 = asyncio.run(parse_profile(mock_client, "404"))
    assert res_404 is None
    assert calls_404[0] == 1

    calls_429 = [0]

    async def mock_get_429(url, *args, **kwargs):
        calls_429[0] += 1
        resp = MagicMock()
        resp.status_code = 429
        return resp

    mock_client.get = mock_get_429
    sleep_delays = []

    async def fake_sleep(delay):
        sleep_delays.append(delay)

    with patch("funpay_analytics.scraper.client.asyncio.sleep", side_effect=fake_sleep):
        res_429 = asyncio.run(parse_profile(mock_client, "429"))
    assert res_429 is None
    assert calls_429[0] == 2
    assert sleep_delays == [5.0]


def test_browser_profile_user_agent_and_sec_ch_ua_match_impersonate():
    from funpay_analytics.core.proxies import IMPERSONATES, get_sec_ch_ua, get_user_agent_for_browser

    for browser in IMPERSONATES:
        ua_win = get_user_agent_for_browser(browser, platform="Windows")
        sec = get_sec_ch_ua(user_agent=ua_win)
        if browser.startswith("edge"):
            ver = browser.replace("edge", "")
            assert f"Edg/{ver}" in ua_win
            assert "Microsoft Edge" in sec
            assert f'v="{ver}"' in sec
        else:
            ver = browser.replace("chrome", "")
            assert f"Chrome/{ver}" in ua_win
            assert "Google Chrome" in sec
            assert f'v="{ver}"' in sec


def test_init_db_fails_explicitly_when_migrations_missing(tmp_path, monkeypatch):
    from funpay_analytics.storage import db as storage_db

    empty_migrations = tmp_path / "empty_migrations"
    empty_migrations.mkdir()
    monkeypatch.setattr(storage_db, "MIGRATIONS_DIR", str(empty_migrations))
    monkeypatch.setenv("FUNPAY_DB_PATH", str(tmp_path / "test.sqlite3"))

    with pytest.raises(RuntimeError, match="No SQL migration files found"):
        storage_db.init_db()


def test_run_pipeline_returns_false_when_queue_file_missing(tmp_path, monkeypatch):
    import parser as fp_parser

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fp_parser, "BASE_DIR", str(tmp_path))

    # Intentionally do NOT create queue.txt
    reports_dir = tmp_path / "reports_v2"
    reports_dir.mkdir()
    existing_report = tmp_path / "market_report_v2.json"
    existing_report.write_text('[{"sentinel": true}]', encoding="utf-8")

    ok = asyncio.run(fp_parser.run_pipeline(base_dir=str(tmp_path)))
    assert ok is False
    assert existing_report.read_text(encoding="utf-8") == '[{"sentinel": true}]'







