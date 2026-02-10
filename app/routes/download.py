import uuid
import json
import asyncio
import logging
import threading
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse, Response
from starlette.background import BackgroundTask
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session
from app.settings.database import get_db, SessionLocal
from app.models.schemas import DownloadRequest, BatchInfoRequest, BatchDownloadRequest
from app.models.models import DownloadHistory, User
from app.services.auth_service import AuthService
from app.services.youtube_service import YouTubeService
from app.services import progress_store
from app.routes.user import trim_user_history

logger = logging.getLogger("turboclip.download")
router = APIRouter()
auth_service = AuthService()
youtube_service = YouTubeService()
limiter = Limiter(key_func=get_remote_address)


def _check_premium(db: Session, user_id: str):
    """Only premium (paid) users can download. Raises 403 if not premium."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_premium:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Premium subscription required. Contact us to upgrade."
        )


def _get_user_download_dir(db: Session, user_id: str) -> str:
    """Return the user's custom download path if set, otherwise the default."""
    import os
    from app.settings.config import settings
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.download_path and os.path.isabs(user.download_path):
        os.makedirs(user.download_path, exist_ok=True)
        return user.download_path
    return settings.DOWNLOAD_DIR


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


@router.post("/info")
@limiter.limit("30/minute")
def get_video_info(request: Request, body: DownloadRequest):
    try:
        if not youtube_service.validate_url(str(body.url)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid YouTube URL"
            )

        info = youtube_service.get_video_info(str(body.url))
        return info
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_video_info failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch video info"
        )


def _make_progress_callback(download_id: str):
    state = {"stream_count": 0, "current_stream": ""}

    def callback(d):
        if progress_store.is_cancelled(download_id):
            raise Exception("Download cancelled by user")

        status_val = d.get("status", "")

        if status_val == "downloading":
            filename = d.get("filename", "")
            if filename != state["current_stream"]:
                state["current_stream"] = filename
                state["stream_count"] += 1

            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)

            if total > 0:
                stream_progress = (downloaded / total) * 100
            else:
                stream_progress = 0

            # For bestvideo+bestaudio: stream 1 = video (0-50%), stream 2 = audio (50-90%)
            # Merge phase = 90-100%
            stream_num = state["stream_count"]
            if stream_num <= 1:
                phase = "downloading_video"
                overall = stream_progress * 0.5  # 0-50%
            else:
                phase = "downloading_audio"
                overall = 50 + stream_progress * 0.4  # 50-90%

            speed = d.get("speed")
            eta = d.get("eta")

            progress_store.update(download_id, {
                "status": "downloading",
                "progress": round(overall, 1),
                "speed": speed,
                "eta": eta,
                "phase": phase,
            })

        elif status_val == "finished":
            # Stream finished downloading, merge may follow
            stream_num = state["stream_count"]
            if stream_num <= 1:
                # First stream done, audio may follow
                progress_store.update(download_id, {
                    "status": "downloading",
                    "progress": 50,
                    "phase": "downloading_audio",
                    "speed": None,
                    "eta": None,
                })
            else:
                # All streams done, merging
                progress_store.update(download_id, {
                    "status": "downloading",
                    "progress": 90,
                    "phase": "merging",
                    "speed": None,
                    "eta": None,
                })

    return callback


def _run_video_download(download_id: str, url: str, format: str, quality: str, user_id: str):
    """Background function that runs the video download and updates progress."""
    import time as _time
    db = SessionLocal()
    user_dir = _get_user_download_dir(db, user_id)
    t_start = _time.time()
    try:
        progress_store.update(download_id, {
            "status": "downloading",
            "progress": 0,
            "phase": "starting",
            "speed": None,
            "eta": None,
        })

        callback = _make_progress_callback(download_id)

        result = youtube_service.download_video(
            url=url,
            format=format,
            quality=quality,
            progress_callback=callback,
            download_dir=user_dir,
        )

        history = DownloadHistory(
            id=result['download_id'],
            user_id=user_id,
            video_url=url,
            video_title=result['title'],
            video_id=result['video_id'],
            format=format,
            quality=quality,
            file_path=result['file_path'],
            file_size=result['file_size'],
            duration=result['duration'],
        )
        db.add(history)
        db.commit()
        trim_user_history(db, user_id)

        progress_store.update(download_id, {
            "status": "done",
            "progress": 100,
            "phase": "done",
            "title": result['title'],
            "download_id": result['download_id'],
        })

    except Exception as e:
        logger.error("Download failed: id=%s error=%s", download_id, e)
        progress_store.update(download_id, {
            "status": "error",
            "progress": 0,
            "phase": "error",
            "error": str(e),
        })
        _cleanup_cancelled(user_dir, db, start_time=t_start)
    finally:
        db.close()


