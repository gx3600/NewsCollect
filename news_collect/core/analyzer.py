"""News analysis engine — polls unprocessed news, classifies via LLM, stores results.

The analyzer runs in cycles: fetch → classify → store → mark processed.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from news_collect.core.llm_client import DeepSeekClient
from news_collect.core.models import AnalysisOpinion, NewsEvent
from news_collect.core.storage import NewsStorage
from news_collect.utils.config import Config

logger = logging.getLogger(__name__)


class NewsAnalyzer:
    """Orchestrates the news analysis pipeline.

    Usage:
        analyzer = NewsAnalyzer()
        stats = analyzer.run_once()          # synchronous single cycle
        # or from async context:
        stats = await analyzer.run_once_async()
    """

    def __init__(
        self,
        storage: Optional[NewsStorage] = None,
        config: Optional[Config] = None,
    ):
        self.config = config or Config()
        self.storage = storage or NewsStorage(self.config.db_path)

        # DeepSeek client — scoped to Chinese futures varieties
        varieties = self.config.futures_varieties
        logger.info(
            f"NewsAnalyzer initialized with {len(varieties)} futures varieties. "
            f"Model: {self.config.deepseek_model}"
        )
        self.llm = DeepSeekClient(
            api_key=self.config.deepseek_api_key,
            base_url=self.config.deepseek_base_url,
            model=self.config.deepseek_model,
            max_tokens=self.config.deepseek_max_tokens,
            temperature=self.config.deepseek_temperature,
            timeout=self.config.deepseek_timeout,
            max_retries=self.config.deepseek_max_retries,
            concurrency=self.config.analysis_concurrency,
            varieties=varieties,
        )

        self.batch_size = self.config.analysis_batch_size
        self._varieties: set[str] = set(varieties)
        self._stats = self._init_stats()

    def _init_stats(self) -> dict:
        return {
            "cycles": 0,
            "total_processed": 0,
            "total_opinions": 0,
            "total_events": 0,
            "total_failures": 0,
        }

    # ── public API ────────────────────────────────────────────

    def run_once(self) -> dict:
        """Run a single analysis cycle synchronously. Returns stats dict."""
        return asyncio.run(self.run_once_async())

    async def run_once_async(self) -> dict:
        """Run a single analysis cycle (async). Returns stats dict."""
        self._stats["cycles"] += 1
        cycle = self._stats["cycles"]
        start = datetime.now()

        # 1. Clean up items that can never be analyzed (no content)
        cleaned = self.storage.mark_no_content_failed()
        if cleaned > 0:
            logger.info(f"Cycle #{cycle}: Cleaned {cleaned} no-content items → failed.")

        # 2. Fetch unprocessed news
        items = self.storage.fetch_unprocessed(limit=self.batch_size)
        if not items:
            logger.debug(f"Cycle #{cycle}: No unprocessed news found.")
            return self._stats

        logger.info(
            f"Cycle #{cycle}: Found {len(items)} unprocessed items, "
            f"classifying with concurrency={self.llm.concurrency}..."
        )

        # 2. Classify via LLM (concurrent)
        results = await self.llm.classify_batch(items)

        # 3. Parse results and accumulate records
        opinions_to_insert: list[AnalysisOpinion] = []
        events_to_insert: list[NewsEvent] = []
        processed_urls: list[str] = []
        failed_urls: list[str] = []
        irrelevant_count = 0
        failures = 0

        for item, llm_result in results:
            if llm_result is None:
                failures += 1
                self._stats["total_failures"] += 1
                failed_urls.append(item["url"])
                continue

            article_type = llm_result.get("type", "")

            # Irrelevant — news doesn't involve any whitelisted variety.
            # Mark as processed (success) without storing analysis results.
            if article_type == "irrelevant":
                irrelevant_count += 1
                processed_urls.append(item["url"])
                continue

            if article_type == "opinion":
                parsed = self._parse_opinions(item["url"], llm_result, item.get("publish_time"))
                if parsed:
                    opinions_to_insert.extend(parsed)
                    processed_urls.append(item["url"])
                else:
                    failures += 1
                    self._stats["total_failures"] += 1
                    failed_urls.append(item["url"])

            elif article_type == "event":
                parsed = self._parse_events(item["url"], llm_result)
                if parsed:
                    events_to_insert.extend(parsed)
                    processed_urls.append(item["url"])
                else:
                    failures += 1
                    self._stats["total_failures"] += 1
                    failed_urls.append(item["url"])

            else:
                logger.warning(
                    f"Unknown LLM response type '{article_type}' for {item['url']}"
                )
                failures += 1
                self._stats["total_failures"] += 1
                failed_urls.append(item["url"])

        # 4. Store results
        opinion_count = 0
        event_count = 0
        if opinions_to_insert:
            opinion_count = self.storage.insert_opinions_batch(opinions_to_insert)
            self._stats["total_opinions"] += opinion_count
        if events_to_insert:
            event_count = self.storage.insert_events_batch(events_to_insert)
            self._stats["total_events"] += event_count

        # 5. Mark processed (success → 1, failure → 2)
        marked = self.storage.mark_processed_batch(processed_urls)
        self._stats["total_processed"] += marked

        failed_marked = 0
        if failed_urls:
            # Deduplicate: a URL might appear in both lists if logic changes.
            # failed takes priority — don't overwrite with processed.
            failed_urls = [u for u in failed_urls if u not in processed_urls]
            failed_marked = self.storage.mark_failed_batch(failed_urls)

        elapsed = (datetime.now() - start).total_seconds()
        logger.info(
            f"Cycle #{cycle} done in {elapsed:.1f}s — "
            f"{len(items)} items → {opinion_count} opinions, {event_count} events, "
            f"{irrelevant_count} irrelevant, "
            f"{marked} processed, {failed_marked} failed, {failures} total failures"
        )

        return self._stats

    # ── response parsing ──────────────────────────────────────

    def _parse_opinions(self, url: str, result: dict, publish_time: str = None) -> list[AnalysisOpinion]:
        """Parse opinion-type LLM response into AnalysisOpinion records.

        Filters out varieties not in the configured whitelist as a safety net.
        """
        opinions_data = result.get("opinions", [])
        if not opinions_data:
            logger.warning(f"Opinion result for {url} has empty opinions list")
            return []

        # Use the article's publish date as analysis_date, fallback to today
        if publish_time:
            try:
                analysis_date = publish_time[:10]  # extract YYYY-MM-DD from ISO format
            except Exception:
                analysis_date = datetime.now().strftime("%Y-%m-%d")
        else:
            analysis_date = datetime.now().strftime("%Y-%m-%d")

        records = []
        for op in opinions_data:
            try:
                variety = op.get("variety", "未知品种")
                # Safety net: skip non-whitelisted varieties
                if self._varieties and variety not in self._varieties:
                    logger.warning(
                        f"Opinion variety '{variety}' not in whitelist for {url} — skipped"
                    )
                    continue

                record = AnalysisOpinion(
                    url=url,
                    variety=variety,
                    analysis_date=analysis_date,
                    short_term_view=op.get("short_term_view", ""),
                    long_term_view=op.get("long_term_view", ""),
                    short_term_view_reason=op.get("short_term_view_reason", ""),
                    long_term_view_reason=op.get("long_term_view_reason", ""),
                )
                records.append(record)
            except Exception as e:
                logger.error(f"Error parsing opinion for {url}: {e}")
        return records

    def _parse_events(self, url: str, result: dict) -> list[NewsEvent]:
        """Parse event-type LLM response into NewsEvent records.

        Filters affected_variety to only include whitelisted varieties.
        """
        events_data = result.get("events", [])
        if not events_data:
            logger.warning(f"Event result for {url} has empty events list")
            return []

        records = []
        for ev in events_data:
            try:
                affects = ev.get("affects_futures", False)
                if isinstance(affects, str):
                    affects = affects.lower() in ("true", "yes", "是")

                affected_variety = ev.get("affected_variety", "")
                # Safety net: filter to only whitelisted varieties
                if self._varieties and affected_variety:
                    parts = [p.strip() for p in affected_variety.split(",")]
                    filtered = [p for p in parts if p in self._varieties]
                    if filtered:
                        affected_variety = ",".join(filtered)
                    else:
                        affected_variety = ""
                        affects = False
                        logger.debug(
                            f"Event affected_variety '{ev.get('affected_variety')}' "
                            f"not in whitelist for {url} — cleared"
                        )

                record = NewsEvent(
                    url=url,
                    event_summary=ev.get("event_summary", ""),
                    event_time=ev.get("event_time") or None,
                    keywords=ev.get("keywords", ""),
                    affects_futures=bool(affects),
                    affected_variety=affected_variety,
                    impact_level=ev.get("impact_level", ""),
                    impact_analysis=ev.get("impact_analysis", ""),
                )
                records.append(record)
            except Exception as e:
                logger.error(f"Error parsing event for {url}: {e}")
        return records

    # ── utility ──────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        return self._stats

    def unprocessed_count(self) -> int:
        return self.storage.unprocessed_count()

    def analysis_stats(self) -> dict:
        return self.storage.analysis_stats()
