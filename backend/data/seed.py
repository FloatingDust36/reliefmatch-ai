# backend/data/seed.py
# Loads realistic Philippine disaster scenario data for development and testing.
# Run once: python -m data.seed (from backend/ with venv active)
# All data is based on actual Cebu City geography and PSA poverty stats.

from app.models.models import LGU, Barangay, User, DisasterEvent, DamageReport, SupplyInventory
from app.core.database import SessionLocal
from datetime import datetime, timezone
import bcrypt
import sys
import os
# Path fix must come BEFORE any app imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def hash_password(password: str) -> str:
    # Call bcrypt directly — passlib is incompatible with bcrypt 4.x on Python 3.13
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def seed():
    db = SessionLocal()
    try:
        # ── LGU ──────────────────────────────────────────────────────────────
        cebu_city = LGU(
            name="Cebu City",
            region="Region VII - Central Visayas",
            province="Cebu",
            latitude=10.3157,
            longitude=123.8854,
        )
        db.add(cebu_city)
        db.flush()  # flush to get the UUID before referencing it below

        # ── BARANGAYS (real Cebu City barangays with realistic PSA data) ─────
        barangays_data = [
            # name, population, lat, lng, poverty_pct, disaster_count
            ("Inayawan",      8_420,  10.2889, 123.8622, 28.4, 7),
            ("Labangon",     12_310,  10.2983, 123.8711, 19.2, 5),
            ("Mambaling",    22_100,  10.2914, 123.8760, 31.7, 9),
            ("Ermita",        6_890,  10.3042, 123.8923, 12.1, 3),
            ("Lahug",        18_540,  10.3301, 123.8941, 8.6,  2),
            ("Duljo-Fatima", 15_670,  10.2841, 123.8798, 35.2, 11),
            ("Basak Pardo",  11_230,  10.2762, 123.8681, 29.8, 8),
            ("Calamba",       9_870,  10.3089, 123.8556, 22.5, 6),
        ]

        barangay_objects = []
        for name, pop, lat, lng, poverty, disaster_cnt in barangays_data:
            b = Barangay(
                name=name,
                lgu_id=cebu_city.id,
                population=pop,
                latitude=lat,
                longitude=lng,
                poverty_incidence_pct=poverty,
                historical_disaster_count=disaster_cnt,
            )
            db.add(b)
            barangay_objects.append(b)
        db.flush()

        # ── USERS ─────────────────────────────────────────────────────────────
        super_admin = User(
            email="admin@reliefmatch.ph",
            hashed_password=hash_password("Admin@1234!"),
            full_name="System Administrator",
            role="super_admin",
        )
        coordinator = User(
            email="coordinator@cebu.gov.ph",
            hashed_password=hash_password("Coord@1234!"),
            full_name="Maria Santos",
            role="lgu_coordinator",
            lgu_id=cebu_city.id,
        )
        # One barangay official per the highest-risk barangay
        brgy_official = User(
            email="official@duljo.cebu.gov.ph",
            hashed_password=hash_password("Official@1234!"),
            full_name="Jose dela Cruz",
            role="barangay_official",
            lgu_id=cebu_city.id,
            # Duljo-Fatima — highest poverty
            barangay_id=barangay_objects[5].id,
        )
        db.add_all([super_admin, coordinator, brgy_official])
        db.flush()

        # ── DISASTER EVENT ────────────────────────────────────────────────────
        event = DisasterEvent(
            lgu_id=cebu_city.id,
            name="Typhoon Carina — July 2024",
            disaster_type="typhoon",
            status="active",
            declared_at=datetime(2024, 7, 24, 8, 0, tzinfo=timezone.utc),
            created_by=coordinator.id,
        )
        db.add(event)
        db.flush()

        # ── DAMAGE REPORTS (one per barangay, varied severity) ────────────────
        reports_data = [
            # brgy_idx, pop_affected, casualties, dmg, destr, road, power, water, hrs_since, goods_kg
            (0, 3200, 12, 145, 38, "partially_blocked",
             False, True,  72,  0),    # Inayawan
            (1, 5800, 4,  210, 15, "accessible",
             True,  True,  48,  450),  # Labangon
            (2, 9100, 31, 380, 97, "cut_off",           False,
             False, None, 0),   # Mambaling — worst
            (3, 1200, 1,  45,  3,  "accessible",
             True,  True,  24,  800),  # Ermita — best off
            (4, 2100, 0,  30,  2,  "accessible",
             True,  True,  12,  1200),  # Lahug
            (5, 7800, 19, 290, 74, "cut_off",
             False, False, None, 0),   # Duljo-Fatima
            (6, 4100, 8,  160, 41, "partially_blocked",
             False, True,  96,  200),  # Basak Pardo
            (7, 3300, 3,  120, 22, "partially_blocked",
             True,  True,  60,  150),  # Calamba
        ]

        for (bi, pa, cas, dmg, dst, road, pwr, wtr, hrs, goods) in reports_data:
            # rough household estimate
            total_structures = barangay_objects[bi].population // 4
            r = DamageReport(
                disaster_event_id=event.id,
                barangay_id=barangay_objects[bi].id,
                submitted_by=brgy_official.id if bi == 5 else coordinator.id,
                population_affected=pa,
                casualty_count=cas,
                structures_damaged=dmg,
                structures_destroyed=dst,
                road_accessibility=road,
                has_power=pwr,
                has_water=wtr,
                hours_since_last_goods=hrs,
                goods_received_qty=goods,
                special_needs_notes="Elderly residents and infants in evacuation center" if bi in [
                    2, 5] else None,
            )
            db.add(r)

        # ── SUPPLY INVENTORY (what DSWD and partners donated) ─────────────────
        supplies = [
            ("food_pack", 2500,  "packs",
             "DSWD Region VII",        10.3180, 123.9022),
            ("water",     8000,  "liters",
             "Philippine Red Cross",   10.3212, 123.8867),
            ("medicine",  350,   "boxes",
             "DOH Central Visayas",    10.3301, 123.8941),
            ("hygiene_kit", 900,  "packs",
             "SM Foundation",          10.3267, 123.9053),
            ("food_pack", 1200,  "packs",
             "Cebu City LGU Stockpile", 10.3157, 123.8854),
        ]
        for gtype, qty, unit, src, wlat, wlng in supplies:
            s = SupplyInventory(
                disaster_event_id=event.id,
                goods_type=gtype,
                quantity=qty,
                unit=unit,
                source_name=src,
                warehouse_latitude=wlat,
                warehouse_longitude=wlng,
                logged_by=coordinator.id,
            )
            db.add(s)

        db.commit()
        print("✅ Seed complete!")
        print(f"   LGU: {cebu_city.name}")
        print(f"   Barangays: {len(barangay_objects)}")
        print(f"   Event: {event.name}")
        print(f"   Damage reports: {len(reports_data)}")
        print(f"   Supply lines: {len(supplies)}")
        print("\nTest credentials:")
        print("  admin@reliefmatch.ph        / Admin@1234!")
        print("  coordinator@cebu.gov.ph     / Coord@1234!")
        print("  official@duljo.cebu.gov.ph  / Official@1234!")

    except Exception as e:
        db.rollback()
        print(f"❌ Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
