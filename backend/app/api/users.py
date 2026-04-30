# backend/app/api/users.py
# User, LGU, and Barangay management endpoints.
#
# Per Doc 4 API Reference:
#   GET  /lgus                    → super_admin
#   POST /lgus                    → super_admin
#   GET  /lgus/{lgu_id}/barangays → any authenticated user
#   POST /barangays               → lgu_coordinator
#   GET  /users                   → super_admin
#   POST /users                   → super_admin
#   PATCH /users/{user_id}        → super_admin
#
# These endpoints are the scaffolding the LGU coordinator needs to set up
# their area before a disaster event can be declared (Week 5 onward).

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.core.security import hash_password
from app.models.models import LGU, Barangay, User

router = APIRouter(tags=["Users & Organizations"])


# ── Pydantic schemas (inline for now, move to schemas/ in Week 5 if it grows) ──


class LGUCreate(BaseModel):
    name: str
    region: str
    province: str
    latitude: float
    longitude: float


class LGUResponse(BaseModel):
    id: UUID
    name: str
    region: str
    province: str
    latitude: float
    longitude: float

    class Config:
        from_attributes = True


class BarangayCreate(BaseModel):
    name: str
    lgu_id: UUID
    population: int
    latitude: float
    longitude: float
    poverty_incidence_pct: float | None = None
    historical_disaster_count: int = 0


class BarangayResponse(BaseModel):
    id: UUID
    name: str
    lgu_id: UUID
    population: int
    latitude: float
    longitude: float
    poverty_incidence_pct: float | None
    historical_disaster_count: int

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str  # super_admin | lgu_coordinator | barangay_official
    lgu_id: UUID | None = None
    barangay_id: UUID | None = None


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    lgu_id: UUID | None
    barangay_id: UUID | None
    is_active: bool

    class Config:
        from_attributes = True


class UserPatch(BaseModel):
    """Only allow updating role and active status — email changes need a separate flow"""

    role: str | None = None
    is_active: bool | None = None


# ── LGU Endpoints ─────────────────────────────────────────────────────────────


@router.get("/lgus", response_model=list[LGUResponse])
def list_lgus(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("super_admin")),
):
    """List all LGUs. Super admin only — LGU coordinators only see their own LGU."""
    return db.query(LGU).order_by(LGU.name).all()


@router.post("/lgus", response_model=LGUResponse, status_code=status.HTTP_201_CREATED)
def create_lgu(
    body: LGUCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("super_admin")),
):
    """Create a new LGU. Used when onboarding a new municipality to the system."""
    lgu = LGU(**body.model_dump())
    db.add(lgu)
    db.commit()
    db.refresh(lgu)
    return lgu


@router.get("/lgus/{lgu_id}/barangays", response_model=list[BarangayResponse])
def list_barangays(
    lgu_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List barangays under an LGU. Any authenticated user can call this.

    LGU coordinators and barangay officials are scoped to their own LGU.
    Super admin can query any LGU.
    """
    # Non-admin users can only see their own LGU's barangays
    if current_user.role != "super_admin" and current_user.lgu_id != lgu_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view barangays within your own LGU.",
        )

    lgu = db.query(LGU).filter(LGU.id == lgu_id).first()
    if not lgu:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="LGU not found"
        )

    return (
        db.query(Barangay)
        .filter(Barangay.lgu_id == lgu_id)
        .order_by(Barangay.name)
        .all()
    )


@router.post(
    "/barangays", response_model=BarangayResponse, status_code=status.HTTP_201_CREATED
)
def create_barangay(
    body: BarangayCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("lgu_coordinator")),
):
    """
    Create a barangay. LGU coordinators can only create barangays within their LGU.

    WHY this restriction? An LGU coordinator from Cebu City should not be able to
    add barangays to Digos — that would corrupt the geographic scoping of all
    disaster events, damage reports, and allocations.
    """
    if current_user.role != "super_admin" and body.lgu_id != current_user.lgu_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only create barangays within your assigned LGU.",
        )

    lgu = db.query(LGU).filter(LGU.id == body.lgu_id).first()
    if not lgu:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="LGU not found"
        )

    barangay = Barangay(**body.model_dump())
    db.add(barangay)
    db.commit()
    db.refresh(barangay)
    return barangay


# ── User Endpoints ────────────────────────────────────────────────────────────


@router.get("/users", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("super_admin")),
):
    """List all users. Super admin only — coordinators and officials manage via their LGU."""
    return db.query(User).order_by(User.full_name).all()


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("super_admin")),
):
    """
    Create a user account. Super admin only.

    In production you'd send a welcome email with a temporary password.
    For OJT scope, the admin sets the initial password directly.
    """
    # Check for duplicate email before trying to insert — gives a better error message
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with email {body.email} already exists.",
        )

    VALID_ROLES = {"super_admin", "lgu_coordinator", "barangay_official"}
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}",
        )

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        lgu_id=body.lgu_id,
        barangay_id=body.barangay_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: UUID,
    body: UserPatch,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("super_admin")),
):
    """
    Update a user's role or active status. Super admin only.
    Uses PATCH (partial update) not PUT — only send the fields you want to change.

    This is the "deactivate account" endpoint — set is_active=false to block login
    without deleting the user's audit history.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Only update fields that were actually sent in the request
    if body.role is not None:
        VALID_ROLES = {"super_admin", "lgu_coordinator", "barangay_official"}
        if body.role not in VALID_ROLES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}",
            )
        user.role = body.role

    if body.is_active is not None:
        user.is_active = body.is_active

    db.commit()
    db.refresh(user)
    return user
