"""Configuration - single source of truth"""
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache
from typing import Optional

class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    Note: groq_api_key and other required env vars must be present before first access.
    For tests, override environment variables before calling get_settings().
    """
    # API Keys
    groq_api_key: str
    groq_model: str = "llama-3.1-8b-instant"
    newsapi_key: Optional[str] = None
    
    # Database - will be derived from data_dir in model_post_init
    database_url: str = ""
    
    # Paths
    data_dir: Path = Path(__file__).parent.parent / "data"
    chroma_dir: str = ""
    cache_dir: str = ""
    
    # Models
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    
    # Limits
    max_articles_per_feed: int = 15
    max_content_length: int = 12000
    chunk_size: int = 500
    chunk_overlap: int = 100
    cache_ttl_days: int = 7
    max_cache_files: int = 500
    
    # Rate limiting
    requests_per_minute: int = 30
    
    # CORS - configurable allowed origins
    allowed_origins: list[str] = ["http://localhost:8501", "http://localhost:3000"]
    
    # US Markets only - strict whitelist
    valid_markets: list[str] = [
        "National", "New York", "Los Angeles", "Chicago", "Houston", "Phoenix",
        "Philadelphia", "San Antonio", "San Diego", "Dallas", "San Jose",
        "Austin", "Jacksonville", "Fort Worth", "Columbus", "Charlotte",
        "San Francisco", "Indianapolis", "Seattle", "Denver", "Boston",
        "Nashville", "Detroit", "Portland", "Las Vegas", "Memphis",
        "Louisville", "Baltimore", "Milwaukee", "Albuquerque", "Tucson",
        "Fresno", "Sacramento", "Atlanta", "Miami", "Tampa", "Orlando",
        "Cleveland", "Raleigh", "Minneapolis", "St. Louis", "Pittsburgh"
    ]
    
    class Config:
        env_file = ".env"
    
    @model_validator(mode='after')
    def validate_chunk_settings(self) -> 'Settings':
        """Ensure chunk_overlap is strictly less than chunk_size."""
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be strictly less than "
                f"chunk_size ({self.chunk_size})"
            )
        return self
    
    def model_post_init(self, __context):
        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Set derived paths
        self.chroma_dir = str(self.data_dir / "chroma")
        self.cache_dir = str(self.data_dir / "cache")
        
        # Create both directories
        Path(self.chroma_dir).mkdir(parents=True, exist_ok=True)
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
        
        # Derive database_url from data_dir so DB lives alongside other data files
        db_path = self.data_dir / "sentiment.db"
        self.database_url = f"sqlite:///{db_path}"


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    
    Note: groq_api_key and other required env vars must be present before first access.
    For tests, override environment variables before calling this function.
    """
    return Settings()


# Lazy settings initialization - don't instantiate at import time
_settings = None

def get_global_settings() -> Settings:
    """
    Get global settings with lazy initialization.
    
    This avoids raising errors at import time if required env vars are missing,
    allowing tests to override environment safely before first access.
    """
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings
