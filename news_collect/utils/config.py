"""Configuration management — loads sources.yaml and settings.yaml."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class SourceConfig:
    """Configuration for a single news source."""

    name: str
    url: str
    enabled: bool = True
    interval: int = 300              # seconds between crawl runs
    use_stealth: bool = False        # use StealthyFetcher
    use_dynamic: bool = False        # use DynamicFetcher (full browser)
    download_delay: float = 1.0      # seconds between requests
    fetch_content: bool = True       # fetch full article body from detail pages
    max_items: int = 10              # max articles per crawl
    selectors: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "SourceConfig":
        return cls(
            name=name,
            url=data.get("url", ""),
            enabled=data.get("enabled", True),
            interval=data.get("interval", 300),
            use_stealth=data.get("use_stealth", False),
            use_dynamic=data.get("use_dynamic", False),
            download_delay=data.get("download_delay", 1.0),
            fetch_content=data.get("fetch_content", True),
            max_items=data.get("max_items", 10),
            selectors=data.get("selectors", {}),
            extra=data.get("extra", {}),
        )


class Config:
    """Singleton configuration loader.

    Usage:
        cfg = Config()
        source_cfg = cfg.get_source("cnbc")
        all_sources = cfg.sources
    """

    _instance: Optional["Config"] = None

    def __new__(cls) -> "Config":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self):
        if self._loaded:
            return
        self._loaded = True
        self._load()

    def _load(self):
        base = Path(__file__).parent.parent.parent  # NewsCollect/

        # Load global settings
        settings_path = base / "config" / "settings.yaml"
        if settings_path.exists():
            with open(settings_path, "r", encoding="utf-8") as f:
                self.settings = yaml.safe_load(f) or {}
        else:
            self.settings = {}

        # Load source configurations
        sources_path = base / "config" / "sources.yaml"
        if sources_path.exists():
            with open(sources_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        else:
            raw = {}

        self._sources: dict[str, SourceConfig] = {}
        for name, data in raw.get("sources", {}).items():
            self._sources[name] = SourceConfig.from_dict(name, data)

    # ── accessors ──────────────────────────────────────────

    @property
    def sources(self) -> dict[str, SourceConfig]:
        return self._sources

    @property
    def enabled_sources(self) -> dict[str, SourceConfig]:
        return {k: v for k, v in self._sources.items() if v.enabled}

    def get_source(self, name: str) -> Optional[SourceConfig]:
        return self._sources.get(name)

    # ── global settings helpers ────────────────────────────

    @property
    def default_concurrency(self) -> int:
        return self.settings.get("concurrency", 5)

    @property
    def default_timeout(self) -> int:
        return self.settings.get("timeout", 30)

    @property
    def default_user_agent(self) -> str:
        return self.settings.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )

    @property
    def proxy_list(self) -> list[str]:
        return self.settings.get("proxies", [])

    @property
    def db_path(self) -> str:
        return self.settings.get("db_path", "data/news.db")

    @property
    def retention_days(self) -> int:
        return self.settings.get("retention_days", 90)

    @property
    def log_level(self) -> str:
        return self.settings.get("log_level", "INFO")
