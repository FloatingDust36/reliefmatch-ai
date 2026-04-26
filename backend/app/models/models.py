# backend/app/models/models.py
# SQLAlchemy ORM models — one class per database table.
# These are the Python representations of your schema from Doc 3.
# Alembic reads these to generate migration scripts automatically.
#
# Why UUID primary keys instead of integers?
# 1. Security: attackers can't guess /reports/1, /reports/2...
# 2. Mergeability: if we ever federate data across LGUs, no ID collisions
# 3. Industry standard for multi-tenant systems like this

import uuid
from sqlalchemy import (
    Boolean, Column, DateTime, DECIMAL, ForeignKey,
    Integer, String, Text, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class LGU(Base):
    __tablename__ = "lgus"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)           # e.g. "Cebu City"
    # e.g. "Region VII - Central Visayas"
    region = Column(String(100), nullable=False)
    province = Column(String(100), nullable=False)
    latitude = Column(DECIMAL(10, 7), nullable=False)
    longitude = Column(DECIMAL(10, 7), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships — SQLAlchemy uses these for ORM joins, not FK constraints
    barangays = relationship("Barangay", back_populates="lgu")
    disaster_events = relationship("DisasterEvent", back_populates="lgu")
    users = relationship("User", back_populates="lgu")


class Barangay(Base):
    __tablename__ = "barangays"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    lgu_id = Column(UUID(as_uuid=True), ForeignKey("lgus.id"), nullable=False)
    population = Column(Integer, nullable=False)
    latitude = Column(DECIMAL(10, 7), nullable=False)
    longitude = Column(DECIMAL(10, 7), nullable=False)
    # PSA data — used in the vulnerability_index feature for XGBoost
    poverty_incidence_pct = Column(DECIMAL(5, 2), nullable=True)
    # How many past disasters hit this barangay — feeds ML vulnerability score
    historical_disaster_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lgu = relationship("LGU", back_populates="barangays")
    damage_reports = relationship("DamageReport", back_populates="barangay")
    allocations = relationship("Allocation", back_populates="barangay")
    users = relationship("User", back_populates="barangay")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(Text, nullable=False)
    full_name = Column(String(255), nullable=False)
    # Role drives all permission checks — see Doc 4 for which endpoints each role can hit
    # super_admin | lgu_coordinator | barangay_official
    role = Column(String(50), nullable=False)
    lgu_id = Column(UUID(as_uuid=True), ForeignKey("lgus.id"), nullable=True)
    barangay_id = Column(UUID(as_uuid=True), ForeignKey(
        "barangays.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    lgu = relationship("LGU", back_populates="users")
    barangay = relationship("Barangay", back_populates="users")
    submitted_reports = relationship("DamageReport", back_populates="submitted_by_user",
                                     foreign_keys="DamageReport.submitted_by")
    created_events = relationship(
        "DisasterEvent", back_populates="created_by_user")
    logged_supplies = relationship(
        "SupplyInventory", back_populates="logged_by_user")
    approved_allocations = relationship("Allocation", back_populates="approved_by_user",
                                        foreign_keys="Allocation.approved_by")
    confirmed_deliveries = relationship("Allocation", back_populates="delivery_confirmed_by_user",
                                        foreign_keys="Allocation.delivery_confirmed_by")


class DisasterEvent(Base):
    __tablename__ = "disaster_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lgu_id = Column(UUID(as_uuid=True), ForeignKey("lgus.id"), nullable=False)
    # e.g. "Typhoon Carina — July 2024"
    name = Column(String(255), nullable=False)
    # Constraining disaster_type here keeps data clean for ML feature engineering
    # typhoon|earthquake|flood|landslide|fire
    disaster_type = Column(String(100), nullable=False)
    # active|closed|archived
    status = Column(String(50), default="active")
    declared_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey(
        "users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lgu = relationship("LGU", back_populates="disaster_events")
    created_by_user = relationship("User", back_populates="created_events")
    damage_reports = relationship(
        "DamageReport", back_populates="disaster_event")
    supply_inventory = relationship(
        "SupplyInventory", back_populates="disaster_event")
    allocations = relationship("Allocation", back_populates="disaster_event")


class DamageReport(Base):
    __tablename__ = "damage_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    disaster_event_id = Column(UUID(as_uuid=True), ForeignKey(
        "disaster_events.id"), nullable=False)
    barangay_id = Column(UUID(as_uuid=True), ForeignKey(
        "barangays.id"), nullable=False)
    submitted_by = Column(UUID(as_uuid=True),
                          ForeignKey("users.id"), nullable=False)

    # These columns feed directly into the XGBoost feature vector (see Doc 4, ML Input Schema)
    population_affected = Column(Integer, nullable=False)
    casualty_count = Column(Integer, default=0)
    structures_damaged = Column(Integer, default=0)
    structures_destroyed = Column(Integer, default=0)
    # road_accessibility is VARCHAR here; the ML service converts to 0/0.5/1.0 float
    # accessible|partially_blocked|cut_off
    road_accessibility = Column(String(50), nullable=False)
    has_power = Column(Boolean, default=True)
    has_water = Column(Boolean, default=True)
    # null = never received goods before this event
    hours_since_last_goods = Column(Integer, nullable=True)
    # in kg, total for this event
    goods_received_qty = Column(DECIMAL(10, 2), default=0)
    special_needs_notes = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())

    disaster_event = relationship(
        "DisasterEvent", back_populates="damage_reports")
    barangay = relationship("Barangay", back_populates="damage_reports")
    submitted_by_user = relationship("User", back_populates="submitted_reports",
                                     foreign_keys=[submitted_by])


class SupplyInventory(Base):
    __tablename__ = "supply_inventory"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    disaster_event_id = Column(UUID(as_uuid=True), ForeignKey(
        "disaster_events.id"), nullable=False)
    # goods_type is the basis for OR-Tools allocation by category
    # food_pack|water|medicine|clothing|hygiene_kit|other
    goods_type = Column(String(100), nullable=False)
    quantity = Column(DECIMAL(10, 2), nullable=False)
    unit = Column(String(50), nullable=False)           # kg|packs|liters|boxes
    # e.g. "DSWD Region VII"
    source_name = Column(String(255), nullable=False)
    # Warehouse coords feed into OR-Tools as the depot/starting point for routing
    warehouse_latitude = Column(DECIMAL(10, 7), nullable=False)
    warehouse_longitude = Column(DECIMAL(10, 7), nullable=False)
    received_at = Column(DateTime(timezone=True), server_default=func.now())
    logged_by = Column(UUID(as_uuid=True), ForeignKey(
        "users.id"), nullable=False)

    disaster_event = relationship(
        "DisasterEvent", back_populates="supply_inventory")
    logged_by_user = relationship("User", back_populates="logged_supplies")
    allocations = relationship("Allocation", back_populates="supply_inventory")


class Allocation(Base):
    __tablename__ = "allocations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    disaster_event_id = Column(UUID(as_uuid=True), ForeignKey(
        "disaster_events.id"), nullable=False)
    barangay_id = Column(UUID(as_uuid=True), ForeignKey(
        "barangays.id"), nullable=False)
    supply_inventory_id = Column(UUID(as_uuid=True), ForeignKey(
        "supply_inventory.id"), nullable=False)
    quantity_allocated = Column(DECIMAL(10, 2), nullable=False)
    # priority_score is the XGBoost output — stored here for audit trail
    priority_score = Column(DECIMAL(5, 2), nullable=False)
    priority_rank = Column(Integer, nullable=False)
    # shap_explanation stores the plain-English string from Doc 5.3
    # e.g. "Brgy. San Roque ranked #1 because: 847 people displaced (+42 pts)..."
    shap_explanation = Column(Text, nullable=False)
    # recommended|approved|dispatched|delivered|cancelled
    status = Column(String(50), default="recommended")

    recommended_at = Column(DateTime(timezone=True), server_default=func.now())
    # These three audit columns track the human decisions on top of the AI recommendation
    approved_by = Column(UUID(as_uuid=True),
                         ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    delivery_confirmed_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    disaster_event = relationship(
        "DisasterEvent", back_populates="allocations")
    barangay = relationship("Barangay", back_populates="allocations")
    supply_inventory = relationship(
        "SupplyInventory", back_populates="allocations")
    approved_by_user = relationship("User", back_populates="approved_allocations",
                                    foreign_keys=[approved_by])
    delivery_confirmed_by_user = relationship("User", back_populates="confirmed_deliveries",
                                              foreign_keys=[delivery_confirmed_by])
