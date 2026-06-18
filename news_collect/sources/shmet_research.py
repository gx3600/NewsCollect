"""上海有色网 (SMM) 研究报告 spider — PDF+Image content via PyMuPDF."""

import logging, re
from typing import AsyncGenerator
from scrapling.fetchers import AsyncStealthySession
from scrapling.spiders import Response, Request
from news_collect.sources.base import BaseNewsSpider
from news_collect.sources import register

logger = logging.getLogger(__name__)
PDF_URL_RE = re.compile(r'href="(https://[^"]+\.pdf)"')
IMG_URL_RE = re.compile(r'(https://[^"]+\.(?:png|jpg|jpeg))')

@register
class ShmetResearchSpider(BaseNewsSpider):
    name: str = "shmet_research"
    source_name: str = "shmet_research"
    start_urls: list[str] = ["https://www.shmet.com/column/column-detail-1005-1008.html"]
    concurrent_requests: int = 1
    download_delay: float = 5.0

    def configure_sessions(self, manager):
        manager.add("default", AsyncStealthySession(headless=True, timeout=30000), lazy=False)

    async def parse(self, response: Response) -> AsyncGenerator:
        logger.info(f"Crawling Shmet Research: {response.url}")
        body = response.body
        if isinstance(body, bytes): body = body.decode("utf-8", errors="replace")
        seen = set()
        for m in re.finditer(r'<a\s+[^>]*href="(/news/newsDetail-\d+-\d+\.html)"[^>]*>(.*?)</a>', body, re.DOTALL):
            if self._limit_reached(): break
            href, raw_text = m.group(1), m.group(2)
            title = re.sub(r"<[^>]+>", "", raw_text).strip()
            title = re.sub(r"\s+", " ", title)
            if len(title) < 5 or href in seen: continue
            seen.add(href)
            url = self._make_absolute(response.url, href)
            raw = {"url": url, "title": title}
            raw = await self._enrich_content(raw)
            yield raw
            self.increment_new()
        logger.info(f"Shmet Research crawl complete: {self.stats['new']} new")

    async def _fetch_article_content(self, url: str, sid: str = "") -> str | None:
        try:
            req = Request(url=url)
            resp = await self._session_manager.fetch(req)
            body = resp.body
            if isinstance(body, bytes): body = body.decode("utf-8", errors="replace")
            pdf_match = PDF_URL_RE.search(body)
            if pdf_match:
                from curl_cffi import requests as curl_requests
                pdf_resp = curl_requests.get(pdf_match.group(1), impersonate="chrome", timeout=30)
                if pdf_resp.status_code == 200:
                    import fitz
                    doc = fitz.open(stream=pdf_resp.content, filetype="pdf")
                    text = "\n".join(page.get_text() for page in doc)
                    doc.close()
                    if len(text.strip()) > 100: return text.strip()
            img_urls = IMG_URL_RE.findall(body)
            if img_urls:
                unique = list(dict.fromkeys(img_urls))
                return "[图片型文章 — 图片列表]\n" + "\n".join(unique[:20])
            return None
        except Exception as e:
            logger.debug(f"Content fetch failed: {e}")
            return None
