"""Train ExtraTreesRegressor on supplied dataset features."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from badge_layout import FEATURE_SCHEMA_VERSION
from feature_extraction import FEATURE_SCHEMA

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"
FEATURES_CSV = DATA_DIR / "features_all.csv"
MODEL_NAME = "sentinel_h2s_model_v1.joblib"
METADATA_NAME = "sentinel_h2s_model_v1_metadata.json"


def train() -> Path:
    if not FEATURES_CSV.exists():
        raise FileNotFoundError(f"Run extract_features.py first — missing {FEATURES_CSV}")

    df = pd.read_csv(FEATURES_CSV)
    train_df = df[df["split"].isin(["train", "validation"])].copy()
    if train_df.empty:
        train_df = df[df["split"] == "train"].copy()

    X = train_df[FEATURE_SCHEMA].values.astype(np.float64)
    y = train_df["h2s_concentration_ppm"].values.astype(np.float64)

    model = ExtraTreesRegressor(
        n_estimators=200,
        max_depth=10,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X, y)

    train_pred = model.predict(X)
    train_rmse = float(np.sqrt(mean_squared_error(y, train_pred)))
    train_mae = float(mean_absolute_error(y, train_pred))
    train_r2 = float(r2_score(y, train_pred))

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = MODELS_DIR / MODEL_NAME

    metadata = {
        "model_name": "SENTINEL-H2S-v1",
        "model_version": "SENTINEL-H2S-v1",
        "model_type": "ExtraTreesRegressor",
        "model_state": "TRAINED",
        "feature_schema": FEATURE_SCHEMA,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "dataset_type": "synthetic_development",
        "dataset_id": "sentinel_synthetic_dataset-v3",
        "label_source": "literature_derived_proxy",
        "is_lab_validated": False,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_samples": int(len(train_df)),
        "split_counts": df["split"].value_counts().to_dict(),
        "metrics": {
            "train_rmse": round(train_rmse, 4),
            "train_mae": round(train_mae, 4),
            "train_r2": round(train_r2, 4),
        },
        "target": "h2s_concentration_ppm",
        "delta_e_max": float(df["delta_e"].max()) if "delta_e" in df.columns else 55.0,
    }

    payload = {"model": model, **metadata}
    joblib.dump(payload, out_path)

    meta_path = MODELS_DIR / METADATA_NAME
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"Saved {out_path}")
    print(f"Train RMSE: {train_rmse:.3f} | MAE: {train_mae:.3f} | R²: {train_r2:.3f}")
    return out_path


if __name__ == "__main__":
    train()
