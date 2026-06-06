"""Source registry — auto-discovery and registration of news source spiders.

Each source module is automatically discovered from the sources/ directory.
Modules export their spider class, which is registered by name.

Usage:
    from news_collect.sources import SOURCE_REGISTRY, list_sources, get_source

    # List all available sources
    for name in list_sources():
        print(name)

    # Get a spider class by name
    SpiderCls = get_source("cnbc")
"""

import importlib
import logging
from pathlib import Path
from typing import Optional, Type

from news_collect.sources.base import BaseNewsSpider

logger = logging.getLogger(__name__)

# Global registry: source_name -> Spider class
SOURCE_REGISTRY: dict[str, Type[BaseNewsSpider]] = {}


def register(cls: Type[BaseNewsSpider]):
    """Decorator to register a news source spider class."""
    name = getattr(cls, "name", cls.__name__.lower())
    SOURCE_REGISTRY[name] = cls
    logger.debug(f"Registered source: {name} ({cls.__name__})")
    return cls


def get_source(name: str) -> Optional[Type[BaseNewsSpider]]:
    """Get a registered spider class by name."""
    return SOURCE_REGISTRY.get(name)


def list_sources() -> list[str]:
    """Return list of all registered source names."""
    return sorted(SOURCE_REGISTRY.keys())


def auto_discover():
    """Auto-discover and import all source modules in the sources/ directory.

    Call this once at startup to populate SOURCE_REGISTRY.
    Source modules use the @register decorator to self-register.
    """
    sources_dir = Path(__file__).parent
    imported = 0

    for py_file in sources_dir.glob("*.py"):
        module_name = py_file.stem
        # Skip private/internal modules
        if module_name.startswith("_") or module_name in ("base",):
            continue

        try:
            importlib.import_module(f"news_collect.sources.{module_name}")
            imported += 1
        except Exception as e:
            logger.warning(f"Failed to import source module '{module_name}': {e}")

    logger.info(f"Discovered {imported} source(s): {list_sources()}")
    return SOURCE_REGISTRY
