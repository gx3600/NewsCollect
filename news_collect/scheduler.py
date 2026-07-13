"""Daemon scheduler — runs crawlers on configurable intervals.

Uses the `schedule` library for lightweight periodic task execution.
Each source runs at its own configured interval independently.

Persistence: tracks last successful crawl time per source in
``data/crawl_state.json``. On restart, detects gaps and runs catch-up
crawls so that no news window is missed.
"""

import concurrent.futures
import json
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import schedule

from news_collect.utils.config import Config

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent.parent / "data" / "crawl_state.json"

# ── backfill configuration ────────────────────────────────
BACKFILL_WINDOW_DAYS = 3        # max days to backfill on restart
BACKFILL_MAX_ITEMS = 200        # increased max_items during backfill
BACKFILL_SIGNIFICANT_GAP_MIN = 30  # minutes — gap exceeding this triggers backfill


class DaemonScheduler:
    """Continuous daemon that runs each enabled source on its own interval.

    Persists crawl state to detect interruptions. On restart, sources
    that fell behind are caught up before entering the normal schedule.

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

        # Load persisted crawl state
        self._state: dict[str, dict] = self._load_state()
        self._state_lock = threading.Lock()

        # Background analysis thread
        self._analysis_thread: Optional[threading.Thread] = None

        # Register signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    # ── state persistence ───────────────────────────────────

    def _load_state(self) -> dict:
        """Load crawl state from data/crawl_state.json.

        Supports backward compatibility with old flat format:
        ``{"source_name": "iso_timestamp"}`` → migrated to new format.
        New format:
        ``{"source_name": {"last_crawl": "...", "coverage_until": "...", "backfill_done": true}}``
        """
        try:
            if STATE_FILE.exists():
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # Detect old flat format: values are plain strings
                    migrated = {}
                    needs_migration = False
                    for name, val in data.items():
                        if isinstance(val, str):
                            migrated[name] = {
                                "last_crawl": val,
                                "coverage_until": val,
                                "backfill_done": True,
                            }
                            needs_migration = True
                        elif isinstance(val, dict):
                            migrated[name] = val
                        else:
                            migrated[name] = {"last_crawl": str(val)}
                    if needs_migration:
                        logger.info("Migrated crawl state from legacy format.")
                    return migrated
        except Exception as e:
            logger.warning(f"Failed to load crawl state: {e}")
        return {}

    def _save_state(self):
        """Persist crawl state to disk."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Failed to save crawl state: {e}")

    def _get_source_state(self, name: str) -> dict:
        """Return the state dict for a single source (never None)."""
        return self._state.get(name, {})

    def _get_last_crawl(self, name: str) -> Optional[datetime]:
        """Return the last successful crawl time for a source, or None."""
        src = self._state.get(name)
        if isinstance(src, dict):
            ts = src.get("last_crawl")
        elif isinstance(src, str):
            ts = src  # legacy flat format
        else:
            return None
        if ts:
            try:
                return datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                pass
        return None

    def _get_coverage_until(self, name: str) -> Optional[datetime]:
        """Return the time up to which coverage is complete (from last backfill)."""
        src = self._state.get(name)
        if isinstance(src, dict):
            ts = src.get("coverage_until")
            if ts:
                try:
                    return datetime.fromisoformat(ts)
                except (ValueError, TypeError):
                    pass
        return None

    def _mark_crawled(self, name: str, coverage_until: Optional[datetime] = None):
        """Record a successful crawl and its coverage window."""
        now = datetime.now(timezone.utc)
        with self._state_lock:
            entry = self._state.get(name, {})
            if isinstance(entry, str):
                entry = {"last_crawl": entry}
            entry["last_crawl"] = now.isoformat()
            if coverage_until is not None:
                entry["coverage_until"] = coverage_until.isoformat()
            else:
                entry["coverage_until"] = now.isoformat()
            self._state[name] = entry
            self._save_state()

    # ── main loop ───────────────────────────────────────────

    def start(self):
        """Start the daemon loop. Blocks until shutdown signal."""
        from news_collect.core.engine import CrawlerEngine

        engine = CrawlerEngine()

        # ── gap detection on startup ───────────────────────────
        now = datetime.now(timezone.utc)
        sources_to_backfill: list[tuple[str, float]] = []  # (name, gap_minutes)
        sources_ok: list[str] = []

        for name, src_cfg in self.config.enabled_sources.items():
            interval = self.interval_override or src_cfg.interval
            self._run_count[name] = 0

            last_crawl = self._get_last_crawl(name)
            if last_crawl:
                gap = (now - last_crawl).total_seconds()
                gap_mins = gap / 60
                if gap_mins > BACKFILL_SIGNIFICANT_GAP_MIN:
                    sources_to_backfill.append((name, gap_mins))
                    logger.warning(
                        f"'{name}': last crawl was {gap_mins:.0f} min ago "
                        f"(interval={interval}s). Will backfill up to "
                        f"{BACKFILL_WINDOW_DAYS} days."
                    )
                else:
                    sources_ok.append(name)
                    logger.info(
                        f"'{name}': last crawl {gap:.0f}s ago, within interval. OK."
                    )
            else:
                # First run — no backfill needed, just do initial crawl
                sources_ok.append(name)
                logger.info(f"'{name}': first run (no previous state).")

            logger.info(
                f"Scheduling '{name}': every {interval}s "
                f"(url={src_cfg.url})"
            )

            def make_job(source_name: str):
                def job():
                    self._crawl_source(engine, source_name)
                return job

            schedule.every(interval).seconds.do(make_job(name))

        # Schedule news analysis task
        analysis_interval = self.config.analysis_interval
        if self.config.deepseek_api_key:
            logger.info(
                f"Starting news analysis: every {analysis_interval}s "
                f"(batch={self.config.analysis_batch_size}, "
                f"concurrency={self.config.analysis_concurrency})"
            )
            # Run analysis in a background thread so it doesn't get blocked
            # by long-running initial crawls.
            self._analysis_thread = threading.Thread(
                target=self._analysis_loop,
                args=(analysis_interval,),
                daemon=True,
            )
            self._analysis_thread.start()
        else:
            logger.warning(
                "DeepSeek API key not configured — news analysis is DISABLED. "
                "Set deepseek.api_key in config/settings.yaml."
            )

        # Schedule daily futures variety update at 08:00 local time
        schedule.every().day.at("08:00").do(self._update_varieties_job)
        logger.info("Scheduled daily futures variety update at 08:00.")

        # ── backfill phase ────────────────────────────────────
        # Sources with significant gaps are backfilled first (largest gap first),
        # then all remaining sources run an initial crawl.
        # ALL initial crawls run concurrently in threads so that a slow source
        # (e.g. THS API iterating many contracts) does not block others.
        initial_names: list[tuple[str, bool]] = []  # (name, is_backfill)

        if sources_to_backfill:
            backfill_names = [n for n, _ in sorted(sources_to_backfill, key=lambda x: -x[1])]
            logger.info(
                f"Backfilling {len(backfill_names)} source(s): {backfill_names}"
            )
            for name in backfill_names:
                initial_names.append((name, True))

        for name in sources_ok:
            initial_names.append((name, False))

        if initial_names:
            logger.info(
                f"Running initial crawl for {len(initial_names)} source(s) concurrently..."
            )
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(len(initial_names), 10)
            ) as pool:
                futures: dict[concurrent.futures.Future, str] = {}
                for name, is_backfill in initial_names:
                    if is_backfill:
                        fut = pool.submit(self._backfill_source, engine, name)
                    else:
                        fut = pool.submit(self._crawl_source, engine, name)
                    futures[fut] = name

                # Wait for all initial crawls to complete (or fail) before
                # entering the main loop, so that the first round of analysis
                # has actual data to process.
                for fut in concurrent.futures.as_completed(futures):
                    name = futures[fut]
                    try:
                        fut.result()
                    except Exception as e:
                        logger.error(
                            f"Initial crawl for '{name}' failed: {e}",
                            exc_info=self.verbose,
                        )

        # ── main loop ────────────────────────────────────────
        logger.info("Daemon running. Press Ctrl+C to stop.")
        while self._running:
            schedule.run_pending()
            time.sleep(1)

        # Persist state on exit
        self._save_state()
        logger.info("Daemon stopped (state saved).")

    def _crawl_source(self, engine, name: str, max_items_override: Optional[int] = None):
        """Run a single source crawl and log results.

        Returns the CrawlResult for coverage analysis (or None on error).
        """
        self._run_count[name] += 1
        run_id = self._run_count[name]
        start = datetime.now()

        logger.info(f"[{name} #{run_id}] Starting crawl...")

        try:
            result = engine.run_sources(
                names=[name],
                max_items_override=max_items_override,
            )

            elapsed = (datetime.now() - start).total_seconds()
            s = result.stats

            logger.info(
                f"[{name} #{run_id}] Done in {elapsed:.1f}s — "
                f"{s.get('total_crawled', 0)} crawled, "
                f"{s.get('total_new', 0)} new, "
                f"{s.get('total_skipped', 0)} duplicates"
            )

            # Persist crawl timestamp
            self._mark_crawled(name)

            return result

        except Exception as e:
            logger.error(f"[{name} #{run_id}] Error: {e}", exc_info=self.verbose)
            return None

    # ── backfill ────────────────────────────────────────────

    def _backfill_source(self, engine, name: str):
        """Backfill a source that has been offline long enough to miss news.

        Runs the source with increased ``max_items`` to capture as many
        articles as the feed/page provides.  Checks whether the collected
        items' ``publish_time`` range covers at least ``BACKFILL_WINDOW_DAYS``
        days into the past.

        The backfill result is persisted in ``crawl_state.json`` so that
        progress is preserved across restarts.
        """
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        backfill_since = now - timedelta(days=BACKFILL_WINDOW_DAYS)
        last_crawl = self._get_last_crawl(name)
        gap_mins = (now - last_crawl).total_seconds() / 60 if last_crawl else float("inf")

        # Check if a previous backfill was interrupted
        prev_coverage = self._get_coverage_until(name)
        if prev_coverage and prev_coverage > backfill_since:
            logger.info(
                f"[backfill:{name}] Previous backfill coverage until "
                f"{prev_coverage.strftime('%Y-%m-%d %H:%M')} — already current."
            )
            self._mark_crawled(name, coverage_until=now)
            return

        logger.info(
            f"[backfill:{name}] Gap: {gap_mins:.0f} min. "
            f"Target coverage: {BACKFILL_WINDOW_DAYS}d back to "
            f"{backfill_since.strftime('%Y-%m-%d %H:%M')}. "
            f"Using max_items={BACKFILL_MAX_ITEMS}."
        )

        # ── run backfill pass ──────────────────────────────
        result = self._crawl_source(engine, name, max_items_override=BACKFILL_MAX_ITEMS)
        if result is None:
            logger.error(f"[backfill:{name}] Backfill failed — will retry on next restart.")
            return

        # ── coverage analysis ──────────────────────────────
        items_with_time = [
            item for item in result.items if item.publish_time is not None
        ]
        if not items_with_time:
            logger.info(
                f"[backfill:{name}] No items with publish_time returned. "
                f"Coverage tracking unavailable for this source."
            )
            self._mark_crawled(name, coverage_until=now)
            return

        earliest = min(item.publish_time for item in items_with_time)
        latest = max(item.publish_time for item in items_with_time)
        coverage_hours = (now - earliest).total_seconds() / 3600

        logger.info(
            f"[backfill:{name}] Collected {len(result.items)} items — "
            f"time range: {earliest.strftime('%Y-%m-%d %H:%M')} → "
            f"{latest.strftime('%Y-%m-%d %H:%M')} "
            f"({coverage_hours:.1f}h coverage)"
        )

        if earliest <= backfill_since:
            logger.info(
                f"[backfill:{name}] ✓ Backfill complete — coverage reaches "
                f"{BACKFILL_WINDOW_DAYS}d window."
            )
            self._mark_crawled(name, coverage_until=now)
        else:
            gap_remaining = (earliest - backfill_since).total_seconds() / 3600
            logger.warning(
                f"[backfill:{name}] △ Backfill partial — "
                f"earliest article at {earliest.strftime('%Y-%m-%d %H:%M')} "
                f"({gap_remaining:.1f}h short of {BACKFILL_WINDOW_DAYS}d target). "
                f"Source feed/page may not provide older content."
            )
            # Record the actual coverage so we know how far we got
            self._mark_crawled(name, coverage_until=earliest)

    def _analysis_loop(self, interval: int):
        """Background thread: continuously run news analysis cycles.

        Runs independently of the crawl loop so that analysis is never
        blocked by long-running initial crawls or slow sources.
        """
        from news_collect.core.analyzer import NewsAnalyzer

        logger.info("[analysis] Background thread started.")
        analyzer = NewsAnalyzer()

        # Run first cycle immediately
        first_cycle = True

        while self._running:
            if not first_cycle:
                # Sleep between cycles, checking _running periodically
                # so shutdown is responsive.
                for _ in range(interval):
                    if not self._running:
                        break
                    time.sleep(1)

            if not self._running:
                break

            first_cycle = False

            try:
                unprocessed = analyzer.unprocessed_count()
                if unprocessed > 0:
                    logger.info(f"[analysis] {unprocessed} unprocessed items pending")
                stats = analyzer.run_once()
                s = stats
                logger.info(
                    f"[analysis] cycle #{s['cycles']} — "
                    f"processed={s['total_processed']}, "
                    f"opinions={s['total_opinions']}, "
                    f"events={s['total_events']}, "
                    f"failures={s['total_failures']}"
                )
            except Exception as e:
                logger.error(f"[analysis] Error: {e}", exc_info=self.verbose)

    def _update_varieties_job(self):
        """Daily job: fetch latest futures varieties from 同花顺 API and
        update config/futures_variety.xlsx. Injects the updated list into
        the running NewsAnalyzer so the next cycle picks up changes."""
        try:
            from news_collect.utils.variety_updater import update_futures_variety

            logger.info("[variety-update] Fetching latest futures varieties...")
            ok = update_futures_variety()
            if ok:
                logger.info("[variety-update] Successfully updated futures_variety.xlsx")
            else:
                logger.warning("[variety-update] Failed to update varieties — will retry tomorrow.")
        except Exception as e:
            logger.error(f"[variety-update] Error: {e}")

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
            "last_crawls": dict(self._state),
        }
