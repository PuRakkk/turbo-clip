import os
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.settings.database import get_db
from app.models.schemas import DownloadHistoryItem, SubscriptionResponse, UserSettings, UserResponse
from app.models.models import DownloadHistory, Subscription, User
from app.services.auth_service import AuthService

router = APIRouter()
auth_service = AuthService()


@router.get("/history", response_model=List[DownloadHistoryItem])
def get_download_history(
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
    limit: int = 50,
    offset: int = 0
):
    history = db.query(DownloadHistory)\
        .filter(DownloadHistory.user_id == user_id)\
        .order_by(DownloadHistory.downloaded_at.desc())\
        .offset(offset)\
        .limit(limit)\
        .all()
    return history


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


@router.delete("/history/{history_id}")
def delete_history_item(
    history_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user)
):
    history = db.query(DownloadHistory)\
        .filter(DownloadHistory.id == history_id)\
        .filter(DownloadHistory.user_id == user_id)\
        .first()

    if not history:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="History item not found"
        )

    db.delete(history)
    db.commit()
    return {"message": "History item deleted"}


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
