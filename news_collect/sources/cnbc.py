"""CNBC financial news spider.

Fetches latest news from CNBC's world news page.
"""

import logging
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)


@register
class CNBCSpider(BaseNewsSpider):
    """Spider for CNBC latest news."""

    name: str = "cnbc"
    source_name: str = "cnbc"
    start_urls: list[str] = [
        "https://www.cnbc.com/world/?region=world",
    ]
    selectors: dict = {
        "article": ".Card-titleAndFooter, .LatestNews-item",
        "title": "a::text, .LatestNews-headline::text",
        "link": "a::attr(href)",
        "time": "time::attr(datetime), .LatestNews-timestamp::attr(datetime)",
        "category": ".Card-channel::text",
    }
    concurrent_requests: int = 3
    download_delay: float = 1.0

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse CNBC world news listing page."""
        logger.info(f"Crawling CNBC: {response.url}")

        # Find all article cards
        articles = response.css(self.selectors["article"])
        logger.debug(f"Found {len(articles)} articles on {response.url}")

        for article in articles:
            try:
                raw = await self.parse_article(response, article)
                if raw:
                    yield raw
                    self.increment_new()
            except Exception as e:
                logger.warning(f"Failed to parse CNBC article: {e}")
                continue

        logger.info(
            f"CNBC crawl complete: {self.stats['new']} new, "
            f"{self.stats['skipped']} skipped"
        )
