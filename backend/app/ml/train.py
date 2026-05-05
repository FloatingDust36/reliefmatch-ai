# backend/app/ml/train.py
#
# Trains the XGBoost risk scoring model on synthetic PH disaster data.
# Run once (or after regenerating training data):
#   python -m app.ml.train
# from backend/ with venv active.
#
# Output: backend/app/ml/risk_model.pkl
# The model file is loaded at startup by predictor.py and reused for
# every POST /events/{event_id}/allocate call.
#
# WHY XGBoost and not a neural network?
# 1. Tabular data with 7 features — XGBoost consistently beats deep learning here
# 2. Fast inference: ~2ms per prediction vs ~50ms for even a small NN
# 3. SHAP values are exact for tree models (TreeExplainer), not approximate
# 4. Interpretability: Cebu City DRRMO can audit individual feature contributions
#    for each barangay — critical for public sector accountability
#
# WHY save as .pkl and not ONNX or a cloud endpoint?
# Simplicity and free hosting. .pkl works on Render's free tier with no
# additional services. For production at scale, ONNX or MLflow would be better.

import os
import sys
import pickle

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
from xgboost import XGBRegressor

# Path fix — allows running as python -m app.ml.train from backend/
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "training_data.csv"
)
MODEL_PATH = os.path.join(os.path.dirname(__file__), "risk_model.pkl")

# ── Feature columns (must match ML Input Schema in Doc 4) ────────────────────
FEATURE_COLS = [
    "population_affected",
    "casualty_count",
    "structure_damage_pct",
    "road_accessibility_score",
    "hours_since_last_goods",
    "goods_received_ratio",
    "vulnerability_index",
]
TARGET_COL = "priority_score"


def train():
    # ── Load data ─────────────────────────────────────────────────────────────
    data_path = os.path.normpath(DATA_PATH)
    if not os.path.exists(data_path):
        raise FileNotFoundError(
            f"Training data not found at {data_path}\n"
            "Run: python -m data.generate_training_data"
        )

    df = pd.read_csv(data_path)
    print(f"Loaded {len(df)} training samples")

    X = df[FEATURE_COLS]
    y = df[TARGET_COL]

    # ── Train/test split ──────────────────────────────────────────────────────
    # 80/20 split — standard for regression on tabular data.
    # random_state=42 ensures reproducible evaluation metrics.
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # ── Model hyperparameters ─────────────────────────────────────────────────
    # These are tuned for our 7-feature, 2000-sample dataset.
    # n_estimators=200: enough trees to fit well, not so many we overfit
    # max_depth=4: shallow trees for a low-dimensional problem
    # learning_rate=0.1: standard starting point; lower = more robust but slower
    # subsample=0.8: row sampling per tree — reduces overfitting
    # colsample_bytree=0.8: feature sampling per tree — reduces correlation
    # min_child_weight=5: minimum sum of instance weight in a leaf — prevents
    #   the model from creating splits that only explain 1-2 data points
    model = XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        objective="reg:squarederror",
        random_state=42,
        n_jobs=-1,  # use all CPU cores
        verbosity=0,  # suppress XGBoost training output
    )

    print("Training XGBoost model...")
    model.fit(X_train, y_train)

    # ── Evaluation ────────────────────────────────────────────────────────────
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)

    print(f"\n📊 Evaluation on held-out test set ({len(X_test)} samples):")
    print(f"   MAE:  {mae:.2f} points  (average prediction error out of 100)")
    print(f"   R²:   {r2:.4f}          (1.0 = perfect, 0 = useless baseline)")

    # For our use case, MAE < 8 points is excellent — it means the model's
    # allocation ranking is accurate even if the exact score is off.
    if mae > 12:
        print(
            "⚠️  MAE is high — consider retraining with more data or tuning hyperparameters"
        )
    else:
        print("✅ Model performance is acceptable for production use")

    # ── Feature importance ────────────────────────────────────────────────────
    print("\n📈 Feature importance (gain — how much each feature reduces loss):")
    importance = model.get_booster().get_score(importance_type="gain")
    for feat, score in sorted(importance.items(), key=lambda x: -x[1]):
        print(f"   {feat:<30} {score:.1f}")

    # ── Save model ────────────────────────────────────────────────────────────
    model_path = os.path.normpath(MODEL_PATH)
    os.makedirs(os.path.dirname(model_path), exist_ok=True)

    with open(model_path, "wb") as f:
        pickle.dump(model, f)

    print(f"\n💾 Model saved → {model_path}")
    print("\nNext step: start FastAPI and call POST /events/{event_id}/allocate")


if __name__ == "__main__":
    train()
