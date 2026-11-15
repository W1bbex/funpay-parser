from __future__ import annotations

import asyncio
import random
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi import requests
from funpayparsers.parsers.reviews_parser import ReviewsParser as DefaultReviewsParser

from funpay_analytics.core import hide_proxy_credentials, logger

from funpay_analytics.parser.lot_filter import extract_profile_lots, match_and_filter_lots

FUNPAY_COOKIES = {"cy": "rub", "locale": "ru"}


def get_smart_delay(is_proxy: bool = False) -> float:
    """Returns randomized jitter delay between scraping requests."""
    chance = random.random()
    if is_proxy:
        if chance < 0.1:
            return random.uniform(1.5, 2.5)
        else:
            return random.uniform(0.5, 1.5)
    else:
        if chance < 0.1:
            return random.uniform(4.0, 6.0)
        else:
            return random.uniform(2.0, 4.0)


async def fetch_seller_reviews(
    client: requests.AsyncSession,
    user_id: str,
    actual_user_id: str,
    initial_batch: Any,
    headers: dict[str, str],
    proxy: str | None = None,
    max_reviews: int | None = None,
    reviews_parser_cls: Any = None,
) -> tuple[dict[str, list[dict[str, Any]]], int] | None:
    """Performs pagination and collects reviews for the target seller."""
    if reviews_parser_cls is None:
        reviews_parser_cls = DefaultReviewsParser
    total_reviews = 0
    categories_reviews: dict[str, list[dict[str, Any]]] = {}

    def process_batch(batch_reviews: list[Any]) -> int:
        nonlocal total_reviews
        count = 0
        for review in batch_reviews:
            if max_reviews is not None and total_reviews >= max_reviews:
                break
            date = (review.date_text or "").strip()
            category = review.category_str or "Неизвестно"
            price_val = float(review.order_total.value) if review.order_total else 0.0

            if category not in categories_reviews:
                categories_reviews[category] = []

            categories_reviews[category].append({
                "price": price_val,
                "rating": review.rating,
                "text": review.text or "",
                "reply": review.reply,
                "date": date,
            })
            total_reviews += 1
            count += 1
        return count

    process_batch(initial_batch.reviews)
    next_id = initial_batch.next_review_id
    page = 2

    while next_id:
        if max_reviews is not None and total_reviews >= max_reviews:
            logger.info(f"[ID {user_id}] Достигнут запрошенный лимит {max_reviews:,} отзывов. Завершаем сбор.")
            break

        post_data = {
            "user_id": actual_user_id,
            "continue": next_id,
            "filter": "",
        }

        post_headers = headers.copy()
        post_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

        success = False
        for attempt in range(4):
            await asyncio.sleep(get_smart_delay(bool(proxy)))
            try:
                r2 = await client.post(
                    "https://funpay.com/users/reviews",
                    data=post_data,
                    headers=post_headers,
                    cookies=FUNPAY_COOKIES,
                )
                if r2.status_code == 429:
                    raise Exception("429 Too Many Requests")
                r2.raise_for_status()
                html_text2 = r2.text
                success = True
                break
            except Exception as e:
                if "429" in str(e):
                    if attempt < 3:
                        delay = (attempt + 1) * 15
                        logger.warning(f"[ID {user_id}] Блок 429 на стр {page}. Ждем {delay}с (Попытка {attempt+1}/4)...")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"[ID {user_id}] Исчерпаны попытки пагинации на стр {page} (429): {e}")
                        break
                else:
                    if attempt < 3:
                        delay = (attempt + 1) * 2
                        logger.warning(
                            f"[ID {user_id}] Временная ошибка пагинации на стр {page} (попытка {attempt+1}/4): {e}. Повтор через {delay}с..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"[ID {user_id}] Исчерпаны попытки пагинации на стр {page}: {e}")
                        break

        if not success:
            logger.error(f"[ID {user_id}] Не удалось пройти страницу {page} после 4 попыток. Отменяем.")
            return None

        try:
            next_batch = reviews_parser_cls(html_text2).parse()
        except Exception as e:
            logger.error(f"[ID {user_id}] Ошибка разбора структуры отзывов на стр {page}: {e}")
            return None
        added = process_batch(next_batch.reviews)

        if page % 5 == 0 or (max_reviews is not None and total_reviews >= max_reviews):
            logger.info(f"[ID {user_id}] Собрано {total_reviews:,} отзывов (страница {page})...")

        if added == 0 or (max_reviews is not None and total_reviews >= max_reviews):
            break

        next_id = next_batch.next_review_id
        page += 1

    return categories_reviews, total_reviews


async def parse_profile(
    client: requests.AsyncSession,
    user_id: str,
    proxy: str | None = None,
    user_agent: str | None = None,
    max_reviews: int | None = None,
    reviews_parser_cls: Any = None,
) -> dict[str, Any] | None:
    """Parses full seller profile and associates candidate lots with reviews."""
    if reviews_parser_cls is None:
        reviews_parser_cls = DefaultReviewsParser
    if not user_agent:
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    url = f"https://funpay.com/users/{user_id}/"
    platform = '"macOS"' if ("Macintosh" in user_agent or "Mac OS X" in user_agent) else '"Windows"'
    headers = {
        "User-Agent": user_agent,
        "X-Requested-With": "XMLHttpRequest",
        "Sec-Ch-Ua": '"Not.A/Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": platform,
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    }

    masked_p = hide_proxy_credentials(proxy) if proxy else None
    proxy_info = f" (через прокси {masked_p})" if masked_p else " (напрямую без прокси)"
    logger.info(f"[ID {user_id}] Начинаем парсинг{proxy_info}...")

    html_text = None
    for attempt in range(2):
        try:
            response = await client.get(url, headers=headers, cookies=FUNPAY_COOKIES)
            if response.status_code == 429:
                raise Exception("429 Too Many Requests")
            response.raise_for_status()
            html_text = response.text
            break
        except Exception as e:
            err_msg = str(e)
            if "curl: (35)" in err_msg or "TLS connect error" in err_msg:
                logger.error(
                    f"[ID {user_id}] Ошибка TLS (35): Соединение с FunPay сброшено/заблокировано (ТСПУ / Cloudflare). "
                    "Требуется рабочий прокси."
                )
                return None
            if "404" in err_msg or (hasattr(e, "response") and getattr(e.response, "status_code", None) == 404):
                logger.warning(f"[ID {user_id}] Пользователь не найден (404).")
                return None
            if attempt < 1:
                if "429" in err_msg:
                    logger.warning(f"[ID {user_id}] Блок 429 на профиле. Пауза 5с перед повтором...")
                    await asyncio.sleep(5.0)
                else:
                    logger.warning(f"[ID {user_id}] Временная ошибка доступа ({e}). Повтор через 2с...")
                    await asyncio.sleep(2.0)
                continue
            logger.error(f"[ID {user_id}] Ошибка доступа: {e}")
            return None

    if not html_text:
        return None

    soup = BeautifulSoup(html_text, "html.parser")
    username_elem = soup.find("span", class_="mr4")
    if not username_elem:
        logger.error(f"[ID {user_id}] Ошибка парсинга: не удалось извлечь никнейм пользователя.")
        return None
    username = username_elem.text.strip()

    all_active_lots = extract_profile_lots(soup, user_id)
    try:
        batch = reviews_parser_cls(html_text).parse()
    except Exception as e:
        logger.error(f"[ID {user_id}] Ошибка разбора структуры профиля: {e}")
        return None
    actual_user_id = str(batch.user_id) if batch.user_id else str(user_id)

    review_res = await fetch_seller_reviews(
        client,
        user_id,
        actual_user_id,
        batch,
        headers,
        proxy=proxy,
        max_reviews=max_reviews,
        reviews_parser_cls=reviews_parser_cls,
    )
    if review_res is None:
        return None
    categories_reviews, total_reviews = review_res

    categories = match_and_filter_lots(all_active_lots, categories_reviews)

    logger.success(f"[ID {user_id}] Готово! Собрано отзывов: {total_reviews}.")

    return {
        "schema_version": 2,
        "seller_id": user_id,
        "username": username,
        "currency": "RUB",
        "total_reviews": total_reviews,
        "categories": categories,
    }