def _run_audio_download(download_id: str, url: str, user_id: str):
    """Background function that runs the audio download and updates progress."""
    import time as _time
    db = SessionLocal()
    user_dir = _get_user_download_dir(db, user_id)
    t_start = _time.time()
    try:
        progress_store.update(download_id, {
            "status": "downloading",
            "progress": 0,
            "phase": "starting",
            "speed": None,
            "eta": None,
        })

        # For audio-only, progress is simpler: 0-90% download, 90-100% conversion
        def audio_callback(d):
            if progress_store.is_cancelled(download_id):
                raise Exception("Download cancelled by user")
            status_val = d.get("status", "")
            if status_val == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes", 0)
                if total > 0:
                    stream_progress = (downloaded / total) * 100
                else:
                    stream_progress = 0
                overall = stream_progress * 0.9  # 0-90%
                progress_store.update(download_id, {
                    "status": "downloading",
                    "progress": round(overall, 1),
                    "phase": "downloading_audio",
                    "speed": d.get("speed"),
                    "eta": d.get("eta"),
                })
            elif status_val == "finished":
                progress_store.update(download_id, {
                    "status": "downloading",
                    "progress": 90,
                    "phase": "converting",
                    "speed": None,
                    "eta": None,
                })

        result = youtube_service.download_audio_only(
            url=url,
            format="mp3",
            progress_callback=audio_callback,
            download_dir=user_dir,
        )

        history = DownloadHistory(
            id=result['download_id'],
            user_id=user_id,
            video_url=url,
            video_title=result['title'],
            video_id=result['video_id'],
            format="mp3",
            quality="audio",
            file_path=result['file_path'],
            file_size=result['file_size'],
            duration=result['duration'],
        )
        db.add(history)
        db.commit()
        trim_user_history(db, user_id)

        progress_store.update(download_id, {
            "status": "done",
            "progress": 100,
            "phase": "done",
            "title": result['title'],
            "download_id": result['download_id'],
        })

    except Exception as e:
        logger.error("Audio download failed: id=%s error=%s", download_id, e)
        progress_store.update(download_id, {
            "status": "error",
            "progress": 0,
            "phase": "error",
            "error": str(e),
        })
        _cleanup_cancelled(user_dir, db, start_time=t_start)
    finally:
        db.close()


@router.post("/video")
@limiter.limit("10/minute")
def download_video(
    request: Request,
    body: DownloadRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user)
):
    if not youtube_service.validate_url(str(body.url)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid YouTube URL"
        )

    _check_premium(db, user_id)

    download_id = str(uuid.uuid4())
    logger.info("Download started: id=%s user=%s url=%s", download_id, user_id, body.url)

    thread = threading.Thread(
        target=_run_video_download,
        args=(download_id, str(body.url), body.format, body.quality, user_id),
        daemon=True,
    )
    thread.start()

    return {"download_id": download_id, "status": "started", "message": "Download started"}


@router.post("/audio")
@limiter.limit("10/minute")
def download_audio(
    request: Request,
    body: DownloadRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user)
):
    if not youtube_service.validate_url(str(body.url)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid YouTube URL"
        )

    _check_premium(db, user_id)

    download_id = str(uuid.uuid4())
    logger.info("Audio download started: id=%s user=%s", download_id, user_id)

    thread = threading.Thread(
        target=_run_audio_download,
        args=(download_id, str(body.url), user_id),
        daemon=True,
    )
    thread.start()

    return {"download_id": download_id, "status": "started", "message": "Download started"}


@router.get("/progress/{download_id}")
async def download_progress(download_id: str):
    """SSE endpoint that streams download progress."""

    async def event_stream():
        while True:
            data = progress_store.get(download_id)

            if data is None:
                # Not found yet — download may not have started
                event = {"status": "waiting", "progress": 0, "phase": "starting"}
            else:
                event = {
                    "status": data.get("status", "unknown"),
                    "progress": data.get("progress", 0),
                    "phase": data.get("phase", ""),
                    "speed": data.get("speed"),
                    "eta": data.get("eta"),
                }

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


