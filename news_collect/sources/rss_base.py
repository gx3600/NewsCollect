"""RSS/Atom feed base class for news sources.

Standalone base class (does NOT depend on Scrapling) for sources that
consume RSS/Atom feeds rather than scraping HTML pages.

Usage:
    from news_collect.sources.rss_base import BaseRssSpider, RssResult

    class MyRssSpider(BaseRssSpider):
        name = "my_source"
        source_name = "my_source"
        feeds = [
            {"url": "https://example.com/rss.xml", "category": "business"},
        ]
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx

from news_collect.core.models import NewsItem

logger = logging.getLogger(__name__)


class RssResult:
    """Minimal result container — compatible with CrawlerEngine's item loop.

    CrawlerEngine expects:
        result = spider.start()
        for raw_item in result.items:
            if isinstance(raw_item, NewsItem): ...
    """

    def __init__(self, items: list[NewsItem]):
        self.items = items


class BaseRssSpider:
    """Base class for RSS/Atom news sources.

    Subclasses must define:
        name: str           — unique source identifier
        source_name: str    — display name stored in DB
        feeds: list[dict]   — [{url, category}, ...]

    Does NOT inherit from Scrapling's Spider — RSS parsing is fundamentally
    different from HTML scraping.  CrawlerEngine detects RSS sources via
    config flag ``use_rss: true`` and routes accordingly.
    """

    # ── override in subclasses ─────────────────────────────

    name: str = ""
    source_name: str = ""          # DB "source" column
    feeds: list[dict] = []         # [{"url": "...", "category": "..."}, ...]
    max_items: int = 0             # 0 = unlimited per feed
    max_age_days: int = 6          # skip articles older than this (0 = no limit)

    def __init__(self, **kwargs):
        if not self.source_name:
            self.source_name = self.name

        self.max_items = kwargs.pop("max_items", self.max_items or 0)
        self.fetch_content = kwargs.pop("fetch_content", False)

        self._proxies: Optional[dict] = None
        self._load_proxy_config()

        self._stats = {"crawled": 0, "new": 0, "skipped": 0}

    # ── proxy ──────────────────────────────────────────────

    def _load_proxy_config(self):
        """Read proxy settings from settings.yaml."""
        try:
            from news_collect.utils.config import Config
            cfg = Config()
            proxy_http = cfg.settings.get("proxy", {}).get("http", "")
            if proxy_http:
                self._proxies = {
                    "http://": proxy_http,
                    "https://": proxy_http,
                }
                logger.debug(f"RSS proxy configured: {proxy_http}")
        except Exception:
            pass

    # ── main entry point ───────────────────────────────────

    def start(self) -> RssResult:
        """Fetch all configured RSS feeds and return collected NewsItems.

        Called by CrawlerEngine._run_single_source().
        """
        all_items: list[NewsItem] = []

        for feed_cfg in self.feeds:
            url = feed_cfg["url"]
            category = feed_cfg.get("category", "")
            label = feed_cfg.get("label", url)

            logger.info(f"[{self.name}] Fetching RSS: {label}")
            try:
                items = self._fetch_and_parse(url, category)
                all_items.extend(items)
                self._stats["crawled"] += len(items)
                self._stats["new"] += len(items)
                logger.info(f"[{self.name}] {label}: {len(items)} items")
            except Exception as e:
                logger.error(f"[{self.name}] Failed to fetch {label}: {e}")

        return RssResult(all_items)

    # ── feed parsing ───────────────────────────────────────

    def _fetch_and_parse(self, url: str, category: str) -> list[NewsItem]:
        """Fetch a single RSS/Atom feed URL and convert entries to NewsItems.

        Args:
            url: RSS/Atom feed URL.
            category: Category label applied to every item from this feed.

        Returns:
            List of NewsItem objects (may be empty on error).
        """
        items: list[NewsItem] = []

        # 1. Fetch
        try:
            transport = httpx.HTTPTransport(
                proxy=self._proxies.get("http://") if self._proxies else None,
            ) if self._proxies else None

            with httpx.Client(
                proxy=self._proxies.get("http://") if self._proxies else None,
                timeout=30.0,
                follow_redirects=True,
            ) as client:
                resp = client.get(url, headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
                })
                resp.raise_for_status()
                raw_xml = resp.text
        except Exception as e:
            logger.error(f"[{self.name}] HTTP error for {url}: {e}")
            return items

        # 2. Parse
        feed = feedparser.parse(raw_xml)
        if feed.bozo:
            logger.warning(f"[{self.name}] Feed parse warning for {url}: {feed.bozo_exception}")

        entries = feed.entries
        logger.debug(f"[{self.name}] {url}: {len(entries)} entries in feed")

        # 3. Convert
        for entry in entries:
            if self.max_items > 0 and len(items) >= self.max_items:
                break

            item = self._entry_to_newsitem(entry, category)
            if item:
                items.append(item)

        return items

    def _entry_to_newsitem(
        self, entry: dict, category: str
    ) -> Optional[NewsItem]:
        """Convert a single feedparser entry to a NewsItem.

        Args:
            entry: feedparser entry dict.
            category: Category label for this feed.

        Returns:
            NewsItem or None (if title/url missing).
        """
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()

        # For Google News RSS, the actual article URL is not provided.
        # Use the guid as a stable unique key; the `link` field goes to
        # a Google redirect page which is less useful but still clickable.
        if not link and entry.get("id"):
            link = entry.get("id", "")

        if not title:
            return None
        if not link:
            return None

        # Publish time — use feedparser's built-in parsed struct_time
        pub_time = self._parse_entry_date(entry)

        # Freshness filter — skip articles older than max_age_days
        if self.max_age_days > 0 and pub_time is not None:
            age = datetime.now(timezone.utc) - pub_time
            if age.days > self.max_age_days:
                return None

        # Content: prefer content:encoded > content > summary
        content = ""
        if entry.get("content"):
            content = entry["content"][0].get("value", "")
        elif entry.get("summary"):
            content = entry.get("summary", "")
        # Strip HTML tags for clean text storage
        if content:
            content = self._strip_html(content)

        return NewsItem(
            url=link,
            title=title,
            source=self.source_name,
            content=content,
            publish_time=pub_time,
            category=category,
            raw_data={
                "feed_title": entry.get("title"),
                "feed_link": entry.get("link"),
                "feed_summary": entry.get("summary", ""),
            },
        )

    # ── helpers ─────────────────────────────────────────────

    @staticmethod
    def _parse_entry_date(entry: dict) -> Optional[datetime]:
        """Extract publish time from a feedparser entry.

        Uses feedparser's built-in ``published_parsed`` / ``updated_parsed``
        (time.struct_time in UTC) as the primary source — reliable and
        avoids manual string parsing.

        Falls back to email.utils.parsedate_to_datetime for RFC 2822 strings
        when struct_time is not available.
        """
        from calendar import timegm
        from email.utils import parsedate_to_datetime

        # 1. Feedparser's built-in parsed struct_time (most reliable)
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            try:
                ts = timegm(parsed)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                pass

        # 2. Fallback: parse RFC 2822 / ISO date string
        published_str = (
            entry.get("published")
            or entry.get("updated")
            or entry.get("dc:date")
            or ""
        )
        if published_str:
            try:
                return parsedate_to_datetime(published_str.strip())
            except Exception:
                pass

        return None

    @staticmethod
    def _strip_html(html: str) -> str:
        """Remove HTML tags, return plain text."""
        import re
        clean = re.sub(r'<[^>]+>', ' ', html)
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()

    # ── stats ───────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        return self._stats

    def increment_new(self):
        self._stats["new"] += 1
        self._stats["crawled"] += 1
