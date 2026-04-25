# backend/app/core/database.py
# Creates the SQLAlchemy engine and session factory.
# All database operations in the app go through the get_db() dependency.

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# connect_args is PostgreSQL-specific — required for Neon's SSL connection
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # Checks connection health before using it from the pool
                         # Prevents "connection closed" errors after idle periods
)

# Each request gets its own session — closed when the request ends
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class that all SQLAlchemy models will inherit from
Base = declarative_base()


def get_db():
    """
    FastAPI dependency — yields a database session per request.
    The finally block ensures the session is always closed,
    even if the request raises an exception.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
