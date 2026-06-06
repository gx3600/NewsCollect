"""Logging setup for NewsCollect."""

import logging
import sys


def setup_logging(level: str = "INFO"):
    """Configure root logger with console handler.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR).
    """
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    root = logging.getLogger("news_collect")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)
    root.propagate = False

    # Quiet down noisy third-party loggers
    logging.getLogger("scrapling").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
