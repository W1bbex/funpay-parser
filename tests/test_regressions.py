import email
import email.policy
import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

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
    extract_user_id,
    hide_proxy_credentials,
    load_proxies,
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


# 7. price: null sum safety
def test_price_null_sum_safety():
    revs = [
        {"price": 100.0},
        {"price": None},
        {"price": 50.0},
        {"other": 10.0},
    ]
    ernd = sum(float(r.get("price") or 0.0) for r in revs if isinstance(r, dict))
    assert ernd == 150.0


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


# 17. Atomic write JSON cleans up temporary files
def test_atomic_write_json_unique_tmp():
    with tempfile.TemporaryDirectory(prefix="funpay-atomic-") as td:
        target_file = Path(td) / "data.json"
        sample = {"users": [1, 2, 3], "status": "ok"}
        atomic_write_json(str(target_file), sample)

        assert target_file.exists()
        loaded = json.loads(target_file.read_text(encoding="utf-8"))
        assert loaded == sample


# 18. FUNPAY_DATA_DIR physical path synchronization
def test_funpay_data_dir_sync(tmp_path, monkeypatch):
    custom_dir = tmp_path / "custom_data"
    monkeypatch.setenv("FUNPAY_DATA_DIR", str(custom_dir))

    sha256, path_rel = save_raw_snapshot("unit_test", b"hello funpay data", "html")
    expected_file = custom_dir / "raw" / "unit_test" / f"{sha256}.html.gz"

    assert expected_file.exists()
    assert os.path.normpath(path_rel) == os.path.normpath(str(expected_file))


# 19. Max reviews batch limit
def test_max_reviews_batch_first_page_limit():
    batch_reviews = [
        MagicMock(date_text="2026-01-01", category_str="Keys", order_total=MagicMock(value="10.0"), rating=5, text="ok", reply=None)
        for _ in range(25)
    ]

    total_reviews = 0
    categories_reviews = {}
    max_reviews = 10

    def process_batch(reviews):
        nonlocal total_reviews
        count = 0
        for review in reviews:
            if max_reviews and total_reviews >= max_reviews:
                break
            category = review.category_str or "\u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u043e"
            if category not in categories_reviews:
                categories_reviews[category] = []
            categories_reviews[category].append(review)
            total_reviews += 1
            count += 1
        return count

    added = process_batch(batch_reviews)
    assert added == 10
    assert total_reviews == 10


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
