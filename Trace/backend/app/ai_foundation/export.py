"""Deterministic JSON/CSV export of scenario operational data."""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List


def export_json(scenario: Dict[str, Any]) -> str:
    return json.dumps(scenario, indent=2, sort_keys=True)


def export_csv(scenario: Dict[str, Any]) -> str:
    """Flatten worker-zone exposure rows for optimization datasets."""
    buf = io.StringIO()
    fields = [
        "worker_id", "zone_id", "h2s_ppm", "exposure", "exposure_duration",
        "risk_level", "permit_status", "skills", "availability",
        "cleaning_required", "evacuation_state", "zone_capacity",
    ]
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    zones = {z["zone_id"]: z for z in scenario.get("zones") or []}
    for worker in scenario.get("workers") or []:
        zid = worker.get("physical_zone_id") or worker.get("assigned_zone_id")
        z = zones.get(zid or "", {})
        w.writerow({
            "worker_id": worker.get("worker_id"),
            "zone_id": zid,
            "h2s_ppm": z.get("h2s_ppm", ""),
            "exposure": worker.get("cumulative_exposure_ppm_min", ""),
            "exposure_duration": worker.get("current_exposure_ppm_min", ""),
            "risk_level": z.get("risk_level", ""),
            "permit_status": worker.get("permit_status", ""),
            "skills": "|".join(worker.get("skills") or []),
            "availability": worker.get("availability", ""),
            "cleaning_required": z.get("cleaning_required", False),
            "evacuation_state": z.get("evacuation_status", "NONE"),
            "zone_capacity": z.get("capacity", ""),
        })
    return buf.getvalue()
