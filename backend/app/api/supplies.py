# backend/app/api/supplies.py
#
# Supply inventory endpoints — tracks incoming relief goods for a disaster event.
# These records are the "what we have" side of the allocation equation.
# The AI optimizer (Week 7) reads from this table to decide what to dispatch.
#
# Role rules per Doc 4:
#   GET    /events/{event_id}/supplies               → any authenticated user
#   POST   /events/{event_id}/supplies               → lgu_coordinator
#   PATCH  /events/{event_id}/supplies/{supply_id}   → lgu_coordinator
#   DELETE /events/{event_id}/supplies/{supply_id}   → lgu_coordinator
#
# WHY allow DELETE here but not on damage_reports?
# Supply quantities legitimately need correction (typos, duplicate logging).
# Damage reports are submitted by barangay officials and form an audit record —
# wrong data there gets corrected via PUT, not deleted.

from uuid import UUID
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.models.models import DisasterEvent, SupplyInventory, User

router = APIRouter(tags=["Supply Inventory"])

# ── Valid enum values ─────────────────────────────────────────────────────────

VALID_GOODS_TYPES = {"food_pack", "water", "medicine", "clothing", "hygiene_kit", "other"}
VALID_UNITS = {"kg", "packs", "liters", "boxes"}


# ── Pydantic Schemas ──────────────────────────────────────────────────────────


class SupplyCreate(BaseModel):
    goods_type: str
    quantity: float
    unit: str
    source_name: str
    warehouse_latitude: float
    warehouse_longitude: float

    @field_validator("goods_type")
    @classmethod
    def validate_goods_type(cls, v):
        if v not in VALID_GOODS_TYPES:
            raise ValueError(
                f"goods_type must be one of: {', '.join(sorted(VALID_GOODS_TYPES))}"
            )
        return v

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, v):
        if v not in VALID_UNITS:
            raise ValueError(f"unit must be one of: {', '.join(sorted(VALID_UNITS))}")
        return v

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v):
        if v <= 0:
            raise ValueError("quantity must be greater than 0")
        return v

    @field_validator("source_name")
    @classmethod
    def validate_source_name(cls, v):
        if not v or not v.strip():
            raise ValueError("source_name cannot be empty")
        return v.strip()


class SupplyPatch(BaseModel):
    """PATCH schema — all fields optional. Only send what changed."""
    goods_type: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    source_name: Optional[str] = None
    warehouse_latitude: Optional[float] = None
    warehouse_longitude: Optional[float] = None

    @field_validator("goods_type")
    @classmethod
    def validate_goods_type(cls, v):
        if v is not None and v not in VALID_GOODS_TYPES:
            raise ValueError(
                f"goods_type must be one of: {', '.join(sorted(VALID_GOODS_TYPES))}"
            )
        return v

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, v):
        if v is not None and v not in VALID_UNITS:
            raise ValueError(f"unit must be one of: {', '.join(sorted(VALID_UNITS))}")
        return v

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v):
        if v is not None and v <= 0:
            raise ValueError("quantity must be greater than 0")
        return v


class SupplyResponse(BaseModel):
    id: UUID
    disaster_event_id: UUID
    goods_type: str
    quantity: float
    unit: str
    source_name: str
    warehouse_latitude: float
    warehouse_longitude: float
    received_at: datetime
    logged_by: UUID

    class Config:
        from_attributes = True


# ── Helper ────────────────────────────────────────────────────────────────────


def _get_event_or_404(event_id: UUID, db: Session) -> DisasterEvent:
    event = db.query(DisasterEvent).filter(DisasterEvent.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disaster event not found",
        )
    return event


def _check_lgu_access(event: DisasterEvent, current_user: User):
    """Non-admin users can only touch supplies for their own LGU's events."""
    if current_user.role != "super_admin" and event.lgu_id != current_user.lgu_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage supplies for events within your LGU.",
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/events/{event_id}/supplies",
    response_model=list[SupplyResponse],
)
def list_supplies(
    event_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all supply inventory records for an event.
    Any authenticated user can view — barangay officials need this to see
    what goods are available when their coordinator runs allocation.
    """
    event = _get_event_or_404(event_id, db)
    _check_lgu_access(event, current_user)

    return (
        db.query(SupplyInventory)
        .filter(SupplyInventory.disaster_event_id == event_id)
        .order_by(SupplyInventory.received_at.desc())
        .all()
    )


@router.post(
    "/events/{event_id}/supplies",
    response_model=SupplyResponse,
    status_code=status.HTTP_201_CREATED,
)
def log_supply(
    event_id: UUID,
    body: SupplyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("lgu_coordinator")),
):
    """
    Log incoming goods for a disaster event.
    LGU coordinators only — they're the ones receiving goods at the warehouse.

    Multiple entries of the same goods_type are intentional: a second
    donation of food_packs from SM Foundation is a new row, not an update.
    The OR-Tools optimizer in Week 7 aggregates by type automatically.
    """
    event = _get_event_or_404(event_id, db)
    _check_lgu_access(event, current_user)

    if event.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot log supplies for a closed or archived event.",
        )

    supply = SupplyInventory(
        disaster_event_id=event_id,
        logged_by=current_user.id,
        **body.model_dump(),
    )
    db.add(supply)
    db.commit()
    db.refresh(supply)
    return supply


@router.patch(
    "/events/{event_id}/supplies/{supply_id}",
    response_model=SupplyResponse,
)
def update_supply(
    event_id: UUID,
    supply_id: UUID,
    body: SupplyPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("lgu_coordinator")),
):
    """
    Correct a supply record — quantity typos happen in the field.

    WHY PATCH instead of delete + re-add?
    Any allocation rows referencing this supply_inventory_id via FK
    would break on delete. PATCH keeps the FK chain intact.
    """
    supply = (
        db.query(SupplyInventory)
        .filter(
            SupplyInventory.id == supply_id,
            SupplyInventory.disaster_event_id == event_id,
        )
        .first()
    )
    if not supply:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supply record not found",
        )

    event = _get_event_or_404(event_id, db)
    _check_lgu_access(event, current_user)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(supply, field, value)

    db.commit()
    db.refresh(supply)
    return supply


@router.delete(
    "/events/{event_id}/supplies/{supply_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_supply(
    event_id: UUID,
    supply_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("lgu_coordinator")),
):
    """
    Remove a supply record — for true duplicates or data entry errors.

    BLOCKED if any allocation references this supply (FK constraint).
    In that case, cancel the allocation first, then delete.
    """
    supply = (
        db.query(SupplyInventory)
        .filter(
            SupplyInventory.id == supply_id,
            SupplyInventory.disaster_event_id == event_id,
        )
        .first()
    )
    if not supply:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supply record not found",
        )

    event = _get_event_or_404(event_id, db)
    _check_lgu_access(event, current_user)

    try:
        db.delete(supply)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot delete: this supply is referenced by an existing allocation. "
                "Cancel the allocation first, or use PATCH to correct the quantity."
            ),
        )