import pytest
import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from parser import parse_profile, get_review_interval, is_candidate
from unittest.mock import patch, MagicMock
from decimal import Decimal

class MockResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        
    def raise_for_status(self):
        pass

class MockSession:
    def __init__(self, get_responses, post_responses):
        self.get_responses = get_responses
        self.post_responses = post_responses
        self.post_call_count = 0

    async def get(self, url, headers=None, **kwargs):
        return self.get_responses.get(url, MockResponse(""))

    async def post(self, url, data=None, headers=None, **kwargs):
        if self.post_call_count < len(self.post_responses):
            resp = self.post_responses[self.post_call_count]
            self.post_call_count += 1
            return resp
        return MockResponse("")

def test_intervals():
    assert get_review_interval(20) == (Decimal('15'), Decimal('25'))
    assert get_review_interval(100) == (Decimal('95'), Decimal('150'))
    assert get_review_interval(200) == (Decimal('150'), Decimal('250'))
    assert get_review_interval(1000) == (Decimal('950'), Decimal('1500'))
    assert get_review_interval(2000) == (Decimal('1500'), Decimal('2500'))
    assert get_review_interval(15) is None

def test_is_candidate():
    lower, upper = get_review_interval(1000)
    # Лот за 1 ₽ должен подходить (q = 950 -> цена = 950 < 1500)
    assert is_candidate(1.0, lower, upper) is True
    # Лот за 2000 ₽ не должен подходить для 1000
    assert is_candidate(2000.0, lower, upper) is False

def test_parser_normal_filter():
    asyncio.run(run_test_normal_filter())

def test_parser_disable_filter():
    asyncio.run(run_test_disable_filter())

def test_parser_pagination():
    asyncio.run(run_test_pagination())

@patch("parser.ReviewsParser")
async def run_test_normal_filter(mock_reviews_parser_class):
    html_profile = """
    <span class="mr4">TestSeller</span>
    <div class="mb20">
        <div class="offer">
            <div class="offer-list-title">Каналы Telegram</div>
            <a href="https://funpay.com/lots/offer?id=111" class="tc-item">
                <div class="tc-desc">Канал 1</div>
                <div class="tc-price">1.00 <span class="rub">₽</span></div>
                <div class="tc-amount">99 шт.</div>
            </a>
            <a href="https://funpay.com/lots/offer?id=222" class="tc-item">
                <div class="tc-desc">Канал 2</div>
                <div class="tc-price">10.00 <span class="rub">₽</span></div>
            </a>
            <a href="https://funpay.com/lots/offer?id=333" class="tc-item">
                <div class="tc-desc">Канал 3</div>
                <div class="tc-price">189.99 <span class="rub">₽</span></div>
            </a>
        </div>
        <div class="offer">
            <div class="offer-list-title">Услуги Telegram</div>
            <a href="https://funpay.com/lots/offer?id=444" class="tc-item">
                <div class="tc-desc">Канал 4</div>
                <div class="tc-price">500.0 <span class="rub">₽</span></div>
            </a>
            <a href="https://funpay.com/lots/offer?id=555" class="tc-item">
                <div class="tc-desc">Канал 5</div>
                <div class="tc-price">1000.0 <span class="rub">₽</span></div>
            </a>
            <a href="https://funpay.com/lots/offer?id=BAD" class="tc-item">
                <div class="tc-desc">Канал Без Цены</div>
            </a>
            <a href="https://funpay.com/lots/offer" class="tc-item">
                <div class="tc-desc">Канал Без ID</div>
                <div class="tc-price">10.0 <span class="rub">₽</span></div>
            </a>
        </div>
    </div>
    """

    session = MockSession(
        get_responses={"https://funpay.com/users/999/": MockResponse(html_profile)},
        post_responses=[]
    )
    
    mock_batch = MagicMock()
    mock_batch.user_id = "999"
    mock_batch.next_review_id = None
    
    # Отзывы 20, 200, 300
    r1 = MagicMock(); r1.category_str = "Telegram"; r1.order_total.value = 20.0
    r1.date_text = "Месяц назад"; r1.rating = 5; r1.text = "1"; r1.reply = None
    
    r2 = MagicMock(); r2.category_str = "Telegram"; r2.order_total.value = 200.0
    r2.date_text = "Месяц назад"; r2.rating = 5; r2.text = "2"; r2.reply = None

    r3 = MagicMock(); r3.category_str = "Telegram"; r3.order_total.value = 300.0
    r3.date_text = "Месяц назад"; r3.rating = 5; r3.text = "3"; r3.reply = None
    
    mock_batch.reviews = [r1, r2, r3]
    
    mock_instance = MagicMock()
    mock_instance.parse.return_value = mock_batch
    mock_reviews_parser_class.return_value = mock_instance

    res = await parse_profile(session, "999")
    
    assert res['schema_version'] == 2
    cats = res['categories']
    assert "Telegram" in cats
    cat = cats["Telegram"]
    
    lots = cat['candidate_lots']
    ids = [l['id'] for l in lots]
    
    # 1, 10, 189.99 pass. 500, 1000 fail.
    # Bad ID "0" or "" or Bad price "0" shouldn't be here
    assert "111" in ids
    assert "222" in ids
    assert "333" in ids
    assert "444" not in ids
    assert "555" not in ids
    
    assert "BAD" not in ids
    assert "0" not in ids
    assert "" not in ids

    # Check stock number vs null
    lot_111 = next(l for l in lots if l['id'] == "111")
    assert lot_111['stock'] == 99
    lot_222 = next(l for l in lots if l['id'] == "222")
    assert lot_222['stock'] is None

