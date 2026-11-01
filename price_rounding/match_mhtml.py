import os
import re
import json
import email
import email.policy
from bs4 import BeautifulSoup
from loguru import logger

def extract_html_from_mhtml(file_path):
    logger.info(f"Распаковываем MHTML файл: {file_path}")
    try:
        with open(file_path, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=email.policy.default)
            
        for part in msg.walk():
            if part.get_content_type() == 'text/html':
                payload = part.get_payload(decode=True)
                if payload:
                    try:
                        return payload.decode('utf-8')
                    except UnicodeDecodeError:
                        return payload.decode('windows-1251', errors='ignore')
    except Exception as e:
        logger.error(f"Ошибка при чтении MHTML: {e}")
        
    return ""

def parse_reviews_from_html(html):
    logger.info("Парсим отзывы из извлеченного HTML...")
    soup = BeautifulSoup(html, "html.parser")
    reviews = {}
    
    items = soup.find_all("div", class_="review-item")
    for item in items:
        # Парсим ID заказа
        order_div = item.find("div", class_="review-item-order")
        order_id = None
        if order_div:
            match = re.search(r'#([A-Z0-9]+)', order_div.text)
            if match:
                order_id = match.group(1)
                
        # Парсим цену из отзыва
        detail_div = item.find("div", class_="review-item-detail")
        review_price = None
        if detail_div:
            match = re.search(r'([\d\s]+(?:[.,]\d+)?)\s*₽', detail_div.text)
            if match:
                price_str = match.group(1).replace(" ", "").replace(",", ".")
                try:
                    review_price = float(price_str)
                except ValueError:
                    pass
                    
        if order_id and review_price is not None:
            reviews[order_id] = review_price

    logger.success(f"Найдено {len(reviews)} уникальных отзывов!")
    return reviews

def main():
    base_dir = os.path.dirname(__file__)
    sales_file = os.path.join(base_dir, "parsed_sales.json")
    mhtml_env = os.environ.get("FUNPAY_PROFILE_MHTML")
    mhtml_file = mhtml_env if mhtml_env else os.path.join(base_dir, "sample_profile.mhtml")
    
    if not os.path.exists(sales_file):
        logger.error("Файл parsed_sales.json не найден! Сначала запустите parse_sales_html.py")
        return
        
    # Читаем спаршенные продажи
    with open(sales_file, "r", encoding="utf-8") as f:
        all_sales = json.load(f)
        
    logger.info(f"Загружено {len(all_sales)} продаж из базы.")
    
    # Достаем HTML из MHTML и парсим отзывы
    html_content = extract_html_from_mhtml(mhtml_file)
    if not html_content:
        logger.error("Не удалось извлечь HTML из MHTML файла. Возможно файл поврежден или имеет другой формат.")
        return
        
    all_reviews = parse_reviews_from_html(html_content)
    
    # СОПОСТАВЛЕНИЕ
    logger.info("Начинаем сопоставление...")
    
    matched_ranges = {}
    total_matched = 0
    
    for order_id, review_price in all_reviews.items():
        if order_id in all_sales:
            total_matched += 1
            real_price = all_sales[order_id]
            rev_str = str(review_price)
            
            if rev_str not in matched_ranges:
                matched_ranges[rev_str] = []
                
            matched_ranges[rev_str].append(real_price)
            
    logger.success(f"Успешно сопоставлено {total_matched} заказов!")
    
    # Формируем итоговый отчет
    final_report = {}
    for rev_str, real_prices_list in matched_ranges.items():
        real_prices_list = sorted(real_prices_list)
        final_report[rev_str] = {
            "min_real_price": real_prices_list[0] if real_prices_list else 0.0,
            "max_real_price": real_prices_list[-1] if real_prices_list else 0.0,
            "unique_variations_count": len(set(real_prices_list)),
            "all_real_prices": real_prices_list
        }
        
    report_file = os.path.join(base_dir, "final_rounding_ranges.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(final_report, f, ensure_ascii=False, indent=4)
        
    logger.success(f"Отчет сохранен в {report_file}")
    
    # Превью
    logger.info("--- ПРЕВЬЮ ДИАПАЗОНОВ ---")
    for rev_str in list(final_report.keys())[:15]:
        data = final_report[rev_str]
        logger.info(f"Отзыв на {rev_str} ₽ => Реальная сумма от {data['min_real_price']} ₽ до {data['max_real_price']} ₽")
    logger.info("Полный список смотрите в final_rounding_ranges.json")

if __name__ == "__main__":
    main()
