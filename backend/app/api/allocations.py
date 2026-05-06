# backend/app/api/allocations.py
#
# The core AI endpoint — what the whole project is building toward.
#
# POST /events/{event_id}/allocate triggers the full ML pipeline:
#   Step 1 — Fetch all damage reports for this event from PostgreSQL
#   Step 2 — Join barangay metadata (poverty_incidence_pct, historical_disaster_count)
#             needed for vulnerability_index feature engineering in predictor.py
#   Step 3 — Run XGBoost scoring + SHAP explanations via score_barangays()
#   Step 4 — Delete old 'recommended' allocations (stale from previous runs)
#             Approved/dispatched/delivered rows are preserved — audit trail
#   Step 5 — For each scored barangay, assign goods from supply inventory
#             Simple proportional allocation: highest-score barangays get
#             the largest share. OR-Tools CVRP optimizer comes in Week 7.
#   Step 6 — Write new Allocation rows to PostgreSQL, return ranked list
#
# GET /events/{event_id}/allocations — reads existing rows, no ML involved.
#
# PATCH status endpoints — approve → dispatch → deliver lifecycle.
#
# WHY delete 'recommended' rows on re-run instead of updating them?
# The set of barangays that filed reports can change between runs —
# new reports come in, road conditions update. A full replace of
# 'recommended' rows is cleaner than trying to diff and patch.
# Approved rows are never touched — coordinators own those decisions.
#
# WHY simple proportional allocation now instead of OR-Tools?
# OR-Tools CVRP needs road distance matrices (OSRM calls) which adds
# significant complexity. The proportional allocator gives meaningful
# results for Week 6 demo. Week 7 replaces _allocate_supplies() with
# the real CVRP optimizer.

from datetime import datetime, timezone
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.ml.predictor import score_barangays
from app.ml.optimizer import solve_cvrp
from app.models.models import (
    Allocation,
    Barangay,
    DamageReport,
    DisasterEvent,
    SupplyInventory,
    User,
)

router = APIRouter(tags=["AI Allocation"])


# ── Response schema ───────────────────────────────────────────────────────────


