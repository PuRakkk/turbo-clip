from pydantic import BaseModel, EmailStr, HttpUrl
from typing import Optional, List
from datetime import datetime


class UserBase(BaseModel):
    email: EmailStr
    username: str

class UserCreate(UserBase):
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class UserResponse(UserBase):
    id: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class VideoFormat(BaseModel):
    format_code: str
    ext: str
    quality: str
    filesize: Optional[int] = None

class VideoMetadata(BaseModel):
    video_id: str
    title: str
    duration: float
    thumnail: Optional[str] = None
    uploader: Optional[str] = None
    upload_date: Optional[str] = None
    availale_formats: List[VideoFormat] = []

class DownloadRequest(BaseModel):
    url: HttpUrl
    format: str = "mp4"
    quality: str = "720p"

class DownloadResponse(BaseModel):
    download_id: str
    status: str
    message: str
    progress: Optional[float] = None

class DownloadHistoryItem(BaseModel):
    id: str
    video_title: str
    video_id: str
    format: str
    quality: str
    file_size: Optional[float]
    downloaded_at: datetime

    class Config:
        from_attributes = True

class SubscriptionResponse(BaseModel):
    id: str
    user_id: str
    tier: str
    is_active: bool
    started_at: datetime
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class SubscriptionPlan(BaseModel):
    name: str
    tier: str
    price: float
    features: dict