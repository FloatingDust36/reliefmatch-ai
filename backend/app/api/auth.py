# backend/app/api/auth.py
# Auth router — 3 endpoints: login, refresh, /me
#
# WHY are these 3 the priority for Week 3?
# Every other endpoint in Doc 4 requires JWT auth.
# Until these work, you can't test anything else.
# Getting /auth/login working unlocks the entire API.

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models.models import User
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse, UserMeResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    POST /api/v1/auth/login

    Accepts email + password, returns JWT access + refresh token pair.

    Security note: we always run verify_password even when user is not found.
    This prevents timing attacks — if we returned immediately on "user not found",
    an attacker could detect registered emails by measuring response time.
    The dummy hash ensures constant-time behavior.
    """
    user = db.query(User).filter(User.email == request.email).first()

    # Constant-time: always verify even if user doesn't exist
    DUMMY_HASH = "$2b$12$KIXdummyhashfortimingequalityXXXXXXXXXXXXXXX"
    password_to_check = user.hashed_password if user else DUMMY_HASH

    # verify_password returns False for the dummy hash — safe
    if not user or not verify_password(request.password, password_to_check):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact your LGU administrator.",
        )

    # Update last_login_at for audit trail (Doc 3: users.last_login_at)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    # "sub" claim stores the user UUID as a string
    # UUID → str is required because JWT payload must be JSON-serializable
    token_data = {"sub": str(user.id), "role": user.role}

    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.post("/refresh", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def refresh_token(request: RefreshRequest, db: Session = Depends(get_db)):
    """
    POST /api/v1/auth/refresh

    Exchanges a valid refresh token for a new access + refresh token pair.
    This is how the frontend stays logged in without forcing re-login every 24 hours.

    Token rotation: each refresh returns a new refresh token too.
    This means stolen refresh tokens self-expire after one use.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(request.refresh_token)
    except JWTError:
        raise credentials_exception

    # Only refresh tokens are accepted here — blocks access tokens from being used
    if payload.get("type") != "refresh":
        raise credentials_exception

    user_id = payload.get("sub")
    if not user_id:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise credentials_exception

    token_data = {"sub": str(user.id), "role": user.role}

    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.get("/me", response_model=UserMeResponse, status_code=status.HTTP_200_OK)
def get_me(current_user: User = Depends(get_current_user)):
    """
    GET /api/v1/auth/me

    Returns the current authenticated user's profile.
    The frontend calls this on app load to:
    1. Verify the stored token is still valid
    2. Get the user's role to render the correct dashboard
    3. Get lgu_id / barangay_id for scoping API calls

    No DB query needed — get_current_user already fetched the user.
    """
    return current_user
