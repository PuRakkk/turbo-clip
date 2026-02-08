from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Float, Enum as SAEnum
from sqlalchemy.orm import relationship
from datetime import datetime
from app.settings.database import Base
import enum

class ApprovalStatus(str, enum.Enum):
    PENDING_PAYMENT = "pending_payment"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_premium = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    download_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    #relations
    subscription = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    download_history = relationship("DownloadHistory", back_populates="user", cascade="all, delete-orphan")

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    tier = Column(String, default="free")
    is_active = Column(Boolean, default=True)

    approval_status = Column(SAEnum(ApprovalStatus), default=ApprovalStatus.PENDING_PAYMENT)
    payment_proof_url = Column(String, nullable=True)
    contact_note = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)

    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="subscription")

class DownloadHistory(Base):
    __tablename__ = "download_history"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    video_url = Column(String, nullable=False)
    video_title = Column(String, nullable=False)
    video_id = Column(String, nullable=False, index=True)
    format = Column(String, default="mp4")
    quality = Column(String, default="720p")
    file_path = Column(String, nullable=True)
    file_size = Column(Float, nullable=True)
    duration = Column(Float, nullable=True)
    ip_address = Column(String, nullable=True, index=True)
    downloaded_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="download_history")