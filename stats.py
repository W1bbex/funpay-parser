import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import json
from utils import logger

def generate_stats():
    if not os.path.exists('reports'):
        logger.warning("Папка reports/ пуста или не существует.")
        return
        
    total_parsed = 0
    total_reviews = 0
    for file in os.listdir('reports_v2'):
        if file.endswith('.json'):
            try:
                with open(os.path.join('reports_v2', file), 'r', encoding='utf-8') as f:
                    res = json.load(f)
                    total_parsed += 1
                    total_reviews += res.get('total_reviews', 0)
            except Exception as e:
                logger.error(f"Ошибка при чтении {file}: {e}")
                
    logger.info("=== ГЛОБАЛЬНАЯ СТАТИСТИКА БАЗЫ ===")
    logger.info(f"Всего пропарсено продавцов: {total_parsed}")
    logger.info(f"Общее количество отзывов: {total_reviews}")

if __name__ == "__main__":
    generate_stats()
