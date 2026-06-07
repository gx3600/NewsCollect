"""Base news spider — extend this to add new financial news sources.

Inherits from Scrapling's Spider and provides a unified interface
for financial news extraction, auto item conversion, and storage.
"""

import logging
from datetime import datetime
from typing import AsyncGenerator, Optional

from scrapling.spiders import Spider, Response

from news_collect.core.models import NewsItem

logger = logging.getLogger(__name__)


class BaseNewsSpider(Spider):
    """Base spider for financial news sources.

    Subclasses must define:
        name: str           — unique source name
        start_urls: list    — starting URLs
        selectors: dict     — CSS/XPath selectors for extraction

    And implement:
        parse(self, response: Response) -> AsyncGenerator
            Yield dicts with keys matching the selector names, or
            call self.item_to_newsitem(raw) to convert to NewsItem.
    """

    # ── override in subclasses ─────────────────────────────

    name: str = "base"
    start_urls: list[str] = []
    selectors: dict = {}          # e.g. {"title": "h2::text", "link": "a::attr(href)"}
    source_name: str = ""         # display name for the database

    # ── content extraction ─────────────────────────────────

    # Whether to fetch full article content from detail pages (can be overridden)
    fetch_content: bool = True

    # Common boilerplate patterns to filter out from extracted content
    _boilerplate_patterns: list[str] = [
        "手机看", "扫一扫", "朋友圈", "分享到", "复制链接",
        "扫码下载", "APP下载", "客户端", "关注我们", "订阅",
        "点赞", "收藏", "举报", "广告", "推广",
        "Copyright", "版权所有", "ICP", "网安备",
        "我知道了", "提示：", "郑重声明",
        "扫码关注", "下载APP", "打开APP", "阅读更多", "查看更多",
        "微信", "微博", "QQ空间", "新浪", "腾讯",
    ]

    # CSS selectors for article body text on detail pages, tried in order.
    # The first selector that returns >100 chars of text is used.
    content_selectors: list[str] = [
        "#ContentBody p::text",
        "#article_content p::text",
        "#article_body p::text",
        "#content p::text",
        ".article-body p::text",
        ".article-content p::text",
        ".article__body p::text",
        ".post-content p::text",
        ".story-body p::text",
        ".caas-body p::text",
        ".txtinfos p::text",
        ".body p::text",
        ".content p::text",
        ".detail-content p::text",
        ".news-content p::text",
        ".article-text p::text",
        "article p::text",
        "[class*=article-body] p::text",
        "[class*=article-content] p::text",
        "[class*=article__body] p::text",
        ".text p::text",
        "p::text",
    ]

    # ── Scrapling Spider settings ──────────────────────────

    concurrent_requests: int = 3
    download_delay: float = 1.0
    robots_txt_obey: bool = True
    development_mode: bool = False  # Scrapling built-in: cache responses for dev

    # ── rate / limit ──────────────────────────────────────

    max_items: int = 10  # Max articles per crawl (0 = unlimited)

    def __init__(self, *args, **kwargs):
        if not self.source_name:
            self.source_name = self.name

        # Accept external storage reference for auto-persisting
        self._storage = kwargs.pop("storage", None)
        self._stats = {"crawled": 0, "new": 0, "skipped": 0}
        super().__init__(*args, **kwargs)

    def _limit_reached(self) -> bool:
        """Check if we've reached the per-crawl item limit."""
        return self.max_items > 0 and self._stats["new"] >= self.max_items

    # ── extraction helpers ─────────────────────────────────

    def extract(
        self,
        response: Response,
        selector_key: str,
        element=None,
    ) -> Optional[str]:
        """Extract text/attribute from the page or an element using configured selectors.

        Args:
            response: The Scrapling Response object.
            selector_key: Key into self.selectors dict.
            element: Optional child element to scope the selector.

        Returns:
            Extracted string or None.
        """
        sel = self.selectors.get(selector_key)
        if not sel:
            return None

        target = element if element is not None else response

        # Try CSS first, then XPath
        try:
            result = target.css(sel).get()
            if result:
                return str(result).strip()
        except Exception:
            pass

        try:
            result = target.xpath(sel).get()
            if result:
                return str(result).strip()
        except Exception:
            pass

        return None

    def extract_all(
        self,
        response: Response,
        selector_key: str,
    ) -> list:
        """Extract multiple elements matching a selector.

        Args:
            response: The Scrapling Response object.
            selector_key: Key into self.selectors dict.

        Returns:
            List of matched elements.
        """
        sel = self.selectors.get(selector_key)
        if not sel:
            return []

        try:
            return response.css(sel)
        except Exception:
            try:
                return response.xpath(sel)
            except Exception:
                return []

    def item_to_newsitem(self, raw: dict) -> NewsItem:
        """Convert a raw dict from parse() into a standardized NewsItem.

        The raw dict should have at minimum: 'url' and 'title'.
        Extra keys like 'content', 'publish_time', 'category', 'raw_data' are optional.

        Args:
            raw: Dict with scraped fields.

        Returns:
            Standardized NewsItem.
        """
        # Parse publish_time if it's a string
        pub_time = raw.get("publish_time")
        if isinstance(pub_time, str):
            pub_time = self._parse_datetime(pub_time)

        return NewsItem(
            url=raw["url"],
            title=raw["title"],
            content=raw.get("content"),
            source=self.source_name,
            publish_time=pub_time,
            category=raw.get("category"),
            raw_data=raw.get("raw_data"),
        )

    @staticmethod
    def _parse_datetime(s: str) -> Optional[datetime]:
        """Try to parse a datetime string in common formats."""
        if not s:
            return None

        formats = [
            "%Y-%m-%dT%H:%M:%S%z",      # ISO 8601 with tz
            "%Y-%m-%dT%H:%M:%S",         # ISO 8601 without tz
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%a, %d %b %Y %H:%M:%S %z",  # RFC 2822
            "%b %d, %Y %I:%M %p",
            "%B %d, %Y %I:%M %p",
            "%B %d, %Y",
            "%m/%d/%Y %H:%M",
            "%m/%d/%Y",
        ]

        from datetime import timezone

        for fmt in formats:
            try:
                dt = datetime.strptime(s.strip(), fmt)
                # If no timezone, assume UTC
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue

        return None

    # ── lifecycle hooks ────────────────────────────────────

    async def parse(self, response: Response) -> AsyncGenerator:
        """Override in subclasses. Must yield dicts or NewsItems."""
        # Default: use selector-driven extraction
        articles = self.extract_all(response, "article")
        for article in articles:
            item = await self.parse_article(response, article)
            if item:
                yield item

    async def parse_article(self, response: Response, article) -> Optional[dict]:
        """Extract fields from a single article element using configured selectors.

        Override this method for custom per-article extraction logic.

        Args:
            response: The full page response.
            article: A single article element.

        Returns:
            Dict with 'url', 'title', and optionally 'content' keys, or None.
        """
        title = self.extract(response, "title", article)
        link = self.extract(response, "link", article)

        if not title or not link:
            return None

        # Build absolute URL
        url = self._make_absolute(response.url, link)

        raw = {
            "url": url,
            "title": title,
            "publish_time": self.extract(response, "time", article),
            "category": self.extract(response, "category", article),
        }

        # Fetch full article content from the detail page
        if self.fetch_content:
            content = await self._fetch_article_content(url)
            if content:
                raw["content"] = content

        return raw

    @staticmethod
    def _make_absolute(base_url: str, link: str) -> str:
        """Convert a relative link to absolute URL."""
        from urllib.parse import urljoin

        return urljoin(base_url, link)

    async def _fetch_article_content(self, url: str) -> Optional[str]:
        """Fetch the full article page and extract body text content.

        Tries each selector in self.content_selectors until one yields
        meaningful text (>100 chars). Filters out common boilerplate lines.

        Args:
            url: The article detail page URL.

        Returns:
            Extracted text content, or None if extraction failed.
        """
        from scrapling.spiders.request import Request

        try:
            request = Request(url=url)
            resp = await self._session_manager.fetch(request)
            for sel in self.content_selectors:
                try:
                    paragraphs = resp.css(sel)
                    if paragraphs:
                        # Collect and filter text from matched elements
                        texts = []
                        for p in paragraphs:
                            t = str(p).strip() if isinstance(p, str) else str(p).strip()
                            if not t:
                                continue
                            # Skip boilerplate
                            if any(bp in t for bp in self._boilerplate_patterns):
                                continue
                            # Skip very short fragments (likely nav items)
                            if len(t) < 8:
                                continue
                            texts.append(t)
                        content = "\n".join(texts)
                        if len(content) > 100:
                            logger.debug(f"Content extracted from {url[:80]} using '{sel}': {len(content)} chars")
                            return content
                except Exception:
                    continue
            logger.debug(f"No content found for {url[:80]}")
            return None
        except Exception as e:
            logger.debug(f"Failed to fetch article content from {url[:80]}: {e}")
            return None

    async def _enrich_content(self, raw: dict) -> dict:
        """Enrich a raw item dict with article content if fetch_content is enabled.

        Args:
            raw: Dict with at least 'url' key.

        Returns:
            The same dict with 'content' key added (or unchanged if disabled/failed).
        """
        if self.fetch_content and "content" not in raw and raw.get("url"):
            content = await self._fetch_article_content(raw["url"])
            if content:
                raw["content"] = content
        return raw

    # ── stats ──────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        return self._stats

    def increment_new(self):
        self._stats["new"] += 1
        self._stats["crawled"] += 1

    def increment_skipped(self):
        self._stats["skipped"] += 1
        self._stats["crawled"] += 1
