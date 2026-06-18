"""Tests for the crawler engine."""

import os
import tempfile
from pathlib import Path

import pytest

from news_collect.core.models import NewsItem
from news_collect.core.storage import NewsStorage
from news_collect.utils.config import Config


class TestCrawlerEngine:
    """Test CrawlerEngine functionality."""

    @pytest.fixture
    def storage(self):
        """Temporary storage."""
        tmp = tempfile.mktemp(suffix=".db")
        s = NewsStorage(tmp)
        yield s
        s.close()
        if os.path.exists(tmp):
            os.remove(tmp)

    def test_engine_creation(self, storage):
        """Test engine initializes correctly."""
        from news_collect.core.engine import CrawlerEngine

        engine = CrawlerEngine(storage=storage)
        assert engine.storage is storage
        assert engine.stats["total_crawled"] == 0

    def test_crawl_result(self):
        """Test CrawlResult representation."""
        from news_collect.core.engine import CrawlResult

        result = CrawlResult(
            items=[],
            stats={"total_crawled": 10, "total_new": 5, "total_skipped": 5},
            source_stats={"eastmoney": {"items": 10, "new": 5, "skipped": 5}},
        )
        assert result.stats["total_new"] == 5
        assert "10" in repr(result)
