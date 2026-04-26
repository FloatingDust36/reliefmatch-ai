# backend/main.py
# Application entry point — creates the FastAPI app and registers routers.
# Keep this file thin. Business logic belongs in app/services/, not here.

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.models import models  # noqa — registers models with SQLAlchemy Base

# Validate environment variables on startup — fail fast if something is missing
settings.validate()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    docs_url="/docs",       # Swagger UI — your best friend during development
    redoc_url="/redoc",     # Alternative API docs
)

# CORS — allows your React frontend (localhost:5173) to call this backend.
# In production, replace "*" with your actual Vercel domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://*.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    """Health check endpoint — used by Koyeb to verify the app is running."""
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    """Explicit health check for deployment platform monitoring."""
    return {"status": "healthy"}
