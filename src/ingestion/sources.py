"""News sources - RSS and NewsAPI"""
import feedparser
import httpx
import asyncio
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    url: str
    title: str
    source: str
    published: Optional[datetime]


# Verified working feeds only
RSS_FEEDS = [
    ("https://www.cnbc.com/id/10000115/device/rss/rss.html", "CNBC"),
    ("https://www.housingwire.com/feed/", "HousingWire"),
    ("https://themortgagereports.com/feed", "MortgageReports"),
    ("https://www.calculatedriskblog.com/feeds/posts/default", "CalculatedRisk"),
    ("https://wolfstreet.com/feed/", "WolfStreet"),
]

NEWSAPI_QUERIES = ["real estate market", "housing prices", "mortgage rates", "home sales"]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RealEstateBot/1.0)"}


class NewsSources:
    def __init__(self):
        from src.config import get_global_settings
        self.newsapi_key = get_global_settings().newsapi_key
    
    def fetch_rss(self) -> list[NewsItem]:
        """Fetch items from RSS feeds (synchronous)."""
        from src.config import get_global_settings
        settings = get_global_settings()
        
        items = []
        for url, source in RSS_FEEDS:
            try:
                feed = feedparser.parse(url, request_headers=HEADERS)
                for entry in feed.entries[:settings.max_articles_per_feed]:
                    link = entry.get('link', '')
                    if not link or not link.startswith('http'):
                        continue
                    
                    pub_date = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        try:
                            pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        except Exception:
                            pass
                    
                    items.append(NewsItem(
                        url=link,
                        title=entry.get('title', '')[:200],
                        source=source,
                        published=pub_date
                    ))
                logger.info(f"RSS {source}: {min(len(feed.entries), settings.max_articles_per_feed)} items")
            except Exception as e:
                logger.warning(f"RSS {source} failed: {e}")
        return items
    
    async def fetch_newsapi(self) -> list[NewsItem]:
        """Fetch items from NewsAPI (async)."""
        if not self.newsapi_key:
            return []
        
        items = []
        async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
            for query in NEWSAPI_QUERIES:
                try:
                    resp = await client.get(
                        "https://newsapi.org/v2/everything",
                        params={
                            "q": query,
                            "language": "en",
                            "sortBy": "publishedAt",
                            "pageSize": 10,
                            "apiKey": self.newsapi_key
                        }
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for article in data.get("articles", []):
                            url = article.get("url", "")
                            if not url:
                                continue
                            
                            pub_date = None
                            if article.get("publishedAt"):
                                try:
                                    pub_date = datetime.fromisoformat(
                                        article["publishedAt"].replace("Z", "+00:00")
                                    )
                                except Exception:
                                    pass
                            
                            items.append(NewsItem(
                                url=url,
                                title=article.get("title", "")[:200],
                                source=article.get("source", {}).get("name", "NewsAPI"),
                                published=pub_date
                            ))
                        logger.info(f"NewsAPI '{query}': {len(data.get('articles', []))} items")
                    elif resp.status_code == 429:
                        logger.warning("NewsAPI rate limited")
                        break
                except Exception as e:
                    logger.warning(f"NewsAPI '{query}' failed: {e}")
                await asyncio.sleep(0.5)
        return items
    
    async def fetch_all(self) -> list[NewsItem]:
        """Fetch from all sources concurrently."""
        # Run RSS fetch in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()
        rss_task = loop.run_in_executor(None, self.fetch_rss)
        newsapi_task = self.fetch_newsapi()
        
        # Run both concurrently
        rss, newsapi = await asyncio.gather(rss_task, newsapi_task)
        
        # Dedupe by URL
        seen = set()
        unique = []
        for item in rss + newsapi:
            if item.url not in seen:
                seen.add(item.url)
                unique.append(item)
        
        logger.info(f"Total unique: {len(unique)} (RSS: {len(rss)}, NewsAPI: {len(newsapi)})")
        return unique
