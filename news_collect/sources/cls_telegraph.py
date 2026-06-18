"""财联社电报 spider — API-based, sign verification.

Uses the same /v1/roll/get_roll_list API as the CLS web app.
Each item contains full content in the API response (no detail-page fetch needed).

Sign mechanism (reverse-engineered from JS source):
  1. Sort param keys case-insensitively
  2. Recursively serialize to key=value pairs (supports nested objects/arrays)
  3. Join with "&"
  4. SHA-1 hash → lowercase hex digest
  5. MD5 hash that hex digest → final sign
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

# CLS operates in China Standard Time (UTC+8)
CST = timezone(timedelta(hours=8))
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)

API_URL = "https://www.cls.cn/v1/roll/get_roll_list"
DETAIL_URL = "https://www.cls.cn/detail/{}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.cls.cn/telegraph",
}


def _serialize_value(key: str, value) -> list[str]:
    """Recursively serialize a param value to key=value strings.

    Mirrors the JS implementation in module 36498:
      - Strings/numbers/booleans → "key=value"
      - Arrays → "key[0]=v0", "key[1]=v1", empty array → "key[]"
      - Objects → "key[subkey]=value"
      - null/None → skipped
    """
    if value is None:
        return []

    if isinstance(value, bool):
        return [f"{key}={str(value).lower()}"]
    elif isinstance(value, (str, int, float)):
        return [f"{key}={value}"]
    elif isinstance(value, list):
        if not value:
            return [f"{key}[]"]
        result = []
        for i, item in enumerate(value):
            result.extend(_serialize_value(f"{key}[{i}]", item))
        return result
    elif isinstance(value, dict):
        result = []
        for k in sorted(value.keys(), key=lambda x: str(x).upper()):
            result.extend(_serialize_value(f"{key}[{k}]", value[k]))
        return result
    return []


def _sort_key(k: str) -> str:
    """Case-insensitive sort comparator (mirrors JS behaviour)."""
    return str(k).upper()


def _serialize_params(params: dict) -> str:
    """Serialize a params dict to a sorted query string."""
    sorted_keys = sorted(params.keys(), key=_sort_key)
    parts = []
    for k in sorted_keys:
        parts.extend(_serialize_value(k, params[k]))
    return "&".join(p for p in parts if p)


def make_sign(params: dict) -> str:
    """Generate the cls.cn API sign for given params.

    Algorithm: MD5(hex(SHA1(sorted_query_string)))
    """
    qs = _serialize_params(params)
    sha1_digest = hashlib.sha1(qs.encode()).hexdigest()
    return hashlib.md5(sha1_digest.encode()).hexdigest()


def _build_params(refresh_type: int = 1, rn: int = 20,
                  last_time: int = 0) -> dict:
    """Build base API params (without sign)."""
    import time
    if last_time <= 0:
        last_time = int(time.time())
    return {
        "app": "CailianpressWeb",
        "os": "web",
        "sv": "8.7.9",
        "refresh_type": str(refresh_type),
        "rn": str(rn),
        "last_time": str(last_time),
    }


@register
class ClsTelegraphSpider(BaseNewsSpider):
    """Spider for 财联社电报 (CLS Telegraph) — real-time financial news flashes.

    Fetches items via the roll list API with SHA1+MD5 signing.
    Each item already contains full content; no separate detail-page
    fetching is needed.
    """

    name: str = "cls_telegraph"
    source_name: str = "cls_telegraph"
    start_urls: list[str] = ["https://www.cls.cn/telegraph"]
    concurrent_requests: int = 1
    download_delay: float = 0.5
    max_items: int = 20
    fetch_content: bool = False  # API returns full content inline

    async def parse(self, response: Response) -> AsyncGenerator:
        from curl_cffi import requests as curl_requests

        seen_ids = set()
        total_new = 0
        last_time = 0

        while total_new < self.max_items:
            params = _build_params(
                refresh_type=1,
                rn=20,
                last_time=last_time,
            )
            sign = make_sign(params)
            params["sign"] = sign

            try:
                resp = curl_requests.get(
                    API_URL, params=params, headers=HEADERS,
                    impersonate="chrome", timeout=15,
                )
                data = resp.json()
            except Exception as e:
                logger.error(f"API request failed: {e}")
                break

            if data.get("errno") != 0:
                logger.debug(f"API error: errno={data.get('errno')}, msg={data.get('msg')}")
                break

            roll_data = (
                (data.get("data", {}).get("data", {}).get("roll_data", []))
                or data.get("data", {}).get("roll_data", [])
            )

            if not roll_data:
                logger.debug("No more items from API")
                break

            for item in roll_data:
                item_id = item.get("id")
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                content = item.get("content", "")
                brief = item.get("brief", "")
                ctime = item.get("ctime", 0)
                img = item.get("img", "")

                # Use content as body; if very short, try brief or title
                body = content.strip() if content else ""
                title_text = item.get("title", "").strip()

                # Telegraph items often lack a formal title — derive from content
                if not title_text and body:
                    # Use first sentence or first 50 chars
                    first_line = body.split("\n")[0].strip()
                    if len(first_line) > 15:
                        title_text = first_line[:80]
                    else:
                        title_text = body[:60]
                elif not title_text and brief:
                    first_line = brief.split("\n")[0].strip()
                    title_text = first_line[:60]

                if not title_text:
                    # Fallback: tag the ID
                    title_text = f"电报{''.join(str(item_id)[-8:])}"

                pub_time = None
                try:
                    ts = int(ctime)
                    if ts > 0:
                        pub_time = datetime.fromtimestamp(ts, tz=CST)
                except (ValueError, TypeError):
                    pass

                url = DETAIL_URL.format(item_id)

                yield {
                    "url": url,
                    "title": title_text,
                    "publish_time": pub_time,
                    "content": body,
                    "category": "telegraph",
                    "raw_data": {
                        "id": item_id,
                        "ctime": ctime,
                        "brief": brief,
                        "img": img,
                        "level": item.get("level", ""),
                        "type": item.get("type", -1),
                        "reading_num": item.get("reading_num", 0),
                    },
                }
                self.increment_new()
                total_new += 1

                if self._limit_reached():
                    break

            # Update last_time for pagination (use oldest item's ctime)
            if roll_data:
                oldest = roll_data[-1].get("ctime", 0)
                if oldest > 0:
                    last_time = int(oldest)

            if self._limit_reached():
                break

        logger.info(f"cls_telegraph: fetched {total_new} items")
