import asyncio
import time
from curl_cffi import requests
from utils import load_proxies, logger, get_browser_for_proxy
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))

async def check_proxy(proxy_url: str, sem: asyncio.Semaphore) -> dict:
    async with sem:
        proxies = {"http": proxy_url, "https": proxy_url}
        browser = get_browser_for_proxy(proxy_url)
        try:
            start = time.time()
            async with requests.AsyncSession(proxies=proxies, impersonate=browser, timeout=5.0) as session:
                resp = await session.get('https://funpay.com')
                if resp.status_code == 200:
                    return {'url': proxy_url, 'ping': time.time() - start}
        except Exception:
            pass
        return None

async def main():
    logger.info("Загрузка прокси из proxies.txt...")
    proxies = []
    proxy_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'proxies.txt')
    if os.path.exists(proxy_file):
        with open(proxy_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    p = line.strip()
                    if not p.startswith("http") and not p.startswith("socks"):
                        parts = p.split(":")
                        if len(parts) == 4:
                            proxies.append(f"socks5://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}")
                        else:
                            proxies.append(f"http://{p}")
                    else:
                        proxies.append(p)
    
    if not proxies:
        logger.error("Нет прокси для проверки!")
        return

    logger.info(f"Найдено {len(proxies)} прокси. Начинаем проверку...")
    sem = asyncio.Semaphore(100) # Одновременно 100 потоков
    tasks = [check_proxy(p, sem) for p in proxies]
    results = await asyncio.gather(*tasks)
    
    valid = [r for r in results if r is not None]
    valid.sort(key=lambda x: x['ping'])
    
    logger.success(f"Проверка завершена! Найдено рабочих: {len(valid)}")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base_dir, 'good_proxies.txt'), 'w', encoding='utf-8') as f:
        for v in valid:
            f.write(f"{v['url']}\n")
            
    logger.success("Рабочие прокси сохранены в good_proxies.txt")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
