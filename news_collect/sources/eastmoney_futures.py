"""东方财富期货 (EastMoney Futures) news spider.

Same structure as eastmoney; different list page for futures-focused news.
"""

import logging
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)


@register
class EastMoneyFuturesSpider(BaseNewsSpider):
    """Spider for 东方财富期货 (EastMoney Futures) news."""

    name: str = "eastmoney_futures"
    source_name: str = "eastmoney_futures"
    start_urls: list[str] = [
        "https://futures.eastmoney.com/a/cqsyw.html",
    ]
    selectors: dict = {
        "article": ".list-wrap li, [class*=main] li, li",
        "title": "a::text",
        "link": "a::attr(href)",
    }
    concurrent_requests: int = 3
    download_delay: float = 0.5

    content_selectors: list[str] = [
        "#ContentBody p::text",
        ".txtinfos p::text",
        ".article-content p::text",
        ".newsContent p::text",
        "p::text",
    ]

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse EastMoney Futures news list."""
        logger.info(f"Crawling EastMoney Futures: {response.url}")

        articles = self.extract_all(response, "article")

        # Filter: only elements with links to /a/ article pages
        filtered = []
        for article in articles:
            link = self.extract(response, "link", article)
            if link and ("/a/" in link or "eastmoney.com/a/" in link):
                filtered.append(article)

        if not filtered:
            logger.debug("Container approach found nothing, using direct link approach")
            all_links = response.css("a[href*='/a/']")

        items_to_parse = filtered if filtered else (all_links if not filtered else [])
        for article in items_to_parse:
            if self._limit_reached():
                break
            try:
                if filtered:
                    raw = await self.parse_article(response, article)
                    if raw:
                        raw = await self._enrich_content(raw)
                else:
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
                logger.warning(f"Failed to parse EastMoney Futures article: {e}")
                continue

        logger.info(f"EastMoney Futures crawl complete: {self.stats['new']} new")
