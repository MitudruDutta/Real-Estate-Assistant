"""Scheduler - singleton, no memory leaks"""
import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class Scheduler:
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, interval_hours: int = 1):
        if self._initialized:
            return
        self._scheduler = AsyncIOScheduler()
        self._interval = interval_hours
        self._initialized = True
    
    def start(self, pipeline_func):
        """Start scheduler with given pipeline function."""
        # Guard against starting twice
        if self._scheduler.running:
            logger.warning("Scheduler already running, updating job only")
            self._scheduler.add_job(
                pipeline_func,
                trigger=IntervalTrigger(hours=self._interval),
                id="ingestion",
                replace_existing=True,
                next_run_time=None
            )
            return
        
        self._scheduler.add_job(
            pipeline_func,
            trigger=IntervalTrigger(hours=self._interval),
            id="ingestion",
            replace_existing=True,
            next_run_time=None  # Don't run immediately
        )
        self._scheduler.start()
        logger.info(f"Scheduler started - interval: {self._interval}h")
    
    def stop(self):
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")
    
    def is_running(self) -> bool:
        return self._scheduler.running
    
    def trigger_now(self, pipeline_func):
        """Run pipeline immediately."""
        asyncio.create_task(pipeline_func())


async def run_ingestion_pipeline(vector_store, db_session_factory):
    """Main ingestion pipeline - called by scheduler."""
    from src.ingestion.sources import NewsSources
    from src.services.ingestion import IngestionService
    from src.models import Article
    
    logger.info("Starting scheduled ingestion...")
    
    sources = NewsSources()
    items = await sources.fetch_all()
    
    if not items:
        logger.info("No items from feeds")
        return
    
    db = db_session_factory()
    try:
        # Get existing URLs - run sync DB operation in thread pool
        existing = await asyncio.to_thread(
            lambda: {a[0] for a in db.query(Article.url).all()}
        )
        new_urls = [item.url for item in items if item.url not in existing]
        
        logger.info(f"New URLs: {len(new_urls)} (skipped {len(items) - len(new_urls)} existing)")
        
        if new_urls:
            service = IngestionService(vector_store)
            result = await service.process_urls(new_urls, db)
            logger.info(f"Processed: {result['processed']}, Chunks: {result['chunks']}")
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        db.rollback()
    finally:
        db.close()
