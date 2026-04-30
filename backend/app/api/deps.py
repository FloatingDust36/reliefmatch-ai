# backend/app/api/deps.py
# FastAPI dependency functions — injected into route handlers via Depends().
#
# WHY a dependency instead of calling security functions inside each route?
# 1. DRY: write auth logic once, inject it into 20+ endpoints
# 2. Testable: you can override get_current_user in tests to mock auth
# 3. OpenAPI: FastAPI reads the security scheme from the dependency and
#    auto-generates the "Authorize" button in /docs — your Swagger UI
#    becomes a real testing tool without extra configuration.
#
# Usage in a route:
#   @router.get("/events")
#   def list_events(current_user: User = Depends(get_current_user)):
#       ...

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_token
from app.models.models import User

# HTTPBearer extracts the token from the "Authorization: Bearer <token>" header.
# auto_error=True means FastAPI returns 403 automatically if the header is missing.
bearer_scheme = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Core auth dependency — verifies JWT and returns the User ORM object.

    Flow:
    1. HTTPBearer extracts the raw token string from the Authorization header
    2. We decode and verify the JWT signature + expiry
    3. We check the token type is "access" (not "refresh")
    4. We look up the user by UUID in the database
    5. We check the user is still active (soft-delete support)

    Raises HTTP 401 for any auth failure — deliberately vague error messages
    so attackers can't distinguish "bad token" from "user not found".
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        # WWW-Authenticate header is required by the HTTP spec for 401 responses
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        # JWTError covers: expired, bad signature, malformed token
        raise credentials_exception

    # Block refresh tokens from being used as access tokens
    if payload.get("type") != "access":
        raise credentials_exception

    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    if not user.is_active:
        # Separate error for deactivated accounts — not a security risk to be specific here
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact your LGU administrator.",
        )

    return user


# ── Role-gated dependencies ───────────────────────────────────────────────────
# These are factory functions that return a dependency pre-configured for a role.
# Usage: Depends(require_role("lgu_coordinator"))
#
# WHY a factory instead of separate require_coordinator() / require_admin() functions?
# Fewer functions to maintain, and it reads more like English in route definitions.


def require_role(*allowed_roles: str):
    """
    Returns a FastAPI dependency that enforces role-based access control.

    Example:
        @router.post("/events")
        def create_event(
            current_user: User = Depends(require_role("lgu_coordinator", "super_admin"))
        ):

    Multiple roles use OR logic — any one of them grants access.
    Always includes super_admin automatically (admin can do anything).
    """

    def _check_role(current_user: User = Depends(get_current_user)) -> User:
        # Super admin bypasses all role checks
        if current_user.role == "super_admin":
            return current_user
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of these roles: {', '.join(allowed_roles)}",
            )
        return current_user

    return _check_role


# ── Convenience shortcuts ─────────────────────────────────────────────────────
# Pre-built dependencies for the three roles — reduces boilerplate in routes.


def require_coordinator(
    current_user: User = Depends(require_role("lgu_coordinator")),
) -> User:
    return current_user


def require_admin(current_user: User = Depends(require_role("super_admin"))) -> User:
    return current_user


def require_barangay_official(
    current_user: User = Depends(require_role("barangay_official")),
) -> User:
    return current_user
