import pytest
import os
import json
import glob
from funpay_analytics.storage.db import init_db, get_db
from funpay_analytics.harvest.json_importer import import_seller_json

@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    import funpay_analytics.storage.db as db_module
    import funpay_analytics.harvest.json_importer as importer_module
    
    # Изоляция SQLite
    original_db_path = db_module.DB_PATH
    temp_db = str(tmp_path / "test_analytics.sqlite3")
    db_module.DB_PATH = temp_db
    
    # Изоляция raw-директории
    # В json_importer.py путь строится от __file__
    # Чтобы не патчить os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    # мы просто пропатчим функцию save_raw_snapshot
    original_save = importer_module.save_raw_snapshot
    
    def mock_save_raw_snapshot(source_type, external_id, content_bytes, extension="json"):
        import hashlib, gzip
        content_sha256 = hashlib.sha256(content_bytes).hexdigest()
        raw_dir = tmp_path / "data" / "raw" / source_type
        raw_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{content_sha256}.{extension}.gz"
        file_path = raw_dir / file_name
        
        if not file_path.exists():
            with gzip.open(file_path, 'wb') as f:
                f.write(content_bytes)
        
        return content_sha256, f"data/raw/{source_type}/{file_name}"
        
    monkeypatch.setattr(importer_module, "save_raw_snapshot", mock_save_raw_snapshot)
    
    init_db()
    
    yield temp_db
    
    db_module.DB_PATH = original_db_path

def get_base_contract():
    return {
      "seller_id": "123456",
      "username": "IvanSeller",
      "currency": "RUB",
      "categories": {
        "Telegram": {
          "reviews": [
            {
              "price": 20.0,
              "rating": 5,
              "text": "Всё отлично",
              "reply": "Спасибо за покупку",
              "date": "В этом месяце"
            },
            {
              "price": 200.0,
              "rating": None,
              "text": "Получил",
              "reply": None,
              "date": "Месяц назад"
            }
          ],
          "candidate_lots": [
            {
              "id": "60019736",
              "section": "Каналы Telegram",
              "text": "Канал 2000 подписчиков",
              "price": 189.99,
              "stock": 10
            }
          ]
        },
        "Genshin": {
          "reviews": [
            {
              "price": 500.0,
              "rating": 4,
              "text": "Всё отлично",
              "reply": None,
              "date": "Год назад"
            }
          ],
          "candidate_lots": [
            {
              "id": "60019736",
              "section": "Каналы Telegram",
              "text": "Канал 2000 подписчиков",
              "price": 189.99,
              "stock": 10
            }
          ]
        }
      }
    }

def test_import_seller_json_full(tmp_path):
    contract_data = get_base_contract()
    test_file = tmp_path / "mock_new.json"
    test_file.write_text(json.dumps(contract_data), encoding='utf-8')
    
    snapshot_id = import_seller_json(str(test_file))
    assert snapshot_id is not None
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, name FROM sellers WHERE id=123456")
        seller = cursor.fetchone()
        assert seller['name'] == "IvanSeller"
        
        cursor.execute("SELECT metadata_json FROM raw_snapshots WHERE id=?", (snapshot_id,))
        meta = json.loads(cursor.fetchone()['metadata_json'])
        assert meta['currency'] == "RUB"
        
        cursor.execute("SELECT review_index, rating, text_content, seller_reply, category_text, price_minor FROM reviews WHERE raw_snapshot_id=? ORDER BY review_index", (snapshot_id,))
        reviews = cursor.fetchall()
        assert len(reviews) == 3
        
        ratings = [r['rating'] for r in reviews]
        assert None in ratings
        
        cursor.execute("SELECT id, is_active FROM lots WHERE seller_id=123456")
        lots = cursor.fetchall()
        assert len(lots) == 1
        assert lots[0]['id'] == 60019736
        assert lots[0]['is_active'] == 1
        
        cursor.execute("SELECT * FROM lot_snapshots WHERE raw_snapshot_id=?", (snapshot_id,))
        lot_snaps = cursor.fetchall()
        assert len(lot_snaps) == 1
        assert lot_snaps[0]['stock'] == 10
        assert lot_snaps[0]['visible_price_minor'] == 18999
        
        cursor.execute("SELECT category_text, lot_id FROM snapshot_candidate_lots WHERE raw_snapshot_id=? ORDER BY category_text", (snapshot_id,))
        links = cursor.fetchall()
        assert len(links) == 2
        categories = [l['category_text'] for l in links]
        assert "Telegram" in categories
        assert "Genshin" in categories
        
    snapshot_id_2 = import_seller_json(str(test_file))
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as c FROM lot_snapshots")
        assert cursor.fetchone()['c'] == 1

def test_import_missing_categories(tmp_path):
    contract_data = {
      "seller_id": "123",
      "username": "Ivan",
      "currency": "RUB"
    }
    test_file = tmp_path / "mock_bad.json"
    test_file.write_text(json.dumps(contract_data), encoding='utf-8')
    with pytest.raises(ValueError, match="Отсутствует или некорректен объект categories"):
        import_seller_json(str(test_file))

