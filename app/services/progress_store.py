import time
from typing import Optional, Dict

# In-memory progress tracking for active downloads
# Key: download_id, Value: progress data dict
_store: Dict[str, dict] = {}

# Auto-cleanup threshold (seconds)
_MAX_AGE = 3600  # 1 hour


def update(download_id: str, data: dict):
    """Update progress for a download."""
    if download_id not in _store:
        _store[download_id] = {"created_at": time.time()}
    _store[download_id].update(data)
    _store[download_id]["updated_at"] = time.time()


def get(download_id: str) -> Optional[dict]:
    """Get progress for a download."""
    _cleanup()
    return _store.get(download_id)


def cancel(download_id: str):
    """Mark a download as cancelled."""
    if download_id in _store:
        _store[download_id]["cancelled"] = True
    else:
        _store[download_id] = {"cancelled": True, "created_at": time.time()}


def is_cancelled(download_id: str) -> bool:
    """Check if a download has been cancelled."""
    data = _store.get(download_id)
    return bool(data and data.get("cancelled"))


def remove(download_id: str):
    """Remove a download from the store."""
    _store.pop(download_id, None)


def _cleanup():
    """Remove entries older than _MAX_AGE."""
    now = time.time()
    expired = [
        did for did, data in _store.items()
        if now - data.get("created_at", now) > _MAX_AGE
    ]
    for did in expired:
        del _store[did]
