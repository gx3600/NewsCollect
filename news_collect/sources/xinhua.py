"""新华网 (Xinhua) financial news spider.

Crawls the fortune (财经) section of xinhuanet.com.
"""

import logging
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)


@register
class XinhuaSpider(BaseNewsSpider):
    """Spider for 新华网 (Xinhua) fortune/financial news."""

    name: str = "xinhua"
    source_name: str = "xinhua"
    start_urls: list[str] = [
        "https://www.news.cn/fortune/index.htm",
    ]
    selectors: dict = {
        "article": "a[href]",
        "title": "::text",
        "link": "::attr(href)",
    }
    concurrent_requests: int = 3
    download_delay: float = 1.0

    # Xinhua-specific content selectors
    content_selectors: list[str] = [
        "#detail p::text",
        "#detail::text",
        ".main-left p::text",
        "p::text",
    ]

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse Xinhua fortune index page."""
        logger.info(f"Crawling Xinhua: {response.url}")

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

                # Filter for Xinhua fortune article pages
                if "/fortune/" not in href or not href.endswith("c.html"):
                    continue

                # Title quality filter
                if len(text) < 15 or len(text) > 200:
                    continue

                # Skip navigation/tag links
                skip_prefixes = [
                    "新华网", "新华社", "财经", "首页", "更多",
                    "返回", "关于我们", "联系我们", "广告服务",
                ]
                if any(text.startswith(p) for p in skip_prefixes):
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

        logger.info(f"Xinhua crawl complete: {self.stats['new']} new")
