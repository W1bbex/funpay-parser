import os
import re
import json
from bs4 import BeautifulSoup
from loguru import logger

def parse_sales_html(html_path, output_json_path):
    logger.info(f"Читаем файл {html_path} ...")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
    except Exception as e:
        logger.error(f"Не удалось прочитать файл: {e}")
        return

    logger.info("Парсим HTML (это может занять несколько секунд, так как файл большой)...")
    soup = BeautifulSoup(html, "html.parser")
    
    sales = {}
    items = soup.find_all("a", class_="tc-item")
    
    for item in items:
        # Парсим ID заказа
        order_div = item.find("div", class_="tc-order")
        order_id = None
        if order_div:
            match = re.search(r'#([A-Z0-9]+)', order_div.text)
            if match:
                order_id = match.group(1)
                
        # Парсим реальную цену продавца
        price_div = item.find("div", class_="tc-seller-sum")
        real_price = None
        if price_div:
            # Убираем пробелы и берем число
            price_text = price_div.text.replace(" ", "").replace(",", ".")
            match = re.search(r'([\d.]+)', price_text)
            if match:
                try:
                    real_price = float(match.group(1))
                except ValueError:
                    pass
                    
        if order_id and real_price is not None:
            sales[order_id] = real_price

    logger.success(f"Найдено {len(sales)} продаж!")
    
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(sales, f, ensure_ascii=False, indent=4)
        
    logger.success(f"Продажи успешно сохранены в удобном формате: {output_json_path}")

if __name__ == "__main__":
    # Путь к HTML-файлу пользователя
    html_file = r"C:\Users\w1bbex\Desktop\Мои продажи _ FunPay_files\Мои продажи _ FunPay.html"
    
    # Куда сохранять результат
    base_dir = os.path.dirname(__file__)
    output_file = os.path.join(base_dir, "parsed_sales.json")
    
    parse_sales_html(html_file, output_file)