@patch("parser.ReviewsParser")
async def run_test_disable_filter(mock_reviews_parser_class):
    html_profile = """
    <span class="mr4">TestSeller</span>
    <div class="mb20">
        <div class="offer">
            <div class="offer-list-title">Каналы Telegram</div>
            <a href="https://funpay.com/lots/offer?id=444" class="tc-item">
                <div class="tc-desc">Канал 4</div>
                <div class="tc-price">500.0 <span class="rub">₽</span></div>
            </a>
            <a href="https://funpay.com/lots/offer?id=555" class="tc-item">
                <div class="tc-desc">Канал 5</div>
                <div class="tc-price">1000.0 <span class="rub">₽</span></div>
            </a>
        </div>
    </div>
    """

    session = MockSession(
        get_responses={"https://funpay.com/users/999/": MockResponse(html_profile)},
        post_responses=[]
    )
    
    mock_batch = MagicMock()
    mock_batch.user_id = "999"
    mock_batch.next_review_id = None
    
    # Отзыв 15
    r1 = MagicMock(); r1.category_str = "Telegram"; r1.order_total.value = 15.0
    r1.date_text = "Месяц назад"; r1.rating = 5; r1.text = "1"; r1.reply = None
    
    mock_batch.reviews = [r1]
    
    mock_instance = MagicMock()
    mock_instance.parse.return_value = mock_batch
    mock_reviews_parser_class.return_value = mock_instance

    res = await parse_profile(session, "999")
    
    cats = res['categories']
    assert "Telegram" in cats
    cat = cats["Telegram"]
    
    lots = cat['candidate_lots']
    ids = [l['id'] for l in lots]
    
    # Filter is disabled, so both 500 and 1000 should pass!
    assert "444" in ids
    assert "555" in ids

