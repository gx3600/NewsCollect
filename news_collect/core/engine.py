"""Crawler engine — orchestrates spider execution, result collection, and storage.

Handles graceful shutdown via signal handlers, uses Scrapling checkpoint
support for pause/resume of long crawls.
"""

import logging
import signal
import sys
from typing import Optional

from news_collect.core.models import NewsItem
from news_collect.core.storage import NewsStorage
from news_collect.utils.config import Config

logger = logging.getLogger(__name__)


class CrawlerEngine:
    """Orchestrates running news source spiders and persisting results.

    Usage:
        engine = CrawlerEngine()
        result = engine.run_sources(["cnbc", "reuters"])
        print(result.stats)
    """

    def __init__(
        self,
        storage: Optional[NewsStorage] = None,
        config: Optional[Config] = None,
    ):
        self.config = config or Config()
        self.storage = storage or NewsStorage(self.config.db_path)

        # Stats
        self._stats: dict = {"total_crawled": 0, "total_new": 0, "total_skipped": 0}
        self._results: list[NewsItem] = []

        # Graceful shutdown
        self._shutdown_requested = False
        self._setup_signal_handlers()

    # ── public API ─────────────────────────────────────────

    def run_sources(
        self,
        names: Optional[list[str]] = None,
        dev_mode: bool = False,
    ) -> "CrawlResult":
        """Run one or more named sources synchronously.

        Scrapling's Spider.start() manages its own async event loop internally,
        so we call it directly from sync code.

        Args:
            names: List of source names to run. If None, runs all enabled sources.
            dev_mode: If True, use cached responses (no live HTTP).

        Returns:
            CrawlResult with stats and items.
        """
        from news_collect.sources import get_source, auto_discover

        # Ensure sources are registered
        auto_discover()

        if names is None:
            names = list(self.config.enabled_sources.keys())

        all_items: list[NewsItem] = []
        source_stats: dict[str, dict] = {}

        for name in names:
            if self._shutdown_requested:
                logger.info("Shutdown requested, skipping remaining sources.")
                break

            source_cfg = self.config.get_source(name)
            if source_cfg is None:
                logger.warning(f"Source '{name}' not found in config, skipping.")
                continue

            if not source_cfg.enabled:
                logger.info(f"Source '{name}' is disabled, skipping.")
                continue

            logger.info(f"─── Running source: {name} ───")

            try:
                items = self._run_single_source(name, source_cfg, dev_mode)
                all_items.extend(items)
                source_stats[name] = {
                    "items": len(items),
                    "new": 0,
                    "skipped": 0,
                }

                # Persist to storage
                inserted, skipped = self.storage.insert_batch(items)
                source_stats[name]["new"] = inserted
                source_stats[name]["skipped"] = skipped

                self._stats["total_new"] += inserted
                self._stats["total_skipped"] += skipped
                self._stats["total_crawled"] += len(items)

                logger.info(
                    f"─── {name}: {len(items)} crawled, "
                    f"{inserted} new, {skipped} duplicates ───"
                )

            except Exception as e:
                logger.error(f"Error running source '{name}': {e}", exc_info=True)
                source_stats[name] = {"items": 0, "new": 0, "skipped": 0, "error": str(e)}

        return CrawlResult(
            items=all_items,
            stats=self._stats,
            source_stats=source_stats,
        )

    def run_all(self, dev_mode: bool = False) -> "CrawlResult":
        """Run all enabled sources from config."""
        names = list(self.config.enabled_sources.keys())
        if not names:
            logger.warning("No enabled sources found in config!")
            return CrawlResult()
        return self.run_sources(names, dev_mode)

    # ── internal ────────────────────────────────────────────

    def _run_single_source(
        self,
        name: str,
        source_cfg,
        dev_mode: bool,
    ) -> list[NewsItem]:
        """Run a single source spider synchronously and return its items.

        Scrapling's Spider.start() uses anyio.run() internally, which manages
        its own asyncio event loop.
        """
        from news_collect.sources import get_source

        SpiderCls = get_source(name)
        if SpiderCls is None:
            raise ValueError(f"Source '{name}' is not registered.")

        spider = SpiderCls(
            crawldir=f"data/checkpoints/{name}" if not dev_mode else None,
        )
        spider.development_mode = dev_mode
        spider.download_delay = source_cfg.download_delay
        spider.fetch_content = source_cfg.fetch_content

        # start() blocks until complete (uses anyio.run internally)
        result = spider.start()

        # Collect items — they could be raw dicts or NewsItem objects
        items: list[NewsItem] = []
        for raw_item in result.items:
            if isinstance(raw_item, NewsItem):
                items.append(raw_item)
            elif isinstance(raw_item, dict):
                items.append(spider.item_to_newsitem(raw_item))

        return items

    # ── signal handling ────────────────────────────────────

    def _setup_signal_handlers(self):
        """Register SIGINT/SIGTERM for graceful shutdown."""
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
        except (ValueError, OSError):
            # Can't set signal handlers in some environments (e.g. threads)
            pass

    def _handle_signal(self, signum, frame):
        """Signal handler — request graceful shutdown."""
        logger.info(f"Received signal {signum}. Shutting down gracefully...")
        self._shutdown_requested = True

    # ── utility ────────────────────────────────────────────

    def cleanup_old_news(self):
        """Delete expired news based on retention_days config."""
        days = self.config.retention_days
        count_before = self.storage.count()
        self.storage.cleanup(days)
        count_after = self.storage.count()
        logger.info(f"Cleanup: removed {count_before - count_after} old records.")

    @property
    def stats(self) -> dict:
        return self._stats


class CrawlResult:
    """Result of a crawl run."""

    def __init__(
        self,
        items: Optional[list[NewsItem]] = None,
        stats: Optional[dict] = None,
        source_stats: Optional[dict] = None,
    ):
        self.items: list[NewsItem] = items or []
        self.stats: dict = stats or {}
        self.source_stats: dict = source_stats or {}

    def __repr__(self) -> str:
        s = self.stats
        return (
            f"<CrawlResult crawled={s.get('total_crawled', 0)} "
            f"new={s.get('total_new', 0)} "
            f"skipped={s.get('total_skipped', 0)}>"
        )
