"""SQLite-based news storage with URL deduplication."""

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from news_collect.core.models import NewsItem


class NewsStorage:
    """Thread-safe SQLite storage for financial news.

    Uses URL as a UNIQUE key for automatic deduplication on insert.
    """

    def __init__(self, db_path: str = "data/news.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path))
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
        """Create tables and indexes if they don't exist."""
        conn = self._conn
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                content TEXT,
                publish_time TEXT,
                crawl_time TEXT NOT NULL,
                category TEXT,
                raw_data TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_source
            ON news(source, crawl_time)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_publish_time
            ON news(publish_time)
        """)
        conn.commit()

    # ── write ──────────────────────────────────────────────

    def insert(self, item: NewsItem) -> bool:
        """Insert a news item. Returns True if inserted, False if it was a duplicate (URL already exists)."""
        try:
            cursor = self._conn.execute(
                """INSERT OR IGNORE INTO news
                   (url, title, source, content, publish_time, crawl_time, category, raw_data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.url,
                    item.title,
                    item.source,
                    item.content,
                    item.publish_time.isoformat() if item.publish_time else None,
                    item.crawl_time.isoformat(),
                    item.category,
                    self._serialize_raw(item.raw_data),
                ),
            )
            self._conn.commit()
            return cursor.rowcount > 0
        except Exception:
            return False

    def insert_batch(self, items: list[NewsItem]) -> tuple[int, int]:
        """Batch insert. Returns (inserted_count, skipped_duplicates)."""
        inserted = 0
        skipped = 0
        for item in items:
            if self.insert(item):
                inserted += 1
            else:
                skipped += 1
        return inserted, skipped

    def exists(self, url: str) -> bool:
        """Check if a URL already exists in storage."""
        row = self._conn.execute(
            "SELECT 1 FROM news WHERE url = ? LIMIT 1", (url,)
        ).fetchone()
        return row is not None

    # ── read ───────────────────────────────────────────────

    def query(
        self,
        source: Optional[str] = None,
        days: int = 7,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Query news items with optional filters."""
        since = (datetime.now() - timedelta(days=days)).isoformat()
        sql = "SELECT * FROM news WHERE crawl_time >= ?"
        params: list = [since]

        if source:
            sql += " AND source = ?"
            params.append(source)

        sql += " ORDER BY crawl_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def stats(self, source: Optional[str] = None) -> dict:
        """Return statistics about stored news."""
        if source:
            row = self._conn.execute(
                "SELECT COUNT(*) as total, MIN(crawl_time) as first_crawl, MAX(crawl_time) as last_crawl FROM news WHERE source = ?",
                (source,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) as total, MIN(crawl_time) as first_crawl, MAX(crawl_time) as last_crawl FROM news"
            ).fetchone()

        # Per-source breakdown
        sources = self._conn.execute(
            "SELECT source, COUNT(*) as count FROM news GROUP BY source ORDER BY count DESC"
        ).fetchall()

        return {
            "total": row["total"],
            "first_crawl": row["first_crawl"],
            "last_crawl": row["last_crawl"],
            "by_source": {s["source"]: s["count"] for s in sources},
        }

    def cleanup(self, retention_days: int = 90):
        """Delete news older than retention_days."""
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
        self._conn.execute("DELETE FROM news WHERE crawl_time < ?", (cutoff,))
        self._conn.commit()

    def count(self, source: Optional[str] = None) -> int:
        """Get total count of news items."""
        if source:
            row = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM news WHERE source = ?", (source,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) as cnt FROM news").fetchone()
        return row["cnt"]

    # ── helpers ────────────────────────────────────────────

    @staticmethod
    def _serialize_raw(raw_data: Optional[dict]) -> Optional[str]:
        if raw_data is None:
            return None
        import json
        return json.dumps(raw_data, ensure_ascii=False)

    def close(self):
        """Close the thread-local connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
