import pytest
import os
import sqlite3
from funpay_analytics.storage.db import init_db
from funpay_analytics.normalize.extract_own_orders import import_orders

@pytest.fixture(autouse=True)
def setup_test_db():
    import funpay_analytics.storage.db as db_module
    original_db_path = db_module.DB_PATH
    import tempfile
    fd, temp_db = tempfile.mkstemp()
    os.close(fd)
    
    db_module.DB_PATH = temp_db
    init_db()
    
    yield
    
    db_module.DB_PATH = original_db_path
    try:
        os.remove(temp_db)
    except:
        pass

def test_import_mock_html(tmp_path):
    mock_html = b'''MIME-Version: 1.0
Content-Type: multipart/related; boundary="----MultipartBoundary"

------MultipartBoundary
Content-Type: text/html; charset="utf-8"

<a class="tc-item" href="https://funpay.com/orders/XM25Y1UL/">
    <div class="tc-order">#XM25Y1UL</div>
    <div class="order-desc">
        <div>Steam 10 RUB</div>
        <div class="text-muted">Steam, Game</div>
    </div>
    <div class="tc-price tc-seller-sum"> 13.01 <span class="unit">rub</span></div>
</a>
------MultipartBoundary--'''

    test_file = tmp_path / "test.mhtml"
    test_file.write_bytes(mock_html)
    
    inserted = import_orders(str(test_file))
    
    assert inserted == 1

    import funpay_analytics.storage.db as db_module
    with db_module.get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT seller_total_minor FROM own_orders WHERE order_id='XM25Y1UL'")
        minor = cursor.fetchone()[0]
        assert minor == 1301  
        
        cursor.execute("SELECT raw_snapshot_id FROM own_orders WHERE order_id='XM25Y1UL'")
        snap_id = cursor.fetchone()[0]
        assert snap_id is not None
        
        cursor.execute("SELECT content_sha256, compressed_path FROM raw_snapshots WHERE id=?", (snap_id,))
        sha, compressed = cursor.fetchone()
        assert len(sha) == 64
        assert compressed.endswith('.mhtml.gz')

def test_import_validation_error(tmp_path):
    mock_html = b'''MIME-Version: 1.0
Content-Type: multipart/related; boundary="----MultipartBoundary"

------MultipartBoundary
Content-Type: text/html; charset="utf-8"

<a class="tc-item" href="https://funpay.com/orders/BROKEN1/">
    <div class="tc-order">#BROKEN1</div>
    <div class="order-desc">
        <div>Missing Price</div>
        <div class="text-muted">Cat</div>
    </div>
</a>
------MultipartBoundary--'''

    test_file = tmp_path / "test.mhtml"
    test_file.write_bytes(mock_html)
    
    # Validation error should prevent import
    with pytest.raises(ValueError, match="ошибок валидации"):
        import_orders(str(test_file))

def test_import_transaction_rollback(tmp_path, monkeypatch):
    mock_html = b'''MIME-Version: 1.0
Content-Type: multipart/related; boundary="----MultipartBoundary"

------MultipartBoundary
Content-Type: text/html; charset="utf-8"

<a class="tc-item" href="https://funpay.com/orders/GOOD123/">
    <div class="tc-order">#GOOD123</div>
    <div class="order-desc">
        <div>Good</div>
        <div class="text-muted">Cat</div>
    </div>
    <div class="tc-price tc-seller-sum"> 100 </div>
</a>
------MultipartBoundary--'''

    test_file = tmp_path / "test.mhtml"
    test_file.write_bytes(mock_html)
    
    import funpay_analytics.storage.db as db_module
    original_get_connection = db_module.get_connection
    
    class BuggyCursor:
        def __init__(self, real_cursor):
            self.real_cursor = real_cursor
            self.insert_count = 0
            
        def execute(self, query, params=None):
            if "INSERT INTO own_orders" in query:
                self.insert_count += 1
                if self.insert_count == 1:
                    raise sqlite3.OperationalError("Artificial Database Error During Transaction")
            if params:
                return self.real_cursor.execute(query, params)
            return self.real_cursor.execute(query)
            
        def fetchone(self):
            return self.real_cursor.fetchone()
            
        def fetchall(self):
            return self.real_cursor.fetchall()
            
    class ProxyConnection:
        def __init__(self, real_conn):
            self.real_conn = real_conn
            
        def cursor(self):
            return BuggyCursor(self.real_conn.cursor())
            
        def commit(self):
            self.real_conn.commit()
            
        def rollback(self):
            self.real_conn.rollback()
            
        def close(self):
            self.real_conn.close()
            
    def mock_get_connection():
        return ProxyConnection(original_get_connection())
        
    monkeypatch.setattr(db_module, "get_connection", mock_get_connection)
    
    with pytest.raises(sqlite3.OperationalError, match="Artificial Database Error During Transaction"):
        import_orders(str(test_file))
        
    with db_module.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM own_orders")
        assert cursor.fetchone()[0] == 0
        
        cursor.execute("SELECT COUNT(*) FROM raw_snapshots")
        assert cursor.fetchone()[0] == 0
