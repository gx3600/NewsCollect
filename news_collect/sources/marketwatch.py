"""MarketWatch financial news spider."""

import logging
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)


@register
class MarketWatchSpider(BaseNewsSpider):
    """Spider for MarketWatch latest news."""

    name: str = "marketwatch"
    source_name: str = "marketwatch"
    start_urls: list[str] = [
        "https://www.marketwatch.com/latest-news?mod=side_nav",
    ]
    selectors: dict = {
        "article": ".article__content, article, [class*=article]",
        "title": "a::text, h3 a::text, .article__headline a::text",
        "link": "a::attr(href), h3 a::attr(href), .article__headline a::attr(href)",
    }
    concurrent_requests: int = 3
    download_delay: float = 2.0
    robots_txt_obey: bool = False  # MarketWatch blocks /latest-news in robots.txt
    fetch_content: bool = False  # MarketWatch returns 401 on article detail pages

    # MarketWatch-specific article content selectors
    content_selectors: list[str] = [
        "[data-type=\"paragraph\"]::text",
        ".StyledNewsKitParagraph::text",
        "p::text",
    ]

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse MarketWatch latest news."""
        logger.info(f"Crawling MarketWatch: {response.url}")

        # Find all article-like links
        all_links = response.css("a[href]")
        seen_urls = set()
        count = 0

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

                # Filter for actual news stories
                if "/story/" not in href:
                    continue
                if len(text) < 15:
                    continue
                # Skip utility links
                skip = ["Skip to", "Subscribe", "Newsletter", "Sign in", "Account",
                        "Facebook", "Twitter", "LinkedIn", "YouTube", "RSS"]
                if any(text.startswith(s) for s in skip):
                    continue

                url = self._make_absolute(response.url, href)
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                raw = {"url": url, "title": text}
                raw = await self._enrich_content(raw)
                yield raw
                self.increment_new()
                count += 1
            except Exception:
                continue

        logger.info(f"MarketWatch crawl complete: {self.stats['new']} new")
