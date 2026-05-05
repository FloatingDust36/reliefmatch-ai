# backend/data/generate_training_data.py
#
# Generates synthetic training data for the XGBoost risk scoring model.
# Run once before training: python -m data.generate_training_data
#
# WHY synthetic data?
# Real Philippine disaster damage reports are scattered across NDRRMC PDFs,
# LGU spreadsheets, and DSWD situation reports — all in different formats.
# For an OJT project, we generate statistically realistic data that matches
# the feature distributions we'd expect from actual typhoon/flood events.
#
# Statistical basis:
# - Population affected: right-skewed (most barangays ~20-40% affected,
#   worst-hit can reach 90%+). Mirrors NDRRMC Typhoon Odette reports.
# - Road accessibility: ~30% cut off during major typhoons (DPWH data)
# - Hours since last goods: peaks at 48-96 hrs for isolated barangays
# - Vulnerability index: correlated with poverty incidence (PSA 2021)
#
# Output: backend/data/training_data.csv
# Columns match ML Input Schema from Doc 4 exactly.

import numpy as np
import pandas as pd
import os

# ── Reproducibility ───────────────────────────────────────────────────────────
# Fixed seed means the same CSV is generated every time.
# Consistent training data = consistent model behavior during dev/testing.
rng = np.random.default_rng(42)

N_SAMPLES = 2000  # Enough for XGBoost to generalize; small enough to train fast


