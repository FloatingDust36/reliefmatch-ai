# backend/app/ml/predictor.py
#
# Inference module — loaded once at startup, called on every /allocate request.
#
# Architecture decision: model is loaded into a module-level singleton (MODEL).
# Why not reload on every request?
# - Loading a .pkl file takes ~200ms — unacceptable for a real-time API
# - FastAPI is async but model.predict() is sync CPU work — that's fine,
#   XGBoost inference is fast enough (~2ms for 8 barangays)
# - If you need to hot-reload the model after retraining, restart Uvicorn.
#   For production, use a model registry (MLflow/Vertex) with version pinning.
#
# SHAP approach: TreeExplainer
# - Exact SHAP values for tree models (not approximations like KernelExplainer)
# - ~5ms per call for our 7-feature model — acceptable for a web request
# - Returns the marginal contribution of each feature to the prediction
#   relative to the expected value across all training samples
#
# The plain-English generation (shap_to_text) intentionally mirrors
# how an NDRRMC situation report describes barangay conditions.
# Coordinators should be able to read these and immediately understand why
# Brgy. X is ranked #1 without needing to understand ML.

import os
import pickle
import logging
from typing import List

import numpy as np
import shap

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
MODEL_PATH = os.path.join(os.path.dirname(__file__), "risk_model.pkl")

# ── Feature column order (MUST match training order exactly) ─────────────────
FEATURE_COLS = [
    "population_affected",
    "casualty_count",
    "structure_damage_pct",
    "road_accessibility_score",
    "hours_since_last_goods",
    "goods_received_ratio",
    "vulnerability_index",
]

# ── Singleton model + explainer ───────────────────────────────────────────────
# Module-level: loaded once when FastAPI imports this module.
# If the .pkl doesn't exist (first run before training), we log a warning
# and return fallback scores — so the API doesn't crash during setup.

_model = None
_explainer = None


def _load_model():
    global _model, _explainer
    if not os.path.exists(MODEL_PATH):
        logger.warning(
            "risk_model.pkl not found. Run: python -m app.ml.train\n"
            "The /allocate endpoint will use heuristic fallback scores until then."
        )
        return

    with open(MODEL_PATH, "rb") as f:
        _model = pickle.load(f)

    # TreeExplainer is initialized with the model, not the data.
    # It computes exact Shapley values by traversing the decision trees.
    _explainer = shap.TreeExplainer(_model)
    logger.info("XGBoost risk model loaded successfully")


# Load on import — FastAPI will trigger this when it starts
_load_model()


# ── Feature engineering ───────────────────────────────────────────────────────
# These transformations convert raw damage report data (from the DB)
# into the numeric features the model was trained on.
# Mirrors the feature engineering described in Doc 4, Part B.


def _road_to_score(road_accessibility: str) -> float:
    """Convert VARCHAR road field to 0/0.5/1.0 float."""
    return {
        "accessible": 1.0,
        "partially_blocked": 0.5,
        "cut_off": 0.0,
    }.get(
        road_accessibility, 0.5
    )  # default to partial if unexpected value


def _compute_goods_received_ratio(
    goods_received_qty: float,
    population_affected: int,
) -> float:
    """
    goods_received ÷ (population × 0.3 kg/day standard).
    0.3 kg/day is the DSWD minimum relief standard per person per day.
    Ratio > 1.0 means oversupplied; < 1.0 means under-served.
    """
    daily_need = population_affected * 0.3
    if daily_need <= 0:
        return 0.0
    return float(goods_received_qty) / daily_need


def _compute_vulnerability_index(
    poverty_incidence_pct: float | None,
    historical_disaster_count: int,
) -> float:
    """
    Composite vulnerability score (0-1).
    Matches the generate_training_data.py formula exactly —
    consistent feature engineering between training and inference is critical.
    If the poverty figure is missing (nullable in schema), use the Cebu median.
    """
    poverty = (poverty_incidence_pct or 19.5) / 100  # normalize to 0-1
    disaster_norm = min(historical_disaster_count, 11) / 11
    return 0.6 * poverty + 0.4 * disaster_norm


