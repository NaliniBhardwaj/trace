"""Evaluate trained model on test + holdout splits; generate proof graphs."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from feature_extraction import FEATURE_SCHEMA

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"
FEATURES_CSV = DATA_DIR / "features_all.csv"
MODEL_PATH = MODELS_DIR / "sentinel_h2s_model_v1.joblib"
METADATA_PATH = MODELS_DIR / "sentinel_h2s_model_v1_metadata.json"


def _metrics(y_true, y_pred):
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "r2": float(r2_score(y_true, y_pred)),
        "samples": int(len(y_true)),
    }


def evaluate() -> dict:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Train first — missing {MODEL_PATH}")
    df = pd.read_csv(FEATURES_CSV)
    payload = joblib.load(MODEL_PATH)
    model = payload["model"]

    eval_df = df[df["split"].isin(["test", "holdout"])].copy()
    if eval_df.empty:
        eval_df = df[df["split"] == "test"].copy()

    X = eval_df[FEATURE_SCHEMA].values.astype(np.float64)
    y = eval_df["h2s_concentration_ppm"].values.astype(np.float64)
    pred = model.predict(X)

    overall = _metrics(y, pred)
    by_split = {}
    for split in eval_df["split"].unique():
        mask = eval_df["split"] == split
        by_split[split] = _metrics(y[mask], pred[mask])

    by_lighting = {}
    if "lighting_type" in eval_df.columns:
        for lt in eval_df["lighting_type"].unique():
            mask = eval_df["lighting_type"] == lt
            if mask.sum() > 0:
                by_lighting[str(lt)] = _metrics(y[mask], pred[mask])

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Predicted vs actual scatter
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(y, pred, alpha=0.7, edgecolors="k", linewidths=0.5)
    lims = [0, max(y.max(), pred.max()) * 1.1]
    ax.plot(lims, lims, "r--", label="Perfect prediction")
    ax.set_xlabel("Actual H₂S (ppm)")
    ax.set_ylabel("Predicted H₂S (ppm)")
    ax.set_title(f"Test set: MAE={overall['mae']:.2f}, RMSE={overall['rmse']:.2f}, R²={overall['r2']:.3f}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(REPORTS_DIR / "predicted_vs_actual.png", dpi=120)
    plt.close(fig)

    # Residuals
    residuals = pred - y
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(residuals, bins=15, edgecolor="black", alpha=0.7)
    ax.axvline(0, color="r", linestyle="--")
    ax.set_xlabel("Prediction error (ppm)")
    ax.set_ylabel("Count")
    ax.set_title("Residual distribution (test + holdout)")
    fig.tight_layout()
    fig.savefig(REPORTS_DIR / "residuals.png", dpi=120)
    plt.close(fig)

    # Feature importance
    if hasattr(model, "feature_importances_"):
        imp = model.feature_importances_
        idx = np.argsort(imp)[::-1][:12]
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.barh([FEATURE_SCHEMA[i] for i in idx[::-1]], imp[idx[::-1]])
        ax.set_xlabel("Importance")
        ax.set_title("Top feature importances (ExtraTrees)")
        fig.tight_layout()
        fig.savefig(REPORTS_DIR / "feature_importance.png", dpi=120)
        plt.close(fig)

    # Metrics by lighting
    if by_lighting:
        fig, ax = plt.subplots(figsize=(7, 4))
        lights = list(by_lighting.keys())
        maes = [by_lighting[l]["mae"] for l in lights]
        ax.bar(lights, maes, color="steelblue", edgecolor="black")
        ax.set_ylabel("MAE (ppm)")
        ax.set_title("MAE by lighting condition")
        ax.tick_params(axis="x", rotation=30)
        fig.tight_layout()
        fig.savefig(REPORTS_DIR / "metrics_by_lighting.png", dpi=120)
        plt.close(fig)

    summary = {
        "model_version": payload.get("model_version", "SENTINEL-H2S-v1"),
        "feature_schema_version": payload.get("feature_schema_version"),
        "dataset_type": payload.get("dataset_type"),
        "overall_test_holdout": overall,
        "by_split": by_split,
        "by_lighting": by_lighting,
        "disclaimer": "Metrics on synthetic Tier-B development dataset — not lab-validated real-world accuracy.",
    }

    with open(REPORTS_DIR / "eval_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    if METADATA_PATH.exists():
        with open(METADATA_PATH, encoding="utf-8") as f:
            meta = json.load(f)
        meta.setdefault("metrics", {}).update({
            "test_mae": round(overall["mae"], 4),
            "test_rmse": round(overall["rmse"], 4),
            "test_r2": round(overall["r2"], 4),
            "test_samples": overall["samples"],
        })
        meta["by_split"] = by_split
        meta["by_lighting"] = by_lighting
        with open(METADATA_PATH, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    evaluate()
