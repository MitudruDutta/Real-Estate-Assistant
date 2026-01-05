"""Ingestion service - orchestrates the pipeline"""
import logging
from uuid import uuid4
from sqlalchemy.orm import Session
from src.models import Article, Market, Sentiment, Alert
from src.ingestion.collector import NewsCollector
from src.extraction.sentiment import SentimentExtractor
from src.analysis.trends import detect_anomaly

logger = logging.getLogger(__name__)

# Region mapping as class-level constant
REGION_MAP = {
    "Northeast": ["New York", "Boston", "Philadelphia", "Pittsburgh", "Baltimore"],
    "Southeast": ["Miami", "Atlanta", "Tampa", "Orlando", "Charlotte", "Nashville", "Jacksonville", "Raleigh"],
    "Midwest": ["Chicago", "Detroit", "Cleveland", "Columbus", "Indianapolis", "Milwaukee", "Minneapolis", "St. Louis"],
    "Southwest": ["Phoenix", "Dallas", "Houston", "San Antonio", "Austin", "Fort Worth", "Albuquerque", "Tucson"],
    "West": ["Los Angeles", "San Francisco", "San Diego", "San Jose", "Seattle", "Portland", "Denver", "Las Vegas", "Sacramento", "Fresno"],
}


def _safe_float(value, default: float) -> float:
    """Safely convert value to float, returning default on failure."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


class IngestionService:
    REGION_MAP = REGION_MAP  # Class-level constant
    
    def __init__(self, vector_store):
        self.collector = NewsCollector()
        self.extractor = SentimentExtractor()
        self.vector_store = vector_store
        from src.config import get_global_settings
        self.valid_markets = set(get_global_settings().valid_markets)
    
    async def process_urls(self, urls: list[str], db: Session) -> dict:
        """Process URLs end-to-end."""
        # Pass empty source_map to collector which will populate it
        source_map = {}
        
        # Collect articles
        articles = await self.collector.collect(urls, source_map)
        if not articles:
            return {"processed": 0, "skipped": len(urls), "chunks": 0}
        
        processed = 0
        total_chunks = 0
        
        for raw in articles:
            try:
                # Check for duplicates
                content_hash = self.collector.content_hash(raw.content)
                exists = db.query(Article).filter(
                    (Article.url == raw.url) | (Article.content_hash == content_hash)
                ).first()
                
                if exists:
                    continue
                
                # Create article
                article = Article(
                    id=str(uuid4()),
                    url=raw.url,
                    title=raw.title,
                    content=raw.content,
                    source=raw.source,
                    published_at=raw.published_at,
                    content_hash=content_hash
                )
                db.add(article)
                db.flush()
                
                # Add to vector store
                chunks = self.vector_store.add(
                    raw.content,
                    {"url": raw.url, "title": raw.title, "article_id": article.id},
                    article.id
                )
                total_chunks += chunks
                
                # Extract sentiment
                extractions = await self.extractor.extract(raw.content)
                
                # Track markets checked for anomaly detection (once per market per article)
                checked_markets = set()
                
                for ext in extractions:
                    market_name = ext.get("market", "National")
                    
                    # Skip invalid markets
                    if market_name not in self.valid_markets:
                        continue
                    
                    market = self._get_or_create_market(db, market_name)
                    
                    # Safe float conversion with clamping
                    sentiment_val = _safe_float(ext.get("sentiment", 0), 0.0)
                    sentiment_val = max(-1.0, min(1.0, sentiment_val))
                    
                    confidence_val = _safe_float(ext.get("confidence", 0.5), 0.5)
                    confidence_val = max(0.0, min(1.0, confidence_val))
                    
                    db.add(Sentiment(
                        id=str(uuid4()),
                        article_id=article.id,
                        market_id=market.id,
                        score=sentiment_val,
                        confidence=confidence_val,
                        topics=ext.get("topics", [])
                    ))
                    
                    # Check for anomaly - only once per market per article
                    if market_name not in checked_markets:
                        checked_markets.add(market_name)
                        if detect_anomaly(db, market_name):
                            db.add(Alert(
                                id=str(uuid4()),
                                market_id=market.id,
                                article_id=article.id,  # Link to triggering article
                                alert_type="sentiment_shift",
                                severity="high",
                                message=f"Unusual sentiment shift detected in {market_name}"
                            ))
                
                db.commit()
                processed += 1
                logger.info(f"Processed: {raw.title[:60]}...")
                
            except Exception as e:
                logger.error(f"Failed to process {raw.url}: {e}")
                db.rollback()
        
        return {"processed": processed, "skipped": len(urls) - processed, "chunks": total_chunks}
    
    def _get_or_create_market(self, db: Session, name: str) -> Market:
        market = db.query(Market).filter(Market.name == name).first()
        if not market:
            # Assign region based on city
            region = self._get_region(name)
            market = Market(name=name, region=region)
            db.add(market)
            db.flush()
        return market
    
    def _get_region(self, market: str) -> str:
        """Map market to US region using class-level constant."""
        for region, cities in self.REGION_MAP.items():
            if market in cities:
                return region
        return "National"
