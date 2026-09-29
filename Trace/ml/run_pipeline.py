"""One-shot: inspect → extract → train → evaluate → deploy."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    steps = [
        [sys.executable, "inspect_dataset.py"],
        [sys.executable, "extract_features.py"],
        [sys.executable, "train.py"],
        [sys.executable, "evaluate.py"],
        [sys.executable, "deploy_artifacts.py"],
    ]
    for cmd in steps:
        print(f"\n>>> {' '.join(cmd)}")
        subprocess.run(cmd, cwd=ROOT, check=True)
    print("\nPipeline complete.")


if __name__ == "__main__":
    main()