@patch("parser.asyncio.sleep")
@patch("parser.ReviewsParser")
async def run_test_pagination(mock_reviews_parser_class, mock_sleep):
    html_profile = """<span class="mr4">TestSeller</span>"""

    session = MockSession(
        get_responses={"https://funpay.com/users/999/": MockResponse(html_profile)},
        post_responses=[MockResponse("post1")]
    )
    
    mock_batch1 = MagicMock()
    mock_batch1.user_id = "999"
    mock_batch1.next_review_id = "12345"
    
    r1 = MagicMock(); r1.category_str = "Steam"; r1.order_total.value = 100.0
    r1.date_text = "Месяц назад"; r1.rating = 5; r1.text = "1"; r1.reply = "Ответ 1"
    
    mock_batch1.reviews = [r1]
    
    mock_batch2 = MagicMock()
    mock_batch2.user_id = "999"
    mock_batch2.next_review_id = None
    
    r2 = MagicMock(); r2.category_str = "Steam"; r2.order_total.value = 200.0
    r2.date_text = "Год назад"; r2.rating = None; r2.text = "2"; r2.reply = None
    
    mock_batch2.reviews = [r2]
    
    mock_instance1 = MagicMock()
    mock_instance1.parse.return_value = mock_batch1
    
    mock_instance2 = MagicMock()
    mock_instance2.parse.return_value = mock_batch2
    
    mock_reviews_parser_class.side_effect = [mock_instance1, mock_instance2]

    res = await parse_profile(session, "999")
    
    assert res['total_reviews'] == 2
    reviews = res['categories']["Steam"]["reviews"]
    assert len(reviews) == 2
    assert reviews[0]['reply'] == "Ответ 1"
    
    # Rating null is preserved, not replaced by 5
    assert reviews[1]['rating'] is None
    # Date "Год назад" is saved
    assert reviews[1]['date'] == "Год назад"
    
    assert session.post_call_count == 1

@patch("parser.ReviewsParser")
@pytest.mark.parametrize("max_reviews, first_page_size", [(1, 1), (10, 25)])
def test_parser_limits_first_page_and_skips_pagination(mock_reviews_parser_class, max_reviews, first_page_size):
    async def run():
        html_profile = """
        <html><body>
        <span class="mr4">TestSeller</span>
        </body></html>
        """
        session = MockSession(
            get_responses={"https://funpay.com/users/999/": MockResponse(html_profile)},
            post_responses=[MockResponse("post1"), MockResponse("post2")]
        )
        mock_batch1 = MagicMock()
        mock_batch1.user_id = "999"
        mock_batch1.next_review_id = "111"
        r1 = MagicMock(); r1.category_str = "Steam"; r1.order_total.value = 100.0
        r1.date_text = "Сегодня"; r1.rating = 5; r1.text = "1"; r1.reply = None
        mock_batch1.reviews = [r1] * first_page_size

        mock_batch2 = MagicMock()
        mock_batch2.user_id = "999"
        mock_batch2.next_review_id = "222"
        r2 = MagicMock(); r2.category_str = "Steam"; r2.order_total.value = 200.0
        r2.date_text = "Вчера"; r2.rating = 5; r2.text = "2"; r2.reply = None
        mock_batch2.reviews = [r2]

        mock_batch3 = MagicMock()
        mock_batch3.user_id = "999"
        mock_batch3.next_review_id = None
        r3 = MagicMock(); r3.category_str = "Steam"; r3.order_total.value = 300.0
        r3.date_text = "Месяц назад"; r3.rating = 5; r3.text = "3"; r3.reply = None
        mock_batch3.reviews = [r3]

        m1 = MagicMock(); m1.parse.return_value = mock_batch1
        m2 = MagicMock(); m2.parse.return_value = mock_batch2
        m3 = MagicMock(); m3.parse.return_value = mock_batch3
        mock_reviews_parser_class.side_effect = [m1, m2, m3]

        res = await parse_profile(session, "999", max_reviews=max_reviews)
        assert res["total_reviews"] == max_reviews
        assert len(res["categories"]["Steam"]["reviews"]) == max_reviews
        assert session.post_call_count == 0
        mock_reviews_parser_class.assert_called_once()

    asyncio.run(run())
