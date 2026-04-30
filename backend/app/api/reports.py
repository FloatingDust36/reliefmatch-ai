# backend/app/api/reports.py
# Damage report endpoints — the primary data collection mechanism for the AI engine.
#
# Per Doc 4:
#   GET  /events/{event_id}/reports               → lgu_coordinator
#   POST /events/{event_id}/reports               → barangay_official
#   GET  /events/{event_id}/reports/{report_id}   → any authenticated user
#   PUT  /events/{event_id}/reports/{report_id}   → barangay_official (own reports only)
#
# These records are what feed the XGBoost risk scoring model in Week 6.
# Data quality here = allocation quality later.
# Validation matters: a typo in population_affected can shift the priority ranking.

from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.models.models import Barangay, DamageReport, DisasterEvent, User

router = APIRouter(tags=["Damage Reports"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class DamageReportCreate(BaseModel):
    barangay_id: UUID
    population_affected: int
    casualty_count: int = 0
    structures_damaged: int = 0
    structures_destroyed: int = 0
    road_accessibility: str  # accessible | partially_blocked | cut_off
    has_power: bool = True
    has_water: bool = True
    hours_since_last_goods: int | None = None
    goods_received_qty: float = 0.0
    special_needs_notes: str | None = None

    @field_validator("road_accessibility")
    @classmethod
    def validate_road_accessibility(cls, v):
        allowed = {"accessible", "partially_blocked", "cut_off"}
        if v not in allowed:
            raise ValueError(f"road_accessibility must be one of: {', '.join(allowed)}")
        return v

    @field_validator("population_affected")
    @classmethod
    def validate_population_positive(cls, v):
        if v < 0:
            raise ValueError("population_affected cannot be negative")
        return v

    @field_validator("hours_since_last_goods")
    @classmethod
    def validate_hours(cls, v):
        if v is not None and v < 0:
            raise ValueError("hours_since_last_goods cannot be negative")
        return v


class DamageReportUpdate(BaseModel):
    """PUT schema — all fields optional for partial updates"""

    population_affected: int | None = None
    casualty_count: int | None = None
    structures_damaged: int | None = None
    structures_destroyed: int | None = None
    road_accessibility: str | None = None
    has_power: bool | None = None
    has_water: bool | None = None
    hours_since_last_goods: int | None = None
    goods_received_qty: float | None = None
    special_needs_notes: str | None = None

    @field_validator("road_accessibility")
    @classmethod
    def validate_road_accessibility(cls, v):
        if v is None:
            return v
        allowed = {"accessible", "partially_blocked", "cut_off"}
        if v not in allowed:
            raise ValueError(f"road_accessibility must be one of: {', '.join(allowed)}")
        return v


class DamageReportResponse(BaseModel):
    id: UUID
    disaster_event_id: UUID
    barangay_id: UUID
    submitted_by: UUID
    population_affected: int
    casualty_count: int
    structures_damaged: int
    structures_destroyed: int
    road_accessibility: str
    has_power: bool
    has_water: bool
    hours_since_last_goods: int | None
    goods_received_qty: float
    special_needs_notes: str | None
    submitted_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Helper ────────────────────────────────────────────────────────────────────


def _get_event_or_404(event_id: UUID, db: Session) -> DisasterEvent:
    event = db.query(DisasterEvent).filter(DisasterEvent.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Disaster event not found"
        )
    return event


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/events/{event_id}/reports", response_model=list[DamageReportResponse])
def list_reports(
    event_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("lgu_coordinator")),
):
    """
    List all damage reports for an event. LGU coordinator and admin only.

    Coordinators are scoped to their own LGU — they shouldn't see reports
    from a typhoon event declared by a different city.
    """
    event = _get_event_or_404(event_id, db)

    if current_user.role != "super_admin" and event.lgu_id != current_user.lgu_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view reports for events within your LGU.",
        )

    return (
        db.query(DamageReport)
        .filter(DamageReport.disaster_event_id == event_id)
        .order_by(DamageReport.submitted_at.desc())
        .all()
    )


@router.post(
    "/events/{event_id}/reports",
    response_model=DamageReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_report(
    event_id: UUID,
    body: DamageReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("barangay_official")),
):
    """
    Submit a damage report for a barangay. Barangay officials only.

    Key validation: the barangay in the report must belong to the same LGU as
    the disaster event. A Lahug official can't file a report for a Davao event.

    One report per barangay per event is enforced — duplicates are rejected.
    The barangay official updates via PUT if the situation changes.
    """
    event = _get_event_or_404(event_id, db)

    if event.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot submit reports for a closed or archived event.",
        )

    # Verify the barangay exists and belongs to the event's LGU
    barangay = db.query(Barangay).filter(Barangay.id == body.barangay_id).first()
    if not barangay:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Barangay not found"
        )
    if barangay.lgu_id != event.lgu_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This barangay does not belong to the LGU that declared this event.",
        )

    # Barangay officials can only submit for their own barangay
    if (
        current_user.role == "barangay_official"
        and current_user.barangay_id != body.barangay_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only submit reports for your assigned barangay.",
        )

    # One report per barangay per event
    existing = (
        db.query(DamageReport)
        .filter(
            DamageReport.disaster_event_id == event_id,
            DamageReport.barangay_id == body.barangay_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A report for this barangay already exists for this event. Use PUT to update it.",
        )

    report = DamageReport(
        disaster_event_id=event_id,
        submitted_by=current_user.id,
        **body.model_dump(),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


@router.get(
    "/events/{event_id}/reports/{report_id}", response_model=DamageReportResponse
)
def get_report(
    event_id: UUID,
    report_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single damage report. Any authenticated user can view."""
    report = (
        db.query(DamageReport)
        .filter(
            DamageReport.id == report_id, DamageReport.disaster_event_id == event_id
        )
        .first()
    )
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report not found"
        )
    return report


@router.put(
    "/events/{event_id}/reports/{report_id}", response_model=DamageReportResponse
)
def update_report(
    event_id: UUID,
    report_id: UUID,
    body: DamageReportUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("barangay_official")),
):
    """
    Update a damage report. Barangay officials can only edit their own submissions.

    WHY allow updates at all?
    Disaster situations evolve — a road that was cut off at 6 AM might reopen by noon.
    Barangay officials need to be able to correct their initial reports.

    The AI model re-runs on every POST /events/{id}/allocate call, so
    updated reports automatically influence the next allocation recommendation.
    """
    report = (
        db.query(DamageReport)
        .filter(
            DamageReport.id == report_id, DamageReport.disaster_event_id == event_id
        )
        .first()
    )
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report not found"
        )

    # Officials can only edit their own submissions
    if (
        current_user.role == "barangay_official"
        and report.submitted_by != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only edit reports you submitted.",
        )

    # Apply only the fields that were sent (exclude_unset=True skips None defaults)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(report, field, value)

    report.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(report)
    return report
