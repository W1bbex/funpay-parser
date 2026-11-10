import email
import email.policy
import json
import os
import tempfile
from io import StringIO
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

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
def test_parse_plain_html(tmp_path):
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
def test_extract_own_orders_charset_windows_1251(tmp_path):
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


def test_show_seller_module_syntax():
    import show_seller
    assert hasattr(show_seller, "main")


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


