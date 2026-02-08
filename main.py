import logging
import shutil
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.settings.config import settings
from app.settings.database import init_db, SessionLocal
from app.routes.auth import router as auth_router
from app.routes.download import router as download_router
from app.routes.user import router as user_router
from app.routes.admin import router as admin_router
from app.routes.tiktok import router as tiktok_router

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("turboclip")

# --- Rate Limiter ---
limiter = Limiter(key_func=get_remote_address)

# --- App ---
app = FastAPI(
    title="TurboClip API",
    description="YouTube Video Downloader Backend",
    version="0.1.0",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- Middleware ---
app.add_middleware(GZipMiddleware, minimum_size=500)

cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]

# Separate exact origins from wildcard patterns (e.g. https://*.ngrok-free.app)
exact_origins = [o for o in cors_origins if "*" not in o]
wildcard_patterns = [o for o in cors_origins if "*" in o]

# Convert wildcard patterns to regex (e.g. https://*.ngrok-free.app -> https://.*\.ngrok-free\.app)
import re as _re
origin_regex = None
if wildcard_patterns:
    regex_parts = []
    for pattern in wildcard_patterns:
        escaped = _re.escape(pattern).replace(r"\*", ".*")
        regex_parts.append(escaped)
    origin_regex = "^(" + "|".join(regex_parts) + ")$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=exact_origins,
    allow_origin_regex=origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# --- Startup ---
@app.on_event("startup")
def startup():
    init_db()
    logger.info("TurboClip API started")

# --- Health Check ---
@app.get("/health")
def health_check():
    status = {"api": "healthy"}

    # Check database
    try:
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        status["database"] = "healthy"
    except Exception:
        status["database"] = "unhealthy"

    # Check FFmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    if settings.FFMPEG_PATH:
        status["ffmpeg"] = settings.FFMPEG_PATH
    elif ffmpeg_path:
        status["ffmpeg"] = ffmpeg_path
    else:
        status["ffmpeg"] = "not found"

    return status

# --- Routers ---
app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(download_router, prefix="/api/download", tags=["Download"])
app.include_router(user_router, prefix="/api/user", tags=["User"])
app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])
app.include_router(tiktok_router, prefix="/api/tiktok", tags=["TikTok"])
