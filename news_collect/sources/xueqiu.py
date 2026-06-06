"""雪球 (Xueqiu) financial news spider.

Xueqiu is a JavaScript SPA — requires StealthySession for rendering.
"""

import logging
from typing import AsyncGenerator

from scrapling.spiders import Response
from scrapling.fetchers import AsyncStealthySession

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)


@register
class XueqiuSpider(BaseNewsSpider):
    """Spider for 雪球 (Xueqiu) trending posts/news."""

    name: str = "xueqiu"
    source_name: str = "xueqiu"
    start_urls: list[str] = [
        "https://xueqiu.com/today",
    ]
    selectors: dict = {
        "article": "a[href]",
        "title": "::text",
        "link": "::attr(href)",
    }
    concurrent_requests: int = 1
    download_delay: float = 2.0

    def configure_sessions(self, manager):
        """Use stealthy browser to render JavaScript."""
        manager.add("default", AsyncStealthySession(headless=True), lazy=False)

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse Xueqiu trending page."""
        logger.info(f"Crawling Xueqiu: {response.url}")

        all_links = response.css("a[href]")
        seen_urls = set()

        for link in all_links:
            try:
                href = link.css("::attr(href)").get()
                text = link.css("::text").get()

                if not href or not text:
                    continue

                text = str(text).strip()
                href = str(href).strip()

                # Filter for Xueqiu post/topic pages
                if "xueqiu.com" not in href and not href.startswith("/"):
                    continue
                if len(text) < 8 or len(text) > 300:
                    continue

                url = self._make_absolute(response.url, href)
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                raw = {"url": url, "title": text}
                raw = await self._enrich_content(raw)
                yield raw
                self.increment_new()
            except Exception:
                continue

        logger.info(f"Xueqiu crawl complete: {self.stats['new']} new")
