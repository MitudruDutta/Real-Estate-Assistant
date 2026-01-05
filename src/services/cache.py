"""LLM cache - file-based with TTL and concurrency control"""
import hashlib
import json
import time
import logging
import threading
import fcntl
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy initialization of cache directory
_cache_dir: Optional[Path] = None
_cache_lock = threading.Lock()


def _get_cache_dir() -> Path:
    """Get cache directory with lazy initialization."""
    global _cache_dir
    if _cache_dir is None:
        from src.config import get_global_settings
        settings = get_global_settings()
        _cache_dir = Path(settings.cache_dir)
        _cache_dir.mkdir(parents=True, exist_ok=True)
    return _cache_dir


def _get_key(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:24]


def get_cached(content: str) -> Optional[list[dict]]:
    """Get cached result for content, with proper error handling."""
    key = _get_key(content)
    cache_file = _get_cache_dir() / f"{key}.json"
    
    if not cache_file.exists():
        return None
    
    try:
        data = json.loads(cache_file.read_text())
        age_days = (time.time() - data.get("ts", 0)) / 86400
        
        from src.config import get_global_settings
        settings = get_global_settings()
        
        if age_days < settings.cache_ttl_days:
            return data.get("result")
        
        # Cache expired, remove it
        try:
            cache_file.unlink()
        except OSError as e:
            logger.warning(f"Failed to remove expired cache file {cache_file}: {e}")
            
    except json.JSONDecodeError as e:
        logger.warning(f"Malformed JSON in cache file {cache_file}: {e}")
        try:
            cache_file.unlink()
        except OSError:
            pass
    except OSError as e:
        logger.warning(f"Failed to read cache file {cache_file}: {e}")
    except PermissionError as e:
        logger.warning(f"Permission denied accessing cache file {cache_file}: {e}")
    
    return None


def set_cached(content: str, result: list[dict]):
    """Cache result with file-based locking for concurrency safety."""
    key = _get_key(content)
    cache_file = _get_cache_dir() / f"{key}.json"
    
    with _cache_lock:
        try:
            _cleanup_old()
            
            # Write with file locking for process safety
            with open(cache_file, 'w') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump({"ts": time.time(), "result": result}, f)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    
        except OSError as e:
            logger.warning(f"Failed to write cache file {cache_file}: {e}")
        except PermissionError as e:
            logger.warning(f"Permission denied writing cache file {cache_file}: {e}")


def _cleanup_old():
    """
    Remove oldest files if over limit.
    Uses internal JSON timestamp for ordering, falls back to mtime.
    Must be called with _cache_lock held.
    """
    from src.config import get_global_settings
    settings = get_global_settings()
    cache_dir = _get_cache_dir()
    
    try:
        files = list(cache_dir.glob("*.json"))
        
        if len(files) <= settings.max_cache_files:
            return
        
        # Build list of (path, timestamp) pairs using internal JSON timestamp
        file_timestamps = []
        for f in files:
            ts = None
            try:
                with open(f, 'r') as fp:
                    fcntl.flock(fp.fileno(), fcntl.LOCK_SH)
                    try:
                        data = json.load(fp)
                        ts = data.get("ts")
                    finally:
                        fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
            except (json.JSONDecodeError, OSError, PermissionError) as e:
                logger.debug(f"Could not read timestamp from {f}, using mtime: {e}")
            
            # Fallback to filesystem mtime if JSON parse fails
            if ts is None:
                try:
                    ts = f.stat().st_mtime
                except OSError:
                    ts = 0
            
            file_timestamps.append((f, ts))
        
        # Sort by timestamp (oldest first)
        file_timestamps.sort(key=lambda x: x[1])
        
        # Delete oldest entries beyond limit
        files_to_delete = len(file_timestamps) - settings.max_cache_files
        for f, _ in file_timestamps[:files_to_delete]:
            try:
                f.unlink()
                logger.debug(f"Cleaned up old cache file: {f}")
            except OSError as e:
                logger.warning(f"Failed to delete cache file {f}: {e}")
            except PermissionError as e:
                logger.warning(f"Permission denied deleting cache file {f}: {e}")
                
    except OSError as e:
        logger.warning(f"Failed to list cache directory for cleanup: {e}")
