"""FastAPI application - clean, rate-limited, production-ready"""
from dotenv import load_dotenv
load_dotenv()

import os
import re
import time
import asyncio
import logging
from functools import wraps
from contextlib import asynccontextmanager
from collections import defaultdict

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from groq import AsyncGroq

from src.models import init_db, get_db, Article, Market, Sentiment, Alert, get_session_factory
from src.config import get_global_settings
from src.services.ingestion import IngestionService
from src.storage.vector_store import VectorStore
from src.analysis.trends import get_market_trend, get_sentiment_history, get_all_market_trends
from src.scheduler import Scheduler, run_ingestion_pipeline

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Rate limiting - per-client tracking
request_counts = defaultdict(list)


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, considering proxies."""
    # Check X-Forwarded-For header first (for proxied requests)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the first IP in the chain (original client)
        return forwarded.split(",")[0].strip()
    
    # Fall back to direct client IP
    if request.client:
        return request.client.host
    
    return "unknown"


def rate_limit(requests_per_minute: int = 30):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, request: Request = None, **kwargs):
            # Extract request from args if not in kwargs
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            
            if request is None:
                # Try to get from kwargs
                request = kwargs.get('request')
            
            # Get per-client key
            client_id = _get_client_ip(request) if request else "unknown"
            
            now = time.time()
            
            # Clean old entries
            request_counts[client_id] = [t for t in request_counts[client_id] if now - t < 60]
            
            if len(request_counts[client_id]) >= requests_per_minute:
                raise HTTPException(429, "Rate limit exceeded")
            
            request_counts[client_id].append(now)
            return await func(*args, **kwargs)
        return wrapper
    return decorator


# App state
class AppState:
    vector_store: VectorStore | None = None
    scheduler: Scheduler | None = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    state.vector_store = VectorStore()
    state.scheduler = Scheduler(interval_hours=1)
    
    # Create pipeline function with dependencies
    async def pipeline():
        await run_ingestion_pipeline(state.vector_store, get_session_factory())
    
    state.scheduler.start(pipeline)
    logger.info("Application started")
    yield
    if state.scheduler:
        state.scheduler.stop()
    logger.info("Application stopped")


app = FastAPI(
    title="Real Estate Sentiment API",
    version="2.0.0",
    lifespan=lifespan
)

# Get allowed origins from config
settings = get_global_settings()
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "").split(",") if os.environ.get("ALLOWED_ORIGINS") else settings.allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request models
URL_PATTERN = re.compile(r'^https?://[^\s/$.?#].[^\s]*$', re.IGNORECASE)


class UrlsRequest(BaseModel):
    urls: list[str]
    
    @field_validator('urls')
    @classmethod
    def validate_urls(cls, v):
        valid = [url.strip() for url in v if URL_PATTERN.match(url.strip())][:20]
        if not valid:
            raise ValueError('No valid URLs provided')
        return valid


class QueryRequest(BaseModel):
    question: str
    
    @field_validator('question')
    @classmethod
    def validate_question(cls, v):
        v = v.strip()
        if len(v) < 5:
            raise ValueError('Question too short')
        if len(v) > 500:
            raise ValueError('Question too long')
        return v


# Endpoints
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "scheduler": "running" if state.scheduler and state.scheduler.is_running() else "stopped",
        "chunks": state.vector_store.count() if state.vector_store else 0
    }


@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    return {
        "articles": db.query(Article).count(),
        "markets": db.query(Market).count(),
        "sentiments": db.query(Sentiment).count(),
        "alerts": db.query(Alert).filter(Alert.acknowledged == False).count(),
        "chunks": state.vector_store.count() if state.vector_store else 0
    }


@app.get("/api/markets")
def list_markets(db: Session = Depends(get_db)):
    """Get all markets with their trends - single query."""
    return get_all_market_trends(db, days=30)


@app.get("/api/markets/{market_name}/trend")
def market_trend(market_name: str, days: int = 30, db: Session = Depends(get_db)):
    if days > 365:
        days = 365
    return get_market_trend(db, market_name, days)


@app.get("/api/markets/{market_name}/history")
def market_history(market_name: str, days: int = 90, db: Session = Depends(get_db)):
    if days > 365:
        days = 365
    return get_sentiment_history(db, market_name, days)


@app.get("/api/articles")
def list_articles(limit: int = 20, source: str = None, db: Session = Depends(get_db)):
    query = db.query(Article).order_by(Article.created_at.desc())
    if source:
        query = query.filter(Article.source == source)
    articles = query.limit(min(limit, 100)).all()
    return [
        {
            "id": a.id,
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "created_at": a.created_at.isoformat() if a.created_at else None
        }
        for a in articles
    ]


@app.get("/api/alerts")
def list_alerts(db: Session = Depends(get_db)):
    alerts = db.query(Alert).filter(Alert.acknowledged == False).order_by(Alert.triggered_at.desc()).limit(50).all()
    return [
        {
            "id": a.id,
            "type": a.alert_type,
            "severity": a.severity,
            "message": a.message,
            "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None
        }
        for a in alerts
    ]


@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, db: Session = Depends(get_db)):
    """Acknowledge an alert. Note: Add authentication in production."""
    # TODO: Add authentication - e.g., Depends(get_current_user)
    # and verify user has permission to acknowledge this alert
    
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(404, "Alert not found")
    
    alert.acknowledged = True
    db.commit()
    return {"status": "acknowledged"}


@app.post("/api/ingest")
async def ingest_urls(req: UrlsRequest, db: Session = Depends(get_db)):
    if not state.vector_store:
        raise HTTPException(503, "Service not ready")
    
    service = IngestionService(state.vector_store)
    result = await service.process_urls(req.urls, db)
    return result


@app.post("/api/ingest/auto")
async def trigger_auto_ingest(background_tasks: BackgroundTasks):
    if not state.vector_store:
        raise HTTPException(503, "Service not ready")
    
    async def run():
        await run_ingestion_pipeline(state.vector_store, get_session_factory())
    
    background_tasks.add_task(run)
    return {"status": "started"}


# LLM query timeout in seconds
LLM_TIMEOUT_SECONDS = 30


@app.post("/api/query")
@rate_limit(requests_per_minute=20)
async def query_articles(req: QueryRequest, request: Request):
    """Query articles using RAG."""
    if not state.vector_store:
        raise HTTPException(503, "Vector store not initialized")
    
    try:
        # Search vector store
        docs = state.vector_store.search(req.question, k=5)
        if not docs:
            return {"answer": "No relevant articles found. Try ingesting some news first.", "sources": []}
        
        # Build context
        context = "\n\n".join([
            f"[{d['title']}] (relevance: {d['relevance']})\n{d['content']}"
            for d in docs
        ])
        
        settings = get_global_settings()
        
        # Query LLM with timeout
        client = AsyncGroq(api_key=settings.groq_api_key)
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=settings.groq_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a real estate market analyst. Answer questions using ONLY the provided article excerpts. Be specific and cite which articles support your answer. If the context doesn't contain relevant information, say so."
                        },
                        {
                            "role": "user",
                            "content": f"Articles:\n{context}\n\nQuestion: {req.question}"
                        }
                    ],
                    temperature=0.2,
                    max_tokens=600
                ),
                timeout=LLM_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.error(f"LLM query timed out after {LLM_TIMEOUT_SECONDS}s")
            raise HTTPException(503, "Query timed out. Please try again.")
        
        # Validate response structure
        if not response.choices or not response.choices[0].message:
            logger.error("Malformed LLM response: missing choices or message")
            raise HTTPException(502, "Invalid response from language model")
        
        answer = response.choices[0].message.content
        if not answer:
            logger.error("Malformed LLM response: empty content")
            raise HTTPException(502, "Empty response from language model")
        
        sources = list(set(d["url"] for d in docs if d.get("url")))
        return {
            "answer": answer,
            "sources": sources,
            "relevance_scores": [d["relevance"] for d in docs]
        }
        
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        logger.exception(f"Query failed: {e}")
        raise HTTPException(500, "An error occurred processing your query")


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )
