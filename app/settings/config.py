from pydantic_settings import BaseSettings

class Settings(BaseSettings):

    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    DOWNLOAD_DIR: str
    MAX_FILE_SIZE_MB: int
    MAX_DOWNLOADS_PER_DAY_FREE: int
    MAX_DOWNLOADS_PER_DAY_BASIC: int
    MAX_DOWNLOADS_PER_DAY_PRO: int

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()