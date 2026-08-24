import os, sys, time, asyncio, random, re
from bs4 import BeautifulSoup
from curl_cffi import requests

# Ensure we're in the right directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from utils import load_proxies, logger, get_browser_for_proxy
from funpayparsers.parsers.reviews_parser import ReviewsParser

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

def get_smart_delay(is_proxy=False):
    chance = random.random()
    if chance < 0.8:
        return random.uniform(1.2, 2.5) if is_proxy else random.uniform(2.5, 5.0)
    elif chance < 0.95:
        return random.uniform(3.0, 5.0) if is_proxy else random.uniform(5.0, 8.0)
    else:
        return random.uniform(5.0, 8.0) if is_proxy else random.uniform(10.0, 15.0)

async def parse_profile(client, user_id: str):
    headers = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': f'https://funpay.com/users/{user_id}/'
    }
    try:
        response = await client.get(f'https://funpay.com/users/{user_id}/', cookies={'cy': 'rub'})
        if response.status_code == 429:
            raise Exception('429 Too Many Requests')
        response.raise_for_status()
        html_text = response.text
    except Exception as e:
        logger.error(f'[ID {user_id}] Ошибка доступа: {e}')
        return None

    total_old = 0
    total_new = 0
    stop_parsing = False
    
    batch = ReviewsParser(html_text).parse()
    actual_user_id = batch.user_id if batch.user_id else user_id

    def process_batch(batch_reviews):
        nonlocal stop_parsing, total_old, total_new
        count = 0
        for review in batch_reviews:
            date = (review.date_text or '').strip().lower()
            if 'месяц назад' in date or 'месяца назад' in date or 'год назад' in date:
                stop_parsing = True
                break
                
            price = review.order_total.value if review.order_total else 0
            total_old += price
            total_new += estimate_review_earnings(price)
            count += 1
        return count

    added = process_batch(batch.reviews)
    next_id = batch.next_review_id
    page = 2
    
    while not stop_parsing and next_id:
        post_data = {'user_id': actual_user_id, 'continue': next_id, 'filter': ''}
        post_headers = headers.copy()
        post_headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
        
        success = False
        for attempt in range(3):
            await asyncio.sleep(get_smart_delay(True))
            try:
                r2 = await client.post('https://funpay.com/users/reviews', data=post_data, headers=post_headers, timeout=10.0)
                if r2.status_code == 429:
                    raise Exception('429')
                r2.raise_for_status()
                html_text2 = r2.text
                success = True
                break
            except Exception:
                await asyncio.sleep(2)
                    
        if not success:
            break
            
        next_batch = ReviewsParser(html_text2).parse()
        added = process_batch(next_batch.reviews)
        if added == 0: break
        next_id = next_batch.next_review_id
        page += 1

    return {'old': total_old, 'new': total_new}

async def worker(queue, proxies, results, sem):
    while True:
        try:
            uid = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
            
        proxy_url = random.choice(proxies) if proxies else None
        browser = get_browser_for_proxy(proxy_url) if proxy_url else "chrome120"
        proxies_dict = {'http': proxy_url, 'https': proxy_url} if proxy_url else None
        
        async with sem:
            try:
                async with requests.AsyncSession(proxies=proxies_dict, impersonate=browser, timeout=15.0) as client:
                    res = await parse_profile(client, uid)
                    if res:
                        results.append(res)
                        logger.info(f'[ID {uid}] Старая: {res["old"]:.2f} rub | Новая (Cardinal): {res["new"]:.2f} rub')
            except Exception as e:
                pass
        queue.task_done()

async def main():
    logger.info('Запуск сравнения топ-200...')
    proxies = load_proxies()
    
    queue = asyncio.Queue()
    with open('queue.txt', 'r', encoding='utf-8') as f:
        lines = [line.strip().split(':')[0] for line in f if line.strip()][:200]
        
    for uid in lines:
        queue.put_nowait(uid)
        
    results = []
    sem = asyncio.Semaphore(15)
    workers = [asyncio.create_task(worker(queue, proxies, results, sem)) for _ in range(15)]
    await asyncio.gather(*workers)
    
    sum_old = sum(r['old'] for r in results)
    sum_new = sum(r['new'] for r in results)
    
    logger.success('--- ИТОГИ СРАВНЕНИЯ ТОП-200 ПРОДАВЦОВ ЗА МЕСЯЦ ---')
    logger.success(f'Старый алгоритм (Без Cardinal): {sum_old:,.2f} rub')
    logger.success(f'Новый алгоритм (Cardinal V1):  {sum_new:,.2f} rub')
    diff = sum_old - sum_new
    perc = diff / sum_old * 100 if sum_old else 0
    logger.success(f'Разница (погрешность старого): {diff:,.2f} rub ({perc:.2f}%)')

if __name__ == '__main__':
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
