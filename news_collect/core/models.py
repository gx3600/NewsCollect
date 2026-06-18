"""Data models for financial news items."""

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
