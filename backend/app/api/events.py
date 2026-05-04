# backend/app/api/events.py
#
# Disaster event CRUD endpoints.
# Events are the top-level container for everything in ReliefMatch:
# damage reports, supply inventory, and allocations all live under an event.
#
# Role rules:
#   - lgu_coordinator: create events, update status, list own LGU events
#   - barangay_official: read only (needs to know what event to report under)
#   - super_admin: full access

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import uuid

from app.core.database import get_db
from app.models.models import DisasterEvent, LGU
from app.api.deps import get_current_user, require_role

router = APIRouter(prefix="/events", tags=["Disaster Events"])


# ---------------------------------------------------------------------------
# Pydantic schemas — defined here to keep schemas close to their router.
# Move to schemas/events.py if this file grows large (Week 5+).
# ---------------------------------------------------------------------------


class EventCreate(BaseModel):
    name: str = Field(..., example="Typhoon Carina — July 2024")
    disaster_type: str = Field(..., example="typhoon")
    declared_at: datetime = Field(..., example="2024-07-24T08:00:00+08:00")

    class Config:
        # Accept datetime strings with timezone info from the frontend
        json_encoders = {datetime: lambda v: v.isoformat()}


class EventUpdate(BaseModel):
    # Only status can be changed post-creation.
    # Name and type are immutable — changing them mid-disaster
    # would break audit trail integrity.
    status: str = Field(..., example="closed")


class EventResponse(BaseModel):
    id: uuid.UUID
    lgu_id: uuid.UUID
    name: str
    disaster_type: str
    status: str
    declared_at: datetime
    closed_at: Optional[datetime]
    created_by: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True  # Pydantic v2: replaces orm_mode


# ---------------------------------------------------------------------------
# Allowed values — validated manually so error messages are human-readable
# rather than a raw DB constraint violation.
# ---------------------------------------------------------------------------

VALID_DISASTER_TYPES = {"typhoon", "earthquake", "flood", "landslide", "fire"}
VALID_STATUSES = {"active", "closed", "archived"}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[EventResponse])
def list_events(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    List disaster events.

    - super_admin sees ALL events across all LGUs.
    - lgu_coordinator and barangay_official see only their own LGU's events.

    Optionally filter by ?status=active|closed|archived
    """
    query = select(DisasterEvent)

    # Scope to user's LGU unless super admin
    if current_user.role != "super_admin":
        if current_user.lgu_id is None:
            # Barangay officials have lgu_id=null directly; resolve via barangay
            # For now raise clearly — this edge case gets fixed when we add
            # barangay_id → lgu_id lookup in Week 5
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not associated with an LGU.",
            )
        query = query.where(DisasterEvent.lgu_id == current_user.lgu_id)

    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{status}'. Must be one of: {sorted(VALID_STATUSES)}",
            )
        query = query.where(DisasterEvent.status == status)

    query = query.order_by(DisasterEvent.declared_at.desc())
    results = db.execute(query).scalars().all()
    return results


@router.post("/", response_model=EventResponse, status_code=201)
def create_event(
    body: EventCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("lgu_coordinator", "super_admin")),
):
    """
    Declare a new disaster event.
    Only lgu_coordinator (for their own LGU) or super_admin can create events.
    """
    if body.disaster_type not in VALID_DISASTER_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid disaster_type '{body.disaster_type}'. "
            f"Must be one of: {sorted(VALID_DISASTER_TYPES)}",
        )

    # Coordinators can only create events for their own LGU
    if current_user.role == "lgu_coordinator":
        if current_user.lgu_id is None:
            raise HTTPException(
                status_code=400,
                detail="Coordinator is not assigned to an LGU.",
            )
        lgu_id = current_user.lgu_id
    else:
        # super_admin: you'd normally pass lgu_id in body.
        # Keeping it simple for now — admin uses their assigned LGU or first LGU.
        # TODO Week 5: add lgu_id field to EventCreate for super_admin use.
        lgu_id = current_user.lgu_id

    event = DisasterEvent(
        lgu_id=lgu_id,
        name=body.name,
        disaster_type=body.disaster_type,
        declared_at=body.declared_at,
        status="active",
        created_by=current_user.id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/{event_id}", response_model=EventResponse)
def get_event(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Fetch a single event by ID.
    Non-admin users can only view events belonging to their LGU.
    """
    event = db.get(DisasterEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")

    # LGU scoping check
    if current_user.role != "super_admin":
        if event.lgu_id != current_user.lgu_id:
            raise HTTPException(status_code=403, detail="Access denied.")

    return event


@router.patch("/{event_id}", response_model=EventResponse)
def update_event_status(
    event_id: uuid.UUID,
    body: EventUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("lgu_coordinator", "super_admin")),
):
    """
    Update event status (active → closed → archived).

    Transition rules:
      active → closed   (relief ops concluded)
      closed → archived (moved to historical record)
      archived → anything: BLOCKED (audit trail must stay immutable)
    """
    event = db.get(DisasterEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")

    if current_user.role == "lgu_coordinator" and event.lgu_id != current_user.lgu_id:
        raise HTTPException(status_code=403, detail="Access denied.")

    if body.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {sorted(VALID_STATUSES)}",
        )

    # Enforce state machine — archived events are immutable
    if event.status == "archived":
        raise HTTPException(
            status_code=400,
            detail="Archived events cannot be modified. This preserves the audit trail.",
        )

    # Stamp closed_at when moving to closed
    if body.status == "closed" and event.status == "active":
        event.closed_at = datetime.now(timezone.utc)

    event.status = body.status
    db.commit()
    db.refresh(event)
    return event
