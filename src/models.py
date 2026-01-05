"""Database models - clean, indexed, production-ready"""
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, Integer, Text, ForeignKey, JSON, Index, Boolean, create_engine, event, func
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()

# Lazy settings initialization
_settings = None

def _get_settings():
    global _settings
    if _settings is None:
        from src.config import get_settings
        _settings = get_settings()
    return _settings


class Article(Base):
    __tablename__ = "articles"
    id = Column(String(36), primary_key=True)
    url = Column(String(2048), unique=True, nullable=False)
    title = Column(String(512))
    content = Column(Text)
    source = Column(String(100))
    published_at = Column(DateTime)
    content_hash = Column(String(64), unique=True)  # SHA-256 hex length
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    sentiments = relationship("Sentiment", back_populates="article", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('ix_article_source_date', 'source', 'created_at'),
    )


class Market(Base):
    __tablename__ = "markets"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    region = Column(String(50))  # e.g., "West", "South", "Midwest", "Northeast"
    
    sentiments = relationship("Sentiment", back_populates="market")
    
    __table_args__ = (
        Index('ix_market_name', 'name'),
    )


class Sentiment(Base):
    __tablename__ = "sentiments"
    id = Column(String(36), primary_key=True)
    article_id = Column(String(36), ForeignKey("articles.id", ondelete="CASCADE"), nullable=False)
    market_id = Column(Integer, ForeignKey("markets.id"), nullable=False)
    score = Column(Float, nullable=False)
    confidence = Column(Float, default=0.5)
    topics = Column(JSON, default=lambda: [])  # Fresh list per instance
    extracted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    article = relationship("Article", back_populates="sentiments")
    market = relationship("Market", back_populates="sentiments")
    
    __table_args__ = (
        Index('ix_sentiment_market_date', 'market_id', 'extracted_at'),
        Index('ix_sentiment_article', 'article_id'),
    )


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(String(36), primary_key=True)
    market_id = Column(Integer, ForeignKey("markets.id"))
    article_id = Column(String(36), ForeignKey("articles.id"), nullable=True)  # Link to triggering article
    alert_type = Column(String(50))
    severity = Column(String(20))  # low, medium, high
    message = Column(Text)
    triggered_at = Column(DateTime, server_default=func.now())
    acknowledged = Column(Boolean, default=False, nullable=False)
    
    __table_args__ = (
        Index('ix_alert_unacked', 'acknowledged', 'triggered_at'),
    )


def _get_engine():
    """Create engine with lazy settings access."""
    settings = _get_settings()
    return create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
        pool_recycle=300,
        echo=False
    )


# Lazy engine initialization
_engine = None

def get_engine():
    global _engine
    if _engine is None:
        _engine = _get_engine()
        # Enable WAL mode for better concurrency
        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
    return _engine


# For backward compatibility
@property
def engine():
    return get_engine()


def get_session_local():
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


# Lazy SessionLocal
_SessionLocal = None

def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = get_session_local()
    return _SessionLocal


# Backward compatibility - SessionLocal is now a function call
# Use get_session_factory() for new code
def SessionLocal():
    """Backward compatibility wrapper. Use get_session_factory() for new code."""
    return get_session_factory()()


def init_db():
    Base.metadata.create_all(get_engine())


def get_db():
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
