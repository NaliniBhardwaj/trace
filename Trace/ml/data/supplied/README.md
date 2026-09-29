# SENTINEL Synthetic H₂S Strip Dataset (Tier B) — v3

**Generated:** 2026-09-14T18:59:59
**Protocol version:** SENTINEL-synthetic-v3-2026-09-15
**Label tier:** literature_derived_proxy (Tier B)
**is_lab_validated:** false (every sample)

## Purpose
Synthetic but fully schema-compliant dataset for developing and testing the
camera → colour-correction → ML → ppm / risk-band pipeline **before** real
lab or chamber data become available.

## Important honesty statement (copy into every model card)
> Model trained on literature-derived proxy labels (see literature_sources.csv),
> not lab-measured exposure. Not yet validated against a calibrated reference
> method. Real lab validation is the immediate next step.

## Dataset statistics
- Total samples: 108
- Train / Val / Test / Holdout: see samples.csv
- Lighting holdout condition: **fluorescent** (never seen in training)
- Concentrations: 0, 5, 10, 15, 20, 30, 50, 75, 100 ppm (straddle 10/20/50 regulatory boundaries)
- Devices: Pixel_7, Samsung_A54
- All images contain the reactive strip + 4 reference patches + QR placeholder

## Colour generation
Strip colours follow a non-linear white → brown → near-black progression that
approximates published lead-acetate optical-density vs cumulative-dose behaviour.
Reference patches use fixed known sRGB values; each photo records the measured
(light-affected) values so that the deterministic correction step can be tested.

## Files
- `metadata/samples.csv`          – master label file (one row per image)
- `metadata/literature_sources.csv`
- `metadata/batches.csv`
- `images/{train,validation,test,holdout}/`
- `baselines/`                    – 0 ppm images per lighting
- `qc/`                           – samples that failed quality or uniformity checks
- `dataset_schema.csv`            – column header template

## How to use
1. Train the regression / classification model **only** on `corrected_strip_rgb`
   (or features derived from it). Never train on the raw photographed colour.
2. Evaluate on the holdout lighting condition and report metrics **per lighting**.
3. Keep the Tier-B disclaimer visible in every UI and model card.
