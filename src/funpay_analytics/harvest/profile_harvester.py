import os
import hashlib
import gzip
import re
from decimal import Decimal
from bs4 import BeautifulSoup
from funpayparsers.parsers import ProfilePageParser
from funpay_analytics.storage.db import get_db

def save_raw_snapshot(source_type, content_bytes, extension="html"):
    content_sha256 = hashlib.sha256(content_bytes).hexdigest()
    
    data_dir = os.environ.get("FUNPAY_DATA_DIR")
    if not data_dir:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        data_dir = os.path.join(base_dir, 'data')
    raw_dir = os.path.join(data_dir, 'raw', source_type)
    os.makedirs(raw_dir, exist_ok=True)
    
    file_name = f"{content_sha256}.{extension}.gz"
    file_path = os.path.join(raw_dir, file_name)
    compressed_path_relative = f"data/raw/{source_type}/{file_name}"
    
    if not os.path.exists(file_path):
        temp_path = file_path + ".tmp"
        with gzip.open(temp_path, 'wb') as f:
            f.write(content_bytes)
        os.replace(temp_path, file_path) 
        
    return content_sha256, compressed_path_relative

def parse_profile(html_content, external_id=None):
    parser = ProfilePageParser(html_content)
    profile_data = parser.parse()
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    category_names = {}
    for c in soup.select('div.offer-list-title'):
        a_tag = c.find('a')
        if a_tag and 'href' in a_tag.attrs:
            href = a_tag['href']
            m = re.search(r'/(?:lots|chips)/(\d+)/', href)
            if m:
                cat_id = int(m.group(1))
                category_names[cat_id] = c.text.strip()
                
    return profile_data, category_names

def import_profile_from_file(file_path):
    with open(file_path, 'rb') as f:
        file_bytes = f.read()
        
    html_content = file_bytes.decode('utf-8', errors='replace')
    
    parser = ProfilePageParser(html_content)
    profile_data = parser.parse()
    seller_id = profile_data.user_id
    
    if not seller_id:
        raise ValueError("Не удалось определить ID продавца из HTML")
        
    content_sha256, compressed_path = save_raw_snapshot('profile', file_bytes, 'html')
    
    profile_data, category_names = parse_profile(html_content, str(seller_id))
    
    with get_db() as conn:
        try:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO raw_snapshots (source_type, external_id, seller_id, content_sha256, compressed_path, parser_status, parser_version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_type, external_id, content_sha256) DO UPDATE SET
                parser_status='success', compressed_path=excluded.compressed_path
            ''', ('profile', str(seller_id), seller_id, content_sha256, compressed_path, 'success', 'v1'))
            
            cursor.execute('''
                SELECT id FROM raw_snapshots 
                WHERE source_type=? AND external_id=? AND content_sha256=?
            ''', ('profile', str(seller_id), content_sha256))
            row = cursor.fetchone()
            if not row:
                raise RuntimeError(f"Не удалось получить ID сохраненного raw_snapshot для {seller_id}")
            snapshot_id = row[0]
            
            username = profile_data.username
            status = profile_data.status_text
            reg_date_text = profile_data.registration_date_text
                
            rating = profile_data.rating.stars if profile_data.rating else 0.0
            reviews_count = profile_data.rating.reviews_amount if profile_data.rating else 0
            
            cursor.execute('''
                INSERT INTO sellers (id, name, status, registered_at, rating, reviews_count)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, status=excluded.status, registered_at=excluded.registered_at,
                rating=excluded.rating, reviews_count=excluded.reviews_count
            ''', (seller_id, username, status, reg_date_text, rating, reviews_count))
            
            cursor.execute('UPDATE lots SET is_active=0 WHERE seller_id=?', (seller_id,))
            
            inserted_lots = 0
            for subcategory_type, categories in profile_data.offers.items():
                for cat_id, offers_list in categories.items():
                    native_section_name = category_names.get(cat_id, "Unknown")
                    
                    for offer in offers_list:
                        lot_id = offer.id
                        title_raw = offer.title
                        
                        visible_price_minor = None
                        if offer.price and offer.price.value is not None:
                            visible_price_minor = int((Decimal(str(offer.price.value)) * Decimal('100')).to_integral_value())
                            
                        data_s_decimal = None
                        if offer.raw_source:
                            data_s_match = re.search(r'data-s="([\d.]+)"', str(offer.raw_source))
                            if data_s_match:
                                data_s_decimal = data_s_match.group(1)
                        
                        cursor.execute('''
                            INSERT INTO lots (id, seller_id, category_id, is_active)
                            VALUES (?, ?, ?, 1)
                            ON CONFLICT(id) DO UPDATE SET is_active=1, category_id=excluded.category_id
                        ''', (lot_id, seller_id, str(cat_id)))
                        
                        cursor.execute('''
                            INSERT INTO lot_snapshots (
                                lot_id, seller_id, native_section_id, native_section_name,
                                title_raw, visible_price_minor, data_s_decimal, auto_delivery, raw_snapshot_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(raw_snapshot_id, lot_id) DO UPDATE SET
                                native_section_name=excluded.native_section_name,
                                title_raw=excluded.title_raw,
                                visible_price_minor=excluded.visible_price_minor,
                                data_s_decimal=excluded.data_s_decimal,
                                auto_delivery=excluded.auto_delivery
                        ''', (
                            lot_id, seller_id, str(cat_id), native_section_name, title_raw,
                            visible_price_minor, data_s_decimal, offer.auto_delivery, snapshot_id
                        ))
                        inserted_lots += 1
                        
            conn.commit()
            return seller_id, inserted_lots
            
        except Exception as e:
            conn.rollback()
            raise e
