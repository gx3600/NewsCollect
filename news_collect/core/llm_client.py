"""DeepSeek API async client for news classification.

Uses aiohttp for concurrent requests with semaphore-bounded concurrency.
Prompt is scoped to Chinese domestic futures markets only.
"""

import asyncio
import json
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# ── Prompt templates ──────────────────────────────────────────────

SYSTEM_PROMPT = (
    "你是一个中国国内期货市场新闻分析专家。"
    "你的任务是将新闻分类为分析观点类、新闻事件类或不相关类。"
    "你只输出 JSON，不输出其他任何内容。"
)

# {varieties} will be replaced with the comma-separated whitelist at runtime
CLASSIFICATION_PROMPT_TEMPLATE = """请分析以下新闻，先根据分类标准进行分类，再根据要求返回分析结果。

## 国内期货品种白名单（只分析以下品种）
{varieties}

## 新闻信息
- 标题：{title}
- 来源：{source}
- 发布时间：{publish_time}
- 正文：
{content}

## 分类标准

**分析观点类 (opinion)**：文章包含对白名单中某个/某些期货品种的市场走势、行情的分析、预测、评论、建议。
**新闻事件类 (event)**：文章报道已发生或即将发生的具体事件、政策变化、数据发布、行业动态等客观事实，且事件可能影响白名单中的期货品种。
**不相关类 (irrelevant)**：文章完全不涉及白名单中的任何期货品种。例如：纯股票分析、海外期货、加密货币、宏观经济但不涉及具体期货品种等。直接返回。

## 输出格式

如果是 **opinion**（仅输出白名单品种）：
{{
  "type": "opinion",
  "opinions": [
    {{
      "variety": "螺纹钢",
      "short_term_view": "利多",
      "long_term_view": "利空",
      "short_term_view_reason": "短期观点的具体原因",
      "long_term_view_reason": "长期观点的具体原因"
    }}
  ],
  "events": []
}}

如果是 **event**：
{{
  "type": "event",
  "opinions": [],
  "events": [
    {{
      "event_summary": "事件简述",
      "event_time": "2024-01-15 或 null",
      "keywords": "提取新闻中最重要的关键词、名词，用逗号分隔",
      "affects_futures": true,
      "affected_variety": "受影响的品种名（必须在白名单中），多个用逗号分隔",
      "impact_level": "弱",
      "impact_analysis": "该事件对相关期货品种的影响分析",
      "expected_end_time": "2024-07-15 或 null"
    }}
  ]
}}

如果是 **irrelevant**（不涉及任何白名单品种或不影响白名单品种）：
{{
  "type": "irrelevant",
  "opinions": [],
  "events": []
}}

## 重要规则
1. 只输出 JSON，不要输出任何其他内容
2. **品种约束**：opinions 中的 variety 和 events 中的 affected_variety **必须严格来自白名单**，不得出现白名单之外的品种
3. 完全不涉及白名单品种或不影响白名单品种 → 返回 irrelevant

## 分析观点类规则(opinion)
1. 如果文章包含多个品种的分析，在 opinions 数组中为每个品种创建一条记录
2. 如果文章包含多个独立事件，在 events 数组中为每个事件创建一条记录
3. 文章同时包含观点和事件时，优先归类为 opinion
4. short_term_view 和 long_term_view 只能是 "利多"、"利空" 或 "震荡"
5. 如果只含短期观点，long_term_view 和 long_term_view_reason 置空字符串；反之亦然

## 新闻事件类规则(event)
8. affects_futures 为 true 或 false
9. **keywords 必填**：从新闻正文中提取最重要的关键词、核心名词，用逗号分隔。必须至少包含3个关键词，不可留空
10. **impact_level 必填**：当 affects_futures 为 true 时必填，只能是 "弱"、"一般"、"强" 或 "很强"。判断依据：该事件短期内对受影响最重的期货品种价格的预期涨跌幅度 — 弱(3%以内)、一般(3%-5%)、强(5%-10%)、很强(10%以上)。如果 affects_futures 为 false，impact_level 置空字符串
11.**expected_end_time**：如果新闻中明确提到事件的结束/决议/公布时间点或某事件预计会发生的时间（如会议日期、政策生效日、数据发布日期、谈判截止日），填入该日期（YYYY-MM-DD格式，如果没有提及具体某月某日，则用预计可能发生的最早的一天）。如果事件是长期的、没有明确结束点的（如持续性地缘冲突、行业趋势、长期政策），填 null
"""


