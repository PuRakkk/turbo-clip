from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.settings.config import settings
from typing import Generator

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,
    pool_timeout=30,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)

    # Add missing columns to existing tables
    from sqlalchemy import inspect, text
    inspector = inspect(engine)

    with engine.begin() as conn:
        if inspector.has_table("users"):
            columns = [col["name"] for col in inspector.get_columns("users")]
            if "download_path" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN download_path VARCHAR"))
            if "is_premium" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_premium BOOLEAN DEFAULT FALSE"))
            if "is_admin" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE"))
            if "instagram_cookie" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN instagram_cookie VARCHAR"))

        if inspector.has_table("download_history"):
            columns = [col["name"] for col in inspector.get_columns("download_history")]
            if "file_path" not in columns:
                conn.execute(text("ALTER TABLE download_history ADD COLUMN file_path VARCHAR"))
            if "ip_address" not in columns:
                conn.execute(text("ALTER TABLE download_history ADD COLUMN ip_address VARCHAR"))

        # Auto-promote admin by email
        if settings.ADMIN_EMAIL:
            conn.execute(
                text("UPDATE users SET is_admin = TRUE WHERE email = :email AND (is_admin IS NULL OR is_admin = FALSE)"),
                {"email": settings.ADMIN_EMAIL},
            )

        # Drop unique constraint/index on username (allow duplicate usernames)
        if inspector.has_table("users"):
            # Drop unique constraints
            unique_constraints = inspector.get_unique_constraints("users")
            for uc in unique_constraints:
                if "username" in uc.get("column_names", []):
                    conn.execute(text(f'ALTER TABLE users DROP CONSTRAINT "{uc["name"]}"'))

            # Drop unique indexes (PostgreSQL often uses these instead of constraints)
            indexes = inspector.get_indexes("users")
            for idx in indexes:
                if idx.get("unique") and "username" in idx.get("column_names", []):
                    conn.execute(text(f'DROP INDEX IF EXISTS "{idx["name"]}"'))