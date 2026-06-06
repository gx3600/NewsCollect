"""Yahoo Finance news spider.

Yahoo Finance blocks simple HTTP requests (403), so we use StealthySession.
"""

import logging
from typing import AsyncGenerator

from scrapling.spiders import Response
from scrapling.fetchers import AsyncStealthySession

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)


@register
class YahooFinanceSpider(BaseNewsSpider):
    """Spider for Yahoo Finance news."""

    name: str = "yahoo_finance"
    source_name: str = "yahoo_finance"
    start_urls: list[str] = [
        "https://finance.yahoo.com/news/",
    ]
    selectors: dict = {
        "article": "a[href]",
        "title": "::text",
        "link": "::attr(href)",
    }
    concurrent_requests: int = 2
    download_delay: float = 2.0

    def configure_sessions(self, manager):
        """Use stealthy browser to bypass 403 blocking."""
        manager.add("default", AsyncStealthySession(headless=True), lazy=False)

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse Yahoo Finance news stream."""
        logger.info(f"Crawling Yahoo Finance: {response.url}")

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

                # Filter for Yahoo Finance news articles
                if "yahoo.com" not in href and not href.startswith("/"):
                    continue
                if len(text) < 15 or len(text) > 300:
                    continue
                # Skip nav/category links
                skip = ["Home", "Mail", "News", "Finance", "Sports", "Entertainment",
                        "Sign in", "Search", "More", "My Portfolio", "Markets",
                        "Industries", "Tech", "Politics", "Watchlist", "Latest",
                        "Popular", "Trending", "Saved", "Yahoo Finance",
                        "Privacy", "Terms", "About", "Settings"]
                if text.strip() in skip:
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

        logger.info(f"Yahoo Finance crawl complete: {self.stats['new']} new")
