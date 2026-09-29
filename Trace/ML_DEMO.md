# SENTINEL ML — Demo & E2E Checklist

## Pitch metrics (synthetic calibration — state honestly)

See `backend/app/ml/artifacts/metrics.json`:

- Cross-validated RMSE: ~1.78 ppm·hour
- Cross-validated R²: ~0.96
- 95% tolerance band: ~±3.5 ppm·hour

Training data is **synthetic**, shaped like colorimetric saturation — not lab H2S gas.

## Demo paths

| Path | How | Purpose |
|------|-----|---------|
| **Photo + ML** | Scan strip → capture with corner guides → online upload | Real LAB ΔE quantitative reading |
| **Demo chips** | QR screen → Demo: LOW/ELEVATED/HIGH/CRITICAL | Risk/alerts without a physical badge |
| **Offline** | Disable network → capture uses on-device CV + shared curve | Field resilience |

## Printable badge

Generate from repo `h2s/`:

```bash
python synthetic_data.py   # also writes printable_badge.png
```

Print `h2s/printable_badge.png` — must match ArUco layout in `backend/app/ml/badge_layout.py`.

## E2E verification

Automated (run `python _run_verify.py` from repo root):

- [x] `model.pkl` + `curve_points.json` + `metrics.json` in `backend/app/ml/artifacts/`
- [x] 8/8 pytest including `POST /scans/from-image`
- [x] Mobile `calibration.ts` synced from trained curve

Manual on device:

- [ ] Phone photo of printed badge → dose + risk + “ML camera analysis (LAB ΔE)” banner
- [ ] Demo CRITICAL chip → local alert notification
- [ ] Offline scan → PENDING → sync when online

## Retrain

```bash
cd h2s
python train_pipeline.py   # full photo pipeline → deploys to backend artifacts
```
