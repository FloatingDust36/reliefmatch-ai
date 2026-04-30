# backend/app/core/security.py
# Centralized auth utilities — password hashing and JWT lifecycle.
#
# WHY bcrypt directly instead of passlib?
# passlib's CryptContext breaks on bcrypt 4.x (Python 3.13 compatible version)
# because bcrypt removed the __about__ attribute passlib relies on.
# We call bcrypt.hashpw / bcrypt.checkpw directly — same algorithm, no wrapper.
#
# WHY python-jose for JWT and not PyJWT?
# python-jose supports RS256 and HS256 with a simpler API for our use case.
# Both are fine; jose was already in requirements.txt.

import bcrypt
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from app.core.config import settings


# ── Password Hashing ──────────────────────────────────────────────────────────


def hash_password(plain_password: str) -> str:
    """
    Hash a plain-text password with bcrypt (cost factor 12).

    Cost factor 12 means ~250ms on modern hardware — slow enough to frustrate
    brute-force attacks, fast enough to not annoy users at login.
    Store the result in users.hashed_password. Never store plain text.
    """
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Compare a login attempt against the stored bcrypt hash.

    bcrypt.checkpw handles the salt extraction automatically — the salt is
    embedded in the hash string itself, which is why you don't pass it separately.
    Returns False (not raises) on mismatch — safe to use in an if-statement.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


# ── JWT Tokens ────────────────────────────────────────────────────────────────


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    Create a signed JWT access token.

    `data` should contain at minimum {"sub": user_id_string}.
    "sub" (subject) is the JWT standard claim for the user identifier.
    We use the UUID string, not the email, so tokens survive email changes.

    The token is signed with SECRET_KEY using HS256.
    Anyone with SECRET_KEY can verify it — keep that key safe in .env.
    """
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload.update(
        {
            "exp": expire,
            "iat": datetime.now(timezone.utc),  # issued-at — useful for audit logs
            "type": "access",  # prevents refresh tokens from being used as access tokens
        }
    )
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """
    Refresh tokens live longer (7 days) but can only be used at /auth/refresh.
    The "type": "refresh" claim blocks them from passing get_current_user checks.

    In production you'd store refresh tokens in the DB to support revocation.
    For the OJT scope, stateless refresh is acceptable.
    """
    payload = data.copy()
    payload.update(
        {
            "exp": datetime.now(timezone.utc) + timedelta(days=7),
            "iat": datetime.now(timezone.utc),
            "type": "refresh",
        }
    )
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decode and verify a JWT. Raises JWTError on invalid/expired tokens.
    Callers (deps.py) should catch JWTError and raise HTTP 401.

    jose automatically validates the `exp` claim — expired tokens raise JWTError.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
