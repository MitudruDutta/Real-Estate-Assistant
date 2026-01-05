"""Trend analysis and anomaly detection"""
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.models import Sentiment, Market


def get_market_trend(db: Session, market_name: str, days: int = 30) -> dict:
    """Get sentiment trend for a market."""
    market = db.query(Market).filter(Market.name == market_name).first()
    if not market:
        return {
            "market": market_name,
            "avg_sentiment": 0,
            "sentiment_change": 0,
            "article_count": 0,
            "confidence": 0,
            "top_topics": [],
            "region": None
        }
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    prev_cutoff = cutoff - timedelta(days=days)
    
    # Current period stats
    current = db.query(
        func.avg(Sentiment.score),
        func.avg(Sentiment.confidence),
        func.count(Sentiment.id)
    ).filter(
        Sentiment.market_id == market.id,
        Sentiment.extracted_at >= cutoff
    ).first()
    
    # Previous period for comparison
    prev_avg = db.query(func.avg(Sentiment.score)).filter(
        Sentiment.market_id == market.id,
        Sentiment.extracted_at >= prev_cutoff,
        Sentiment.extracted_at < cutoff
    ).scalar()
    
    # Top topics
    sentiments = db.query(Sentiment.topics).filter(
        Sentiment.market_id == market.id,
        Sentiment.extracted_at >= cutoff
    ).all()
    
    topic_counts = {}
    for s in sentiments:
        if s.topics:
            for t in s.topics:
                topic_counts[t] = topic_counts.get(t, 0) + 1
    
    top_topics = sorted(topic_counts.keys(), key=lambda x: topic_counts[x], reverse=True)[:5]
    
    avg_sentiment = current[0] or 0
    avg_confidence = current[1] or 0
    
    return {
        "market": market_name,
        "region": market.region,
        "avg_sentiment": round(avg_sentiment, 3),
        "sentiment_change": round(avg_sentiment - (prev_avg or 0), 3),
        "article_count": current[2],
        "confidence": round(avg_confidence, 2),
        "top_topics": top_topics
    }


def get_sentiment_history(db: Session, market_name: str, days: int = 90) -> list[dict]:
    """Get daily sentiment history."""
    market = db.query(Market).filter(Market.name == market_name).first()
    if not market:
        return []
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    results = db.query(
        func.date(Sentiment.extracted_at).label("date"),
        func.avg(Sentiment.score).label("sentiment"),
        func.count(Sentiment.id).label("count")
    ).filter(
        Sentiment.market_id == market.id,
        Sentiment.extracted_at >= cutoff
    ).group_by(
        func.date(Sentiment.extracted_at)
    ).order_by("date").all()
    
    return [
        {"date": str(r.date), "sentiment": round(r.sentiment, 3), "articles": r.count}
        for r in results
    ]


def get_all_market_trends(db: Session, days: int = 30) -> list[dict]:
    """Get trends for all markets in one query - fixes N+1 problem."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    results = db.query(
        Market.name,
        Market.region,
        func.avg(Sentiment.score).label("avg_sentiment"),
        func.avg(Sentiment.confidence).label("avg_confidence"),
        func.count(Sentiment.id).label("article_count")
    ).join(Sentiment).filter(
        Sentiment.extracted_at >= cutoff
    ).group_by(Market.id).order_by(func.avg(Sentiment.score).desc()).all()
    
    return [
        {
            "market": r.name,
            "region": r.region,
            "avg_sentiment": round(r.avg_sentiment or 0, 3),
            "confidence": round(r.avg_confidence or 0, 2),
            "article_count": r.article_count
        }
        for r in results
    ]


def detect_anomaly(db: Session, market_name: str) -> bool:
    """Detect if recent sentiment is anomalous using z-score."""
    market = db.query(Market).filter(Market.name == market_name).first()
    if not market:
        return False
    
    # Get last 30 days of scores
    cutoff_30 = datetime.now(timezone.utc) - timedelta(days=30)
    cutoff_3 = datetime.now(timezone.utc) - timedelta(days=3)
    
    scores = [s[0] for s in db.query(Sentiment.score).filter(
        Sentiment.market_id == market.id,
        Sentiment.extracted_at >= cutoff_30
    ).all()]
    
    if len(scores) < 5:
        return False
    
    # Calculate stats
    mean = sum(scores) / len(scores)
    variance = sum((x - mean) ** 2 for x in scores) / len(scores)
    stddev = max(variance ** 0.5, 0.1)
    
    # Recent average
    recent = db.query(func.avg(Sentiment.score)).filter(
        Sentiment.market_id == market.id,
        Sentiment.extracted_at >= cutoff_3
    ).scalar()
    
    if recent is None:
        return False
    
    z_score = abs((recent - mean) / stddev)
    return z_score > 2.0