def generate_dataset(n: int) -> pd.DataFrame:
    """
    Generate n rows of synthetic barangay disaster data.
    Each row is one barangay's condition during one disaster event.
    """

    # ── Feature 1: population_affected ───────────────────────────────────────
    # Range: 0 to ~15,000 (Cebu barangays range 3k-25k total population).
    # Distribution: gamma — right-skewed, matching disaster survey data.
    # Most barangays: 200-3000 affected. Extreme outliers: 8000+
    population_affected = rng.gamma(shape=2.0, scale=1200, size=n).astype(int)
    population_affected = np.clip(population_affected, 10, 15000)

    # ── Feature 2: casualty_count ─────────────────────────────────────────────
    # Strongly correlated with population affected + road accessibility.
    # Most barangays report 0-5; rare worst-case: 50+
    casualty_count = rng.poisson(lam=3.0, size=n)
    # Bump casualties for large-population events (realistic correlation)
    high_pop_mask = population_affected > 5000
    casualty_count[high_pop_mask] += rng.poisson(lam=15.0, size=high_pop_mask.sum())

    # ── Feature 3: structure_damage_pct ──────────────────────────────────────
    # Fraction of structures damaged or destroyed (0.0 = none, 1.0 = all).
    # Bimodal: mild events cluster near 0.1, severe events cluster near 0.7.
    # Beta distribution with two modes via mixture:
    mild = rng.beta(a=1.5, b=8.0, size=n)  # mostly low damage
    severe = rng.beta(a=5.0, b=2.0, size=n)  # mostly high damage
    severe_mask = rng.random(n) < 0.25  # 25% of events are severe
    structure_damage_pct = np.where(severe_mask, severe, mild)

    # ── Feature 4: road_accessibility_score ──────────────────────────────────
    # 0.0 = cut_off, 0.5 = partially_blocked, 1.0 = accessible
    # During major typhoons, ~30% cut off, ~40% partial, ~30% accessible
    road_probs = [0.30, 0.40, 0.30]  # [cut_off, partial, accessible]
    road_choices = rng.choice([0.0, 0.5, 1.0], p=road_probs, size=n)

    # ── Feature 5: hours_since_last_goods ────────────────────────────────────
    # 0 = received goods today; 240 = 10 days with nothing.
    # Distribution: exponential with high tail for isolated barangays.
    # Cut-off barangays get extra delay (road = 0.0 → harder to reach).
    base_hours = rng.exponential(scale=48.0, size=n)
    # Isolated barangays average 2x longer wait
    isolation_factor = np.where(road_choices == 0.0, 2.0, 1.0)
    hours_since_last_goods = (base_hours * isolation_factor).astype(int)
    hours_since_last_goods = np.clip(hours_since_last_goods, 0, 240)

    # ── Feature 6: goods_received_ratio ──────────────────────────────────────
    # goods_received ÷ (population × 0.3 kg/day standard).
    # 0.0 = nothing received; 1.0 = fully met need; >1.0 = oversupplied.
    # Inversely correlated with hours_since_last_goods (more time = less goods).
    # Beta distribution: most barangays under-supplied (< 0.5)
    goods_received_ratio = rng.beta(a=1.5, b=4.0, size=n)
    # Barangays with recent goods (< 12 hrs) are more likely well-supplied
    recent_goods_mask = hours_since_last_goods < 12
    goods_received_ratio[recent_goods_mask] = rng.beta(
        a=3.0, b=2.0, size=recent_goods_mask.sum()
    )

    # ── Feature 7: vulnerability_index ───────────────────────────────────────
    # Composite: poverty_incidence × historical_disaster_count, normalized 0-1.
    # Based on PSA 2021 poverty rates for Cebu barangays (8.6% to 35.2%)
    # and NDRRMC historical hit counts (2 to 11 per barangay).
    poverty = rng.uniform(0.08, 0.36, size=n)
    disaster_history = rng.integers(1, 12, size=n)
    # Normalize both to 0-1 and take weighted average
    vulnerability_index = (0.6 * poverty + 0.4 * (disaster_history / 11)).clip(0, 1)

    # ── Target: priority_score (0-100) ───────────────────────────────────────
    # This is what XGBoost will learn to predict.
    # We construct it as a weighted combination matching the feature importance
    # described in Doc 5.1, then add noise to simulate real-world variance.
    #
    # Weight rationale (must match SHAP explanation logic in ml/predictor.py):
    #   population_affected    +25 pts max  (most people = most need)
    #   road_accessibility     +30 pts max  (can't reach = can't help)
    #   hours_since_last_goods +20 pts max  (time without goods = urgency)
    #   casualty_count         +10 pts max  (injury/death = priority)
    #   structure_damage_pct   +8 pts max   (total loss = need reconstruction)
    #   goods_received_ratio   +4 pts max   (undersupplied = priority)
    #   vulnerability_index    +3 pts max   (baseline poverty amplifies need)

    score = (
        25 * (population_affected / 15000)
        + 30 * (1 - road_choices)  # road 0.0 (cut off) → full 30 pts
        + 20 * (hours_since_last_goods / 240)
        + 10 * np.tanh(casualty_count / 20)  # diminishing returns
        + 8 * structure_damage_pct
        + 4 * (1 - goods_received_ratio).clip(0, 1)
        + 3 * vulnerability_index
    )

    # Add Gaussian noise (std=5) — real data has unexplained variance
    score += rng.normal(loc=0, scale=5.0, size=n)
    score = np.clip(score, 0, 100).round(2)

    return pd.DataFrame(
        {
            "population_affected": population_affected,
            "casualty_count": casualty_count,
            "structure_damage_pct": structure_damage_pct.round(4),
            "road_accessibility_score": road_choices,
            "hours_since_last_goods": hours_since_last_goods,
            "goods_received_ratio": goods_received_ratio.round(4),
            "vulnerability_index": vulnerability_index.round(4),
            "priority_score": score,
        }
    )


if __name__ == "__main__":
    df = generate_dataset(N_SAMPLES)

    # Save relative to this file's location
    out_path = os.path.join(os.path.dirname(__file__), "training_data.csv")
    df.to_csv(out_path, index=False)

    print(f"✅ Generated {len(df)} training samples → {out_path}")
    print("\nFeature summary:")
    print(df.describe().round(2).to_string())
    print(f"\nPriority score distribution:")
    print(f"  Min:    {df.priority_score.min():.1f}")
    print(f"  Median: {df.priority_score.median():.1f}")
    print(f"  Max:    {df.priority_score.max():.1f}")
    print(f"  High urgency (>70): {(df.priority_score > 70).sum()} barangays")
    print(f"  Critical (>85):     {(df.priority_score > 85).sum()} barangays")
