"""DeepSeek API async client for news classification.

Uses aiohttp for concurrent requests with semaphore-bounded concurrency.
"""

import asyncio
import json
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# ── Prompt template ──────────────────────────────────────────────

CLASSIFICATION_PROMPT = """你是一个专业的金融新闻分析助手。请分析以下新闻，判断它是"分析观点类"还是"新闻事件类"，并提取结构化信息。

## 新闻信息
- 标题：{title}
- 来源：{source}
- 发布时间：{publish_time}
- 正文：
{content}

## 分类标准

**分析观点类 (opinion)**：文章主要是作者对市场走势、品种行情的分析、预测、评论、建议。包含对某个/某些期货品种的观点判断。
**新闻事件类 (event)**：文章主要报道已经发生或即将发生的具体事件、政策变化、数据发布、行业动态等客观事实。

## 输出要求

请严格按照以下 JSON 格式返回（不要包含 markdown 代码块标记，只输出纯 JSON）：

{{
  "type": "opinion",
  "opinions": [
    {{
      "variety": "品种名称（如：螺纹钢、原油、铜等）",
      "short_term_view": "利多",
      "long_term_view": "利空",
      "short_term_view_reason": "短期观点的具体原因",
      "long_term_view_reason": "长期观点的具体原因"
    }},
    {{
      "variety": "铁矿石",
      "short_term_view": "利空",
      "long_term_view": "",
      "short_term_view_reason": "仅分析了短期，长期未提及",
      "long_term_view_reason": ""
    }}
  ],
  "events": []
}}

或者：

{{
  "type": "event",
  "opinions": [],
  "events": [
    {{
      "event_summary": "事件简述（一句话说清楚）",
      "event_time": "2024-01-15 或 null",
      "affects_futures": true,
      "affected_variety": "受影响的期货品种名称，多个用逗号分隔",
      "impact_analysis": "该事件对期货市场的影响分析"
    }}
  ]
}}

## 重要规则
1. 如果文章包含多个品种的分析，请在 opinions 数组中为每个品种创建一条记录
2. 如果文章包含多个独立事件，请在 events 数组中为每个事件创建一条记录
3. 如果文章同时包含观点和事件，优先归类为 opinion（分析观点类）
4. short_term_view 和 long_term_view 只能是 "利多"、"利空" 或 "震荡"
5. 如果新闻中只包含短期观点，long_term_view 和 long_term_view_reason 置空字符串；只包含长期观点同理。两者都有则都返回，不必强行填充
6. affects_futures 为 true 或 false
7. 品种名称使用中文全称
8. 只输出 JSON，不要输出任何其他内容
"""


class DeepSeekClient:
    """Async client for DeepSeek API (OpenAI-compatible chat completions)."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        max_tokens: int = 4096,
        temperature: float = 0.1,
        timeout: int = 120,
        max_retries: int = 3,
        concurrency: int = 50,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.concurrency = concurrency
        self._semaphore: Optional[asyncio.Semaphore] = None

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.concurrency)
        return self._semaphore

    # ── public API ────────────────────────────────────────────

    async def classify(
        self,
        title: str,
        content: str,
        source: str = "",
        publish_time: str = "",
    ) -> Optional[dict]:
        """Classify a single news article. Returns parsed JSON dict or None on failure."""
        prompt = CLASSIFICATION_PROMPT.format(
            title=title,
            source=source,
            publish_time=publish_time or "未知",
            content=content[:8000],  # truncate long content
        )

        async with self.semaphore:
            return await self._call_api(prompt)

    async def classify_batch(
        self,
        items: list[dict],
    ) -> list[tuple[dict, Optional[dict]]]:
        """Classify a batch of news items concurrently.

        Each item in `items` should be a dict with keys:
        url, title, source, content, publish_time.

        Returns list of (item, result) tuples. result is None if classification failed.
        """
        tasks = []
        for item in items:
            tasks.append(
                self._classify_one(item)
            )
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: list[tuple[dict, Optional[dict]]] = []
        for item, result in zip(items, results):
            if isinstance(result, Exception):
                logger.error(f"LLM classify error for {item['url']}: {result}")
                output.append((item, None))
            else:
                output.append((item, result))
        return output

    # ── internal ──────────────────────────────────────────────

    async def _classify_one(self, item: dict) -> Optional[dict]:
        """Classify a single item with its metadata."""
        return await self.classify(
            title=item.get("title", ""),
            content=item.get("content", ""),
            source=item.get("source", ""),
            publish_time=str(item.get("publish_time", "") or ""),
        )

    async def _call_api(self, prompt: str) -> Optional[dict]:
        """Call DeepSeek chat completions API with retry logic."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一个专业的金融新闻分析助手。你只输出 JSON，不输出其他任何内容。"},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            return self._parse_response(data)
                        elif response.status == 429:
                            # Rate limited — exponential backoff
                            wait = 2 ** attempt
                            logger.warning(
                                f"DeepSeek rate limited (429), retrying in {wait}s (attempt {attempt+1}/{self.max_retries})"
                            )
                            await asyncio.sleep(wait)
                        elif response.status >= 500:
                            wait = 2 ** attempt
                            logger.warning(
                                f"DeepSeek server error ({response.status}), retrying in {wait}s"
                            )
                            await asyncio.sleep(wait)
                        else:
                            body = await response.text()
                            logger.error(
                                f"DeepSeek API error {response.status}: {body[:500]}"
                            )
                            return None
            except asyncio.TimeoutError:
                logger.warning(
                    f"DeepSeek timeout (attempt {attempt+1}/{self.max_retries})"
                )
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.error(
                    f"DeepSeek request error (attempt {attempt+1}/{self.max_retries}): {e}"
                )
                await asyncio.sleep(2 ** attempt)

        logger.error("DeepSeek API call failed after all retries")
        return None

    def _parse_response(self, data: dict) -> Optional[dict]:
        """Parse the API response and extract the structured JSON."""
        try:
            content = data["choices"][0]["message"]["content"]
            # Strip markdown code fences if present
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            return json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse LLM response: {e}")
            # Log the raw content for debugging
            try:
                raw = data["choices"][0]["message"]["content"]
                logger.debug(f"Raw LLM response: {raw[:500]}")
            except Exception:
                pass
            return None
