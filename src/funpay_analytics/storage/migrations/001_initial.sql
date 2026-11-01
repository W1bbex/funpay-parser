-- 001_initial.sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Immutable Raw Layer
CREATE TABLE IF NOT EXISTS raw_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL, -- profile | reviews | lot | own_orders | order_page
    seller_id INTEGER,
    external_id TEXT,
    fetched_at_utc DATETIME DEFAULT CURRENT_TIMESTAMP,
    http_status INTEGER,
    content_sha256 TEXT,
    compressed_path TEXT,
    parser_status TEXT DEFAULT 'pending',
    parser_version TEXT,
    error_code TEXT,
    created_at_utc DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_type, external_id, content_sha256)
);

-- Own Orders (Ground Truth)
CREATE TABLE IF NOT EXISTS own_orders (
    order_id TEXT PRIMARY KEY,
    seller_id INTEGER,
    title_raw TEXT NOT NULL,
    title_normalized TEXT,
    category_text TEXT,
    native_market_name TEXT,
    native_section_name TEXT,
    quantity INTEGER,
    seller_total_minor INTEGER,
    buyer_total_minor INTEGER,
    currency TEXT DEFAULT 'RUB',
    opened_at DATETIME,
    closed_at DATETIME,
    has_public_review BOOLEAN DEFAULT 0,
    raw_snapshot_id INTEGER REFERENCES raw_snapshots(id),
    source_level TEXT DEFAULT 'preview'
);
