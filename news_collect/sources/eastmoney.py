"""东方财富 (EastMoney) financial news spider."""

import logging
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)


@register
class EastMoneySpider(BaseNewsSpider):
    """Spider for 东方财富 (EastMoney) financial news."""

    name: str = "eastmoney"
    source_name: str = "eastmoney"
    start_urls: list[str] = [
        "https://finance.eastmoney.com/a/czqyw.html",
    ]
    selectors: dict = {
        "article": ".list-wrap li, [class*=main] li, li",
        "title": "a::text",
        "link": "a::attr(href)",
        "time": "span.time::text, .time::text",
    }
    concurrent_requests: int = 3
    download_delay: float = 0.5

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse EastMoney financial news list."""
        logger.info(f"Crawling EastMoney: {response.url}")

        # Try container-based approach first
        articles = self.extract_all(response, "article")

        # Filter: only elements that have links to /a/ article pages
        filtered = []
        for article in articles:
            link = self.extract(response, "link", article)
            if link and ("/a/" in link or "eastmoney.com/a/" in link):
                filtered.append(article)

        if not filtered:
            # Fallback: directly find all article links
            logger.debug("Container approach found nothing, using direct link approach")
            all_links = response.css("a[href*='/a/']")
            logger.debug(f"Found {len(all_links)} direct article links")

        logger.debug(f"Found {len(filtered) if filtered else len(all_links) if not filtered else 0} relevant articles")

        items_to_parse = filtered if filtered else (all_links if not filtered else [])
        for article in items_to_parse:
            try:
                if filtered:
                    raw = await self.parse_article(response, article)
                else:
                    # For direct links, extract differently
                    title = article.css("::text").get()
                    link = article.css("::attr(href)").get()
                    if not title or not link:
                        continue
                    raw = {
                        "url": self._make_absolute(response.url, link),
                        "title": str(title).strip(),
                    }
                    raw = await self._enrich_content(raw)
                if raw:
                    yield raw
                    self.increment_new()
            except Exception as e:
                logger.warning(f"Failed to parse EastMoney article: {e}")
                continue

        logger.info(f"EastMoney crawl complete: {self.stats['new']} new")
