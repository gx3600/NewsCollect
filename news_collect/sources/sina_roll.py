"""新浪财经滚动新闻 (Sina Finance Roll) spider.

Focused on the futures/commodities roll (c/56995).
"""

import logging
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)


@register
class SinaRollSpider(BaseNewsSpider):
    """Spider for 新浪财经滚动 (Sina Finance Roll) futures news."""

    name: str = "sina_roll"
    source_name: str = "sina_roll"
    start_urls: list[str] = [
        "https://finance.sina.com.cn/roll/c/56995.shtml",
    ]
    concurrent_requests: int = 3
    download_delay: float = 1.0

    content_selectors: list[str] = [
        "#artibody p::text",
        "#article_content p::text",
        ".article-content p::text",
        ".article p::text",
        "p::text",
    ]

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse Sina roll news list."""
        logger.info(f"Crawling Sina Roll: {response.url}")

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

                # Filter for sina finance article pages
                if "sina.com.cn" not in href and not href.startswith("/"):
                    continue
                if not href.endswith(".shtml"):
                    continue

                if len(text) < 15 or len(text) > 200:
                    continue

                # Skip obvious non-article links
                skip = ["首页", "股票", "基金", "期货", "外汇", "黄金", "专栏",
                        "更多", "登录", "注册", "导航", "搜索"]
                if text in skip:
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

        logger.info(f"Sina Roll crawl complete: {self.stats['new']} new")
