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
    docs_url="/docs",  # Swagger UI — your best friend during development
    redoc_url="/redoc",  # Alternative API docs
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

# ── Register Routers ──────────────────────────────────────────────────────────
# Import here (not at top of file) to keep import errors close to where they're used.
# All routes are prefixed with /api/v1 per Doc 4.

from app.api import auth, users, events, reports, supplies  # noqa: E402

app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(events.router, prefix=settings.API_V1_PREFIX)
app.include_router(reports.router, prefix=settings.API_V1_PREFIX)
app.include_router(supplies.router, prefix=settings.API_V1_PREFIX)

# Week 4 onward — uncomment as you build each router:
# from app.api import allocations, public
# app.include_router(allocations.router, prefix=settings.API_V1_PREFIX)
# app.include_router(public.router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root():
    """Health check endpoint — used by Render to verify the app is running."""
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
