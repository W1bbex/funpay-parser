import sys
import os
import time
import re
import json
import random
from bs4 import BeautifulSoup
from loguru import logger

# Добавляем путь к Cardinal
cardinal_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "Cardinal"))
if not os.path.exists(cardinal_path):
    cardinal_path = r"C:\Projects\Cardinal"
sys.path.append(cardinal_path)
try:
    from FunPayAPI.account import Account
except ImportError as e:
    logger.error("Не удалось импортировать FunPayAPI. Проверьте путь.")
    raise e

import config

def get_reviews_page(account, user_id, continue_id=None):
    headers = {
        "x-requested-with": "XMLHttpRequest",
        "accept": "application/json, text/javascript, */*; q=0.01"
    }
    
    if continue_id:
        payload = {"user_id": user_id, "continue": continue_id, "request": "reviews"}
        res = account.method("post", f"users/{user_id}/", headers, payload, raise_not_200=True)
        try:
            data = res.json()
            return data.get("html", ""), data.get("continue")
        except Exception:
            return res.text, None
    else:
        res = account.method("get", f"users/{user_id}/", headers, {}, raise_not_200=True)
        return res.text, None

def parse_reviews(html):
    if not html:
        return [], None
        
    soup = BeautifulSoup(html, "html.parser")
    reviews = []
    last_id = None
    
    for item in soup.find_all("div", class_="review-item"):
        last_id = item.get("data-id")
        
        order_div = item.find("div", class_="review-item-order")
        order_id = None
        if order_div:
            match = re.search(r'#([A-Z0-9]+)', order_div.text)
            if match:
                order_id = match.group(1)
                
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
            reviews.append((last_id, order_id, review_price))
            
    return reviews, last_id

def main():
    if config.GOLDEN_KEY == "ВСТАВЬТЕ_ВАШ_GOLDEN_KEY_СЮДА":
        logger.error("Пожалуйста, укажите ваш GOLDEN_KEY в файле config.py")
        return
        
    logger.info("Инициализация аккаунта через FunPayAPI...")
    acc = Account(config.GOLDEN_KEY)
    try:
        acc.get(update_phpsessid=False)
        logger.info(f"Авторизован как: {acc.username} (ID: {acc.id})")
    except Exception as e:
        logger.error(f"Ошибка авторизации: {e}")
        return
        
    base_dir = os.path.dirname(__file__)
    
    # ЭТАП 1: Парсим ВСЕ ПРОДАЖИ (Заказы)
    logger.info("ЭТАП 1: Собираем список всех продаж...")
    all_sales = {}
    start_from = None
    sales_pages_fetched = 0
    
    while True:
        try:
            next_start, sales_list, _, _ = acc.get_sales(start_from=start_from)
            for s in sales_list:
                all_sales[s.id] = float(s.price)
                
            sales_pages_fetched += 1
            if sales_pages_fetched % 5 == 0:
                logger.info(f"Собрано {len(all_sales)} продаж...")
                
            if not next_start or not sales_list:
                break
                
            start_from = next_start
            time.sleep(random.uniform(config.DELAY_MIN, config.DELAY_MAX))
            
        except Exception as e:
            logger.error(f"Ошибка при сборе продаж: {e}")
            break
            
    logger.success(f"Всего собрано {len(all_sales)} продаж из истории аккаунта!")
    
    # ЭТАП 2: Парсим ВСЕ ОТЗЫВЫ
    logger.info("ЭТАП 2: Собираем список всех отзывов...")
    all_reviews = {}
    continue_id = None
    reviews_pages_fetched = 0
    
    try:
        html, _ = get_reviews_page(acc, acc.id)
    except Exception as e:
        logger.error(f"Ошибка при получении первой страницы отзывов: {e}")
        return
        
    while True:
        try:
            reviews, last_id = parse_reviews(html)
            
            if not reviews:
                break
                
            for _, order_id, review_price in reviews:
                all_reviews[order_id] = float(review_price)
                
            reviews_pages_fetched += 1
            if reviews_pages_fetched % 5 == 0:
                logger.info(f"Собрано {len(all_reviews)} отзывов...")
                
            if not last_id:
                break
                
            time.sleep(random.uniform(config.DELAY_MIN, config.DELAY_MAX))
            html, _ = get_reviews_page(acc, acc.id, continue_id=last_id)
            
            if not html:
                break
                
        except Exception as e:
            logger.error(f"Ошибка при сборе отзывов (страница {reviews_pages_fetched}): {e}")
            break
            
    logger.success(f"Всего собрано {len(all_reviews)} отзывов!")
    
    # ЭТАП 3: СОПОСТАВЛЕНИЕ
    logger.info("ЭТАП 3: Сопоставляем отзывы и продажи...")
    
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
            
    logger.info(f"Успешно сопоставлено {total_matched} заказов!")
    
    # ЭТАП 4: ФОРМИРУЕМ ОТЧЕТ
    logger.info("ЭТАП 4: Вычисляем диапазоны...")
    
    final_report = {}
    for rev_str, real_prices_set in matched_ranges.items():
        real_prices_list = sorted(list(real_prices_set))
        final_report[rev_str] = {
            "min_real_price": real_prices_list[0] if real_prices_list else 0.0,
            "max_real_price": real_prices_list[-1] if real_prices_list else 0.0,
            "unique_variations_count": len(real_prices_list),
            "all_real_prices": real_prices_list
        }
        
    report_file = os.path.join(base_dir, "final_rounding_ranges.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(final_report, f, ensure_ascii=False, indent=4)
        
    logger.success(f"Готово! Анализ сохранен в {report_file}")
    
    # Выводим небольшое превью в консоль
    logger.info("--- ПРЕВЬЮ ДИАПАЗОНОВ ---")
    for rev_str in list(final_report.keys())[:10]:
        data = final_report[rev_str]
        logger.info(f"Отзыв на {rev_str} ₽ => Реальная сумма от {data['min_real_price']} ₽ до {data['max_real_price']} ₽")
    logger.info("...")

if __name__ == "__main__":
    main()
