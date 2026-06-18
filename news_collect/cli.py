"""CLI entry point for NewsCollect.

Commands:
    news-collect run [--source X] [--once]   Run crawlers
    news-collect list-sources                  List available sources
    news-collect stats [--source X] [--days N] Show storage stats
    news-collect daemon [--interval N]        Run as daemon
    news-collect init                          Initialize config and directories
"""

import logging
import sys
from typing import Optional

import click

from news_collect.utils.config import Config
from news_collect.utils.logging import setup_logging

logger = logging.getLogger(__name__)


@click.group()
@click.version_option(version="0.1.0", prog_name="news-collect")
@click.pass_context
def main(ctx: click.Context):
    """NewsCollect - Multi-source financial news crawler powered by Scrapling."""
    ctx.ensure_object(dict)


# ── init ───────────────────────────────────────────────────

@main.command()
def init():
    """Initialize NewsCollect: create config files and data directories."""
    from pathlib import Path

    # Ensure directories exist
    dirs = ["data/checkpoints", "config"]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)

    # Create default settings.yaml if missing
    settings_path = Path("config/settings.yaml")
    if not settings_path.exists():
        settings_path.write_text(DEFAULT_SETTINGS, encoding="utf-8")
        click.echo("✓ Created config/settings.yaml")

    # Create default sources.yaml if missing
    sources_path = Path("config/sources.yaml")
    if not sources_path.exists():
        sources_path.write_text(DEFAULT_SOURCES, encoding="utf-8")
        click.echo("✓ Created config/sources.yaml")

    click.echo("✓ NewsCollect initialized successfully!")
    click.echo(f"  Data directory: {Path('data').absolute()}")
    click.echo(f"  Database:       data/news.db")
    click.echo(f"  Checkpoints:    data/checkpoints/")


# ── run ────────────────────────────────────────────────────

@main.command()
@click.option(
    "--source", "-s",
    multiple=True,
    help="Source name(s) to crawl (repeatable). If omitted, runs all enabled sources.",
)
@click.option("--once/--no-once", default=True, help="Run once and exit (default).")
@click.option(
    "--dev", "dev_mode",
    is_flag=True,
    help="Development mode: use cached responses, no live HTTP.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable debug logging.",
)
def run(source: tuple[str, ...], once: bool, dev_mode: bool, verbose: bool):
    """Run news crawlers for specified sources."""
    cfg = Config()
    setup_logging(level="DEBUG" if verbose else cfg.log_level)

    from news_collect.core.engine import CrawlerEngine

    engine = CrawlerEngine()

    names = list(source) if source else None

    click.echo(f"Starting crawl: {', '.join(names) if names else 'all enabled sources'}")
    if dev_mode:
        click.echo("[DEV MODE] Using cached responses only.")

    result = engine.run_sources(names=names, dev_mode=dev_mode)

    # Print summary
    click.echo()
    click.echo("=" * 50)
    click.echo("CRAWL SUMMARY")
    click.echo("=" * 50)
    click.echo(f"  Total crawled:  {result.stats.get('total_crawled', 0)}")
    click.echo(f"  New articles:   {result.stats.get('total_new', 0)}")
    click.echo(f"  Duplicates:     {result.stats.get('total_skipped', 0)}")
    click.echo()

    if result.source_stats:
        click.echo("Per-source breakdown:")
        for name, stats in result.source_stats.items():
            status = "OK" if "error" not in stats else "ERR"
            if "error" in stats:
                click.echo(f"  [{status}] {name}: ERROR - {stats['error']}")
            else:
                click.echo(
                    f"  [{status}] {name}: {stats['items']} crawled, "
                    f"{stats['new']} new, {stats['skipped']} dupes"
                )


# ── list-sources ───────────────────────────────────────────

