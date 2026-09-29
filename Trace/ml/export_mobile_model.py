"""Export compact tree JSON for on-device offline inference."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np

from feature_extraction import FEATURE_SCHEMA

ROOT = Path(__file__).resolve().parent
MODEL_PATH = ROOT / "models" / "sentinel_h2s_model_v1.joblib"
OUT_PATH = ROOT.parent / "mobile" / "assets" / "ml" / "model_trees.json"
MAX_TREES = 40


def _export_tree(estimator) -> dict:
    t = estimator.tree_
    return {
        "features": t.feature.tolist(),
        "thresholds": t.threshold.tolist(),
        "children_left": t.children_left.tolist(),
        "children_right": t.children_right.tolist(),
        "values": t.value.reshape(-1).tolist(),
    }


def export() -> Path:
    payload = joblib.load(MODEL_PATH)
    model = payload["model"]
    trees = [_export_tree(est) for est in model.estimators_[:MAX_TREES]]
    out = {
        "model_version": payload.get("model_version", "SENTINEL-H2S-v1"),
        "feature_schema": FEATURE_SCHEMA,
        "n_trees": len(trees),
        "trees": trees,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f)
    print(f"Exported {len(trees)} trees to {OUT_PATH}")
    return OUT_PATH


if __name__ == "__main__":
    export()
