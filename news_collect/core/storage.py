"""SQLite-based news storage with URL deduplication."""

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from news_collect.core.models import AnalysisOpinion, NewsEvent, NewsItem


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
                processed INTEGER NOT NULL DEFAULT 0,
                raw_data TEXT
            )
        """)
        # Add processed column to existing tables (safe to run even if exists)
        try:
            conn.execute("ALTER TABLE news ADD COLUMN processed INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass  # column already exists
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_source
            ON news(source, crawl_time)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_publish_time
            ON news(publish_time)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_processed
            ON news(processed, crawl_time)
        """)

        # ── analysis result tables ─────────────────────────
        # Migrate: drop old table if schema changed (dev safety — no prod data yet)
        try:
            conn.execute("ALTER TABLE analysis_opinions RENAME COLUMN short_term_impact TO short_term_view")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE analysis_opinions RENAME COLUMN long_term_impact TO long_term_view")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE analysis_opinions RENAME COLUMN short_term_reason TO short_term_view_reason")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE analysis_opinions RENAME COLUMN long_term_reason TO long_term_view_reason")
        except Exception:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis_opinions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                variety TEXT NOT NULL,
                analysis_date TEXT,
                short_term_view TEXT,
                long_term_view TEXT,
                short_term_view_reason TEXT,
                long_term_view_reason TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_opinions_url
            ON analysis_opinions(url)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_opinions_variety
            ON analysis_opinions(variety, analysis_date)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS news_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                event_summary TEXT NOT NULL,
                event_time TEXT,
                keywords TEXT DEFAULT '',
                affects_futures INTEGER NOT NULL DEFAULT 0,
                affected_variety TEXT,
                impact_level TEXT DEFAULT '',
                impact_analysis TEXT,
                expected_end_time TEXT,
                created_at TEXT NOT NULL
            )
        """)
        # Migrate: add keywords column to existing table
        try:
            conn.execute("ALTER TABLE news_events ADD COLUMN keywords TEXT DEFAULT ''")
        except Exception:
            pass  # column already exists
        # Migrate: add impact_level column to existing table
        try:
            conn.execute("ALTER TABLE news_events ADD COLUMN impact_level TEXT DEFAULT ''")
        except Exception:
            pass  # column already exists
        # Migrate: add expected_end_time column
        try:
            conn.execute("ALTER TABLE news_events ADD COLUMN expected_end_time TEXT")
        except Exception:
            pass
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_url
            ON news_events(url)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_time
            ON news_events(event_time)
        """)
        conn.commit()

    # ── write ──────────────────────────────────────────────

    def insert(self, item: NewsItem) -> bool:
        """Insert a news item. Returns True if inserted, False if it was a duplicate (URL already exists)."""
        try:
            cursor = self._conn.execute(
                """INSERT OR IGNORE INTO news
                   (url, title, source, content, publish_time, crawl_time, category, processed, raw_data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.url,
                    item.title,
                    item.source,
                    item.content,
                    item.publish_time.isoformat() if item.publish_time else None,
                    item.crawl_time.isoformat(),
                    item.category,
                    item.processed,
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

    # ── analysis methods ──────────────────────────────────

    def fetch_unprocessed(self, limit: int = 50) -> list[dict]:
        """Fetch unprocessed news items (processed=0), oldest first.

        Includes items whose content is empty but whose title is long enough
        (>20 chars) to serve as content for the LLM (e.g. Sina 7x24 flash news).

        Returns list of dicts with keys: id, url, title, source, content, publish_time.
        """
        rows = self._conn.execute(
            """SELECT id, url, title, source, content, publish_time
               FROM news
               WHERE processed = 0
                 AND (
                   (content IS NOT NULL AND content != '')
                   OR (length(title) > 20)
                 )
               ORDER BY crawl_time ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def insert_opinion(self, opinion: AnalysisOpinion) -> bool:
        """Insert a single analysis opinion record. Returns True on success."""
        try:
            self._conn.execute(
                """INSERT INTO analysis_opinions
                   (url, variety, analysis_date, short_term_view,
                    long_term_view, short_term_view_reason, long_term_view_reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    opinion.url,
                    opinion.variety,
                    opinion.analysis_date,
                    opinion.short_term_view,
                    opinion.long_term_view,
                    opinion.short_term_view_reason,
                    opinion.long_term_view_reason,
                    opinion.created_at,
                ),
            )
            self._conn.commit()
            return True
        except Exception:
            return False

    def insert_opinions_batch(self, opinions: list[AnalysisOpinion]) -> int:
        """Batch insert opinion records. Returns count inserted."""
        count = 0
        for op in opinions:
            if self.insert_opinion(op):
                count += 1
        return count

    def insert_event(self, event: NewsEvent) -> bool:
        """Insert a single news event record. Returns True on success."""
        try:
            self._conn.execute(
                """INSERT INTO news_events
                   (url, event_summary, event_time, keywords, affects_futures,
                    affected_variety, impact_level, impact_analysis,
                    expected_end_time, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.url,
                    event.event_summary,
                    event.event_time,
                    event.keywords or "",
                    1 if event.affects_futures else 0,
                    event.affected_variety,
                    event.impact_level or "",
                    event.impact_analysis,
                    event.expected_end_time,
                    event.created_at,
                ),
            )
            self._conn.commit()
            return True
        except Exception:
            return False

    def insert_events_batch(self, events: list[NewsEvent]) -> int:
        """Batch insert event records. Returns count inserted."""
        count = 0
        for ev in events:
            if self.insert_event(ev):
                count += 1
        return count

    def _retry_on_lock(self, fn, *args, max_retries: int = 5):
        """Retry a DB write operation on SQLite lock errors with backoff."""
        import time
        for attempt in range(max_retries):
            try:
                return fn(*args)
            except Exception as e:
                err = str(e).lower()
                if "locked" in err or "database is" in err:
                    wait = 0.05 * (2 ** attempt)  # 50ms, 100ms, 200ms, 400ms, 800ms
                    time.sleep(wait)
                    continue
                return None  # non-lock error → don't retry
        return None  # all retries exhausted

    def mark_processed(self, url: str) -> bool:
        """Mark a news item as processed (processed=1)."""

        def _do():
            self._conn.execute(
                "UPDATE news SET processed = 1 WHERE url = ?", (url,)
            )
            self._conn.commit()
            return True

        return self._retry_on_lock(_do) or False

    def mark_processed_batch(self, urls: list[str]) -> int:
        """Mark multiple URLs as processed. Returns count updated."""
        if not urls:
            return 0

        def _do():
            placeholders = ",".join("?" for _ in urls)
            cursor = self._conn.execute(
                f"UPDATE news SET processed = 1 WHERE url IN ({placeholders})",
                urls,
            )
            self._conn.commit()
            return cursor.rowcount

        return self._retry_on_lock(_do) or 0

    def mark_failed(self, url: str) -> bool:
        """Mark a news item as failed (processed=2). Failed items are
        excluded from future analysis cycles to avoid wasting tokens."""

        def _do():
            self._conn.execute(
                "UPDATE news SET processed = 2 WHERE url = ?", (url,)
            )
            self._conn.commit()
            return True

        return self._retry_on_lock(_do) or False

    def mark_failed_batch(self, urls: list[str]) -> int:
        """Mark multiple URLs as failed (processed=2). Returns count updated."""
        if not urls:
            return 0

        def _do():
            placeholders = ",".join("?" for _ in urls)
            cursor = self._conn.execute(
                f"UPDATE news SET processed = 2 WHERE url IN ({placeholders})",
                urls,
            )
            self._conn.commit()
            return cursor.rowcount

        return self._retry_on_lock(_do) or 0

    def mark_no_content_failed(self) -> int:
        """Mark unprocessable items as failed (processed=2).

        Only marks items where content is empty AND the title is too short
        (<=20 chars) to serve as content. Items with long titles (e.g. Sina
        7x24 flash news) are kept for analysis — the title will be used as
        the LLM prompt content.
        Returns the count of items marked.
        """
        try:
            cursor = self._conn.execute(
                """UPDATE news SET processed = 2
                   WHERE processed = 0
                   AND (content IS NULL OR content = '')
                   AND length(title) <= 20"""
            )
            self._conn.commit()
            return cursor.rowcount
        except Exception:
            return 0

    def unprocessed_count(self) -> int:
        """Return the count of unprocessed news items with content."""
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM news WHERE processed = 0 AND content IS NOT NULL AND content != ''"
        ).fetchone()
        return row["cnt"] if row else 0

    def analysis_stats(self) -> dict:
        """Return statistics about analysis results."""
        opinions_count = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM analysis_opinions"
        ).fetchone()["cnt"]
        events_count = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM news_events"
        ).fetchone()["cnt"]
        opinions_by_variety = self._conn.execute(
            "SELECT variety, COUNT(*) as cnt FROM analysis_opinions GROUP BY variety ORDER BY cnt DESC"
        ).fetchall()
        events_affecting = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM news_events WHERE affects_futures = 1"
        ).fetchone()["cnt"]

        return {
            "total_opinions": opinions_count,
            "total_events": events_count,
            "events_affecting_futures": events_affecting,
            "opinions_by_variety": {r["variety"]: r["cnt"] for r in opinions_by_variety},
        }

    def close(self):
        """Close the thread-local connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
