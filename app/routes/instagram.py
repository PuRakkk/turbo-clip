import uuid
import json
import asyncio
import logging
import threading
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session
from app.settings.database import get_db, SessionLocal
from app.models.schemas import DownloadRequest, BatchDownloadRequest, InstagramInfoRequest, CarouselDownloadRequest
from app.models.models import DownloadHistory, User
from app.services.auth_service import AuthService
from app.services.instagram_service import InstagramService
from app.services import progress_store
from app.routes.user import trim_user_history

logger = logging.getLogger("turboclip.instagram.routes")
router = APIRouter()
auth_service = AuthService()
instagram_service = InstagramService()
limiter = Limiter(key_func=get_remote_address)


def _check_premium(db: Session, user_id: str):
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_premium:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Premium subscription required."
        )


def _get_user_instagram_cookie(db: Session, user_id: str) -> str:
    """Return the user's Instagram cookie string, or empty string."""
    user = db.query(User).filter(User.id == user_id).first()
    return (user.instagram_cookie or '') if user else ''


def _get_user_download_dir(db: Session, user_id: str) -> str:
    """Return the user's custom download path if set, otherwise the default."""
    import os
    from app.settings.config import settings
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.download_path and os.path.isabs(user.download_path):
        os.makedirs(user.download_path, exist_ok=True)
        return user.download_path
    return settings.DOWNLOAD_DIR


def _instagram_error_hint(error: str) -> str:
    """Translate Instagram-specific errors into user-friendly messages."""
    err_lower = str(error).lower()
    if 'login' in err_lower or 'authentication' in err_lower:
        return (
            "Instagram requires authentication for this content. "
            "Please add your Instagram cookie in Settings."
        )
    if 'private' in err_lower:
        return (
            "This content appears to be private. "
            "Please check the URL or add your Instagram cookie in Settings."
        )
    if 'not found' in err_lower or '404' in err_lower:
        return "Content not found. The post may have been deleted or the URL is invalid."
    return str(error)


def _cleanup_files_by_id(download_dir: str, download_id: str):
    """Remove all files belonging to a download_id from disk."""
    import os
    if not download_dir or not os.path.isdir(download_dir):
        return
    for f in os.listdir(download_dir):
        if f.startswith(download_id):
            path = os.path.join(download_dir, f)
            try:
                os.remove(path)
                logger.info("Cleanup: removed %s", f)
            except OSError:
                pass


def _cleanup_cancelled(download_dir, db, completed_ids=None, start_time=None):
    """Clean up files after a cancelled or failed download."""
    import os
    import re
    import time as _time

    if not download_dir or not os.path.isdir(download_dir):
        return

    if completed_ids:
        for dl_id in completed_ids:
            _cleanup_files_by_id(download_dir, dl_id)
            try:
                db.query(DownloadHistory).filter(DownloadHistory.id == dl_id).delete()
            except Exception:
                pass
        try:
            db.commit()
        except Exception:
            db.rollback()

    if start_time:
        uuid_re = re.compile(
            r'^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'
        )
        for f in os.listdir(download_dir):
            m = uuid_re.match(f)
            if not m:
                continue
            path = os.path.join(download_dir, f)
            if not os.path.isfile(path):
                continue
            try:
                if os.path.getmtime(path) < start_time:
                    continue
            except OSError:
                continue
            file_id = m.group(1)
            if not db.query(DownloadHistory).filter(DownloadHistory.id == file_id).first():
                try:
                    os.remove(path)
                    logger.info("Cleanup orphan: %s", f)
                except OSError:
                    pass


# --- Smart unified info endpoint ---