# ── SHAP → Plain English ──────────────────────────────────────────────────────


def _shap_to_text(
    shap_values: np.ndarray,
    feature_values: dict,
    priority_score: float,
    priority_rank: int,
    barangay_name: str,
) -> str:
    """
    Convert SHAP values into a human-readable explanation string.

    Format: "Brgy. X ranked #N because: <reason1> (+X pts), <reason2> (+Y pts), ..."
    The coordinator sees this in the allocation table and map popups.

    We take the top 3 contributors (by absolute SHAP value) and describe them
    in plain language that a Cebu City DRRMO officer would understand.
    """
    feature_names = FEATURE_COLS
    shap_array = np.array(shap_values)

    # Sort features by absolute SHAP value, descending
    sorted_indices = np.argsort(np.abs(shap_array))[::-1]
    top_3 = sorted_indices[:3]

    reasons = []
    for idx in top_3:
        fname = feature_names[idx]
        shap_val = shap_array[idx]
        fval = feature_values.get(fname, 0)
        direction = "+" if shap_val > 0 else "-"
        pts = abs(round(shap_val, 1))

        # Human-readable descriptions for each feature
        if fname == "population_affected":
            reasons.append(f"{int(fval):,} residents affected ({direction}{pts} pts)")
        elif fname == "road_accessibility_score":
            road_label = {
                0.0: "no road access",
                0.5: "partial road access",
                1.0: "road clear",
            }.get(fval, "road access unknown")
            reasons.append(f"{road_label} ({direction}{pts} pts)")
        elif fname == "hours_since_last_goods":
            days = int(fval) // 24
            hrs = int(fval) % 24
            if days > 0:
                time_str = f"{days}d {hrs}h without goods"
            else:
                time_str = f"{int(fval)} hrs without goods"
            reasons.append(f"{time_str} ({direction}{pts} pts)")
        elif fname == "casualty_count":
            reasons.append(f"{int(fval)} casualties reported ({direction}{pts} pts)")
        elif fname == "structure_damage_pct":
            reasons.append(
                f"{round(fval * 100, 0):.0f}% structures damaged ({direction}{pts} pts)"
            )
        elif fname == "goods_received_ratio":
            if fval < 0.5:
                desc = f"only {round(fval * 100):.0f}% of daily need received"
            elif fval > 1.0:
                desc = "supply exceeds current need"
            else:
                desc = f"{round(fval * 100):.0f}% of daily need received"
            reasons.append(f"{desc} ({direction}{pts} pts)")
        elif fname == "vulnerability_index":
            reasons.append(f"high poverty/disaster-history area ({direction}{pts} pts)")

    reason_str = ", ".join(reasons)
    return (
        f"Brgy. {barangay_name} ranked #{priority_rank} "
        f"(score: {priority_score:.0f}/100) because: {reason_str}"
    )


# ── Main inference function ───────────────────────────────────────────────────