@main.command(name="list-sources")
def list_sources():
    """List all available and configured news sources."""
    from news_collect.sources import auto_discover, list_sources as get_names

    cfg = Config()
    auto_discover()

    click.echo("Available news sources:")
    click.echo("-" * 60)

    all_names = get_names()
    if not all_names:
        click.echo("  (no sources registered)")
        return

    for name in all_names:
        src_cfg = cfg.get_source(name)
        if src_cfg:
            status = "enabled" if src_cfg.enabled else "disabled"
            click.echo(
                f"  {name:20s}  [{status}]  interval={src_cfg.interval}s  "
                f"stealth={src_cfg.use_stealth}  delay={src_cfg.download_delay}s"
            )
        else:
            click.echo(f"  {name:20s}  [no config]")

    # Also show configured-but-not-registered sources
    configured = set(cfg.sources.keys())
    registered = set(all_names)
    missing = configured - registered
    if missing:
        click.echo()
        click.echo("Configured but not yet implemented:")
        for name in sorted(missing):
            click.echo(f"  {name} (in config/sources.yaml but no spider module)")


# ── stats ──────────────────────────────────────────────────

@main.command()
@click.option("--source", "-s", default=None, help="Filter by source name.")
@click.option("--days", "-d", default=7, help="Show stats for last N days (default: 7).")
def stats(source: Optional[str], days: int):
    """Display storage statistics."""
    cfg = Config()

    from news_collect.core.storage import NewsStorage

    storage = NewsStorage(cfg.db_path)
    s = storage.stats(source=source)

    click.echo("Storage Statistics")
    click.echo("=" * 40)
    click.echo(f"  Database:     {cfg.db_path}")
    click.echo(f"  Total news:   {s['total']}")
    click.echo(f"  First crawl:  {s['first_crawl'] or 'N/A'}")
    click.echo(f"  Last crawl:   {s['last_crawl'] or 'N/A'}")
    click.echo()

    if s["by_source"]:
        click.echo("News count by source:")
        for src, cnt in s["by_source"].items():
            click.echo(f"  {src:20s}  {cnt:6d} articles")

    # Show recent news
    if s["total"] > 0:
        click.echo()
        click.echo(f"Recent news (last {days} days):")
        click.echo("-" * 60)
        items = storage.query(source=source, days=days, limit=20)
        for item in items:
            title = item["title"][:80] if item["title"] else "(no title)"
            click.echo(
                f"  [{item['source']:15s}] {title}"
            )
            click.echo(f"    {item['url']}")

    storage.close()


# ── daemon ─────────────────────────────────────────────────

@main.command()
@click.option(
    "--interval", "-i",
    default=None,
    type=int,
    help="Default interval in seconds between crawl rounds (overrides per-source intervals).",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable debug logging.",
)
def daemon(interval: Optional[int], verbose: bool):
    """Run NewsCollect as a continuous daemon with scheduled crawls.

    Each source crawls at its configured interval (from sources.yaml).
    Press Ctrl+C to stop gracefully.
    """
    cfg = Config()
    setup_logging(level="DEBUG" if verbose else cfg.log_level)

    from news_collect.scheduler import DaemonScheduler

    scheduler = DaemonScheduler(
        interval_override=interval,
        verbose=verbose,
    )

    click.echo("Starting NewsCollect daemon...")
    click.echo(f"Sources: {list(cfg.enabled_sources.keys())}")
    click.echo("Press Ctrl+C to stop.")
    click.echo()

    scheduler.start()


# ── default configs (for `init` command) ───────────────────

DEFAULT_SETTINGS = """\
# Global settings for NewsCollect

# Database path
db_path: "data/news.db"

# Concurrency & rate limiting
concurrency: 5
timeout: 30
download_delay: 1.0

# Data retention (days)
retention_days: 90

# Logging
log_level: "INFO"

# Proxies (optional, one per line)
proxies: []
#  - "http://user:pass@proxy1.example.com:8080"

# User agent (fallback only, Scrapling handles impersonation)
user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
"""

