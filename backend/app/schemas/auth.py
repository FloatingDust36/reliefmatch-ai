# backend/app/schemas/auth.py
# Pydantic v2 schemas for auth endpoints.
#
# WHY separate schemas from ORM models?
# The ORM model (models.py) maps to the database — it has hashed_password,
# is_active, FK columns, etc. You NEVER want to serialize those directly to JSON.
# Schemas give you precise control over what goes in and what comes out of each endpoint.
#
# Naming convention: *Request for input, *Response for output.

from pydantic import BaseModel, EmailStr, field_validator
from uuid import UUID


# ── Request Schemas ───────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    """POST /auth/login body"""

    email: EmailStr  # Pydantic validates email format — rejects "notanemail"
    password: str

    class Config:
        # Allows use in FastAPI form bodies if we ever switch to OAuth2PasswordRequestForm
        from_attributes = True


class RefreshRequest(BaseModel):
    """POST /auth/refresh body — sends the refresh token back to get a new access token"""

    refresh_token: str


# ── Response Schemas ──────────────────────────────────────────────────────────


class TokenResponse(BaseModel):
    """
    Returned by /auth/login and /auth/refresh.

    access_token: short-lived (default 24h per config), sent in Authorization header
    refresh_token: long-lived (7 days), used ONLY at /auth/refresh
    token_type: always "bearer" — tells the client how to send the token
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserMeResponse(BaseModel):
    """
    Returned by GET /auth/me — the current user's profile.

    Deliberately excludes: hashed_password, last_login_at (privacy),
    and raw FK UUIDs — those are internal implementation details.
    Role IS included because the frontend uses it to show/hide UI elements.
    """

    id: UUID
    email: str
    full_name: str
    role: str  # super_admin | lgu_coordinator | barangay_official
    lgu_id: UUID | None
    barangay_id: UUID | None
    is_active: bool

    class Config:
        from_attributes = True  # Allows Pydantic to read SQLAlchemy model attributes