@router.post("/info")
@limiter.limit("30/minute")
def get_instagram_info(
    request: Request,
    body: InstagramInfoRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    url = str(body.url)
    user_cookie = _get_user_instagram_cookie(db, user_id)
    try:
        if instagram_service.is_profile_url(url):
            result = instagram_service.get_profile_posts(
                url, limit=body.limit, offset=body.offset, user_cookie=user_cookie
            )
            posts = result["posts"]
            return {
                "type": "profile",
                "videos": posts,
                "count": len(posts),
                "has_more": result["has_more"],
                "offset": body.offset,
            }
        else:
            info = instagram_service.get_post_info(url, user_cookie=user_cookie)
            if info.get('is_carousel'):
                info_type = "carousel"
            elif info.get('media_type') == 'image':
                info_type = "image"
            else:
                info_type = "video"
            return {"type": info_type, "info": info}
    except Exception as e:
        err_str = str(e).lower()
        if 'rate limit' in err_str or '429' in err_str or 'too many' in err_str:
            logger.warning("Instagram rate limited: %s", e)
            raise HTTPException(status_code=429, detail=str(e))
        if 'authentication' in err_str or 'login' in err_str:
            logger.warning("Instagram auth required: %s", e)
            raise HTTPException(status_code=403, detail=str(e))
        logger.error("get_instagram_info failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_instagram_error_hint(str(e)),
        )


# --- Progress callbacks ---

def _make_instagram_progress_callback(download_id: str):
    def callback(d):
        if progress_store.is_cancelled(download_id):
            raise Exception("Download cancelled by user")
        status_val = d.get("status", "")
        if status_val == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            pct = (downloaded / total * 95) if total > 0 else 0
            progress_store.update(download_id, {
                "status": "downloading",
                "progress": round(pct, 1),
                "speed": d.get("speed"),
                "eta": d.get("eta"),
                "phase": "downloading",
            })
        elif status_val == "finished":
            progress_store.update(download_id, {
                "status": "downloading",
                "progress": 95,
                "phase": "finalizing",
                "speed": None,
                "eta": None,
            })
    return callback


# --- Background download functions ---

def _run_instagram_video_download(download_id: str, url: str, user_id: str):
    import time as _time
    db = SessionLocal()
    user_dir = _get_user_download_dir(db, user_id)
    user_cookie = _get_user_instagram_cookie(db, user_id)
    t_start = _time.time()
    try:
        progress_store.update(download_id, {
            "status": "downloading", "progress": 0, "phase": "starting",
            "speed": None, "eta": None,
        })

        callback = _make_instagram_progress_callback(download_id)
        result = instagram_service.download_video(
            url=url, progress_callback=callback, download_dir=user_dir,
            user_cookie=user_cookie,
        )

        history = DownloadHistory(
            id=result['download_id'], user_id=user_id,
            video_url=url, video_title=result['title'],
            video_id=result['video_id'], format='mp4',
            quality='best', file_path=result['file_path'],
            file_size=result['file_size'], duration=result['duration'],
        )
        db.add(history)
        db.commit()
        trim_user_history(db, user_id)

        progress_store.update(download_id, {
            "status": "done", "progress": 100, "phase": "done",
            "title": result['title'], "download_id": result['download_id'],
        })
    except Exception as e:
        logger.error("Instagram download failed: id=%s error=%s", download_id, e)
        progress_store.update(download_id, {
            "status": "error", "progress": 0, "phase": "error",
            "error": _instagram_error_hint(str(e)),
        })
        _cleanup_cancelled(user_dir, db, start_time=t_start)
    finally:
        db.close()


def _run_instagram_audio_download(download_id: str, url: str, user_id: str):
    import time as _time
    db = SessionLocal()
    user_dir = _get_user_download_dir(db, user_id)
    user_cookie = _get_user_instagram_cookie(db, user_id)
    t_start = _time.time()
    try:
        progress_store.update(download_id, {
            "status": "downloading", "progress": 0, "phase": "starting",
            "speed": None, "eta": None,
        })

        def audio_callback(d):
            if progress_store.is_cancelled(download_id):
                raise Exception("Download cancelled by user")
            status_val = d.get("status", "")
            if status_val == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes", 0)
                pct = (downloaded / total * 90) if total > 0 else 0
                progress_store.update(download_id, {
                    "status": "downloading", "progress": round(pct, 1),
                    "phase": "downloading_audio", "speed": d.get("speed"), "eta": d.get("eta"),
                })
            elif status_val == "finished":
                progress_store.update(download_id, {
                    "status": "downloading", "progress": 90,
                    "phase": "converting", "speed": None, "eta": None,
                })

        result = instagram_service.download_audio_only(
            url=url, format="mp3", progress_callback=audio_callback, download_dir=user_dir,
            user_cookie=user_cookie,
        )

        history = DownloadHistory(
            id=result['download_id'], user_id=user_id,
            video_url=url, video_title=result['title'],
            video_id=result['video_id'], format="mp3",
            quality="audio", file_path=result['file_path'],
            file_size=result['file_size'], duration=result['duration'],
        )
        db.add(history)
        db.commit()
        trim_user_history(db, user_id)

        progress_store.update(download_id, {
            "status": "done", "progress": 100, "phase": "done",
            "title": result['title'], "download_id": result['download_id'],
        })
    except Exception as e:
        logger.error("Instagram audio download failed: id=%s error=%s", download_id, e)
        progress_store.update(download_id, {
            "status": "error", "progress": 0, "phase": "error",
            "error": _instagram_error_hint(str(e)),
        })
        _cleanup_cancelled(user_dir, db, start_time=t_start)
    finally:
        db.close()


def _run_instagram_carousel_download(download_id: str, media_items: list, title: str, user_id: str):
    import time as _time
    db = SessionLocal()
    user_dir = _get_user_download_dir(db, user_id)
    user_cookie = _get_user_instagram_cookie(db, user_id)
    t_start = _time.time()
    completed_downloads = []

    try:
        total = len(media_items)
        progress_store.update(download_id, {
            "status": "downloading", "progress": 0, "phase": "downloading_items",
            "speed": None, "eta": None,
            "completed_downloads": [], "saved_count": 0, "total_count": total,
        })

        def carousel_callback(d):
            if progress_store.is_cancelled(download_id):
                raise Exception("Download cancelled by user")
            cb_status = d.get("status", "")
            if cb_status == "downloading_item":
                idx = d["item_index"]
                total_items = d["item_total"]
                pct = (idx / total_items) * 95
                progress_store.update(download_id, {
                    "status": "downloading",
                    "progress": round(pct, 1),
                    "phase": "downloading_items",
                    "phase_detail": f"Item {idx + 1} of {total_items}",
                    "speed": None, "eta": None,
                    "completed_downloads": completed_downloads,
                    "saved_count": len(completed_downloads),
                    "total_count": total_items,
                })
            elif cb_status == "item_complete":
                result = d["result"]
                # Store in download history so /download/file/{id} can serve it
                history = DownloadHistory(
                    id=result['download_id'], user_id=user_id,
                    video_url='carousel_item', video_title=result['title'],
                    video_id=f"carousel_{d['item_index'] + 1}",
                    format=result['format'], quality='carousel',
                    file_path=result['file_path'],
                    file_size=result['file_size'], duration=0,
                )
                db.add(history)
                db.commit()
                trim_user_history(db, user_id)

                completed_downloads.append({
                    "download_id": result['download_id'],
                    "title": result['title'],
                })

                idx = d["item_index"]
                total_items = d["item_total"]
                pct = ((idx + 1) / total_items) * 95
                progress_store.update(download_id, {
                    "status": "downloading",
                    "progress": round(pct, 1),
                    "phase": "downloading_items",
                    "speed": None, "eta": None,
                    "completed_downloads": completed_downloads,
                    "saved_count": len(completed_downloads),
                    "total_count": total_items,
                })

        result = instagram_service.download_carousel_items(
            media_items=media_items,
            title=title,
            download_dir=user_dir,
            progress_callback=carousel_callback,
            user_cookie=user_cookie,
        )

        progress_store.update(download_id, {
            "status": "done", "progress": 100, "phase": "done",
            "title": title,
            "completed_downloads": completed_downloads,
            "saved_count": result['saved_count'],
            "total_count": result['total_count'],
        })
    except Exception as e:
        logger.error("Instagram carousel download failed: id=%s error=%s", download_id, e)
        progress_store.update(download_id, {
            "status": "error", "progress": 0, "phase": "error",
            "error": _instagram_error_hint(str(e)),
        })
        _cleanup_cancelled(user_dir, db,
                           completed_ids=[dl['download_id'] for dl in completed_downloads],
                           start_time=t_start)
    finally:
        db.close()


def _run_instagram_batch_download(batch_id: str, video_urls: list, user_id: str):
    import time as _time
    db = SessionLocal()
    total = len(video_urls)
    failed = []
    completed_downloads = []
    user_dir = _get_user_download_dir(db, user_id)
    user_cookie = _get_user_instagram_cookie(db, user_id)
    t_start = _time.time()

    progress_store.update(batch_id, {
        "status": "downloading", "total": total, "completed": 0,
        "current_title": "", "current_progress": 0, "failed": [],
        "completed_downloads": [],
    })

    try:
        for i, url in enumerate(video_urls):
            if progress_store.is_cancelled(batch_id):
                logger.info("Instagram batch %s cancelled by user at %d/%d", batch_id, i, total)
                break

            def make_video_callback(idx):
                def callback(d):
                    if progress_store.is_cancelled(batch_id):
                        raise Exception("Download cancelled by user")
                    if d.get("status") == "downloading":
                        t = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                        dl = d.get("downloaded_bytes", 0)
                        pct = (dl / t * 100) if t > 0 else 0
                        progress_store.update(batch_id, {
                            "status": "downloading", "total": total,
                            "completed": idx, "current_progress": round(pct, 1),
                            "failed": failed,
                        })
                return callback

            try:
                result = instagram_service.download_video(
                    url=url, progress_callback=make_video_callback(i), download_dir=user_dir,
                    user_cookie=user_cookie,
                )

                completed_downloads.append({
                    "download_id": result['download_id'],
                    "title": result.get('title', ''),
                })

                history = DownloadHistory(
                    id=result['download_id'], user_id=user_id,
                    video_url=url, video_title=result['title'],
                    video_id=result['video_id'], format='mp4',
                    quality='best', file_path=result['file_path'],
                    file_size=result['file_size'], duration=result['duration'],
                )
                db.add(history)
                db.commit()
                trim_user_history(db, user_id)
                logger.info("Instagram batch %s: downloaded %d/%d - %s", batch_id, i + 1, total, result['title'])

            except Exception as e:
                logger.error("Instagram batch %s: failed %d/%d url=%s error=%s", batch_id, i + 1, total, url, e)
                failed.append({"url": url, "error": str(e)})

            progress_store.update(batch_id, {
                "status": "downloading", "total": total, "completed": i + 1,
                "current_title": "", "current_progress": 0, "failed": failed,
                "completed_downloads": completed_downloads,
            })

        if progress_store.is_cancelled(batch_id):
            _cleanup_cancelled(user_dir, db,
                               completed_ids=[dl['download_id'] for dl in completed_downloads],
                               start_time=t_start)
            progress_store.update(batch_id, {
                "status": "error", "total": total,
                "completed": 0, "error": "Download cancelled by user",
                "failed": failed, "completed_downloads": [],
            })
        else:
            progress_store.update(batch_id, {
                "status": "done", "total": total,
                "completed": total - len(failed), "failed": failed,
                "completed_downloads": completed_downloads,
            })

    except Exception as e:
        logger.error("Instagram batch crashed: %s error=%s", batch_id, e)
        progress_store.update(batch_id, {
            "status": "error", "total": total, "completed": 0,
            "error": _instagram_error_hint(str(e)), "failed": failed,
        })
        _cleanup_cancelled(user_dir, db,
                           completed_ids=[dl['download_id'] for dl in completed_downloads],
                           start_time=t_start)
    finally:
        db.close()


# --- Endpoints ---

@router.post("/video")
@limiter.limit("10/minute")
def download_instagram_video(
    request: Request,
    body: DownloadRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    _check_premium(db, user_id)

    download_id = str(uuid.uuid4())
    logger.info("Instagram download started: id=%s user=%s url=%s", download_id, user_id, body.url)

    thread = threading.Thread(
        target=_run_instagram_video_download,
        args=(download_id, str(body.url), user_id),
        daemon=True,
    )
    thread.start()
    return {"download_id": download_id, "status": "started", "message": "Instagram download started"}


@router.post("/audio")
@limiter.limit("10/minute")
def download_instagram_audio(
    request: Request,
    body: DownloadRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    _check_premium(db, user_id)

    download_id = str(uuid.uuid4())
    logger.info("Instagram audio download started: id=%s user=%s", download_id, user_id)

    thread = threading.Thread(
        target=_run_instagram_audio_download,
        args=(download_id, str(body.url), user_id),
        daemon=True,
    )
    thread.start()
    return {"download_id": download_id, "status": "started", "message": "Instagram audio download started"}


@router.post("/carousel/items")
@limiter.limit("10/minute")
def download_instagram_carousel(
    request: Request,
    body: CarouselDownloadRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    _check_premium(db, user_id)

    if not body.media_items:
        raise HTTPException(status_code=400, detail="No media items to download")

    download_id = str(uuid.uuid4())
    logger.info("Instagram carousel download started: id=%s user=%s count=%d", download_id, user_id, len(body.media_items))

    thread = threading.Thread(
        target=_run_instagram_carousel_download,
        args=(download_id, body.media_items, body.title, user_id),
        daemon=True,
    )
    thread.start()
    return {"download_id": download_id, "status": "started", "count": len(body.media_items)}


@router.post("/batch/download")
@limiter.limit("3/minute")
def instagram_batch_download(
    request: Request,
    body: BatchDownloadRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    _check_premium(db, user_id)
    if not body.video_urls:
        raise HTTPException(status_code=400, detail="No posts to download")

    batch_id = str(uuid.uuid4())
    logger.info("Instagram batch download started: id=%s user=%s count=%d", batch_id, user_id, len(body.video_urls))

    thread = threading.Thread(
        target=_run_instagram_batch_download,
        args=(batch_id, body.video_urls, user_id),
        daemon=True,
    )
    thread.start()
    return {"batch_id": batch_id, "status": "started", "count": len(body.video_urls)}


# --- SSE Progress ---

@router.get("/progress/{download_id}")
async def instagram_download_progress(download_id: str):
    async def event_stream():
        while True:
            data = progress_store.get(download_id)
            if data is None:
                event = {"status": "waiting", "progress": 0, "phase": "starting"}
            else:
                event = {
                    "status": data.get("status", "unknown"),
                    "progress": data.get("progress", 0),
                    "phase": data.get("phase", ""),
                    "speed": data.get("speed"),
                    "eta": data.get("eta"),
                }
                if "completed_downloads" in data:
                    event["completed_downloads"] = data["completed_downloads"]
                    event["saved_count"] = data.get("saved_count", 0)
                    event["total_count"] = data.get("total_count", 0)
                if data.get("status") == "done":
                    event["title"] = data.get("title", "")
                    event["download_id"] = data.get("download_id", "")
                    yield f"data: {json.dumps(event)}\n\n"
                    break
                if data.get("status") == "error":
                    event["error"] = data.get("error", "Unknown error")
                    yield f"data: {json.dumps(event)}\n\n"
                    break
            yield f"data: {json.dumps(event)}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "identity",
        },
    )


@router.get("/batch/progress/{batch_id}")
async def instagram_batch_progress(batch_id: str):
    async def event_stream():
        while True:
            data = progress_store.get(batch_id)
            if data is None:
                event = {"status": "waiting", "total": 0, "completed": 0}
            else:
                event = {
                    "status": data.get("status", "unknown"),
                    "total": data.get("total", 0),
                    "completed": data.get("completed", 0),
                    "current_title": data.get("current_title", ""),
                    "current_progress": data.get("current_progress", 0),
                    "failed": data.get("failed", []),
                    "completed_downloads": data.get("completed_downloads", []),
                }
                if data.get("status") in ("done", "error"):
                    if data.get("error"):
                        event["error"] = data["error"]
                    yield f"data: {json.dumps(event)}\n\n"
                    break
            yield f"data: {json.dumps(event)}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "identity",
        },
    )


@router.post("/cancel/{download_id}")
def cancel_instagram_download(
    download_id: str,
    user_id: str = Depends(auth_service.get_current_user),
):
    progress_store.cancel(download_id)
    logger.info("Instagram download cancelled: id=%s user=%s", download_id, user_id)
    return {"status": "cancelled", "download_id": download_id}


# --- Image proxy (Instagram CDN blocks cross-origin) ---

_image_cache: dict = {}
_IMAGE_CACHE_TTL = 300  # 5 minutes


@router.get("/proxy-image")
def proxy_instagram_image(url: str):
    """Proxy Instagram CDN images to avoid cross-origin blocking."""
    import urllib.request
    import html as _html
    import time as _time
    from fastapi.responses import Response

    # Unescape HTML entities (&amp; -> &) that may come from HTML-extracted URLs
    url = _html.unescape(url)

    if not url or 'instagram' not in url and 'fbcdn' not in url and 'cdninstagram' not in url:
        raise HTTPException(status_code=400, detail="Invalid image URL")

    # Check cache
    cached = _image_cache.get(url)
    if cached and _time.time() - cached['ts'] < _IMAGE_CACHE_TTL:
        return Response(
            content=cached['data'],
            media_type=cached['content_type'],
            headers={"Cache-Control": "public, max-age=300"},
        )

    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get('Content-Type', 'image/jpeg')
            data = resp.read()

        # Cache it (limit cache size)
        if len(_image_cache) > 200:
            oldest_key = min(_image_cache, key=lambda k: _image_cache[k]['ts'])
            del _image_cache[oldest_key]

        _image_cache[url] = {'data': data, 'content_type': content_type, 'ts': _time.time()}

        return Response(
            content=data,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=300"},
        )
    except Exception as e:
        logger.warning("Image proxy failed for %s: %s", url[:80], e)
        raise HTTPException(status_code=502, detail="Failed to fetch image")
