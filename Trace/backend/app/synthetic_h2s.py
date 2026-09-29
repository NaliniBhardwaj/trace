"""
Deterministic synthetic H2S reading generator (Phase 3).

Feeds the SAME process_h2s_reading() path as future STRIP_ML / SENSOR data.
Not random noise — structured scenarios with fixed seed.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from app import models
from app.safety_engine import process_h2s_reading


@dataclass
class ScenarioPoint:
    offset_minutes: float
    h2s_ppm: float


# Deterministic scenario templates (ppm over relative minutes)
SCENARIOS = {
    "NORMAL_ROOM": [
        ScenarioPoint(0, 0.1),
        ScenarioPoint(5, 0.15),
        ScenarioPoint(10, 0.12),
        ScenarioPoint(15, 0.18),
        ScenarioPoint(20, 0.1),
    ],
    "LOW_H2S": [
        ScenarioPoint(0, 0.5),
        ScenarioPoint(5, 0.8),
        ScenarioPoint(10, 1.0),
        ScenarioPoint(15, 0.9),
        ScenarioPoint(20, 0.7),
    ],
    "ELEVATED_HOLD": [
        ScenarioPoint(0, 1.2),
        ScenarioPoint(5, 1.5),
        ScenarioPoint(10, 2.0),
        ScenarioPoint(15, 1.8),
        ScenarioPoint(20, 1.5),
    ],
    "GRADUAL_BUILDUP": [
        ScenarioPoint(0, 0.2),
        ScenarioPoint(5, 1.5),
        ScenarioPoint(10, 4.0),
        ScenarioPoint(15, 8.0),
        ScenarioPoint(20, 12.0),
    ],
    "SPIKE": [
        ScenarioPoint(0, 0.3),
        ScenarioPoint(5, 0.4),
        ScenarioPoint(10, 25.0),
        ScenarioPoint(15, 5.0),
        ScenarioPoint(20, 1.0),
    ],
    "PERSISTENT_HIGH": [
        ScenarioPoint(0, 12.0),
        ScenarioPoint(5, 14.0),
        ScenarioPoint(10, 13.0),
        ScenarioPoint(15, 15.0),
        ScenarioPoint(20, 12.5),
    ],
    "CRITICAL_EVENT": [
        ScenarioPoint(0, 2.0),
        ScenarioPoint(5, 20.0),
        ScenarioPoint(10, 80.0),
        ScenarioPoint(15, 120.0),
        ScenarioPoint(20, 110.0),  # remains CRITICAL (threshold 100)
    ],
    "RECOVERY": [
        ScenarioPoint(0, 40.0),
        ScenarioPoint(5, 15.0),
        ScenarioPoint(10, 5.0),
        ScenarioPoint(15, 1.5),
        ScenarioPoint(20, 0.3),
    ],
}

# Default zone → scenario assignment (deterministic)
ZONE_SCENARIO = {
    "Z-CTRL": "NORMAL_ROOM",
    "Z-PROC-A": "GRADUAL_BUILDUP",
    "Z-PROC-B": "ELEVATED_HOLD",
    "Z-COMP": "PERSISTENT_HIGH",
    "Z-PUMP": "SPIKE",
    "Z-STOR": "NORMAL_ROOM",
    "Z-TANK": "CRITICAL_EVENT",
    "Z-MAINT": "RECOVERY",
    "Z-REST": "PERSISTENT_HIGH",
}


def generate_scenario_readings(
    scenario_name: str,
    base_time: datetime,
    zone_id: str,
    worker_id: Optional[str] = None,
    seed: int = 42,
) -> List[dict]:
    rng = random.Random(seed)
    points = SCENARIOS.get(scenario_name, SCENARIOS["NORMAL_ROOM"])
    out = []
    for i, pt in enumerate(points):
        # tiny deterministic jitter (< 5%) so values aren't perfectly flat
        jitter = 1.0 + rng.uniform(-0.03, 0.03)
        ppm = max(0.0, round(pt.h2s_ppm * jitter, 3))
        ts = base_time + timedelta(minutes=pt.offset_minutes)
        out.append({
            "zone_id": zone_id,
            "worker_id": worker_id,
            "h2s_ppm": ppm,
            "timestamp": ts,
            "source": "SYNTHETIC",
            "is_synthetic": True,
            "client_reading_uuid": f"syn-{scenario_name}-{zone_id}-{seed}-{i}",
            "scenario": scenario_name,
        })
    return out


def run_synthetic_for_zone(
    db: Session,
    zone: models.Zone,
    base_time: Optional[datetime] = None,
    worker_id: Optional[str] = None,
    seed: int = 42,
) -> List[models.H2SReading]:
    scenario = ZONE_SCENARIO.get(zone.code, "NORMAL_ROOM")
    base = base_time or datetime.utcnow() - timedelta(minutes=20)
    payloads = generate_scenario_readings(scenario, base, zone.id, worker_id, seed=seed)
    readings = []
    for p in payloads:
        reading, _, _, _ = process_h2s_reading(
            db,
            zone_id=p["zone_id"],
            h2s_ppm=p["h2s_ppm"],
            occurred_at=p["timestamp"],
            source="SYNTHETIC",
            worker_id=p.get("worker_id"),
            is_synthetic=True,
            client_reading_uuid=p["client_reading_uuid"],
        )
        readings.append(reading)
    return readings


def run_synthetic_plant(
    db: Session,
    base_time: Optional[datetime] = None,
    seed: int = 42,
) -> int:
    """Generate synthetic readings for all zones; attach to workers in each zone."""
    count = 0
    zones = db.query(models.Zone).all()
    for z in zones:
        workers = db.query(models.Worker).filter(models.Worker.zone_id == z.id).all()
        wid = workers[0].id if workers else None
        readings = run_synthetic_for_zone(db, z, base_time=base_time, worker_id=wid, seed=seed)
        count += len(readings)
    return count
