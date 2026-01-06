"""FastAPI application"""
from dotenv import load_dotenv
load_dotenv()

import re
import time
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

from src.models import init_db, get_db, Article, Market, Sentiment, Alert, SessionLocal
from src.config import get_settings
from src.services.ingestion import IngestionService
from src.storage.vector_store import VectorStore
from src.analysis.trends import get_market_trend, get_sentiment_history, get_all_market_trends
from src.scheduler import Scheduler, run_ingestion_pipeline

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Simple rate limiting
_rate_limits = defaultdict(list)

class AppState:
    vector_store: VectorStore | None = None
    scheduler: Scheduler | None = None

state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    state.vector_store = VectorStore()
    state.scheduler = Scheduler(interval_hours=1)
    
    async def pipeline():
        await run_ingestion_pipeline(state.vector_store, SessionLocal)
    
    state.scheduler.start(pipeline)
    logger.info("Application started")
    yield
    if state.scheduler:
        state.scheduler.stop()

app = FastAPI(title="Real Estate Sentiment API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
            raise ValueError('No valid URLs')
        return valid

class QueryRequest(BaseModel):
    question: str
    
    @field_validator('question')
    @classmethod
    def validate_question(cls, v):
        v = v.strip()
        if len(v) < 5 or len(v) > 500:
            raise ValueError('Question must be 5-500 chars')
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
        "alerts": db.query(Alert).filter(Alert.acknowledged == 0).count(),
        "chunks": state.vector_store.count() if state.vector_store else 0
    }

@app.get("/api/markets")
def list_markets(db: Session = Depends(get_db)):
    return get_all_market_trends(db, days=30)

@app.get("/api/markets/{market_name}/trend")
def market_trend(market_name: str, days: int = 30, db: Session = Depends(get_db)):
    return get_market_trend(db, market_name, min(days, 365))

@app.get("/api/markets/{market_name}/history")
def market_history(market_name: str, days: int = 90, db: Session = Depends(get_db)):
    return get_sentiment_history(db, market_name, min(days, 365))

@app.get("/api/articles")
def list_articles(limit: int = 20, db: Session = Depends(get_db)):
    articles = db.query(Article).order_by(Article.created_at.desc()).limit(min(limit, 100)).all()
    return [
        {"id": a.id, "title": a.title, "url": a.url, "source": a.source, 
         "created_at": a.created_at.isoformat() if a.created_at else None}
        for a in articles
    ]

@app.get("/api/alerts")
def list_alerts(db: Session = Depends(get_db)):
    alerts = db.query(Alert).filter(Alert.acknowledged == 0).order_by(Alert.triggered_at.desc()).limit(50).all()
    return [
        {"id": a.id, "type": a.alert_type, "severity": a.severity, "message": a.message,
         "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None}
        for a in alerts
    ]

@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.acknowledged = 1
    db.commit()
    return {"status": "acknowledged"}

@app.post("/api/ingest")
async def ingest_urls(req: UrlsRequest, db: Session = Depends(get_db)):
    if not state.vector_store:
        raise HTTPException(503, "Service not ready")
    service = IngestionService(state.vector_store)
    return await service.process_urls(req.urls, db)

@app.post("/api/ingest/auto")
async def trigger_auto_ingest(background_tasks: BackgroundTasks):
    if not state.vector_store:
        raise HTTPException(503, "Service not ready")
    
    async def run():
        await run_ingestion_pipeline(state.vector_store, SessionLocal)
    
    background_tasks.add_task(run)
    return {"status": "started"}

@app.post("/api/query")
async def query_articles(req: QueryRequest):
    settings = get_settings()
    if not state.vector_store:
        return {"answer": "Service not ready", "sources": [], "error": True}
    
    try:
        docs = state.vector_store.search(req.question, k=5)
        if not docs:
            return {"answer": "No relevant articles found. Try ingesting news first.", "sources": []}
        
        context = "\n\n".join([f"[{d['title']}]\n{d['content']}" for d in docs])
        
        client = AsyncGroq(api_key=settings.groq_api_key)
        response = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": "You are a real estate analyst. Answer using ONLY the provided context. Be specific."},
                {"role": "user", "content": f"Articles:\n{context}\n\nQuestion: {req.question}"}
            ],
            temperature=0.2,
            max_tokens=600
        )
        
        sources = list(set(d["url"] for d in docs if d.get("url")))
        return {"answer": response.choices[0].message.content, "sources": sources}
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return {"answer": f"Error: {str(e)}", "sources": [], "error": True}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
