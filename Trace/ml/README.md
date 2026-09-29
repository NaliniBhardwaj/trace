# SENTINEL ML Training Pipeline (v3 strip card)

Lightweight supervised regression for H₂S strip card camera analysis.

## Dataset

**Authoritative training data:** `data/supplied/` (sentinel_synthetic_dataset v3)

- 108 samples, lead-acetate strip card layout
- Reactive strip + 4 reference patches + checkerboard fiducial
- Target: `h2s_concentration_ppm` (0–100 ppm)
- Labels: `literature_derived_proxy` (Tier B synthetic development)

## Important disclaimer

Model trained on **literature-derived proxy labels**, not lab-measured exposure. Suitable for development, demo, and pipeline validation — not for scientific certification.

## Quick start

```powershell
cd sentinel/ml
pip install -r requirements.txt
python run_pipeline.py
```

Or step-by-step:

```powershell
python inspect_dataset.py
python extract_features.py
python train.py
python evaluate.py
python deploy_artifacts.py
```

## Artifacts

| File | Description |
|------|-------------|
| `models/sentinel_h2s_model_v1.joblib` | Trained ExtraTreesRegressor |
| `models/sentinel_h2s_model_v1_metadata.json` | Model metadata + metrics |
| `reports/predicted_vs_actual.png` | ML proof scatter plot |
| `reports/eval_summary.json` | Test/holdout MAE, RMSE, R² |

Deployed to `backend/app/ml/artifacts/` and `mobile/assets/ml/`.

## Feature schema

v2-strip-card: RGB/HSV/LAB strip statistics, 4-patch `ref_patch_delta_e`, quality metrics — see `feature_extraction.py`.

## Inference

```powershell
python inference.py data/supplied/images/test/H2S-2026-0014_5ppm_daylight.png
```

Runtime: `POST /scans/from-image` on backend; offline via `mobile/src/ml/inference.ts`.
