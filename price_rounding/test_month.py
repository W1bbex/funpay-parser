import json
from loguru import logger
import email
from email import policy
from bs4 import BeautifulSoup
import re

EXPECTED_EARNINGS = {
    10: 2.99,    
    20: 16.29,   
    30: 26.46,   
    40: 34.28,   
    50: 44.85,   
    60: 53.37,   
    70: 60.94,   
    90: 79.31,   
    100: 97.12,  
    200: 169.22, 
    300: 281.30, 
    400: 345.93, 
}

def estimate_review_earnings(review_price: float) -> float:
    price = int(review_price)
    if price in EXPECTED_EARNINGS:
        return EXPECTED_EARNINGS[price]
    return price * 0.85

def main():
    # Загружаем реальные продажи
    sales_data = {}
    try:
        from pathlib import Path
        with open(Path(__file__).resolve().parent / "parsed_sales.json", "r", encoding="utf-8") as f:
            sales = json.load(f)
            sales_data = {("#" + str(k) if not str(k).startswith("#") else str(k)): float(v) for k, v in sales.items()}
    except Exception as e:
        logger.error(f"Ошибка загрузки продаж: {e}")
        return

    # Загружаем MHTML и парсим отзывы
    mhtml_env = os.environ.get("FUNPAY_PROFILE_MHTML")
    mhtml_path = mhtml_env if mhtml_env else str(Path(__file__).resolve().parent / "sample_profile.mhtml")
    try:
        with open(mhtml_path, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
    except Exception as e:
        logger.error(f"Ошибка чтения MHTML: {e}")
        return

    html_content = ""
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            html_content = part.get_content()
            break
            
    if not html_content:
        logger.error("HTML часть не найдена")
        return

    soup = BeautifulSoup(html_content, 'html.parser')
    reviews = soup.find_all('div', class_='review-item')
    
    total_real = 0.0
    total_estimated = 0.0
    total_naive = 0.0
    
    recent_real = 0.0
    recent_estimated = 0.0
    recent_naive = 0.0
    
    count_all = 0
    count_recent = 0
    
    # Считаем, что первый отзыв со словом "месяц" или "мес." - это граница
    is_recent = True

    for item in reviews:
        # Дата
        date_div = item.find('div', class_='review-item-date')
        if not date_div: continue
        date_str = date_div.text.strip().lower()
        
        # Если встретили "месяц назад" или "2 месяца", значит недавние закончились
        if "месяц" in date_str or "мес." in date_str or "год" in date_str:
            is_recent = False
            
        # ID заказа
        order_div = item.find('div', class_='review-item-order')
        if not order_div: continue
        order_link = order_div.find('a')
        if not order_link: continue
        order_text = order_link.text.strip()
        if not order_text.startswith('#'): continue
        order_id = order_text

        # Цена отзыва
        price_div = item.find('div', class_='review-item-detail')
        if not price_div: continue
        price_text = price_div.text.strip()
        match = re.search(r'([\d\s,]+)\s*₽', price_text)
        if not match: continue
        
        try:
            rev_price = float(match.group(1).replace(" ", "").replace(",", "."))
        except:
            continue
            
        if order_id in sales_data:
            real_price = sales_data[order_id]
            est_price = estimate_review_earnings(rev_price)
            
            # Накапливаем за всё время
            total_real += real_price
            total_estimated += est_price
            total_naive += rev_price
            count_all += 1
            
            # Накапливаем за недавнее время (последний месяц)
            if is_recent:
                recent_real += real_price
                recent_estimated += est_price
                recent_naive += rev_price
                count_recent += 1

    err_naive = ((total_naive - total_real) / total_real * 100) if total_real > 0 else 0.0
    err_est = ((total_estimated - total_real) / total_real * 100) if total_real > 0 else 0.0
    print("\n--- РЕЗУЛЬТАТЫ ЗА ВСЁ ВРЕМЯ ---")
    print(f"Отзывов: {count_all}")
    print(f"НАИВНЫЙ ПАРСИНГ (Цена = Отзыв): {total_naive:.2f} ₽ (Ошибка: {err_naive:.2f}%)")
    print(f"ОЦЕНКА ПАРСЕРА (Среднее):       {total_estimated:.2f} ₽ (Ошибка: {err_est:.2f}%)")
    print(f"РЕАЛЬНАЯ ВЫРУЧКА (Из базы):     {total_real:.2f} ₽")

if __name__ == "__main__":
    main()
