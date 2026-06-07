"""金融界期货 (JRJ Futures) financial news spider.

The main page is a JS SPA — requires headless browser for rendering.
Article detail pages are regular HTML and use lightweight Fetcher.
"""

import logging
from typing import AsyncGenerator

from scrapling.spiders import Response
from scrapling.fetchers import AsyncStealthySession, FetcherSession

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)


@register
class JRJFuturesSpider(BaseNewsSpider):
    """Spider for 金融界期货 (JRJ Futures) news."""

    name: str = "jrj_futures"
    source_name: str = "jrj_futures"
    start_urls: list[str] = [
        "https://futures.jrj.com.cn/",
    ]
    concurrent_requests: int = 1
    download_delay: float = 3.0

    content_selectors: list[str] = [
        ".article_content p::text",
        ".article p::text",
        "[class*=content] p::text",
        "p::text",
    ]

    def configure_sessions(self, manager):
        """Use stealth browser for SPA rendering + lightweight session for articles."""
        manager.add("default", AsyncStealthySession(headless=True), lazy=False)
        manager.add("content", FetcherSession(), lazy=True)

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse JRJ Futures page (JS-rendered)."""
        logger.info(f"Crawling JRJ Futures: {response.url}")

        all_links = response.css("a[href]")
        seen_urls = set()

        for link in all_links:
            if self._limit_reached():
                break
            try:
                href = link.css("::attr(href)").get()
                text = link.css("::text").get()

                if not href or not text:
                    continue

                text = str(text).strip()
                href = str(href).strip()

                # Match JRJ article URLs: /YYYY/MM/DDhhmmss(id).shtml
                if not href.endswith(".shtml"):
                    continue
                if "jrj.com.cn" not in href and not href.startswith("/"):
                    continue

                # Title quality filter
                if len(text) < 15 or len(text) > 250:
                    continue

                url = self._make_absolute(response.url, href)
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                raw = {"url": url, "title": text}
                # Use lightweight session for article pages
                raw = await self._enrich_content(raw, sid="content")
                yield raw
                self.increment_new()

            except Exception:
                continue

        logger.info(f"JRJ Futures crawl complete: {self.stats['new']} new")

    async def _enrich_content(self, raw: dict, sid: str = "") -> dict:
        """Enrich with content using specified session."""
        if self.fetch_content and "content" not in raw and raw.get("url"):
            content = await self._fetch_article_content(raw["url"], sid=sid)
            if content:
                raw["content"] = content
        return raw

    async def _fetch_article_content(self, url: str, sid: str = "") -> str | None:
        """Fetch article page with lightweight session."""
        from scrapling.spiders.request import Request

        try:
            request = Request(url=url, sid=sid) if sid else Request(url=url)
            resp = await self._session_manager.fetch(request)
            for sel in self.content_selectors:
                try:
                    paragraphs = resp.css(sel)
                    if paragraphs:
                        texts = []
                        for p in paragraphs:
                            t = str(p).strip() if isinstance(p, str) else str(p).strip()
                            if not t:
                                continue
                            if any(bp in t for bp in self._boilerplate_patterns):
                                continue
                            if len(t) < 8:
                                continue
                            texts.append(t)
                        content = "\n".join(texts)
                        if len(content) > 100:
                            return content
                except Exception:
                    continue
            return None
        except Exception:
            return None