@router.get("/file/{download_id}")
def get_downloaded_file(
    download_id: str,
    db: Session = Depends(get_db)
):
    import os
    import re

    MIME_TYPES = {
        '.mp4': 'video/mp4',
        '.mkv': 'video/x-matroska',
        '.webm': 'video/webm',
        '.mp3': 'audio/mpeg',
        '.m4a': 'audio/mp4',
        '.zip': 'application/zip',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.webp': 'image/webp',
    }

    def sanitize_filename(name: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', '', name).strip()

    def _cleanup_file(path: str):
        try:
            os.remove(path)
            logger.info("Auto-deleted served file: %s", path)
        except OSError:
            pass

    def serve_file(file_path: str, filename: str):
        ext = os.path.splitext(file_path)[1].lower()
        mime = MIME_TYPES.get(ext, 'application/octet-stream')
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type=mime,
            content_disposition_type="attachment",
            background=BackgroundTask(_cleanup_file, file_path),
        )

    # Look up the stored file path from download history
    history = db.query(DownloadHistory).filter(DownloadHistory.id == download_id).first()
    if history and history.file_path and os.path.exists(history.file_path):
        ext = os.path.splitext(history.file_path)[1] or f".{history.format}"
        if history.video_title:
            filename = sanitize_filename(history.video_title) + ext
        else:
            filename = os.path.basename(history.file_path)
        return serve_file(history.file_path, filename)

    # Fallback: scan default download dir
    from app.settings.config import settings
    download_dir = settings.DOWNLOAD_DIR
    for ext in ['mp4', 'webm', 'mkv', 'mp3', 'm4a', 'zip', 'jpg', 'jpeg', 'png', 'webp']:
        file_path = os.path.join(download_dir, f"{download_id}.{ext}")
        if os.path.exists(file_path):
            return serve_file(file_path, f"{download_id}.{ext}")

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="File no longer available. Please re-download."
    )


@router.get("/proxy-image")
@limiter.limit("60/minute")
def proxy_image(
    request: Request,
    url: str,
    filename: str = "image.webp",
    user_id: str = Depends(auth_service.get_current_user),
):
    """Proxy a TikTok CDN image to the browser as a download."""
    import urllib.request
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if not parsed.hostname or 'tiktokcdn' not in parsed.hostname:
        raise HTTPException(status_code=400, detail="Invalid image URL")

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=15)
        content = resp.read()
        content_type = resp.headers.get('Content-Type', 'image/webp')
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch image")

    import re
    safe_filename = re.sub(r'[<>:"/\\|?*]', '', filename).strip() or 'image.webp'

    return Response(
        content=content,
        media_type=content_type,
        headers={
            'Content-Disposition': f'attachment; filename="{safe_filename}"',
        },
    )


# --- Batch Shorts Download ---

