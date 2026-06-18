"""Mysteel general news spider."""

import logging, re
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)

LIST_URL = "https://news.mysteel.com/article/p-3578,1981,8060-------------1.html"


def _fetch_list_html(url: str, max_retries: int = 5) -> str | None:
    import time
    from curl_cffi import requests as curl_requests
    for attempt in range(max_retries):
        try:
            resp = curl_requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                impersonate="chrome124",
                timeout=20,
            )
            if resp.status_code != 200:
                continue
            if "captcha" in resp.text.lower():
                logger.warning(f"Mysteel captcha, retry {attempt + 1}/{max_retries}...")
                time.sleep(2)
                continue
            return resp.text
        except Exception as e:
            logger.warning(f"Mysteel fetch error: {e}, retry {attempt + 1}/{max_retries}")
            time.sleep(2)
    return None


@register
class MysteelNewsSpider(BaseNewsSpider):
    """Spider for Mysteel general (综合) news."""

    name: str = "mysteel_news"
    source_name: str = "mysteel_news"
    start_urls: list[str] = [LIST_URL]
    concurrent_requests: int = 3
    download_delay: float = 1.0

    content_selectors: list[str] = [
        "#article-content p::text",
        "#article-content::text",
        "#text > p::text",
        "#text p::text",
        ".editor::text",
        ".content-text::text",
        "[class*=content]::text",
        "p::text",
    ]

    async def parse(self, response: Response) -> AsyncGenerator:
        html = _fetch_list_html(LIST_URL)
        if not html:
            logger.error("Mysteel News: failed to fetch list page")
            return

        logger.info(f"Crawling Mysteel News: {LIST_URL}")
        seen_urls = set()

        for m in re.finditer(
            r'<a\s+[^>]*href="([^"]*(?:/a/|mysteel\.com/a/)\d+/\w+\.html)[^"]*"[^>]*>([^<]{15,200})</a>',
            html, re.IGNORECASE,
        ):
            if self._limit_reached():
                break
            href = m.group(1).strip()
            text = m.group(2).strip()
            text = re.sub(r'<[^>]+>', '', text).strip()

            if not href or not text:
                continue
            if len(text) < 15 or len(text) > 200:
                continue

            url = self._make_absolute(LIST_URL, href)
            if url in seen_urls:
                continue
            seen_urls.add(url)

            raw = {"url": url, "title": text}
            raw = await self._enrich_content(raw)
            yield raw
            self.increment_new()

        logger.info(f"Mysteel News crawl complete: {self.stats['new']} new")