DEFAULT_SOURCES = """\
# News source configurations
# Each source defines: url, selectors, crawl interval, fetcher type
# fetch_content: if true (default), crawl article detail pages to extract full body text
# max_items: max articles per crawl (default 10)

sources:
  eastmoney:
    enabled: true
    url: "https://finance.eastmoney.com/a/czqyw.html"
    interval: 60
    fetch_content: true
    max_items: 10
    selectors:
      article: ".list-wrap li, [class*=main] li, li"
      title: "a::text"
      link: "a::attr(href)"

  mysteel:
    enabled: true
    url: "https://list1.mysteel.com/article/p-1947-------------1.html"
    interval: 60
    fetch_content: true
    max_items: 10
    selectors:
      article: "a[href]"
      title: "::text"
      link: "::attr(href)"
"""


"""CLI entry point for NewsCollect.

Commands:
    news-collect run [--source X] [--once]   Run crawlers
    news-collect list-sources                  List available sources
    news-collect stats [--source X] [--days N] Show storage stats
    news-collect daemon [--interval N]        Run as daemon
    news-collect init                          Initialize config and directories
"""

import logging
import sys
from typing import Optional

import click

from news_collect.utils.config import Config
from news_collect.utils.logging import setup_logging

logger = logging.getLogger(__name__)


@click.group()
@click.version_option(version="0.1.0", prog_name="news-collect")
@click.pass_context
def main(ctx: click.Context):
    """NewsCollect - Multi-source financial news crawler powered by Scrapling."""
    ctx.ensure_object(dict)


# ── init ───────────────────────────────────────────────────

@main.command()
def init():
    """Initialize NewsCollect: create config files and data directories."""
    from pathlib import Path

    # Ensure directories exist
    dirs = ["data/checkpoints", "config"]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)

    # Create default settings.yaml if missing
    settings_path = Path("config/settings.yaml")
    if not settings_path.exists():
        settings_path.write_text(DEFAULT_SETTINGS, encoding="utf-8")
        click.echo("✓ Created config/settings.yaml")

    # Create default sources.yaml if missing
    sources_path = Path("config/sources.yaml")
    if not sources_path.exists():
        sources_path.write_text(DEFAULT_SOURCES, encoding="utf-8")
        click.echo("✓ Created config/sources.yaml")

    click.echo("✓ NewsCollect initialized successfully!")
    click.echo(f"  Data directory: {Path('data').absolute()}")
    click.echo(f"  Database:       data/news.db")
    click.echo(f"  Checkpoints:    data/checkpoints/")


# ── run ────────────────────────────────────────────────────

@main.command()
@click.option(
    "--source", "-s",
    multiple=True,
    help="Source name(s) to crawl (repeatable). If omitted, runs all enabled sources.",
)
@click.option("--once/--no-once", default=True, help="Run once and exit (default).")
@click.option(
    "--dev", "dev_mode",
    is_flag=True,
    help="Development mode: use cached responses, no live HTTP.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable debug logging.",
)
def run(source: tuple[str, ...], once: bool, dev_mode: bool, verbose: bool):
    """Run news crawlers for specified sources."""
    cfg = Config()
    setup_logging(level="DEBUG" if verbose else cfg.log_level)

    from news_collect.core.engine import CrawlerEngine

    engine = CrawlerEngine()

    names = list(source) if source else None

    click.echo(f"Starting crawl: {', '.join(names) if names else 'all enabled sources'}")
    if dev_mode:
        click.echo("[DEV MODE] Using cached responses only.")

    result = engine.run_sources(names=names, dev_mode=dev_mode)

    # Print summary
    click.echo()
    click.echo("=" * 50)
    click.echo("CRAWL SUMMARY")
    click.echo("=" * 50)
    click.echo(f"  Total crawled:  {result.stats.get('total_crawled', 0)}")
    click.echo(f"  New articles:   {result.stats.get('total_new', 0)}")
    click.echo(f"  Duplicates:     {result.stats.get('total_skipped', 0)}")
    click.echo()

    if result.source_stats:
        click.echo("Per-source breakdown:")
        for name, stats in result.source_stats.items():
            status = "OK" if "error" not in stats else "ERR"
            if "error" in stats:
                click.echo(f"  [{status}] {name}: ERROR - {stats['error']}")
            else:
                click.echo(
                    f"  [{status}] {name}: {stats['items']} crawled, "
                    f"{stats['new']} new, {stats['skipped']} dupes"
                )