def _run_batch_download(batch_id: str, video_urls: list, format: str, quality: str, user_id: str):
    """Background function that downloads multiple videos sequentially."""
    import time as _time
    db = SessionLocal()
    total = len(video_urls)
    failed = []
    completed_downloads = []  # [{download_id, title}] — frontend uses these to fetch files
    user_dir = _get_user_download_dir(db, user_id)
    t_start = _time.time()

    progress_store.update(batch_id, {
        "status": "downloading",
        "total": total,
        "completed": 0,
        "current_title": "",
        "current_progress": 0,
        "failed": [],
        "completed_downloads": [],
    })

    try:
        for i, url in enumerate(video_urls):
            if progress_store.is_cancelled(batch_id):
                logger.info("Batch %s cancelled by user at %d/%d", batch_id, i, total)
                break

            # Progress callback for the current video
            def make_video_callback(idx):
                def callback(d):
                    if progress_store.is_cancelled(batch_id):
                        raise Exception("Download cancelled by user")
                    if d.get("status") == "downloading":
                        t = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                        dl = d.get("downloaded_bytes", 0)
                        pct = (dl / t * 100) if t > 0 else 0
                        progress_store.update(batch_id, {
                            "status": "downloading",
                            "total": total,
                            "completed": idx,
                            "current_progress": round(pct, 1),
                            "failed": failed,
                        })
                return callback

            try:
                result = youtube_service.download_video(
                    url=url,
                    format=format,
                    quality=quality,
                    progress_callback=make_video_callback(i),
                    download_dir=user_dir,
                )

                completed_downloads.append({
                    "download_id": result['download_id'],
                    "title": result.get('title', ''),
                })

                progress_store.update(batch_id, {
                    "status": "downloading",
                    "total": total,
                    "completed": i,
                    "current_title": result.get('title', ''),
                    "current_progress": 100,
                    "failed": failed,
                    "completed_downloads": completed_downloads,
                })

                history = DownloadHistory(
                    id=result['download_id'],
                    user_id=user_id,
                    video_url=url,
                    video_title=result['title'],
                    video_id=result['video_id'],
                    format=format,
                    quality=quality,
                    file_path=result['file_path'],
                    file_size=result['file_size'],
                    duration=result['duration'],
                )
                db.add(history)
                db.commit()
                trim_user_history(db, user_id)
                logger.info("Batch %s: downloaded %d/%d - %s", batch_id, i + 1, total, result['title'])

            except Exception as e:
                logger.error("Batch %s: failed %d/%d url=%s error=%s", batch_id, i + 1, total, url, e)
                failed.append({"url": url, "error": str(e)})

            # Update completed count
            progress_store.update(batch_id, {
                "status": "downloading",
                "total": total,
                "completed": i + 1,
                "current_title": "",
                "current_progress": 0,
                "failed": failed,
                "completed_downloads": completed_downloads,
            })

        # If cancelled mid-batch, clean up all already-completed files
        if progress_store.is_cancelled(batch_id):
            _cleanup_cancelled(user_dir, db,
                               completed_ids=[dl['download_id'] for dl in completed_downloads],
                               start_time=t_start)
            progress_store.update(batch_id, {
                "status": "error",
                "total": total,
                "completed": 0,
                "error": "Download cancelled by user",
                "failed": failed,
                "completed_downloads": [],
            })
        else:
            progress_store.update(batch_id, {
                "status": "done",
                "total": total,
                "completed": total - len(failed),
                "current_title": "",
                "current_progress": 100,
                "failed": failed,
                "completed_downloads": completed_downloads,
            })

    except Exception as e:
        logger.error("Batch download crashed: %s error=%s", batch_id, e)
        progress_store.update(batch_id, {
            "status": "error",
            "total": total,
            "completed": 0,
            "error": str(e),
            "failed": failed,
        })
        _cleanup_cancelled(user_dir, db,
                           completed_ids=[dl['download_id'] for dl in completed_downloads],
                           start_time=t_start)
    finally:
        db.close()


@router.post("/batch/info")
@limiter.limit("10/minute")
def get_batch_info(
    request: Request,
    body: BatchInfoRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    _check_premium(db, user_id)

    try:
        result = youtube_service.get_channel_shorts(body.url, limit=body.limit, offset=body.offset)
        return {
            "videos": result["videos"],
            "count": len(result["videos"]),
            "has_more": result["has_more"],
            "offset": body.offset,
        }
    except Exception as e:
        logger.error("get_batch_info failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load shorts from this channel"
        )


@router.post("/batch/download")
@limiter.limit("3/minute")
def batch_download(
    request: Request,
    body: BatchDownloadRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    _check_premium(db, user_id)

    if not body.video_urls:
        raise HTTPException(status_code=400, detail="No videos to download")

    batch_id = str(uuid.uuid4())
    logger.info("Batch download started: id=%s user=%s count=%d", batch_id, user_id, len(body.video_urls))

    thread = threading.Thread(
        target=_run_batch_download,
        args=(batch_id, body.video_urls, body.format, body.quality, user_id),
        daemon=True,
    )
    thread.start()

    return {"batch_id": batch_id, "status": "started", "count": len(body.video_urls)}


@router.post("/cancel/{download_id}")
def cancel_download(
    download_id: str,
    user_id: str = Depends(auth_service.get_current_user),
):
    progress_store.cancel(download_id)
    logger.info("Download cancelled: id=%s user=%s", download_id, user_id)
    return {"status": "cancelled", "download_id": download_id}


@router.get("/batch/progress/{batch_id}")
async def batch_progress(batch_id: str):

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
