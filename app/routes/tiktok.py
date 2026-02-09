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
from app.models.schemas import DownloadRequest, BatchDownloadRequest, TikTokInfoRequest, SlideshowDownloadRequest
from app.models.models import DownloadHistory, User
from app.services.auth_service import AuthService
from app.services.tiktok_service import TikTokService
from app.services import progress_store
from app.routes.user import trim_user_history

logger = logging.getLogger("turboclip.tiktok.routes")
router = APIRouter()
auth_service = AuthService()
tiktok_service = TikTokService()
limiter = Limiter(key_func=get_remote_address)


def _check_premium(db: Session, user_id: str):
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_premium:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Premium subscription required."
        )


def _get_user_douyin_cookie(db: Session, user_id: str) -> str:
    """Return the user's Douyin cookie string, or empty string."""
    user = db.query(User).filter(User.id == user_id).first()
    return (user.douyin_cookie or '') if user else ''


def _get_user_download_dir(db: Session, user_id: str) -> str:
    """Return the user's custom download path if set, otherwise the default."""
    import os
    from app.settings.config import settings
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.download_path and os.path.isabs(user.download_path):
        os.makedirs(user.download_path, exist_ok=True)
        return user.download_path
    return settings.DOWNLOAD_DIR


def _douyin_cookie_hint(error: str) -> str:
    """Translate Douyin-specific errors into user-friendly messages."""
    err_lower = str(error).lower()
    if ('douyin' in err_lower and ('video info' in err_lower or 'download url' in err_lower)):
        return (
            "Failed to fetch this Douyin video. "
            "The video may be private, deleted, or region-restricted. "
            "Please check the URL and try again."
        )
    if 'item_list not found' in err_lower or 'render_data' in err_lower:
        return (
            "Could not extract video data from Douyin. "
            "The video may be private or the page structure has changed."
        )
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
    """Clean up files after a cancelled or failed download.

    - completed_ids: list of download_ids whose files+DB records should be removed
    - start_time: scan for orphan files created after this timestamp (for single downloads)
    """
    import os
    import re
    import time as _time

    if not download_dir or not os.path.isdir(download_dir):
        return

    # 1. Remove files & DB rows for known completed downloads (batch/slideshow)
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

    # 2. Remove orphan files created after start_time that have no DB record
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
def get_tiktok_info(
    request: Request,
    body: TikTokInfoRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    url = str(body.url)
    user_cookie = _get_user_douyin_cookie(db, user_id)
    try:
        if tiktok_service.is_profile_url(url):
            result = tiktok_service.get_profile_videos(url, limit=body.limit, offset=body.offset,
                                                       user_cookie=user_cookie)
            videos = result["videos"]
            return {
                "type": "profile",
                "videos": videos,
                "count": len(videos),
                "has_more": result["has_more"],
                "offset": body.offset,
            }
        else:
            info = tiktok_service.get_video_info(url, user_cookie=user_cookie)
            info_type = "slideshow" if info.get("is_slideshow") else "video"
            return {"type": info_type, "info": info}
    except Exception as e:
        logger.error("get_tiktok_info failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_douyin_cookie_hint(str(e)),
        )


# --- Progress callbacks ---

def _make_tiktok_progress_callback(download_id: str):
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

def _run_tiktok_video_download(download_id: str, url: str, user_id: str):
    import time as _time
    db = SessionLocal()
    user_dir = _get_user_download_dir(db, user_id)
    user_cookie = _get_user_douyin_cookie(db, user_id)
    t_start = _time.time()
    try:
        progress_store.update(download_id, {
            "status": "downloading", "progress": 0, "phase": "starting",
            "speed": None, "eta": None,
        })

        callback = _make_tiktok_progress_callback(download_id)
        result = tiktok_service.download_video(
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
        logger.error("TikTok download failed: id=%s error=%s", download_id, e)
        progress_store.update(download_id, {
            "status": "error", "progress": 0, "phase": "error",
            "error": _douyin_cookie_hint(str(e)),
        })
        _cleanup_cancelled(user_dir, db, start_time=t_start)
    finally:
        db.close()


def _run_tiktok_audio_download(download_id: str, url: str, user_id: str):
    import time as _time
    db = SessionLocal()
    user_dir = _get_user_download_dir(db, user_id)
    user_cookie = _get_user_douyin_cookie(db, user_id)
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

        result = tiktok_service.download_audio_only(
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
        logger.error("TikTok audio download failed: id=%s error=%s", download_id, e)
        progress_store.update(download_id, {
            "status": "error", "progress": 0, "phase": "error",
            "error": _douyin_cookie_hint(str(e)),
        })
        _cleanup_cancelled(user_dir, db, start_time=t_start)
    finally:
        db.close()


def _run_tiktok_slideshow_download(download_id: str, url: str, user_id: str):
    import time as _time
    db = SessionLocal()
    user_dir = _get_user_download_dir(db, user_id)
    user_cookie = _get_user_douyin_cookie(db, user_id)
    t_start = _time.time()
    try:
        progress_store.update(download_id, {
            "status": "downloading", "progress": 0, "phase": "starting",
            "speed": None, "eta": None,
        })

        def slideshow_callback(d):
            if progress_store.is_cancelled(download_id):
                raise Exception("Download cancelled by user")
            cb_status = d.get("status", "")
            if cb_status == "downloading_image":
                idx = d["image_index"]
                total_img = d["image_total"]
                pct = ((idx + 1) / total_img) * 85
                progress_store.update(download_id, {
                    "status": "downloading",
                    "progress": round(pct, 1),
                    "phase": "downloading_images",
                    "phase_detail": f"Image {idx + 1} of {total_img}",
                    "speed": None, "eta": None,
                })
            elif cb_status == "zipping":
                progress_store.update(download_id, {
                    "status": "downloading", "progress": 90,
                    "phase": "creating_zip",
                    "speed": None, "eta": None,
                })

        result = tiktok_service.download_slideshow(
            url=url, progress_callback=slideshow_callback, download_dir=user_dir,
            user_cookie=user_cookie,
        )

        history = DownloadHistory(
            id=result['download_id'], user_id=user_id,
            video_url=url, video_title=result['title'],
            video_id=result['video_id'], format='zip',
            quality='slideshow', file_path=result['file_path'],
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
        logger.error("TikTok slideshow download failed: id=%s error=%s", download_id, e)
        progress_store.update(download_id, {
            "status": "error", "progress": 0, "phase": "error",
            "error": _douyin_cookie_hint(str(e)),
        })
        _cleanup_cancelled(user_dir, db, start_time=t_start)
    finally:
        db.close()


def _run_tiktok_slideshow_images(download_id: str, image_urls: list, title: str, user_id: str):
    import time as _time
    db = SessionLocal()
    user_dir = _get_user_download_dir(db, user_id)
    t_start = _time.time()
    completed_downloads = []

    try:
        progress_store.update(download_id, {
            "status": "downloading", "progress": 0, "phase": "downloading_images",
            "speed": None, "eta": None,
            "completed_downloads": [], "saved_count": 0, "total_count": len(image_urls),
        })

        def images_callback(d):
            if progress_store.is_cancelled(download_id):
                raise Exception("Download cancelled by user")
            cb_status = d.get("status", "")
            if cb_status == "downloading_image":
                idx = d["image_index"]
                total_img = d["image_total"]
                pct = (idx / total_img) * 95
                progress_store.update(download_id, {
                    "status": "downloading",
                    "progress": round(pct, 1),
                    "phase": "downloading_images",
                    "phase_detail": f"Image {idx + 1} of {total_img}",
                    "speed": None, "eta": None,
                    "completed_downloads": completed_downloads,
                    "saved_count": len(completed_downloads),
                    "total_count": total_img,
                })
            elif cb_status == "image_complete":
                result = d["result"]
                # Store in download history so /download/file/{id} can serve it
                history = DownloadHistory(
                    id=result['download_id'], user_id=user_id,
                    video_url='slideshow_image', video_title=result['title'],
                    video_id=f"slide_{d['image_index'] + 1}",
                    format=result['format'], quality='slideshow',
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

                idx = d["image_index"]
                total_img = d["image_total"]
                pct = ((idx + 1) / total_img) * 95
                progress_store.update(download_id, {
                    "status": "downloading",
                    "progress": round(pct, 1),
                    "phase": "downloading_images",
                    "speed": None, "eta": None,
                    "completed_downloads": completed_downloads,
                    "saved_count": len(completed_downloads),
                    "total_count": total_img,
                })

        result = tiktok_service.download_slideshow_images(
            image_urls=image_urls,
            title=title,
            download_dir=user_dir,
            progress_callback=images_callback,
        )

        progress_store.update(download_id, {
            "status": "done", "progress": 100, "phase": "done",
            "title": title,
            "completed_downloads": completed_downloads,
            "saved_count": result['saved_count'],
            "total_count": result['total_count'],
        })
    except Exception as e:
        logger.error("TikTok slideshow images download failed: id=%s error=%s", download_id, e)
        progress_store.update(download_id, {
            "status": "error", "progress": 0, "phase": "error",
            "error": _douyin_cookie_hint(str(e)),
        })
        _cleanup_cancelled(user_dir, db,
                           completed_ids=[dl['download_id'] for dl in completed_downloads],
                           start_time=t_start)
    finally:
        db.close()


def _run_tiktok_batch_download(batch_id: str, video_urls: list, user_id: str):
    import time as _time
    db = SessionLocal()
    total = len(video_urls)
    failed = []
    completed_downloads = []
    user_dir = _get_user_download_dir(db, user_id)
    user_cookie = _get_user_douyin_cookie(db, user_id)
    t_start = _time.time()

    progress_store.update(batch_id, {
        "status": "downloading", "total": total, "completed": 0,
        "current_title": "", "current_progress": 0, "failed": [],
        "completed_downloads": [],
    })

    try:
        for i, url in enumerate(video_urls):
            if progress_store.is_cancelled(batch_id):
                logger.info("TikTok batch %s cancelled by user at %d/%d", batch_id, i, total)
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
                # Detect slideshow vs video
                try:
                    info = tiktok_service.get_video_info(url, user_cookie=user_cookie)
                    is_slideshow = info.get('is_slideshow', False)
                except Exception:
                    is_slideshow = False

                if is_slideshow:
                    result = tiktok_service.download_slideshow(
                        url=url, progress_callback=make_video_callback(i), download_dir=user_dir,
                        user_cookie=user_cookie,
                    )
                    fmt, quality_val = 'zip', 'slideshow'
                else:
                    result = tiktok_service.download_video(
                        url=url, progress_callback=make_video_callback(i), download_dir=user_dir,
                        user_cookie=user_cookie,
                    )
                    fmt, quality_val = 'mp4', 'best'

                completed_downloads.append({
                    "download_id": result['download_id'],
                    "title": result.get('title', ''),
                })

                history = DownloadHistory(
                    id=result['download_id'], user_id=user_id,
                    video_url=url, video_title=result['title'],
                    video_id=result['video_id'], format=fmt,
                    quality=quality_val, file_path=result['file_path'],
                    file_size=result['file_size'], duration=result['duration'],
                )
                db.add(history)
                db.commit()
                trim_user_history(db, user_id)
                logger.info("TikTok batch %s: downloaded %d/%d - %s", batch_id, i + 1, total, result['title'])

            except Exception as e:
                logger.error("TikTok batch %s: failed %d/%d url=%s error=%s", batch_id, i + 1, total, url, e)
                failed.append({"url": url, "error": str(e)})

            progress_store.update(batch_id, {
                "status": "downloading", "total": total, "completed": i + 1,
                "current_title": "", "current_progress": 0, "failed": failed,
                "completed_downloads": completed_downloads,
            })

        # If cancelled mid-batch, clean up all already-completed files
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
        logger.error("TikTok batch crashed: %s error=%s", batch_id, e)
        progress_store.update(batch_id, {
            "status": "error", "total": total, "completed": 0,
            "error": _douyin_cookie_hint(str(e)), "failed": failed,
        })
        _cleanup_cancelled(user_dir, db,
                           completed_ids=[dl['download_id'] for dl in completed_downloads],
                           start_time=t_start)
    finally:
        db.close()


# --- Endpoints ---

@router.post("/video")
@limiter.limit("10/minute")
def download_tiktok_video(
    request: Request,
    body: DownloadRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    _check_premium(db, user_id)

    download_id = str(uuid.uuid4())
    logger.info("TikTok download started: id=%s user=%s url=%s", download_id, user_id, body.url)

    thread = threading.Thread(
        target=_run_tiktok_video_download,
        args=(download_id, str(body.url), user_id),
        daemon=True,
    )
    thread.start()
    return {"download_id": download_id, "status": "started", "message": "TikTok download started"}


@router.post("/audio")
@limiter.limit("10/minute")
def download_tiktok_audio(
    request: Request,
    body: DownloadRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    _check_premium(db, user_id)

    download_id = str(uuid.uuid4())
    logger.info("TikTok audio download started: id=%s user=%s", download_id, user_id)

    thread = threading.Thread(
        target=_run_tiktok_audio_download,
        args=(download_id, str(body.url), user_id),
        daemon=True,
    )
    thread.start()
    return {"download_id": download_id, "status": "started", "message": "TikTok audio download started"}


@router.post("/slideshow")
@limiter.limit("10/minute")
def download_tiktok_slideshow(
    request: Request,
    body: DownloadRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    _check_premium(db, user_id)

    download_id = str(uuid.uuid4())
    logger.info("TikTok slideshow download started: id=%s user=%s url=%s", download_id, user_id, body.url)

    thread = threading.Thread(
        target=_run_tiktok_slideshow_download,
        args=(download_id, str(body.url), user_id),
        daemon=True,
    )
    thread.start()
    return {"download_id": download_id, "status": "started", "message": "TikTok slideshow download started"}


@router.post("/slideshow/images")
@limiter.limit("10/minute")
def download_tiktok_slideshow_images(
    request: Request,
    body: SlideshowDownloadRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    _check_premium(db, user_id)

    if not body.image_urls:
        raise HTTPException(status_code=400, detail="No images to download")

    download_id = str(uuid.uuid4())
    logger.info("TikTok slideshow images download started: id=%s user=%s count=%d", download_id, user_id, len(body.image_urls))

    thread = threading.Thread(
        target=_run_tiktok_slideshow_images,
        args=(download_id, body.image_urls, body.title, user_id),
        daemon=True,
    )
    thread.start()
    return {"download_id": download_id, "status": "started", "count": len(body.image_urls)}


@router.post("/batch/download")
@limiter.limit("3/minute")
def tiktok_batch_download(
    request: Request,
    body: BatchDownloadRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    _check_premium(db, user_id)
    if not body.video_urls:
        raise HTTPException(status_code=400, detail="No videos to download")

    batch_id = str(uuid.uuid4())
    logger.info("TikTok batch download started: id=%s user=%s count=%d", batch_id, user_id, len(body.video_urls))

    thread = threading.Thread(
        target=_run_tiktok_batch_download,
        args=(batch_id, body.video_urls, user_id),
        daemon=True,
    )
    thread.start()
    return {"batch_id": batch_id, "status": "started", "count": len(body.video_urls)}


# --- SSE Progress ---

@router.get("/progress/{download_id}")
async def tiktok_download_progress(download_id: str):
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
                # Relay slideshow image completions for smartDownload
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
async def tiktok_batch_progress(batch_id: str):
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
def cancel_tiktok_download(
    download_id: str,
    user_id: str = Depends(auth_service.get_current_user),
):
    progress_store.cancel(download_id)
    logger.info("TikTok download cancelled: id=%s user=%s", download_id, user_id)
    return {"status": "cancelled", "download_id": download_id}