class AllocationResponse(BaseModel):
    id: UUID
    disaster_event_id: UUID
    barangay_id: UUID
    barangay_name: str
    supply_inventory_id: UUID
    goods_type: str
    quantity_allocated: float
    priority_score: float
    priority_rank: int
    shap_explanation: str
    status: str
    recommended_at: datetime
    approved_at: Optional[datetime] = None
    dispatched_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_event_or_404(event_id: UUID, db: Session) -> DisasterEvent:
    event = db.query(DisasterEvent).filter(DisasterEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Disaster event not found")
    return event


def _check_lgu_access(event: DisasterEvent, user: User):
    if user.role != "super_admin" and event.lgu_id != user.lgu_id:
        raise HTTPException(status_code=403, detail="Access denied — wrong LGU")


def _build_response(alloc: Allocation, db: Session) -> AllocationResponse:
    """Join Barangay name + SupplyInventory goods_type for the frontend."""
    barangay = db.get(Barangay, alloc.barangay_id)
    supply = db.get(SupplyInventory, alloc.supply_inventory_id)
    return AllocationResponse(
        id=alloc.id,
        disaster_event_id=alloc.disaster_event_id,
        barangay_id=alloc.barangay_id,
        barangay_name=barangay.name if barangay else "Unknown",
        supply_inventory_id=alloc.supply_inventory_id,
        goods_type=supply.goods_type if supply else "unknown",
        quantity_allocated=float(alloc.quantity_allocated),
        priority_score=float(alloc.priority_score),
        priority_rank=alloc.priority_rank,
        shap_explanation=alloc.shap_explanation,
        status=alloc.status,
        recommended_at=alloc.recommended_at,
        approved_at=alloc.approved_at,
        dispatched_at=alloc.dispatched_at,
        delivered_at=alloc.delivered_at,
    )


def _allocate_supplies(
    scored_barangays: list[dict],
    supplies: list[SupplyInventory],
    depot_lat: float,
    depot_lon: float,
) -> list[dict]:
    """
    OR-Tools CVRP routing + proportional quantity allocation.

    Step 1 — Run CVRP to get optimal delivery order and truck assignment.
    Step 2 — Pool all supplies by goods_type, summing across ALL sources.
             (Fixes the Week 6 bug where only the first supply_id per
             goods_type was used — multiple donations now all count.)
    Step 3 — Distribute quantities proportionally by priority_score.
    Step 4 — Return one allocation row per barangay per goods_type,
             with delivery_order and truck_id attached.
    """
    if not scored_barangays or not supplies:
        return []

    # ── Step 1: OR-Tools routing ──────────────────────────────────────────────
    scored_barangays = solve_cvrp(depot_lat, depot_lon, scored_barangays)

    # ── Step 2: Pool supplies by goods_type, keep all source IDs ─────────────
    # WHY keep all source IDs? Each SupplyInventory row is a separate donation
    # with its own warehouse location. We use the first source_id for the FK
    # in allocations (one row per barangay per goods_type) but sum all quantities.
    # OR-Tools Week 7+ extension: route from each warehouse separately.
    supply_pool: dict[str, dict] = {}
    for s in supplies:
        gt = s.goods_type
        if gt not in supply_pool:
            supply_pool[gt] = {"supply_id": s.id, "total_qty": 0.0}
        supply_pool[gt]["total_qty"] += float(s.quantity)

    # ── Step 3: Proportional distribution by priority_score ──────────────────
    total_score = sum(b["priority_score"] for b in scored_barangays)
    if total_score == 0:
        total_score = 1

    allocations = []
    for barangay in scored_barangays:
        proportion = barangay["priority_score"] / total_score

        for goods_type, pool in supply_pool.items():
            qty = round(pool["total_qty"] * proportion, 1)
            if qty <= 0:
                continue

            allocations.append(
                {
                    "barangay_id": barangay["barangay_id"],
                    "supply_inventory_id": pool["supply_id"],
                    "quantity_allocated": qty,
                    "priority_score": barangay["priority_score"],
                    "priority_rank": barangay["priority_rank"],
                    "shap_explanation": barangay["shap_explanation"],
                    "delivery_order": barangay.get(
                        "delivery_order", barangay["priority_rank"]
                    ),
                    "truck_id": barangay.get("truck_id", 0),
                }
            )

    return allocations


# ── POST /events/{event_id}/allocate ─────────────────────────────────────────


@router.post(
    "/events/{event_id}/allocate",
    response_model=list[AllocationResponse],
    status_code=status.HTTP_201_CREATED,
)
def run_allocation(
    event_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("lgu_coordinator")),
):
    """
    Trigger the AI allocation engine for a disaster event.
    Returns ranked list of allocation recommendations.
    """
    event = _get_event_or_404(event_id, db)
    _check_lgu_access(event, current_user)

    if event.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Can only run allocation on active events.",
        )

    # ── Step 1: Fetch damage reports ──────────────────────────────────────────
    reports = (
        db.query(DamageReport).filter(DamageReport.disaster_event_id == event_id).all()
    )
    if not reports:
        raise HTTPException(
            status_code=422,
            detail="No damage reports found for this event. "
            "Barangay officials must submit reports before allocation can run.",
        )

    # ── Step 2: Join barangay metadata ────────────────────────────────────────
    barangay_data = []
    for report in reports:
        barangay = db.get(Barangay, report.barangay_id)
        if not barangay:
            continue
        barangay_data.append(
            {
                # Damage report fields → ML features
                "barangay_id": report.barangay_id,
                "barangay_name": barangay.name,
                "population_affected": report.population_affected,
                "casualty_count": report.casualty_count or 0,
                "structures_damaged": report.structures_damaged or 0,
                "structures_destroyed": report.structures_destroyed or 0,
                "road_accessibility": report.road_accessibility,
                "hours_since_last_goods": report.hours_since_last_goods,
                "goods_received_qty": float(report.goods_received_qty or 0),
                # Barangay metadata → vulnerability_index feature
                "poverty_incidence_pct": float(barangay.poverty_incidence_pct or 19.5),
                "historical_disaster_count": barangay.historical_disaster_count or 0,
                # Coordinates → OR-Tools CVRP routing
                "latitude": float(barangay.latitude),
                "longitude": float(barangay.longitude),
            }
        )

    if not barangay_data:
        raise HTTPException(status_code=422, detail="No valid barangay data found.")

    # ── Step 3: Run ML scoring ────────────────────────────────────────────────
    scored = score_barangays(barangay_data)

    # ── Step 4: Fetch supply inventory ────────────────────────────────────────
    supplies = (
        db.query(SupplyInventory)
        .filter(SupplyInventory.disaster_event_id == event_id)
        .all()
    )
    if not supplies:
        raise HTTPException(
            status_code=422,
            detail="No supply inventory found for this event. "
            "Log incoming goods before running allocation.",
        )

    # ── Step 5: Delete stale 'recommended' allocations ───────────────────────
    # Preserve approved/dispatched/delivered — those are human decisions
    db.query(Allocation).filter(
        Allocation.disaster_event_id == event_id,
        Allocation.status == "recommended",
    ).delete(synchronize_session=False)

    # ── Step 6: Proportional allocation → write to DB ─────────────────────────
    # Use first supply's warehouse as the depot for OR-Tools routing
    depot_lat = float(supplies[0].warehouse_latitude)
    depot_lon = float(supplies[0].warehouse_longitude)
    allocation_plans = _allocate_supplies(scored, supplies, depot_lat, depot_lon)

    new_allocations = []
    for plan in allocation_plans:
        # Append routing info to the SHAP explanation — no schema change needed
        explanation = (
            f"{plan['shap_explanation']} "
            f"[Truck {plan['truck_id'] + 1}, Stop {plan['delivery_order']}]"
        )
        alloc = Allocation(
            disaster_event_id=event_id,
            barangay_id=plan["barangay_id"],
            supply_inventory_id=plan["supply_inventory_id"],
            quantity_allocated=plan["quantity_allocated"],
            priority_score=plan["priority_score"],
            priority_rank=plan["priority_rank"],
            shap_explanation=explanation,
            status="recommended",
        )
        db.add(alloc)
        new_allocations.append(alloc)

    db.commit()
    for alloc in new_allocations:
        db.refresh(alloc)

    # Sort by rank before returning
    new_allocations.sort(key=lambda a: a.priority_rank)
    return [_build_response(a, db) for a in new_allocations]