class DeepSeekClient:
    """Async client for DeepSeek API (OpenAI-compatible chat completions).

    Scoped to Chinese domestic futures markets — the prompt includes a
    whitelist of varieties loaded from config/futures_variety.xlsx.
    """

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
        varieties: Optional[list[str]] = None,
        use_json_mode: bool = True,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.concurrency = concurrency
        self.use_json_mode = use_json_mode
        self._semaphore: Optional[asyncio.Semaphore] = None

        # Build the classification prompt with the variety whitelist baked in
        varieties_list = varieties or []
        self.varieties: set[str] = set(varieties_list)
        varieties_str = "、".join(varieties_list) if varieties_list else "（未配置品种白名单）"
        self.classification_prompt = CLASSIFICATION_PROMPT_TEMPLATE.format(
            varieties=varieties_str,
            title="{title}",
            source="{source}",
            publish_time="{publish_time}",
            content="{content}",
        )

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
        # If content is empty but title is long enough, use title as content.
        effective_content = content.strip() if content else ""
        if not effective_content and len(title) > 20:
            effective_content = title

        # Use replace() instead of format() because the prompt already contains
        # JSON curly braces that would confuse str.format().
        prompt = self.classification_prompt
        prompt = prompt.replace("{title}", title)
        prompt = prompt.replace("{source}", source)
        prompt = prompt.replace("{publish_time}", publish_time or "未知")
        prompt = prompt.replace("{content}", effective_content[:8000])

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
        tasks = [self._classify_one(item) for item in items]
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
        """Classify a single item with its metadata. Post-processes the raw
        LLM result to filter out non-whitelisted varieties."""
        raw = await self.classify(
            title=item.get("title", ""),
            content=item.get("content", ""),
            source=item.get("source", ""),
            publish_time=str(item.get("publish_time", "") or ""),
        )
        if raw is None:
            return None

        # ── post-filter: ensure only whitelisted varieties appear ──
        if self.varieties:
            raw = self._filter_varieties(raw, item.get("url", "?"))
        return raw

    def _filter_varieties(self, result: dict, url: str) -> dict:
        """Filter opinions and events to only include whitelisted varieties."""
        # Filter opinions
        opinions = result.get("opinions", [])
        if opinions:
            filtered_ops = []
            for op in opinions:
                variety = op.get("variety", "")
                if variety in self.varieties:
                    filtered_ops.append(op)
                else:
                    logger.debug(
                        f"Filtered out non-whitelist variety '{variety}' from {url}"
                    )
            result["opinions"] = filtered_ops

            # If all opinions were filtered out and type was opinion, check if
            # it should become irrelevant
            if not filtered_ops and result.get("type") == "opinion":
                events = result.get("events", [])
                if not events:
                    result["type"] = "irrelevant"

        # Filter events' affected_variety
        events = result.get("events", [])
        if events:
            for ev in events:
                affected = ev.get("affected_variety", "")
                if affected:
                    parts = [p.strip() for p in affected.split(",")]
                    filtered_parts = [p for p in parts if p in self.varieties]
                    ev["affected_variety"] = ",".join(filtered_parts)
                    if not filtered_parts:
                        ev["affects_futures"] = False
                        ev["affected_variety"] = ""

        return result

    async def _call_api(self, prompt: str) -> Optional[dict]:
        """Call DeepSeek chat completions API with retry logic."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        # Enable JSON mode — dramatically reduces format errors
        if self.use_json_mode:
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(self.max_retries):
            try:
                # Separate connect and read timeouts for better resilience
                connect_timeout = min(10, self.timeout)
                read_timeout = max(self.timeout - connect_timeout, 10)

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(
                            total=self.timeout,
                            connect=connect_timeout,
                            sock_read=read_timeout,
                        ),
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            return self._parse_response(data)
                        elif response.status == 429:
                            # Rate limited — prefer Retry-After header, else exponential backoff
                            retry_after = response.headers.get("Retry-After")
                            if retry_after is not None:
                                try:
                                    wait = int(retry_after)
                                except ValueError:
                                    wait = 2 ** attempt
                            else:
                                wait = 2 ** attempt
                            logger.warning(
                                f"DeepSeek rate limited (429), retrying in {wait}s "
                                f"(attempt {attempt+1}/{self.max_retries})"
                            )
                            await asyncio.sleep(wait)
                        elif response.status >= 500:
                            wait = 2 ** attempt
                            logger.warning(
                                f"DeepSeek server error ({response.status}), "
                                f"retrying in {wait}s (attempt {attempt+1}/{self.max_retries})"
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
        """Parse the API response and extract the structured JSON.

        JSON mode should return clean JSON, but we keep the markdown-fence
        stripping as a fallback for models/providers that don't respect it.
        """
        try:
            content = data["choices"][0]["message"]["content"]
            content = content.strip()

            # Fallback: strip markdown code fences if present
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            return json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse LLM response: {e}")
            try:
                raw = data["choices"][0]["message"]["content"]
                logger.debug(f"Raw LLM response: {raw[:500]}")
            except Exception:
                pass
            return None
