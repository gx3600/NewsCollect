"""Daemon scheduler — runs crawlers on configurable intervals.

Uses the `schedule` library for lightweight periodic task execution.
Each source runs at its own configured interval independently.
"""

import logging
import signal
import sys
import time
from datetime import datetime
from typing import Optional

import schedule

from news_collect.utils.config import Config

logger = logging.getLogger(__name__)


class DaemonScheduler:
    """Continuous daemon that runs each enabled source on its own interval.

    Usage:
        scheduler = DaemonScheduler()
        scheduler.start()      # blocks until Ctrl+C
    """

    def __init__(
        self,
        interval_override: Optional[int] = None,
        verbose: bool = False,
    ):
        self.config = Config()
        self.interval_override = interval_override
        self.verbose = verbose
        self._running = True
        self._run_count: dict[str, int] = {}

        # Register signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def start(self):
        """Start the daemon loop. Blocks until shutdown signal."""
        from news_collect.core.engine import CrawlerEngine

        engine = CrawlerEngine()

        # Schedule each enabled source
        for name, src_cfg in self.config.enabled_sources.items():
            interval = self.interval_override or src_cfg.interval
            self._run_count[name] = 0

            logger.info(
                f"Scheduling '{name}': every {interval}s "
                f"(url={src_cfg.url})"
            )

            # Create a closure to capture the source name
            def make_job(source_name: str):
                def job():
                    self._crawl_source(engine, source_name)
                return job

            schedule.every(interval).seconds.do(make_job(name))

        # Run immediately on start
        logger.info("Running initial crawl for all sources...")
        for name in self.config.enabled_sources:
            self._crawl_source(engine, name)

        # Main loop
        logger.info("Daemon running. Press Ctrl+C to stop.")
        while self._running:
            schedule.run_pending()
            time.sleep(1)

        logger.info("Daemon stopped.")

    def _crawl_source(self, engine, name: str):
        """Run a single source crawl and log results."""
        self._run_count[name] += 1
        run_id = self._run_count[name]
        start = datetime.now()

        logger.info(f"[{name} #{run_id}] Starting crawl...")

        try:
            result = engine.run_sources(names=[name])

            elapsed = (datetime.now() - start).total_seconds()
            s = result.stats

            logger.info(
                f"[{name} #{run_id}] Done in {elapsed:.1f}s — "
                f"{s.get('total_crawled', 0)} crawled, "
                f"{s.get('total_new', 0)} new, "
                f"{s.get('total_skipped', 0)} duplicates"
            )
        except Exception as e:
            logger.error(f"[{name} #{run_id}] Error: {e}", exc_info=self.verbose)

    def _handle_shutdown(self, signum, frame):
        """Graceful shutdown on signal."""
        logger.info(f"Received signal {signum}. Shutting down...")
        self._running = False

    def status(self) -> dict:
        """Return current daemon status."""
        return {
            "running": self._running,
            "sources": dict(self._run_count),
            "scheduled_jobs": len(schedule.get_jobs()),
        }
