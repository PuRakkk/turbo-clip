import os
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.settings.database import get_db
from app.models.schemas import SubscriptionResponse, UserSettings, UserResponse
from app.models.models import DownloadHistory, Subscription, User
from app.services.auth_service import AuthService

logger = logging.getLogger("turboclip.user")
router = APIRouter()
auth_service = AuthService()

MAX_HISTORY_PER_USER = 30


def trim_user_history(db: Session, user_id: str, max_entries: int = MAX_HISTORY_PER_USER):
    """Keep only the most recent `max_entries` history rows for a user.

    Deletes the oldest entries and removes their files from disk.
    """
    count = db.query(DownloadHistory)\
        .filter(DownloadHistory.user_id == user_id)\
        .count()

    if count <= max_entries:
        return

    # Get the entries that are beyond the limit (oldest first)
    old_entries = db.query(DownloadHistory)\
        .filter(DownloadHistory.user_id == user_id)\
        .order_by(DownloadHistory.downloaded_at.desc())\
        .offset(max_entries)\
        .all()

    for entry in old_entries:
        # Try to delete the file from disk
        if entry.file_path:
            try:
                if os.path.exists(entry.file_path):
                    os.remove(entry.file_path)
                    logger.info("Trim: deleted file %s", os.path.basename(entry.file_path))
            except OSError:
                pass
        db.delete(entry)

    db.commit()
    logger.info("Trimmed %d old history entries for user %s", len(old_entries), user_id)


@router.get("/subscription", response_model=SubscriptionResponse)
def get_subscription(
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user)
):
    subscription = db.query(Subscription)\
        .filter(Subscription.user_id == user_id)\
        .filter(Subscription.is_active == True)\
        .first()

    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found"
        )
    return subscription


def _user_response(user: User) -> dict:
    """Build a UserResponse dict with has_douyin_cookie computed."""
    resp = UserResponse.model_validate(user).model_dump()
    resp['has_douyin_cookie'] = bool(user.douyin_cookie and user.douyin_cookie.strip())
    return resp


@router.put("/settings")
def update_user_settings(
    body: UserSettings,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if body.download_path is not None:
        user.download_path = body.download_path[:500] if body.download_path else None

    if body.douyin_cookie is not None:
        # Empty string = clear cookie, non-empty = save cookie
        user.douyin_cookie = body.douyin_cookie.strip() if body.douyin_cookie.strip() else None

    db.commit()
    db.refresh(user)
    return _user_response(user)
