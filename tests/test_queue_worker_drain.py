import asyncio
import pytest
from unittest.mock import patch, AsyncMock
from parser import parse_worker, mass_parse


def test_parse_worker_exits_on_consecutive_errors():
    async def _run():
        queue = asyncio.Queue()
        queue.put_nowait("1001")
        queue.put_nowait("1002")
        queue.put_nowait("1003")
        queue.put_nowait("1004")

        results = []
        library = {}
        stats = {"parsed_count": 0, "total_reviews": 0, "errors": 0, "proxy_success": {}}
        retry_map = {}

        # Mock parse_profile to always return None (simulating failure)
        with patch("parser.parse_profile", new=AsyncMock(return_value=None)):
            with patch("parser.requests.AsyncSession") as mock_session_cls:
                mock_session = AsyncMock()
                mock_session.__aenter__.return_value = mock_session
                mock_session_cls.return_value = mock_session

                # Worker will fail 3 times and break
                await parse_worker(1, "test-ip", "http://fake-proxy:8080", queue, results, library, stats, retry_map)

        # Worker should have exited after consecutive errors, leaving items in queue
        assert queue.qsize() > 0
        assert stats["errors"] >= 3

    asyncio.run(_run())


def test_mass_parse_detects_undrained_queue(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "queue.txt").write_text("1001:5\n1002:10\n1003:15\n", encoding="utf-8")

    library = {}
    stats = {"parsed_count": 0, "total_reviews": 0, "errors": 0, "proxy_success": {}}

    async def _run():
        # Mock parse_worker to immediately exit without draining queue
        async def fake_worker(*args, **kwargs):
            pass

        with patch("parser.load_proxies", return_value=["http://p1:8080"]):
            with patch("parser.ping_and_rank", new=AsyncMock(return_value=[{"name": "p1", "url": "http://p1:8080"}])):
                with patch("parser.parse_worker", new=fake_worker):
                    await mass_parse(library, stats)

    asyncio.run(_run())
    assert stats.get("unprocessed_count", 0) == 3
