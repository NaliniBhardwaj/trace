"""Validate supplied SENTINEL synthetic dataset v3."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = ROOT / "data" / "supplied"


def inspect(data_dir: Path) -> int:
    manifest = data_dir / "metadata" / "samples.csv"
    if not manifest.exists():
        print(f"ERROR: missing {manifest}")
        return 1

    df = pd.read_csv(manifest)
    print(f"Protocol: {df['protocol_version'].iloc[0] if 'protocol_version' in df.columns else 'unknown'}")
    print(f"Total samples: {len(df)}")
    print("\nSplit counts:")
    print(df["split"].value_counts().to_string())
    print("\nConcentration (ppm) distribution:")
    print(df["h2s_concentration_ppm"].value_counts().sort_index().to_string())
    print("\nLighting types per split:")
    if "lighting_type" in df.columns:
        print(df.groupby(["split", "lighting_type"]).size().to_string())

    missing = 0
    for _, row in df.iterrows():
        img_path = data_dir / row["image_path"]
        if not img_path.exists():
            missing += 1
            print(f"MISSING: {row['image_path']}")
    print(f"\nMissing images: {missing}/{len(df)}")

    if "quality_ok" in df.columns:
        bad = df[~df["quality_ok"].astype(str).str.lower().isin(["true", "1", "yes"])]
        print(f"quality_ok=false rows: {len(bad)}")

    print("\nLayout: SENTINEL strip card (4 ref patches + checkerboard) — NOT ArUco")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args()
    raise SystemExit(inspect(args.data))
