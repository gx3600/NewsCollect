"""Data models for financial news items and analysis results."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class NewsItem:
    """A single financial news article."""

    url: str
    title: str
    source: str
    content: Optional[str] = None
    publish_time: Optional[datetime] = None
    crawl_time: datetime = field(default_factory=datetime.now)
    category: Optional[str] = None
    processed: int = 0
    raw_data: Optional[dict] = None

    def to_dict(self) -> dict:
        """Convert to dict for storage insertion."""
        return asdict(self)

    @property
    def url_hash(self) -> str:
        """Simple hash of the URL for dedup checks."""
        import hashlib
        return hashlib.sha256(self.url.encode()).hexdigest()[:16]


@dataclass
class AnalysisOpinion:
    """AI-analyzed opinion/analysis article, split by variety (品种).

    One row per variety per article. An article covering multiple varieties
    produces multiple AnalysisOpinion records.
    """

    url: str
    variety: str                          # 品种名称
    analysis_date: str                    # 分析日期 (YYYY-MM-DD)
    short_term_view: str                  # 短期观点: "利多" | "利空" | "震荡"
    long_term_view: str                   # 长期观点: "利多" | "利空" | "震荡"
    short_term_view_reason: str           # 短期观点原因
    long_term_view_reason: str            # 长期观点原因
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NewsEvent:
    """AI-extracted news event, split by individual event.

    One row per event per article. An article containing multiple events
    produces multiple NewsEvent records.
    """

    url: str
    event_summary: str                    # 事件简述
    event_time: Optional[str] = None      # 事件发生时间 (YYYY-MM-DD HH:MM 或 null)
    keywords: str = ""                    # 新闻关键字，逗号分隔
    affects_futures: bool = False         # 是否直接影响期货市场
    affected_variety: str = ""            # 影响品种
    impact_level: str = ""                # 影响程度: 弱/一般/强/很强
    impact_analysis: str = ""             # 影响分析
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)
