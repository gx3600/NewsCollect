"""同花顺期货API新闻 spider — ID-based incremental fetch.

Tracks the highest seq (news ID) seen across runs via a state file.
Each run starts from the last recorded seq, fetches all newer items,
and records the new highest seq for the next run.

Stop conditions:
  Per contract: entire page of 25 items has seq <= last_seq
  Global: 5 consecutive contracts return 0 new items
"""

import json, logging, re
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from scrapling.spiders import Response

from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)

NEWS_LIST_API = "https://ftapi.10jqka.com.cn/futgwapi/api/news/time_news/v1/news_list"
COMMUNITY_API = "https://fupage.10jqka.com.cn/futgwapi/api/news/v1/community/getInfo"
NEWS_INFO_API = "https://fupage.10jqka.com.cn/futgwapi/api/news/news_info/v1/news_info"
STATE_FILE = Path(__file__).parent.parent.parent / "config" / "ths_api_seq.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://goodsfu.10jqka.com.cn/",
}

EMPTY_CONTRACT_LIMIT = 5  # Stop after N consecutive contracts return 0 new


def _load_state() -> int:
    """Load the last seq from config/ths_api_seq.txt (manually editable)."""
    try:
        if STATE_FILE.exists():
            text = STATE_FILE.read_text(encoding="utf-8").strip()
            # Format: seq=677472479 or just the number
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("#") or not line:
                    continue
                if "=" in line:
                    return int(line.split("=")[-1].strip())
                return int(line)
    except Exception:
        pass
    return 0


