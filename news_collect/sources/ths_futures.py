"""同花顺期货 (10jqka/THS Futures) news spider.

Crawls the futures/goods news list page.
"""

import logging
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)


@register
class THSFuturesSpider(BaseNewsSpider):
    """Spider for 同花顺期货 (10jqka) futures news."""

    name: str = "ths_futures"
    source_name: str = "ths_futures"
    start_urls: list[str] = [
        "https://goodsfu.10jqka.com.cn/qhgd_list/",
    ]
    concurrent_requests: int = 3
    download_delay: float = 1.0

    content_selectors: list[str] = [
        ".article-content p::text",
        ".news-content p::text",
        "#main-text p::text",
        "[class*=content] p::text",
        "p::text",
    ]

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse THS Futures news list."""
        logger.info(f"Crawling THS Futures: {response.url}")

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

                # Match article URLs: /YYYYMMDD/cXXXXXX.shtml on 10jqka domains
                if not href.endswith(".shtml"):
                    continue
                if "10jqka.com.cn" not in href and not href.startswith("/"):
                    continue

                # Title quality filter
                if len(text) < 15 or len(text) > 250:
                    continue

                # Deduplicate titles (many articles appear twice in the list)
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

        logger.info(f"THS Futures crawl complete: {self.stats['new']} new")
