"""Extract ML features from supplied dataset images via strip-card preprocessing."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import pandas as pd

from feature_extraction import FEATURE_SCHEMA, check_quality, extract_features_from_corrected
from preprocessing import preprocess_strip_card

ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "data" / "supplied" / "metadata" / "samples.csv"
DEFAULT_DATA_ROOT = ROOT / "data" / "supplied"
OUT_PATH = ROOT / "data" / "features_all.csv"


def extract_from_manifest(
    manifest_path: Path,
    data_root: Path,
    out_path: Path,
) -> int:
    df = pd.read_csv(manifest_path)
    rows_out = []
    skipped = 0

    for _, row in df.iterrows():
        img_path = data_root / row["image_path"]
        if not img_path.exists():
            skipped += 1
            continue
        img = cv2.imread(str(img_path))
        if img is None:
            skipped += 1
            continue

        try:
            prep = preprocess_strip_card(img)
            feats = extract_features_from_corrected(
                prep.corrected_bgr,
                ref_patch_delta_e=prep.reference_patch_delta_e,
                temperature_c=float(row.get("temperature_c", 0) or 0),
                humidity_pct=float(row.get("humidity_pct", 0) or 0),
                exposure_duration_min=float(row.get("exposure_duration_min", 15) or 15),
            )
            quality = check_quality(feats)
            if not quality.ok:
                skipped += 1
                continue
        except Exception:
            skipped += 1
            continue

        feats["sample_id"] = row["sample_id"]
        feats["image_path"] = row["image_path"]
        feats["split"] = row["split"]
        feats["h2s_concentration_ppm"] = float(row["h2s_concentration_ppm"])
        feats["lighting_type"] = row.get("lighting_type", "")
        feats["preprocessing_method"] = prep.method
        rows_out.append(feats)

    if not rows_out:
        raise RuntimeError(f"No features extracted from {manifest_path}")

    out_df = pd.DataFrame(rows_out)
    meta_cols = ["sample_id", "image_path", "split", "h2s_concentration_ppm", "lighting_type", "preprocessing_method"]
    cols = meta_cols + FEATURE_SCHEMA
    out_df[cols].to_csv(out_path, index=False)
    print(f"Wrote {len(rows_out)} rows to {out_path} (skipped {skipped})")
    return len(rows_out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()
    extract_from_manifest(args.manifest, args.data_root, args.out)