def _save_state(highest_seq: int):
    """Write the latest seq to config/ths_api_seq.txt."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        f"# THS API last fetched seq (edit manually if needed)\n"
        f"seq={highest_seq}\n",
        encoding="utf-8",
    )


def _load_contracts() -> list[dict]:
    try:
        import openpyxl
        xlsx_path = Path(__file__).parent.parent.parent / "config" / "futures_variety.xlsx"
        if not xlsx_path.exists():
            logger.warning(f"futures_variety.xlsx not found at {xlsx_path}")
            return []
        wb = openpyxl.load_workbook(xlsx_path)
        sheet = wb.active
        contracts, seen = [], set()
        for row in sheet.iter_rows(min_row=2, values_only=True):
            tab_name, market_id, code, contract_name, keywords = row
            if not code or not market_id:
                continue
            key = (str(code), str(market_id))
            if key in seen:
                continue
            seen.add(key)
            contracts.append({
                "tab": str(tab_name) if tab_name else "",
                "market_id": str(market_id),
                "code": str(code),
                "name": str(contract_name) if contract_name else str(code),
            })
        wb.close()
        logger.info(f"Loaded {len(contracts)} unique contracts")
        return contracts
    except Exception as e:
        logger.error(f"Failed to load futures_variety.xlsx: {e}")
        return []


def _extract_url_param(url: str, param: str) -> str | None:
    m = re.search(rf'{param}=([^&]+)', url)
    return m.group(1) if m else None


def _clean_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", "", html)
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&").replace("&quot;", '"').replace("&apos;", "'")
    return re.sub(r"\s+", " ", text).strip()


def _fetch_content(url: str) -> str | None:
    from curl_cffi import requests as curl_requests
    try:
        if "community" in url:
            pid = _extract_url_param(url, "pid") or ""
            source = _extract_url_param(url, "source") or ""
            analog = _extract_url_param(url, "isSimulate") or "0"
            api_url = f"{COMMUNITY_API}?pid={pid}&source={source}&analog={analog}"
        elif "news/home.html" in url:
            seq = _extract_url_param(url, "seq") or ""
            typ = _extract_url_param(url, "type") or "1"
            api_url = f"{NEWS_INFO_API}?seq={seq}&type={typ}"
        elif "goodsfu" in url:
            return None
        else:
            return None
        resp = curl_requests.get(api_url, headers=HEADERS, impersonate="chrome", timeout=15)
        data = resp.json()
        if data.get("code") != 0:
            return None
        text = _clean_html(data.get("data", {}).get("content", ""))
        return text if len(text) > 50 else None
    except Exception as e:
        logger.debug(f"Content fetch failed: {e}")
        return None


@register
class THSApiSpider(BaseNewsSpider):
    """Spider for 同花顺期货API新闻 — seq-based incremental fetch.

    Tracks highest seq across runs. Each run fetches only items
    with seq > last_run_highest_seq, then records the new max.
    Auto-stops when 5 consecutive contracts have 0 new items.
    """

    name: str = "ths_api"
    source_name: str = "ths_api"
    start_urls: list[str] = [NEWS_LIST_API]
    concurrent_requests: int = 1
    download_delay: float = 0.3
    max_items: int = 0  # Unlimited — controlled by seq tracking

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._contracts = _load_contracts()

    async def parse(self, response: Response) -> AsyncGenerator:
        from curl_cffi import requests as curl_requests

        if not self._contracts:
            logger.error("No contracts loaded.")
            return

        last_seq = _load_state()
        logger.info(f"Starting incremental fetch from seq > {last_seq}")

        seen_urls = set()
        highest_seq = last_seq
        total_new = 0
        empty_streak = 0

        for contract in self._contracts:
            if empty_streak >= EMPTY_CONTRACT_LIMIT:
                logger.info(
                    f"{EMPTY_CONTRACT_LIMIT} consecutive empty contracts, "
                    f"caught up to latest. Stopping."
                )
                break

            code, market_id = contract["code"], contract["market_id"]
            page, contract_done, new_from_contract = 1, False, 0

            while not contract_done:
                params = {
                    "code": code, "market_id": market_id,
                    "page": page, "page_size": 25, "review_version": "false",
                }

                try:
                    resp = curl_requests.get(
                        NEWS_LIST_API, params=params, headers=HEADERS,
                        impersonate="chrome", timeout=15
                    )
                    data = resp.json()
                except Exception as e:
                    logger.debug(f"API failed for {code} p{page}: {e}")
                    break

                if data.get("code") != 0:
                    break

                items = data.get("data", {}).get("page_items", [])
                total_pages = data.get("data", {}).get("pages", 0)

                if not items:
                    break

                # Check if this entire page is below watermark
                page_max_seq = max(
                    (int(item.get("seq", 0) or 0) for item in items), default=0
                )
                if page_max_seq <= last_seq:
                    logger.debug(f"{code} p{page}: all seq <= {last_seq}, done")
                    contract_done = True
                    break

                for item in items:
                    seq_str = item.get("seq", "0")
                    try:
                        seq = int(seq_str)
                    except (ValueError, TypeError):
                        seq = 0

                    if seq <= last_seq:
                        continue  # Already fetched in previous run

                    url = item.get("url", "")
                    title = item.get("title", "")
                    create_time = item.get("create_time", "")

                    if not url or not title:
                        continue
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    # Track highest seq seen this run
                    if seq > highest_seq:
                        highest_seq = seq

                    pub_time = None
                    try:
                        ts = int(create_time)
                        pub_time = datetime.fromtimestamp(ts, tz=timezone.utc)
                    except (ValueError, TypeError):
                        pass

                    content = _fetch_content(url)

                    yield {
                        "url": url,
                        "title": title,
                        "publish_time": pub_time,
                        "content": content or "",
                    }
                    self.increment_new()
                    new_from_contract += 1
                    total_new += 1

                if page >= total_pages:
                    contract_done = True
                page += 1

            if new_from_contract == 0:
                empty_streak += 1
            else:
                empty_streak = 0
                logger.info(f"{code}({contract['name']}): +{new_from_contract} new")

        # Save state for next run
        if highest_seq > last_seq:
            _save_state(highest_seq)
            logger.info(
                f"Crawl complete: {total_new} new items. "
                f"Seq advanced {last_seq} -> {highest_seq} (delta: +{highest_seq - last_seq})"
            )
        else:
            logger.info(f"Crawl complete: 0 new items (caught up at seq {highest_seq})")
