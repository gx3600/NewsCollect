"""生意社期货新闻 spider — 100ppi.com futures news.

Page structure (simple server-rendered HTML):
  List:  futures.100ppi.com/news---{page}.html
  Article: futures.100ppi.com/detail-YYYYMMDD-NNNNNN.html

The list page uses a classic <li> + <a> structure with category labels.
Article detail has clean HTML with .nd-info (time) and .nd-c (content).
"""

import logging
import re
from datetime import datetime, timezone
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)

BASE = "https://futures.100ppi.com"
LIST_URL = f"{BASE}/news---{{page}}.html"
MAX_PAGES = 3  # Scan up to 3 pages (~60 articles) to find fresh ones


@register
class PPIFuturesSpider(BaseNewsSpider):
    """Spider for 生意社 (100ppi.com) futures news."""

    name: str = "100ppi_futures"
    source_name: str = "100ppi_futures"
    start_urls: list[str] = [LIST_URL.format(page=1)]
    concurrent_requests: int = 1
    download_delay: float = 0.5
    max_items: int = 10

    content_selectors: list[str] = [
        ".nd-c p::text",
        ".nd-c::text",
        ".news-detail p::text",
        "p::text",
    ]

    async def parse(self, response: Response) -> AsyncGenerator:
        """Parse the news list page and follow article links."""
        logger.info(f"Crawling 100ppi futures: {response.url}")

        seen_ids = set()

        for page in range(1, MAX_PAGES + 1):
            if self._limit_reached():
                break

            if page > 1:
                from scrapling.spiders.request import Request
                req = Request(url=LIST_URL.format(page=page))
                resp = await self._session_manager.fetch(req)
                if not resp or resp.status_code != 200:
                    logger.debug(f"Page {page} not available, stopping")
                    break
            else:
                resp = response

            articles = resp.css("li")
            for article in articles:
                if self._limit_reached():
                    break

                link_el = article.css("a[href*='detail-']")
                link = link_el.css("::attr(href)").get()
                title = link_el.css("::text").get()

                if not link or not title:
                    continue

                title = str(title).strip()
                link = str(link).strip()

                # Extract article ID for dedup
                m = re.search(r"detail-(\d+)-(\d+)\.html", link)
                if not m:
                    continue
                article_id = int(m.group(2))
                if article_id in seen_ids:
                    continue
                seen_ids.add(article_id)

                # Try to get date from list page as fallback
                date_span = article.css("span::text").get()
                fallback_date = str(date_span).strip() if date_span else ""

                url = BASE + "/" + link if not link.startswith("http") else link

                raw = {
                    "url": url,
                    "title": title,
                }

                # Enrich with content + time from detail page
                if self.fetch_content:
                    enriched = await self._enrich_content(raw)
                    if enriched:
                        raw = enriched

                # Fallback: use list-page date if detail page didn't yield time
                if not raw.get("publish_time") and fallback_date:
                    try:
                        dt = datetime.strptime(fallback_date, "%Y%m%d")
                        raw["publish_time"] = dt.replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass

                yield raw
                self.increment_new()

        logger.info(f"100ppi_futures: fetched {len(seen_ids)} items")