def test_import_missing_review_field_rolls_back(tmp_path):
    contract_data = get_base_contract()
    del contract_data["categories"]["Telegram"]["reviews"][0]["rating"]
    test_file = tmp_path / "mock_rollback.json"
    test_file.write_text(json.dumps(contract_data), encoding='utf-8')
    
    raw_dir = tmp_path / "data" / "raw" / "seller_snapshot_v2"
    initial_files = set(raw_dir.glob("*.gz")) if raw_dir.exists() else set()
    
    with pytest.raises(ValueError, match="Отсутствует поле rating"):
        import_seller_json(str(test_file))
        
    final_files = set(raw_dir.glob("*.gz")) if raw_dir.exists() else set()
    assert initial_files == final_files
    
def test_import_conflicting_lot_data(tmp_path):
    contract_data = get_base_contract()
    contract_data["categories"]["Genshin"]["candidate_lots"][0]["price"] = 999.99
    test_file = tmp_path / "mock_conflict.json"
    test_file.write_text(json.dumps(contract_data), encoding='utf-8')
    
    with pytest.raises(ValueError, match="Конфликт данных для лота"):
        import_seller_json(str(test_file))

def test_import_stock_null(tmp_path):
    contract_data = get_base_contract()
    contract_data["categories"]["Telegram"]["candidate_lots"][0]["stock"] = None
    contract_data["categories"]["Genshin"]["candidate_lots"][0]["stock"] = None
    test_file = tmp_path / "mock_stock_null.json"
    test_file.write_text(json.dumps(contract_data), encoding='utf-8')
    
    snap_id = import_seller_json(str(test_file))
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT stock FROM lot_snapshots WHERE raw_snapshot_id=?", (snap_id,))
        lot_snaps = cursor.fetchall()
        assert lot_snaps[0]['stock'] is None

def test_absent_candidate_not_deactivated(tmp_path):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sellers (id, name) VALUES (123456, 'IvanSeller')")
        cursor.execute("INSERT INTO lots (id, seller_id, is_active) VALUES (999, 123456, 1)")
        conn.commit()
        
    contract_data = get_base_contract()
    test_file = tmp_path / "mock_no_deactivate.json"
    test_file.write_text(json.dumps(contract_data), encoding='utf-8')
    import_seller_json(str(test_file))
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT is_active FROM lots WHERE id=999")
        lot = cursor.fetchone()
        assert lot['is_active'] == 1

def test_lot_hijack_prevention(tmp_path):
    # Лот уже принадлежит продавцу 999
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sellers (id, name) VALUES (999, 'AnotherSeller')")
        cursor.execute("INSERT INTO lots (id, seller_id, is_active) VALUES (60019736, 999, 1)")
        conn.commit()
        
    contract_data = get_base_contract()
    test_file = tmp_path / "mock_hijack.json"
    test_file.write_text(json.dumps(contract_data), encoding='utf-8')
    
    with pytest.raises(ValueError, match="уже принадлежит продавцу 999"):
        import_seller_json(str(test_file))

def test_migration_003_deduplication(tmp_path):
    import sqlite3
    db_path = str(tmp_path / "migr_test.sqlite3")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Применяем 001 и 002
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    m001 = os.path.join(base_dir, 'src', 'funpay_analytics', 'storage', 'migrations', '001_initial.sql')
    m002 = os.path.join(base_dir, 'src', 'funpay_analytics', 'storage', 'migrations', '002_stage2.sql')
    m003 = os.path.join(base_dir, 'src', 'funpay_analytics', 'storage', 'migrations', '003_stage2_update.sql')
    
    with open(m001, 'r', encoding='utf-8') as f:
        cursor.executescript(f.read())
    with open(m002, 'r', encoding='utf-8') as f:
        cursor.executescript(f.read())
        
    # Вставляем зависимые данные
    cursor.execute("INSERT INTO raw_snapshots (id, source_type) VALUES (1, 'test')")
    cursor.execute("INSERT INTO sellers (id, name) VALUES (123, 'test')")
    cursor.execute("INSERT INTO lots (id, seller_id) VALUES (456, 123)")
    
    # Вставляем дубликаты в старую lot_snapshots
    cursor.execute('''INSERT INTO lot_snapshots (lot_id, seller_id, raw_snapshot_id) VALUES (456, 123, 1)''')
    cursor.execute('''INSERT INTO lot_snapshots (lot_id, seller_id, raw_snapshot_id) VALUES (456, 123, 1)''')
    conn.commit()
    
    cursor.execute("SELECT COUNT(*) FROM lot_snapshots")
    assert cursor.fetchone()[0] == 2
    
    # Применяем 003
    with open(m003, 'r', encoding='utf-8') as f:
        cursor.executescript(f.read())
        
    cursor.execute("SELECT COUNT(*) FROM lot_snapshots")
    assert cursor.fetchone()[0] == 1
    
    # Проверка констрейнта
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute('''INSERT INTO lot_snapshots (lot_id, seller_id, raw_snapshot_id) VALUES (456, 123, 1)''')
        
    conn.close()
