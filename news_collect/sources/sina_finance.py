"""新浪财经 (Sina Finance) financial news spider."""

import logging
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)


@register
class SinaFinanceSpider(BaseNewsSpider):
    """Spider for 新浪财经 (Sina Finance) news."""

    name: str = "sina_finance"
    source_name: str = "sina_finance"
    start_urls: list[str] = [
        "https://finance.sina.com.cn/",
    ]
    selectors: dict = {
        "article": ".main-content a, .feed-card-item a, [class*=news] a",
        "title": "::text",
        "link": "::attr(href)",
    }
    concurrent_requests: int = 3
    download_delay: float = 1.0

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse Sina Finance homepage."""
        logger.info(f"Crawling Sina Finance: {response.url}")

        # Find all links that look like news articles
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

                # Filter: only Sina finance article URLs with meaningful titles
                if not href.startswith(("http", "https://finance", "//finance")):
                    continue
                if len(text) < 10 or len(text) > 200:
                    continue
                # Skip obvious nav links
                skip_words = ["首页", "股票", "基金", "期货", "外汇", "黄金", "专栏", "更多",
                              "登录", "注册", "首页", "导航", "搜索"]
                if text in skip_words:
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
            except Exception as e:
                continue

        logger.info(f"Sina Finance crawl complete: {self.stats['new']} new")
