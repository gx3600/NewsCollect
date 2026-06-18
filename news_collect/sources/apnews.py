"""Associated Press (AP) news via Google News RSS.

AP deprecated its official RSS feeds (apf-topnews etc. now return HTML).
Google News RSS provides a stable alternative.

Note: article URLs point to Google News redirect pages.

For native AP article URLs, deploy RSSHub locally and switch
the feed URLs to e.g. ``http://rsshub:1200/apnews/topics/ap-top-news``.
"""

from news_collect.sources.rss_base import BaseRssSpider
from news_collect.sources import register


@register
class ApNewsSpider(BaseRssSpider):
    """Associated Press news via Google News RSS."""

    name = "apnews"
    source_name = "apnews"
    feeds = [
        {
            "url": (
                "https://news.google.com/rss/search?"
                "q=site:apnews.com&hl=en-US&gl=US&ceid=US:en"
            ),
            "category": "breaking",
            "label": "AP News (Google News)",
        },
        {
            "url": (
                "https://news.google.com/rss/search?"
                "q=site:apnews.com+business&hl=en-US&gl=US&ceid=US:en"
            ),
            "category": "business",
            "label": "AP Business (Google News)",
        },
        {
            "url": (
                "https://news.google.com/rss/search?"
                "q=site:apnews.com+politics&hl=en-US&gl=US&ceid=US:en"
            ),
            "category": "politics",
            "label": "AP Politics (Google News)",
        },
    ]
