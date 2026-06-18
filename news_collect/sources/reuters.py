"""Reuters news via Google News RSS.

Reuters deprecated its official RSS feeds.  Google News RSS provides
a stable alternative — it returns Reuters articles aggregated through
Google News search.

Note: article URLs point to Google News redirect pages (not direct
Reuters links).  The ``guid`` serves as the dedup key via the DB's
UNIQUE(url) constraint.

For native Reuters article URLs, deploy RSSHub locally and switch
the feed URLs to e.g. ``http://rsshub:1200/reuters/world``.
"""

from news_collect.sources.rss_base import BaseRssSpider
from news_collect.sources import register


@register
class ReutersSpider(BaseRssSpider):
    """Reuters news via Google News RSS (official feeds deprecated)."""

    name = "reuters"
    source_name = "reuters"
    feeds = [
        {
            "url": (
                "https://news.google.com/rss/search?"
                "q=site:reuters.com&hl=en-US&gl=US&ceid=US:en"
            ),
            "category": "breaking",
            "label": "Reuters (Google News)",
        },
        {
            "url": (
                "https://news.google.com/rss/search?"
                "q=site:reuters.com+business&hl=en-US&gl=US&ceid=US:en"
            ),
            "category": "business",
            "label": "Reuters Business (Google News)",
        },
        {
            "url": (
                "https://news.google.com/rss/search?"
                "q=site:reuters.com+politics&hl=en-US&gl=US&ceid=US:en"
            ),
            "category": "politics",
            "label": "Reuters Politics (Google News)",
        },
    ]
