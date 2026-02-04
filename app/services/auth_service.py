import uuid
from datetime import datetime, timedelta
import jwt
from bcrypt import hashpw, checkpw, gensalt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.settings.database import get_db
from app.models.models import User
from app.models.schemas import UserCreate
from app.settings.config import settings

security = HTTPBearer()

class AuthService:
    @staticmethod
    def hash_password(password: str) -> str:
        salt = gensalt()
        return hashpw(password.encode(), salt).decode()
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        return checkpw(plain_password.encode(), hashed_password.encode())
    
    @staticmethod
    def create_user(db: Session, user: UserCreate) -> User:
        new_user = User(
            id=str(uuid.uuid4()),
            email=user.email,
            username=user.username,
            hashed_password=AuthService.hash_password(user.password),
            is_active=True
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user
    
    @staticmethod
    def get_user_by_email(db: Session, email: str):
        return db.query(User).filter(User.email == email).first()
    
    @staticmethod
    def authenticate_user(db: Session, email: str, password: str):
        user = AuthService.get_user_by_email(db, email)
        if not user or not AuthService.verify_password(password, user.hashed_password):
            return None
        return user
    
    @staticmethod
    def create_access_token(user_id: str) -> str:
        payload = {
            "user_id": user_id,
            "exp": datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    
    @staticmethod
    def verify_token(token: str) -> str:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id = payload.get("user_id")
            if user_id is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
            return user_id
        
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
        
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Token")
        
    async def get_current_user(self, credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
        return AuthService.verify_token(credentials.credentials)