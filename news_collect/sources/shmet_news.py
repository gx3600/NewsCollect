"""SMM 新闻 spider — shmet.com news column (id=1025, parentId=996).

This column contains general SMM news articles (not PDF reports).
Uses the shmet API directly (api.shmet.com/api).

API flow:
  1. GET  /rest/news/newsList  → list of articles with newsId, title, summary
  2. POST /rest/news/v2/getNewsById → full article content (HTML)
"""

import logging
import re
from datetime import datetime, timezone
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)

API_BASE = "https://api.shmet.com/api"
LIST_API = f"{API_BASE}/rest/news/newsList"
DETAIL_API = f"{API_BASE}/rest/news/v2/getNewsById"
ARTICLE_URL = "https://www.shmet.com/news/newsDetail-2-{}.html"

# Column parameters (from parentId=996, column id=1025)
COL_TYPE = "1007"
COL_ID = "1025"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "x-requested-with": "XMLHttpRequest",
    "Referer": "https://www.shmet.com/column/column.html?id=1025&parentId=996",
    "Content-Type": "application/json;charset=UTF-8",
}


def _clean_html(html: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", "", html)
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&").replace("&quot;", '"')
    return re.sub(r"\s+", " ", text).strip()


def _fetch_list(page: int = 1, page_size: int = 10) -> list[dict]:
    """Fetch article list from the shmet API."""
    import curl_cffi.requests as curl_requests

    params = {
        "currentPage": page,
        "pageSize": page_size,
        "colType": COL_TYPE,
        "colId": COL_ID,
    }
    try:
        resp = curl_requests.get(
            LIST_API, params=params, headers=HEADERS,
            impersonate="chrome124", timeout=15,
        )
        data = resp.json()
        if data.get("code") == "000000":
            return data.get("data", {}).get("dataList", [])
    except Exception as e:
        logger.error(f"List API failed: {e}")
    return []


def _fetch_detail(news_id: str) -> dict | None:
    """Fetch full article detail via POST API."""
    import curl_cffi.requests as curl_requests

    try:
        resp = curl_requests.post(
            DETAIL_API, json={"newsId": news_id},
            headers=HEADERS, impersonate="chrome124", timeout=15,
        )
        data = resp.json()
        if data.get("code") == "000000":
            return data.get("data", {})
    except Exception as e:
        logger.debug(f"Detail API failed for {news_id}: {e}")
    return None


@register
class ShmetNewsSpider(BaseNewsSpider):
    """Spider for SMM news column (id=1025)."""

    name: str = "shmet_news"
    source_name: str = "shmet_news"
    start_urls: list[str] = [
        "https://www.shmet.com/column/column.html?id=1025&parentId=996"
    ]
    concurrent_requests: int = 1
    download_delay: float = 0.3
    max_items: int = 10
    fetch_content: bool = True  # Detail API gives full content

    async def parse(self, response: Response) -> AsyncGenerator:
        seen_ids = set()
        total = 0
        page = 1

        while total < self.max_items:
            items = _fetch_list(page=page, page_size=min(self.max_items - total, 20))
            if not items:
                logger.debug(f"No more items on page {page}")
                break

            for item in items:
                if self._limit_reached():
                    break

                news_id = str(item.get("newsId", ""))
                if not news_id or news_id in seen_ids:
                    continue
                seen_ids.add(news_id)

                title = item.get("title", "")
                summary = item.get("summary", "")

                # Fetch full content
                content = ""
                pub_time = None
                if self.fetch_content:
                    detail = _fetch_detail(news_id)
                    if detail:
                        content = _clean_html(detail.get("content", ""))
                        if not content:
                            content = summary
                        push_date = detail.get("pushDate", 0)
                        if push_date:
                            try:
                                ts = int(push_date) / 1000  # ms → seconds
                                pub_time = datetime.fromtimestamp(ts, tz=timezone.utc)
                            except (ValueError, TypeError):
                                pass

                if not content and summary:
                    content = summary

                url = ARTICLE_URL.format(news_id)

                yield {
                    "url": url,
                    "title": title,
                    "publish_time": pub_time,
                    "content": content,
                    "category": "shmet_news",
                    "raw_data": {
                        "newsId": news_id,
                        "summary": summary,
                        "source": item.get("source", ""),
                        "tagList": item.get("tagList", []),
                    },
                }
                self.increment_new()
                total += 1

            page += 1

        logger.info(f"shmet_news: fetched {total} items across {page - 1} pages")
