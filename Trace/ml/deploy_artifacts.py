"""Deploy trained model + metadata + reports to backend and mobile assets."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"
BACKEND_ARTIFACTS = ROOT.parent / "backend" / "app" / "ml" / "artifacts"
MOBILE_ML_ASSETS = ROOT.parent / "mobile" / "assets" / "ml"

MODEL_NAME = "sentinel_h2s_model_v1.joblib"
METADATA_NAME = "sentinel_h2s_model_v1_metadata.json"


def deploy() -> None:
    import subprocess
    import sys

    src_model = MODELS_DIR / MODEL_NAME
    src_meta = MODELS_DIR / METADATA_NAME
    if not src_model.exists():
        raise FileNotFoundError(f"Missing {src_model} — run train.py first")

    subprocess.run([sys.executable, "export_mobile_model.py"], cwd=ROOT, check=True)

    BACKEND_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_model, BACKEND_ARTIFACTS / MODEL_NAME)
    if src_meta.exists():
        shutil.copy2(src_meta, BACKEND_ARTIFACTS / METADATA_NAME)

    MOBILE_ML_ASSETS.mkdir(parents=True, exist_ok=True)
    if src_meta.exists():
        shutil.copy2(src_meta, MOBILE_ML_ASSETS / METADATA_NAME)
    for png in ["predicted_vs_actual.png", "metrics_by_lighting.png"]:
        src = REPORTS_DIR / png
        if src.exists():
            shutil.copy2(src, MOBILE_ML_ASSETS / png)

    print(f"Deployed to {BACKEND_ARTIFACTS}")
    print(f"Mobile assets: {MOBILE_ML_ASSETS}")


if __name__ == "__main__":
    deploy()