def score_barangays(barangay_reports: list[dict]) -> list[dict]:
    """
    Score and rank barangays by disaster relief urgency.

    Input:  list of dicts, one per barangay, containing damage report
            fields + barangay metadata (name, poverty_incidence_pct,
            historical_disaster_count).

    Output: same list, sorted by priority_score descending, with added:
            - priority_score (float 0-100)
            - priority_rank (int, 1 = most urgent)
            - shap_explanation (str, plain English)

    If the model hasn't been trained yet, falls back to a heuristic
    that mirrors the training data's weight logic — so you can test
    the full API flow even before Week 6 ML is complete.
    """
    if not barangay_reports:
        return []

    # ── Feature engineering ───────────────────────────────────────────────────
    feature_rows = []
    for r in barangay_reports:
        pop = r.get("population_affected", 0)
        row = {
            "population_affected": pop,
            "casualty_count": r.get("casualty_count", 0),
            "structure_damage_pct": _compute_structure_pct(r),
            "road_accessibility_score": _road_to_score(
                r.get("road_accessibility", "accessible")
            ),
            "hours_since_last_goods": float(r.get("hours_since_last_goods") or 240),
            "goods_received_ratio": _compute_goods_received_ratio(
                r.get("goods_received_qty", 0), pop
            ),
            "vulnerability_index": _compute_vulnerability_index(
                r.get("poverty_incidence_pct"),
                r.get("historical_disaster_count", 0),
            ),
        }
        feature_rows.append(row)

    import pandas as pd

    X = pd.DataFrame(feature_rows)[FEATURE_COLS]

    # ── Predict ───────────────────────────────────────────────────────────────
    if _model is None:
        logger.warning("Model not loaded — using heuristic fallback scores")
        scores = _heuristic_scores(feature_rows)
        shap_values_list = [None] * len(scores)
    else:
        scores = _model.predict(X).tolist()
        # SHAP values shape: (n_samples, n_features)
        shap_values_matrix = _explainer.shap_values(X)
        shap_values_list = shap_values_matrix.tolist()

    # ── Rank + attach explanations ────────────────────────────────────────────
    scored = []
    for i, (report, score) in enumerate(zip(barangay_reports, scores)):
        scored.append(
            {
                **report,
                "priority_score": round(float(score), 2),
                "_shap_values": shap_values_list[i],
                "_feature_values": feature_rows[i],
            }
        )

    # Sort descending — rank 1 is the most urgent
    scored.sort(key=lambda x: x["priority_score"], reverse=True)

    # Attach rank + plain-English explanation
    for rank, item in enumerate(scored, start=1):
        shap_vals = item.pop("_shap_values")
        feat_vals = item.pop("_feature_values")

        item["priority_rank"] = rank

        if shap_vals is not None:
            item["shap_explanation"] = _shap_to_text(
                shap_vals,
                feat_vals,
                item["priority_score"],
                rank,
                item.get("barangay_name", f"Barangay #{rank}"),
            )
        else:
            # Fallback explanation when model isn't loaded
            item["shap_explanation"] = (
                f"Brgy. {item.get('barangay_name', '?')} ranked #{rank} "
                f"(score: {item['priority_score']:.0f}/100) — "
                f"heuristic: {item.get('population_affected', 0):,} affected, "
                f"road: {item.get('road_accessibility', 'unknown')}, "
                f"{item.get('hours_since_last_goods', 0)} hrs without goods"
            )

    return scored


def _compute_structure_pct(report: dict) -> float:
    """
    Estimate structure_damage_pct from raw counts.
    The damage report stores damaged+destroyed counts; we need a fraction.
    We use a rough estimate: typical Cebu barangay ~population/4 households.
    """
    population = report.get("population_affected", 1) or 1
    # Assume ~4 persons per household as the Philippine average (PSA 2020)
    est_total_structures = max(population // 4, 1)
    damaged = report.get("structures_damaged", 0) or 0
    destroyed = report.get("structures_destroyed", 0) or 0
    return min((damaged + destroyed) / est_total_structures, 1.0)


def _heuristic_scores(feature_rows: list[dict]) -> list[float]:
    """
    Fallback when model.pkl doesn't exist yet.
    Mirrors the weight logic from generate_training_data.py exactly,
    so the API returns meaningful scores even before Week 6 training.
    """
    scores = []
    for r in feature_rows:
        score = (
            25 * (r["population_affected"] / 15000)
            + 30 * (1 - r["road_accessibility_score"])
            + 20 * (r["hours_since_last_goods"] / 240)
            + 10 * float(np.tanh(r["casualty_count"] / 20))
            + 8 * r["structure_damage_pct"]
            + 4 * max(0, 1 - r["goods_received_ratio"])
            + 3 * r["vulnerability_index"]
        )
        scores.append(round(float(np.clip(score, 0, 100)), 2))
    return scores
