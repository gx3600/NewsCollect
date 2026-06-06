"""华尔街见闻 (WallStreetCN) financial news spider.

WallStreetCN is a JavaScript SPA, so we use StealthySession to render JS.
"""

import logging
from typing import AsyncGenerator

from scrapling.spiders import Response
from scrapling.fetchers import AsyncStealthySession

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)


@register
class WallStreetCNSpider(BaseNewsSpider):
    """Spider for 华尔街见闻 (WallStreetCN) global financial news."""

    name: str = "wallstreetcn"
    source_name: str = "wallstreetcn"
    start_urls: list[str] = [
        "https://wallstreetcn.com/news/global",
    ]
    selectors: dict = {
        "article": "article, [class*=article], [class*=item], [class*=card]",
        "title": "a::text, h3::text",
        "link": "a::attr(href)",
    }
    concurrent_requests: int = 2
    download_delay: float = 2.0

    def configure_sessions(self, manager):
        """Use stealthy browser session to render JavaScript."""
        manager.add("default", AsyncStealthySession(headless=True), lazy=False)

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse WallStreetCN global news page."""
        logger.info(f"Crawling WallStreetCN: {response.url}")

        # Find all links with useful text
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

                # Filter for wallstreetcn article pages
                if "wallstreetcn.com" not in href and not href.startswith("/"):
                    continue
                if len(text) < 10 or len(text) > 300:
                    continue
                # Skip obvious non-article text
                skip = ["首页", "快讯", "资讯", "专栏", "会员", "直播", "搜索",
                        "登录", "注册", "热门", "最新", "推荐", "更多"]
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
            except Exception as e:
                continue

        logger.info(f"WallStreetCN crawl complete: {self.stats['new']} new")
