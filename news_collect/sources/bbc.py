"""BBC News via official RSS feeds.

Routes:
    world    — Breaking / World news
    business — Business / Finance
    politics — UK & World Politics
"""

from news_collect.sources.rss_base import BaseRssSpider
from news_collect.sources import register


@register
class BbcSpider(BaseRssSpider):
    """BBC RSS news source."""

    name = "bbc"
    source_name = "bbc"
    feeds = [
        {
            "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
            "category": "breaking",
            "label": "BBC World",
        },
        {
            "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
            "category": "business",
            "label": "BBC Business",
        },
        {
            "url": "https://feeds.bbci.co.uk/news/politics/rss.xml",
            "category": "politics",
            "label": "BBC Politics",
        },
    ]
