"""华尔街见闻 (WallStreetCN) financial news spider.

WallStreetCN is a JavaScript SPA that loads content via API.
We call the API directly using curl_cffi to avoid Scrapling framework interference.
"""

import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)

# WallStreetCN API endpoints
INFO_FLOW_API = "https://api-one.wallstcn.com/apiv1/content/information-flow?channel=global-channel&limit=50"
LIVES_API = "https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&client=pc&limit=50&first_page=true"


@register
class WallStreetCNSpider(BaseNewsSpider):
    """Spider for 华尔街见闻 (WallStreetCN) global financial news.

    Uses the WallStreetCN API directly for reliable data extraction.
    """

    name: str = "wallstreetcn"
    source_name: str = "wallstreetcn"
    start_urls: list[str] = [
        "https://wallstreetcn.com/news/global",  # Placeholder; API called manually
    ]
    concurrent_requests: int = 2
    download_delay: float = 1.0
    fetch_content: bool = False  # API already returns content_short

    async def parse(self, response: Response) -> AsyncGenerator:
        """Fetch WallStreetCN APIs and parse JSON responses."""
        logger.info("Crawling WallStreetCN via API")

        try:
            from curl_cffi import requests as curl_requests
        except ImportError:
            logger.error("curl_cffi not available")
            return

        # Collect items from both APIs
        all_items = []
        seen_uris = set()

        for api_url in [INFO_FLOW_API, LIVES_API]:
            try:
                api_resp = curl_requests.get(api_url, impersonate="chrome", timeout=15)
                body = api_resp.text
                data = json.loads(body) if isinstance(body, str) else body
            except Exception as e:
                logger.warning(f"Failed to fetch {api_url}: {e}")
                continue

            raw_items = []
            if isinstance(data, dict):
                raw_data = data.get("data", {})
                if isinstance(raw_data, dict):
                    raw_items = raw_data.get("items", [])

            for item in raw_items:
                try:
                    # Handle info-flow format: resource is nested
                    resource = item.get("resource", item)

                    title = resource.get("title", "")
                    uri = resource.get("uri", "")
                    content_text = resource.get("content_text", "") or resource.get("content_short", "") or resource.get("content", "")
                    display_time = resource.get("display_time")
                    resource_type = item.get("resource_type", resource.get("type", ""))

                    if not title or not uri:
                        continue

                    title = str(title).strip()
                    uri = str(uri).strip()

                    if len(title) < 10 or len(title) > 300:
                        continue

                    if uri in seen_uris:
                        continue
                    seen_uris.add(uri)

                    pub_time = None
                    if display_time:
                        try:
                            pub_time = datetime.fromtimestamp(int(display_time), tz=timezone.utc)
                        except (ValueError, TypeError):
                            pass

                    raw = {
                        "url": uri,
                        "title": title,
                        "content": str(content_text).strip() if content_text else None,
                        "publish_time": pub_time,
                    }
                    all_items.append(raw)
                    if len(all_items) >= self.max_items:
                        break

                except Exception as e:
                    continue

            if len(all_items) >= self.max_items:
                break

        # Yield collected items (up to max_items)
        for raw in all_items[:self.max_items]:
            yield raw
            self.increment_new()

        logger.info(f"WallStreetCN crawl complete: {self.stats['new']} new from {len(all_items)} items")
