-- 003_stage2_update.sql

-- 1. Recreate lot_snapshots to add UNIQUE(raw_snapshot_id, lot_id) constraint
CREATE TABLE IF NOT EXISTS lot_snapshots_new (
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
    raw_snapshot_id INTEGER REFERENCES raw_snapshots(id),
    UNIQUE(raw_snapshot_id, lot_id)
);

INSERT INTO lot_snapshots_new (
    id, lot_id, seller_id, native_section_id, native_section_name, 
    title_raw, title_normalized, visible_price_minor, data_s_decimal, 
    stock, auto_delivery, snapshot_time_utc, raw_snapshot_id
)
SELECT 
    id, lot_id, seller_id, native_section_id, native_section_name, 
    title_raw, title_normalized, visible_price_minor, data_s_decimal, 
    stock, auto_delivery, snapshot_time_utc, raw_snapshot_id
FROM (
    SELECT *, ROW_NUMBER() OVER(PARTITION BY raw_snapshot_id, lot_id ORDER BY id DESC) as rn
    FROM lot_snapshots
) sub
WHERE rn = 1;

DROP TABLE lot_snapshots;
ALTER TABLE lot_snapshots_new RENAME TO lot_snapshots;

-- 2. Recreate reviews table to use (raw_snapshot_id, review_index) as PK
CREATE TABLE IF NOT EXISTS reviews_new (
    raw_snapshot_id INTEGER REFERENCES raw_snapshots(id),
    review_index INTEGER, 
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
    date_parsed DATETIME,
    PRIMARY KEY (raw_snapshot_id, review_index)
);

INSERT INTO reviews_new (
    raw_snapshot_id, review_index, seller_id, rating, text_content, seller_reply, 
    date_text_raw, category_text, price_minor, order_id, buyer_id, buyer_name, date_parsed
)
SELECT 
    raw_snapshot_id, 
    (ROW_NUMBER() OVER(PARTITION BY raw_snapshot_id ORDER BY id) - 1) as review_index,
    seller_id, rating, text_content, seller_reply, date_text_raw, category_text, price_minor, 
    order_id, buyer_id, buyer_name, date_parsed
FROM reviews;

DROP TABLE reviews;
ALTER TABLE reviews_new RENAME TO reviews;

-- 3. Add snapshot_candidate_lots table
CREATE TABLE IF NOT EXISTS snapshot_candidate_lots (
    raw_snapshot_id INTEGER NOT NULL,
    category_text TEXT NOT NULL,
    lot_id INTEGER NOT NULL,
    PRIMARY KEY (raw_snapshot_id, category_text, lot_id),
    FOREIGN KEY(raw_snapshot_id) REFERENCES raw_snapshots(id),
    FOREIGN KEY(lot_id) REFERENCES lots(id)
);

-- 4. Add metadata column to raw_snapshots
ALTER TABLE raw_snapshots ADD COLUMN metadata_json TEXT;
