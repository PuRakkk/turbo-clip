import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.settings.database import get_db
from app.models.models import User
from app.services.auth_service import AuthService

logger = logging.getLogger("turboclip.admin")
router = APIRouter()
auth_service = AuthService()


def _require_admin(db: Session, user_id: str):
    """Raise 403 if the current user is not an admin."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )


class UserAdminView(BaseModel):
    id: str
    email: str
    username: str
    is_active: bool
    is_premium: bool
    is_admin: bool
    created_at: str

    class Config:
        from_attributes = True


class TogglePremiumRequest(BaseModel):
    is_premium: bool


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    _require_admin(db, user_id)
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "is_active": u.is_active,
            "is_premium": u.is_premium,
            "is_admin": u.is_admin,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@router.patch("/users/{target_user_id}/premium")
def toggle_premium(
    target_user_id: str,
    body: TogglePremiumRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(auth_service.get_current_user),
):
    _require_admin(db, user_id)

    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.is_premium = body.is_premium
    db.commit()
    logger.info("Admin %s set is_premium=%s for user %s", user_id, body.is_premium, target_user_id)
    return {"message": "Updated", "is_premium": target.is_premium}
