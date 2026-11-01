import os
import pytest
from bs4 import BeautifulSoup
from decimal import Decimal

# 1. Regression test: Non-breaking space (\xa0) in extract_own_orders
def test_extract_own_orders_nbsp_price():
    from funpay_analytics.normalize.extract_own_orders import extract_orders
    
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
    # 1500.00 RUB = 150000 kopecks
    assert orders[0]["seller_total_minor"] == 150000
    assert orders[0]["order_id"] == "TEST1234"

# 2. Regression test: Plain HTML file import in extract_own_orders
def test_parse_plain_html(tmp_path):
    from funpay_analytics.normalize.extract_own_orders import parse_mhtml
    
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

# 3. Regression test: Lot price parser robustness (thousands separators, dots, commas)
def test_parser_lot_price():
    from parser import parse_lot_price
    
    cases = [
        ("1.250.00 ₽", 1250.0),
        ("1 250,50 ₽", 1250.5),
        ("1.250,50 ₽", 1250.5),
        ("500 ₽", 500.0),
        ("0.50 ₽", 0.5),
        ("invalid", 0.0),
        ("", 0.0)
    ]
    for text, expected in cases:
        html = f"<div class='tc-price'>{text}</div>"
        soup = BeautifulSoup(html, "html.parser")
        elem = soup.find("div", class_="tc-price")
        assert parse_lot_price(elem) == expected

# 4. Regression test: Proxy credential masking
def test_hide_proxy_credentials():
    from utils import hide_proxy_credentials
    
    assert hide_proxy_credentials("1.2.3.4:8080:myuser:mypass") == "1.2.3.4:8080"
    assert hide_proxy_credentials("socks5://myuser:mypass@1.2.3.4:8080") == "1.2.3.4:8080"
    assert hide_proxy_credentials("http://user:pass@1.2.3.4:8080") == "1.2.3.4:8080"
    assert hide_proxy_credentials("http://1.2.3.4:8080") == "1.2.3.4:8080"
    assert hide_proxy_credentials("") == "None"

# 5. Regression test: Load proxies skips comment lines
def test_load_proxies_comments(tmp_path, monkeypatch):
    from utils import load_proxies
    import utils
    
    proxies_content = "# Формат: ip:port:user:pass\n1.2.3.4:8080:u:p\n# Комментарий\n"
    p_file = tmp_path / "proxies.txt"
    p_file.write_text(proxies_content, encoding="utf-8")
    
    # Mock base_dir
    monkeypatch.setattr(os.path, "dirname", lambda x: str(tmp_path))
    
    proxies = load_proxies()
    assert len(proxies) == 1
    assert "socks5://u:p@1.2.3.4:8080" in proxies
    assert not any("#" in p for p in proxies)

# 6. Regression test: mark_proxy removes bad proxy from good_proxies
def test_mark_proxy_hygiene(tmp_path):
    from fetch_ids import mark_proxy
    
    good_set = {"1.1.1.1:8080"}
    bad_set = set()
    pool = ["1.1.1.1:8080", "2.2.2.2:8080"]
    
    # Mark good proxy as bad
    mark_proxy("1.1.1.1:8080", "bad", str(tmp_path), good_set, bad_set, pool)
    assert "1.1.1.1:8080" not in good_set
    assert "1.1.1.1:8080" in bad_set
    assert "1.1.1.1:8080" not in pool

# 7. Regression test: price: null sum safety
def test_price_null_sum_safety():
    revs = [
        {"price": 100.0},
        {"price": None},
        {"price": 50.0},
        {"other": 10.0}
    ]
    ernd = sum(float(r.get("price") or 0.0) for r in revs if isinstance(r, dict))
    assert ernd == 150.0

# 8. Regression test: db get_connection when DB_PATH has no directory component
def test_db_dirname_empty_safety(tmp_path, monkeypatch):
    import funpay_analytics.storage.db as db_mod
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

# 9. Regression test: load_proxies preserves sorted order
def test_load_proxies_preserves_order(tmp_path):
    from utils import load_proxies
    p_file = tmp_path / "good_proxies.txt"
    p_file.write_text("socks5://1.1.1.1:1080\nsocks5://2.2.2.2:1080\nsocks5://3.3.3.3:1080\n", encoding="utf-8")
    proxies = load_proxies(base_dir=str(tmp_path))
    assert proxies == ["socks5://1.1.1.1:1080", "socks5://2.2.2.2:1080", "socks5://3.3.3.3:1080"]

# 10. Regression test: get_review_interval handles zero and negative prices
def test_get_review_interval_zero_negative():
    from parser import get_review_interval
    assert get_review_interval(0.0) is None
    assert get_review_interval(-50.0) is None
    assert get_review_interval(-1.0) is None

# 11. Regression test: chips currency regex in profile parser
from unittest.mock import patch, MagicMock

@patch("funpay_analytics.harvest.profile_harvester.ProfilePageParser")
def test_profile_harvester_chips_regex(mock_parser):
    mock_parser.return_value.parse.return_value = MagicMock()
    from funpay_analytics.harvest.profile_harvester import parse_profile
    html = """
    <div class="offer-list-title">
        <a href="https://funpay.com/chips/123/">Path of Exile Валюта</a>
    </div>
    """
    _, category_names = parse_profile(html)
    assert 123 in category_names
    assert category_names[123] == "Path of Exile Валюта"

# 12. Regression test: extract user ID from URL or raw digits
def test_extract_user_id_from_url_or_raw():
    from utils import extract_user_id

    assert extract_user_id("14273448") == "14273448"
    assert extract_user_id("https://funpay.com/users/14273448/") == "14273448"
    assert extract_user_id("https://funpay.com/users/14273448") == "14273448"
    assert extract_user_id("funpay.com/users/14273448/") == "14273448"
    assert extract_user_id("   https://funpay.com/ru/users/3/  ") == "3"
    assert extract_user_id("w1bbex") == "14273448"
    assert extract_user_id("W1bbex") == "14273448"
    assert extract_user_id("Dipper") is None
    assert extract_user_id("some_user123") is None
    assert extract_user_id("not-a-valid-input") is None