# ── list-sources ───────────────────────────────────────────

@main.command(name="list-sources")
def list_sources():
    """List all available and configured news sources."""
    from news_collect.sources import auto_discover, list_sources as get_names

    cfg = Config()
    auto_discover()

    click.echo("Available news sources:")
    click.echo("-" * 60)

    all_names = get_names()
    if not all_names:
        click.echo("  (no sources registered)")
        return

    for name in all_names:
        src_cfg = cfg.get_source(name)
        if src_cfg:
            status = "enabled" if src_cfg.enabled else "disabled"
            click.echo(
                f"  {name:20s}  [{status}]  interval={src_cfg.interval}s  "
                f"stealth={src_cfg.use_stealth}  delay={src_cfg.download_delay}s"
            )
        else:
            click.echo(f"  {name:20s}  [no config]")

    # Also show configured-but-not-registered sources
    configured = set(cfg.sources.keys())
    registered = set(all_names)
    missing = configured - registered
    if missing:
        click.echo()
        click.echo("Configured but not yet implemented:")
        for name in sorted(missing):
            click.echo(f"  {name} (in config/sources.yaml but no spider module)")


# ── stats ──────────────────────────────────────────────────

@main.command()
@click.option("--source", "-s", default=None, help="Filter by source name.")
@click.option("--days", "-d", default=7, help="Show stats for last N days (default: 7).")
def stats(source: Optional[str], days: int):
    """Display storage statistics."""
    cfg = Config()

    from news_collect.core.storage import NewsStorage

    storage = NewsStorage(cfg.db_path)
    s = storage.stats(source=source)

    click.echo("Storage Statistics")
    click.echo("=" * 40)
    click.echo(f"  Database:     {cfg.db_path}")
    click.echo(f"  Total news:   {s['total']}")
    click.echo(f"  First crawl:  {s['first_crawl'] or 'N/A'}")
    click.echo(f"  Last crawl:   {s['last_crawl'] or 'N/A'}")
    click.echo()

    if s["by_source"]:
        click.echo("News count by source:")
        for src, cnt in s["by_source"].items():
            click.echo(f"  {src:20s}  {cnt:6d} articles")

    # Show recent news
    if s["total"] > 0:
        click.echo()
        click.echo(f"Recent news (last {days} days):")
        click.echo("-" * 60)
        items = storage.query(source=source, days=days, limit=20)
        for item in items:
            title = item["title"][:80] if item["title"] else "(no title)"
            click.echo(
                f"  [{item['source']:15s}] {title}"
            )
            click.echo(f"    {item['url']}")

    storage.close()


# ── daemon ─────────────────────────────────────────────────

@main.command()
@click.option(
    "--interval", "-i",
    default=None,
    type=int,
    help="Default interval in seconds between crawl rounds (overrides per-source intervals).",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable debug logging.",
)
def daemon(interval: Optional[int], verbose: bool):
    """Run NewsCollect as a continuous daemon with scheduled crawls.

    Each source crawls at its configured interval (from sources.yaml).
    Press Ctrl+C to stop gracefully.
    """
    cfg = Config()
    setup_logging(level="DEBUG" if verbose else cfg.log_level)

    from news_collect.scheduler import DaemonScheduler

    scheduler = DaemonScheduler(
        interval_override=interval,
        verbose=verbose,
    )

    click.echo("Starting NewsCollect daemon...")
    click.echo(f"Sources: {list(cfg.enabled_sources.keys())}")
    click.echo("Press Ctrl+C to stop.")
    click.echo()

    scheduler.start()