# ── GET /events/{event_id}/allocations ───────────────────────────────────────


@router.get(
    "/events/{event_id}/allocations",
    response_model=list[AllocationResponse],
)
def get_allocations(
    event_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch all allocation rows for an event, sorted by priority rank.
    Any authenticated user can view — barangay officials need to see
    their own allocation status.
    """
    event = _get_event_or_404(event_id, db)
    _check_lgu_access(event, current_user)

    allocations = (
        db.query(Allocation)
        .filter(Allocation.disaster_event_id == event_id)
        .order_by(Allocation.priority_rank)
        .all()
    )
    return [_build_response(a, db) for a in allocations]


# ── PATCH approve ─────────────────────────────────────────────────────────────


@router.patch(
    "/events/{event_id}/allocations/{alloc_id}/approve",
    response_model=AllocationResponse,
)
def approve_allocation(
    event_id: UUID,
    alloc_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("lgu_coordinator")),
):
    """Coordinator approves an AI recommendation — moves it to 'approved'."""
    alloc = (
        db.query(Allocation)
        .filter(
            Allocation.id == alloc_id,
            Allocation.disaster_event_id == event_id,
        )
        .first()
    )
    if not alloc:
        raise HTTPException(status_code=404, detail="Allocation not found")
    if alloc.status != "recommended":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve — current status is '{alloc.status}'",
        )

    alloc.status = "approved"
    alloc.approved_by = current_user.id
    alloc.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alloc)
    return _build_response(alloc, db)


# ── PATCH dispatch ────────────────────────────────────────────────────────────


@router.patch(
    "/events/{event_id}/allocations/{alloc_id}/dispatch",
    response_model=AllocationResponse,
)
def dispatch_allocation(
    event_id: UUID,
    alloc_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("lgu_coordinator")),
):
    """Mark goods as physically dispatched from the warehouse."""
    alloc = (
        db.query(Allocation)
        .filter(
            Allocation.id == alloc_id,
            Allocation.disaster_event_id == event_id,
        )
        .first()
    )
    if not alloc:
        raise HTTPException(status_code=404, detail="Allocation not found")
    if alloc.status != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot dispatch — must be approved first. Current status: '{alloc.status}'",
        )

    alloc.status = "dispatched"
    alloc.dispatched_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alloc)
    return _build_response(alloc, db)


# ── PATCH deliver ─────────────────────────────────────────────────────────────


@router.patch(
    "/events/{event_id}/allocations/{alloc_id}/deliver",
    response_model=AllocationResponse,
)
def confirm_delivery(
    event_id: UUID,
    alloc_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("barangay_official")),
):
    """Barangay official confirms goods were received on the ground."""
    alloc = (
        db.query(Allocation)
        .filter(
            Allocation.id == alloc_id,
            Allocation.disaster_event_id == event_id,
        )
        .first()
    )
    if not alloc:
        raise HTTPException(status_code=404, detail="Allocation not found")
    if alloc.status != "dispatched":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot confirm delivery — goods not dispatched yet. Current status: '{alloc.status}'",
        )

    alloc.status = "delivered"
    alloc.delivered_at = datetime.now(timezone.utc)
    alloc.delivery_confirmed_by = current_user.id
    db.commit()
    db.refresh(alloc)
    return _build_response(alloc, db)
