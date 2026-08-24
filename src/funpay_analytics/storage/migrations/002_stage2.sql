-- 002_stage2.sql

CREATE TABLE IF NOT EXISTS sellers (
    id INTEGER PRIMARY KEY,
    name TEXT,
    status TEXT,
    registered_at DATETIME,
    rating REAL,
    reviews_count INTEGER,
    last_seen_at DATETIME
);

-- Active lots (latest state)
CREATE TABLE IF NOT EXISTS lots (
    id INTEGER PRIMARY KEY,
    seller_id INTEGER REFERENCES sellers(id),
    category_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT 1
);

-- Lot Snapshots (historical record)
CREATE TABLE IF NOT EXISTS lot_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id INTEGER REFERENCES lots(id),
    seller_id INTEGER REFERENCES sellers(id),
    native_section_id TEXT,
    native_section_name TEXT,
    title_raw TEXT,
    title_normalized TEXT,
    visible_price_minor INTEGER,
    data_s_decimal TEXT, 
    stock INTEGER,
    auto_delivery BOOLEAN,
    snapshot_time_utc DATETIME DEFAULT CURRENT_TIMESTAMP,
    raw_snapshot_id INTEGER REFERENCES raw_snapshots(id)
);

-- Public Reviews
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_snapshot_id INTEGER REFERENCES raw_snapshots(id),
    seller_id INTEGER REFERENCES sellers(id),
    
    rating INTEGER,
    text_content TEXT,
    seller_reply TEXT,
    date_text_raw TEXT,
    category_text TEXT,
    price_minor INTEGER,
    
    order_id TEXT,
    buyer_id INTEGER,
    buyer_name TEXT,
    date_parsed DATETIME
);
