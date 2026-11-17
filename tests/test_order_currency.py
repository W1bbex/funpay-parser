"""Own-order imports retain the currency encoded in the saved page."""

from html import escape

import pytest

from funpay_analytics.normalize.extract_own_orders import import_orders
from funpay_analytics.storage.db import get_db, init_db


def write_order(tmp_path, price, *, mhtml=False):
    html = ('<html><a class="tc-item"><div class="tc-order">#CUR123</div>'
            '<div class="order-desc"><div>Service</div><div>Steam</div></div>'
            f'<div class="tc-price tc-seller-sum">{escape(price)}</div></a></html>')
    path = tmp_path / ("orders.mhtml" if mhtml else "orders.html")
    if mhtml:
        html = 'MIME-Version: 1.0\nContent-Type: text/html; charset="utf-8"\n\n' + html
    path.write_text(html, encoding="utf-8")
    return path


@pytest.mark.parametrize(("price", "minor", "currency"), [
    ("12.34 USD", 1234, "USD"), ("$1,234.56", 123456, "USD"),
    ("1.234,56 EUR", 123456, "EUR"), ("1 234,56 €", 123456, "EUR"),
    ("1\u00a0234,56 руб.", 123456, "RUB"), ("1234.56 ₽", 123456, "RUB"),
    ("12,34 р.", 1234, "RUB"),
])
@pytest.mark.parametrize("mhtml", [False, True])
def test_currency_and_minor_units_survive_idempotent_import(tmp_path, price, minor, currency, mhtml):
    init_db()
    source = write_order(tmp_path, price, mhtml=mhtml)
    assert import_orders(source) == 1
    assert import_orders(source) == 1
    with get_db() as conn:
        rows = conn.execute("SELECT seller_total_minor, currency FROM own_orders").fetchall()
        snapshots = conn.execute("SELECT COUNT(*) FROM raw_snapshots").fetchone()[0]
    assert [tuple(row) for row in rows] == [(minor, currency)]
    assert snapshots == 1


@pytest.mark.parametrize("price", ["12.34 GBP", "£12.34", "12.34", "12.34 USD EUR"])
def test_unknown_or_ambiguous_currency_is_rejected_before_database_write(tmp_path, price):
    init_db()
    with pytest.raises(ValueError, match="[Вв]алют"):
        import_orders(write_order(tmp_path, price))
    with get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM own_orders").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM raw_snapshots").fetchone()[0] == 0
