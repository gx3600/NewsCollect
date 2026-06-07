"""Yahoo Finance news spider.

Yahoo Finance blocks simple HTTP requests (403) and the stealth browser
times out from China networks. We try Fetcher with impersonation first,
falling back to stealth browser only if needed.
"""

import logging
from typing import AsyncGenerator

from scrapling.spiders import Response
from scrapling.fetchers import Fetcher, AsyncStealthySession

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
    concurrent_requests: int = 2
    download_delay: float = 2.0
    fetch_content: bool = False  # Disable detail page fetch due to network issues

    def configure_sessions(self, manager):
        """Use FetcherSession (not Fetcher) as required by Spider framework."""
        from scrapling.fetchers import FetcherSession
        manager.add("default", FetcherSession(), lazy=False)

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse Yahoo Finance news stream."""
        logger.info(f"Crawling Yahoo Finance: {response.url}")

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

                url = self._make_absolute(response.url, href)

                # Only match Yahoo Finance news article URLs
                if "finance.yahoo.com/news/" not in url:
                    continue

                # Title length filter
                if len(text) < 20 or len(text) > 250:
                    continue

                # Skip obvious non-article text
                skip = ["Home", "Mail", "News", "Finance", "Sports", "Entertainment",
                        "Sign in", "Search", "More", "My Portfolio", "Markets",
                        "Industries", "Tech", "Politics", "Watchlist", "Latest",
                        "Popular", "Trending", "Yahoo Finance", "Privacy", "Terms",
                        "About", "Settings", "Newsletters", "Personal Finance"]
                if text.strip() in skip:
                    continue

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                raw = {"url": url, "title": text}
                yield raw
                self.increment_new()

            except Exception:
                continue

        logger.info(f"Yahoo Finance crawl complete: {self.stats['new']} new")
