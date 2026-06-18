"""证券之星期货 (StockStar Futures) news spider.

The site declares UTF-8 but actually uses GBK encoding.
We use curl_cffi with manual GBK decoding for both list and article pages.
"""

import logging
import re
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)

# Encodings to try when decoding stockstar pages
_ENCODINGS = ["gbk", "gb18030", "gb2312", "utf-8", "latin-1"]


def _decode_gbk(raw_bytes: bytes) -> str:
    """Try to decode bytes with various Chinese encodings, falling back to utf-8."""
    for enc in _ENCODINGS:
        try:
            return raw_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def _extract_links(html: str) -> list[tuple[str, str]]:
    """Extract article links from list page HTML using regex."""
    links = []
    # Find <a href="...">text</a> with stockstar article URLs
    pattern = r'<a[^>]*href="([^"]*(?:/IG\d+\.shtml)[^"]*)"[^>]*>(.*?)</a>'
    matches = re.findall(pattern, html, re.DOTALL)
    for href, raw_text in matches:
        text = re.sub(r"<[^>]+>", "", raw_text).strip()
        if text and len(text) >= 15:
            links.append((href, text))
    return links


@register
class StockStarFuturesSpider(BaseNewsSpider):
    """Spider for 证券之星期货 (StockStar Futures) news."""

    name: str = "stockstar_futures"
    source_name: str = "stockstar_futures"
    start_urls: list[str] = [
        "https://futures.stockstar.com/list/2961.shtml",
    ]
    concurrent_requests: int = 3
    download_delay: float = 1.0

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse StockStar futures list with GBK decoding."""
        logger.info(f"Crawling StockStar Futures: {response.url}")

        try:
            from curl_cffi import requests as curl_requests

            # Fetch with curl_cffi and decode as GBK
            cresp = curl_requests.get(
                self.start_urls[0], impersonate="chrome", timeout=15
            )
            html = _decode_gbk(cresp.content)
        except Exception as e:
            logger.error(f"Failed to fetch list page: {e}")
            return

        links = _extract_links(html)
        seen_urls = set()

        for href, text in links:
            if self._limit_reached():
                break

            url = self._make_absolute(self.start_urls[0], href)
            if url in seen_urls:
                continue
            seen_urls.add(url)

            raw = {"url": url, "title": text}
            raw = await self._enrich_content(raw)
            yield raw
            self.increment_new()

        logger.info(f"StockStar Futures crawl complete: {self.stats['new']} new")

    async def _fetch_article_content(self, url: str, sid: str = "") -> str | None:
        """Fetch article with GBK encoding via curl_cffi."""
        try:
            from curl_cffi import requests as curl_requests

            cresp = curl_requests.get(url, impersonate="chrome", timeout=15)
            html = _decode_gbk(cresp.content)

            # Find content container
            content_html = ""
            for cls in ["article_content", "content", "article-content"]:
                m = re.search(
                    rf'<(?:div|section|article)\s+class="[^"]*{cls}[^"]*"[^>]*>(.*?)</(?:div|section|article)>',
                    html, re.DOTALL | re.IGNORECASE,
                )
                if m:
                    content_html = m.group(1)
                    break

            if not content_html:
                content_html = html

            # Strip scripts, styles, tags
            text = re.sub(r"<script[^>]*>.*?</script>", "", content_html, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", "\n", text)
            text = re.sub(r"&nbsp;|&lt;|&gt;|&amp;|&quot;", " ", text)
            text = re.sub(r"&#?\w+;", " ", text)

            # Clean up
            lines = [l.strip() for l in text.split("\n")]
            lines = [l for l in lines if len(l) >= 12]
            bp = self._boilerplate_patterns
            lines = [l for l in lines if not any(b in l for b in bp)]

            content = "\n".join(lines)
            if len(content) > 100:
                return content
            return None
        except Exception:
            return None
