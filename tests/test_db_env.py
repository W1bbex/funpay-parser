import os
import subprocess
import sqlite3
import pytest

def test_cli_funpay_db_path_env(tmp_path):
    # Создаем путь к тестовой БД
    custom_db_path = str(tmp_path / "custom_test.sqlite3")
    
    # Запускаем funpay-analytics init-db в отдельном процессе 
    # с установленной переменной окружения FUNPAY_DB_PATH
    env = os.environ.copy()
    env["FUNPAY_DB_PATH"] = custom_db_path
    
    # Мы можем вызвать python -m funpay_analytics.cli init-db
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
    result = subprocess.run(
        ["python", "-m", "funpay_analytics.cli", "init-db"],
        env=env,
        cwd=base_dir,
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0
    
    # Проверяем, что файл БД был создан по кастомному пути
    assert os.path.exists(custom_db_path)
    
    # Проверяем, что таблица schema_migrations существует
    conn = sqlite3.connect(custom_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
    assert cursor.fetchone() is not None
    conn.close()
