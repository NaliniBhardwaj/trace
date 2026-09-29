"""Generate tests/fixtures/badge_sample.jpg for from-image API tests."""

from pathlib import Path

import cv2
import numpy as np

FIXTURE = Path(__file__).parent / "fixtures" / "badge_sample.jpg"


def main():
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    # Import h2s synthetic renderer via repo path
    import sys
    h2s = Path(__file__).resolve().parents[4] / "h2s"
    sys.path.insert(0, str(h2s))
    from synthetic_data import render_canonical_badge, simulate_strip_lab_for_dose, apply_fake_camera_conditions

    strip_lab = simulate_strip_lab_for_dose(18.0)
    canonical = render_canonical_badge(strip_lab)
    photo = apply_fake_camera_conditions(canonical)
    cv2.imwrite(str(FIXTURE), photo)
    print(f"Wrote {FIXTURE}")


if __name__ == "__main__":
    main()
