"""Article collector - fetch and parse HTML"""
import hashlib
import re
import asyncio
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class RawArticle:
    url: str
    title: str
    content: str
    source: str
    published_at: Optional[datetime]


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}

REMOVE_PATTERNS = [
    r'skip\s*(to\s*)?(content|navigation)', r'sign\s*(up|in)', r'subscribe',
    r'newsletter', r'advertisement', r'sponsored', r'cookie', r'privacy\s*policy',
    r'terms\s*of\s*(use|service)', r'copyright', r'all\s*rights\s*reserved',
    r'follow\s*us', r'share\s*this', r'related\s*articles', r'you\s*may\s*also',
]

# Semaphore limit for concurrent requests
MAX_CONCURRENT_REQUESTS = 10


class NewsCollector:
    async def collect(self, urls: list[str], source_map: Optional[dict[str, str]] = None) -> list[RawArticle]:
        """Fetch and parse articles concurrently with rate limiting."""
        source_map = source_map or {}
        
        # Use semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        
        async with httpx.AsyncClient(timeout=25, headers=HEADERS, follow_redirects=True) as client:
            tasks = [
                self._fetch_with_semaphore(semaphore, client, url, source_map.get(url, "Web"))
                for url in urls
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        articles = []
        seen_hashes = set()
        
        for r in results:
            if isinstance(r, RawArticle) and r.content:
                h = self.content_hash(r.content)
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    articles.append(r)
        
        logger.info(f"Collected {len(articles)}/{len(urls)} articles")
        return articles
    
    async def _fetch_with_semaphore(
        self, 
        semaphore: asyncio.Semaphore, 
        client: httpx.AsyncClient, 
        url: str, 
        source: str
    ) -> Optional[RawArticle]:
        """Wrapper that acquires semaphore before fetching."""
        async with semaphore:
            return await self._fetch(client, url, source)
    
    async def _fetch(self, client: httpx.AsyncClient, url: str, source: str) -> Optional[RawArticle]:
        """Fetch URL with retry logic and proper error handling."""
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                resp = await client.get(url)
                
                if resp.status_code == 200:
                    return self._parse(url, resp.text, source)
                elif resp.status_code == 429:
                    # Rate limited - backoff and retry
                    wait_time = 3 * (attempt + 1)
                    logger.warning(f"Rate limited on {url}, waiting {wait_time}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait_time)
                    continue  # Retry after backoff
                else:
                    logger.warning(f"HTTP {resp.status_code} for {url} (source: {source})")
                    return None
                    
            except httpx.TimeoutException as e:
                logger.warning(f"Timeout fetching {url} (attempt {attempt + 1}/{max_attempts}): {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                    
            except httpx.HTTPStatusError as e:
                logger.warning(f"HTTP error fetching {url}: {e}")
                return None
                
            except httpx.NetworkError as e:
                logger.warning(f"Network error fetching {url} (attempt {attempt + 1}/{max_attempts}): {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                    
            except Exception as e:
                logger.error(f"Unexpected error fetching {url}: {e}")
                return None
        
        logger.warning(f"Failed to fetch {url} after {max_attempts} attempts (source: {source})")
        return None
    
    def _parse(self, url: str, html: str, source: str) -> Optional[RawArticle]:
        soup = BeautifulSoup(html, "html.parser")
        
        # Get title
        title = ""
        for tag in [soup.find("h1"), soup.find("title")]:
            if tag:
                title = tag.get_text(strip=True)[:200]
                break
        
        # Try to extract publication date from meta tags
        published_at = self._extract_publish_date(soup)
        
        # Remove junk elements
        for tag in soup(["script", "style", "nav", "footer", "aside", "iframe", "noscript", "svg", "button", "form", "header"]):
            tag.decompose()
        
        # Find main content
        content_tag = soup.find("article") or soup.find("main") or soup.find(class_=re.compile(r'article|content|post', re.I))
        if not content_tag:
            content_tag = soup.body
        
        if not content_tag:
            return None
        
        # Extract and clean text
        text = content_tag.get_text(separator=" ", strip=True)
        text = self._clean(text)
        
        if len(text) < 300:
            return None
        
        from src.config import get_global_settings
        settings = get_global_settings()
        
        return RawArticle(
            url=url,
            title=title,
            content=text[:settings.max_content_length],
            source=source,
            published_at=published_at  # Use extracted date or None, not current time
        )
    
    def _extract_publish_date(self, soup: BeautifulSoup) -> Optional[datetime]:
        """Try to extract publication date from HTML meta tags."""
        # Common meta tag patterns for publication date
        date_selectors = [
            ('meta', {'property': 'article:published_time'}),
            ('meta', {'name': 'pubdate'}),
            ('meta', {'name': 'publishdate'}),
            ('meta', {'name': 'date'}),
            ('meta', {'property': 'og:published_time'}),
            ('meta', {'itemprop': 'datePublished'}),
            ('time', {'itemprop': 'datePublished'}),
            ('time', {'datetime': True}),
        ]
        
        for tag_name, attrs in date_selectors:
            tag = soup.find(tag_name, attrs)
            if tag:
                date_str = tag.get('content') or tag.get('datetime') or tag.string
                if date_str:
                    parsed = self._parse_date(date_str)
                    if parsed:
                        return parsed
        
        return None
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse various date formats to timezone-aware datetime."""
        if not date_str:
            return None
        
        date_str = date_str.strip()
        
        # Try ISO format first
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
        
        # Try common formats
        formats = [
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d',
            '%B %d, %Y',
            '%b %d, %Y',
            '%d %B %Y',
            '%d %b %Y',
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        
        return None
    
    def _clean(self, text: str) -> str:
        # Remove junk phrases
        for pattern in REMOVE_PATTERNS:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Normalize whitespace (single pass - removes all extra whitespace including newlines)
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
    
    @staticmethod
    def content_hash(content: str) -> str:
        """Generate SHA-256 hash (64 char hex) for content deduplication."""
        return hashlib.sha256(content[:5000].encode()).hexdigest()
