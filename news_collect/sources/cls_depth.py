"""财联社深度文章 spider — cls.cn/depth (id=1124, 能源主题).

Fetches depth articles via the CLS v3 API and extracts full content
from server-side rendered (SSR) article pages.

API flow:
  1. GET  /v3/depth/list/1124  → list of articles (id, ctime, title, brief)
  2. GET  /detail/{id}         → SSR page with __NEXT_DATA__ containing full content

The SSR page contains a __NEXT_DATA__ JSON blob with articleDetail.content
(HTML format), ctime, author, and other metadata.
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)

LIST_API = "https://www.cls.cn/v3/depth/list/1124"
DETAIL_URL = "https://www.cls.cn/detail/{}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.cls.cn/depth?id=1124",
}

# Sign mechanism (same as cls_telegraph)
def _make_sign(params: dict) -> str:
    def _sv(key, value):
        if value is None:
            return []
        if isinstance(value, bool):
            return [f"{key}={str(value).lower()}"]
        if isinstance(value, (str, int, float)):
            return [f"{key}={value}"]
        if isinstance(value, list):
            if not value:
                return [f"{key}[]"]
            result = []
            for i, item in enumerate(value):
                result.extend(_sv(f"{key}[{i}]", item))
            return result
        if isinstance(value, dict):
            result = []
            for kk in sorted(value.keys(), key=lambda x: str(x).upper()):
                result.extend(_sv(f"{key}[{kk}]", value[kk]))
            return result
        return []

    sorted_keys = sorted(params.keys(), key=lambda x: str(x).upper())
    parts = []
    for k in sorted_keys:
        parts.extend(_sv(k, params[k]))
    qs = "&".join(p for p in parts if p)
    sha1_digest = hashlib.sha1(qs.encode()).hexdigest()
    return hashlib.md5(sha1_digest.encode()).hexdigest()


def _clean_html(html: str) -> str:
    """Strip HTML tags, unescape entities, and normalize whitespace."""
    if not html:
        return ""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", html)
    # Decode common HTML entities
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&").replace("&quot;", '"').replace("&#x27;", "'")
    text = text.replace("&#39;", "'")
    return re.sub(r"\s+", " ", text).strip()


@register
class ClsDepthSpider(BaseNewsSpider):
    """Spider for 财联社深度文章 (CLS Depth) — energy theme (id=1124)."""

    name: str = "cls_depth"
    source_name: str = "cls_depth"
    start_urls: list[str] = ["https://www.cls.cn/depth?id=1124"]
    concurrent_requests: int = 1
    download_delay: float = 0.5
    max_items: int = 10
    fetch_content: bool = True  # SSR page contains full content

    async def parse(self, response: Response) -> AsyncGenerator:
        from curl_cffi import requests as curl_requests

        import time
        base_params = {
            "app": "CailianpressWeb",
            "os": "web",
            "sv": "8.7.9",
        }
        sign = _make_sign(base_params)
        base_params["sign"] = sign

        # Fetch article list
        list_items = []
        try:
            resp = curl_requests.get(
                LIST_API, params=base_params, headers=HEADERS,
                impersonate="chrome124", timeout=15,
            )
            data = resp.json()
            if data.get("errno") == 0:
                list_items = data.get("data", [])
        except Exception as e:
            logger.error(f"List API failed: {e}")
            return

        logger.info(f"cls_depth: got {len(list_items)} items from list API")

        seen_ids = set()
        total = 0

        for item in list_items:
            if self._limit_reached():
                break

            article_id = str(item.get("id", ""))
            if not article_id or article_id in seen_ids:
                continue
            seen_ids.add(article_id)

            title = item.get("title", "")
            brief = item.get("brief", "")
            ctime = item.get("ctime", 0)

            # Parse publish time
            pub_time = None
            try:
                ts = int(ctime)
                if ts > 0:
                    pub_time = datetime.fromtimestamp(ts, tz=timezone.utc)
            except (ValueError, TypeError):
                pass

            content = ""
            url = DETAIL_URL.format(article_id)

            # Fetch article detail for full content
            if self.fetch_content:
                try:
                    dresp = curl_requests.get(
                        url, headers=HEADERS,
                        impersonate="chrome124", timeout=15,
                    )
                    if dresp.status_code == 200:
                        # Extract __NEXT_DATA__
                        m = re.search(
                            r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                            dresp.text, re.DOTALL,
                        )
                        if m:
                            ndata = json.loads(m.group(1))
                            detail = (
                                ndata.get("props", {})
                                .get("pageProps", {})
                                .get("articleDetail", {})
                            )
                            if detail:
                                raw_content = detail.get("content", "")
                                content = _clean_html(raw_content)
                                if not content:
                                    content = brief
                except Exception as e:
                    logger.debug(f"Detail fetch failed for {article_id}: {e}")

            if not content and brief:
                content = brief

            yield {
                "url": url,
                "title": title,
                "publish_time": pub_time,
                "content": content,
                "category": "cls_depth",
                "raw_data": {
                    "id": article_id,
                    "brief": brief,
                    "ctime": ctime,
                    "author": item.get("author", ""),
                    "tags": item.get("article_tag", []),
                },
            }
            self.increment_new()
            total += 1

        logger.info(f"cls_depth: fetched {total} items")
