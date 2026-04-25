# backend/app/core/config.py
# Centralized configuration — reads all environment variables in one place.
# Every other module imports from here instead of calling os.getenv() directly.
# This means if an env var name changes, you fix it in one place only.

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    PROJECT_NAME: str = "ReliefMatch AI"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # JWT Auth
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
    )

    def validate(self):
        """Call this on startup to catch missing env vars early."""
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL is not set in .env")
        if not self.SECRET_KEY:
            raise ValueError("SECRET_KEY is not set in .env")


# Single instance imported everywhere
settings = Settings()
