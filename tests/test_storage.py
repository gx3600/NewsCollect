"""Tests for SQLite news storage."""

import os
import tempfile
from pathlib import Path

import pytest

from news_collect.core.models import NewsItem
from news_collect.core.storage import NewsStorage


class TestNewsStorage:
    """Test the NewsStorage class."""

    @pytest.fixture
    def storage(self):
        """Create a temporary storage for testing."""
        tmp = tempfile.mktemp(suffix=".db")
        s = NewsStorage(tmp)
        yield s
        s.close()
        if os.path.exists(tmp):
            os.remove(tmp)

    def test_insert_and_exists(self, storage):
        """Test inserting a news item and checking existence."""
        item = NewsItem(
            url="https://example.com/news/1",
            title="Test News",
            source="test",
            content="This is a test.",
        )

        # First insert should succeed
        assert storage.insert(item) is True
        assert storage.exists("https://example.com/news/1") is True

        # Duplicate insert should return False
        assert storage.insert(item) is False

    def test_insert_batch(self, storage):
        """Test batch insert with dedup."""
        items = [
            NewsItem(url=f"https://example.com/news/{i}", title=f"News {i}", source="test")
            for i in range(5)
        ]
        # Add a duplicate
        items.append(NewsItem(url="https://example.com/news/0", title="News 0 dup", source="test"))

        inserted, skipped = storage.insert_batch(items)
        assert inserted == 5
        assert skipped == 1

    def test_query(self, storage):
        """Test querying with filters."""
        from datetime import datetime, timedelta

        for i in range(10):
            item = NewsItem(
                url=f"https://example.com/{i}",
                title=f"Article {i}",
                source="test" if i < 5 else "other",
                publish_time=datetime.now() - timedelta(hours=i),
            )
            storage.insert(item)

        # Query all recent
        results = storage.query(days=1, limit=100)
        assert len(results) == 10

        # Query by source
        results = storage.query(source="test", days=1)
        assert len(results) == 5

        # Query with limit
        results = storage.query(limit=3)
        assert len(results) == 3

    def test_stats(self, storage):
        """Test stats generation."""
        for i in range(3):
            item = NewsItem(
                url=f"https://example.com/{i}",
                title=f"Article {i}",
                source="test",
            )
            storage.insert(item)

        s = storage.stats()
        assert s["total"] == 3
        assert s["by_source"]["test"] == 3

    def test_cleanup(self, storage):
        """Test old data cleanup."""
        from datetime import datetime, timedelta

        # Insert an old item
        old_item = NewsItem(
            url="https://example.com/old",
            title="Old News",
            source="test",
            crawl_time=datetime.now() - timedelta(days=100),
        )
        storage.insert(old_item)

        # Insert a recent item
        new_item = NewsItem(
            url="https://example.com/new",
            title="New News",
            source="test",
        )
        storage.insert(new_item)

        assert storage.count() == 2

        # Cleanup items older than 90 days
        storage.cleanup(retention_days=90)
        assert storage.count() == 1
        assert storage.exists("https://example.com/new") is True
        assert storage.exists("https://example.com/old") is False
