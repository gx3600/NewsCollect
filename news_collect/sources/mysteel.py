"""Mysteel (我的钢铁网) commodity/futures news spider.

Crawls the non-ferrous metals news section.
"""

import logging
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)


@register
class MysteelSpider(BaseNewsSpider):
    """Spider for Mysteel (我的钢铁网) commodity news."""

    name: str = "mysteel"
    source_name: str = "mysteel"
    start_urls: list[str] = [
        "https://list1.mysteel.com/article/p-1947----02---------2.html",
    ]
    concurrent_requests: int = 3
    download_delay: float = 1.0

    content_selectors: list[str] = [
        "#article-content::text",
        ".editor::text",
        ".content-text::text",
        "#content-text::text",
        ".content-main::text",
        "[class*=content]::text",
        "p::text",
    ]

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse Mysteel news list page."""
        logger.info(f"Crawling Mysteel: {response.url}")

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

                # Match mysteel article URLs: /a/YYMMDDHH/xxxx.html
                if "/a/" not in href or not href.endswith(".html"):
                    continue
                if "mysteel.com" not in href and not href.startswith("/"):
                    continue

                # Title quality filter
                if len(text) < 15 or len(text) > 200:
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

        logger.info(f"Mysteel crawl complete: {self.stats['new']} new")
