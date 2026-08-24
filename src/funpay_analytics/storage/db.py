import sqlite3
import os
import glob
from contextlib import contextmanager

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
default_db_path = os.path.join(BASE_DIR, 'data', 'analytics.sqlite3')
DB_PATH = os.environ.get("FUNPAY_DB_PATH", default_db_path)
MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), 'migrations')

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        
        # We need to create schema_migrations first if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        
        migration_files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))
        for file_path in migration_files:
            filename = os.path.basename(file_path)
            # Example: 001_initial.sql -> 1
            version = int(filename.split('_')[0])
            
            cursor.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (version,))
            if not cursor.fetchone():
                print(f"Applying migration: {filename}")
                with open(file_path, 'r', encoding='utf-8') as f:
                    sql_script = f.read()
                try:
                    cursor.executescript(sql_script)
                    cursor.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    raise Exception(f"Migration failed {filename}: {e}")

if __name__ == '__main__':
    init_db()
    print(f"Database initialized at {os.path.abspath(DB_PATH)}")
