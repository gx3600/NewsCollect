"""CNN news via Google News RSS.

CNN deprecated its official RSS feeds around 2017–2024 — the old feeds
return articles from years ago and are not maintained.  Google News RSS
provides current CNN articles aggregated through Google News search.

(If RSSHub is deployed locally, switch to e.g. ``http://rsshub:1200/cnn/...``)
"""

from news_collect.sources.rss_base import BaseRssSpider
from news_collect.sources import register


@register
class CnnSpider(BaseRssSpider):
    """CNN news via Google News RSS (official feeds deprecated)."""

    name = "cnn"
    source_name = "cnn"
    feeds = [
        {
            "url": (
                "https://news.google.com/rss/search?"
                "q=site:cnn.com&hl=en-US&gl=US&ceid=US:en"
            ),
            "category": "breaking",
            "label": "CNN (Google News)",
        },
        {
            "url": (
                "https://news.google.com/rss/search?"
                "q=site:cnn.com+business&hl=en-US&gl=US&ceid=US:en"
            ),
            "category": "business",
            "label": "CNN Business (Google News)",
        },
        {
            "url": (
                "https://news.google.com/rss/search?"
                "q=site:cnn.com+politics&hl=en-US&gl=US&ceid=US:en"
            ),
            "category": "politics",
            "label": "CNN Politics (Google News)",
        },
    ]
