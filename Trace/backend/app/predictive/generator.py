"""
Synthetic operational dataset generator for Phase 15.

Produces temporal sequences of workers, zones, and operational events.
Clearly labeled source="synthetic". NOT real site data.

Reproducible via deterministic random seed.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

GENERATOR_VERSION = "phase15-synth-v1.0.0"

SKILLS = ["general", "confined_space", "hot_work", "gas_testing", "cleaning"]
ROLES = ["OPERATOR", "TECHNICIAN", "HSE", "SUPERVISOR"]
DEPARTMENTS = ["Operations", "Maintenance", "HSE", "Logistics"]
ZONE_TYPES = ["PROCESSING", "STORAGE", "MECHANICAL", "CONTROL", "RESTRICTED"]
RISK_LEVELS = ["NORMAL", "ELEVATED", "HIGH", "CRITICAL"]
EVENT_TYPES = [
    "scan",
    "exposure_observation",
    "cleaning_event",
    "rotation",
    "reassignment",
    "zone_escalation",
    "zone_recovery",
    "worker_unavailability",
    "incident_like",
]


@dataclass
class GeneratorConfig:
    seed: int = 42
    n_workers: int = 20
    n_zones: int = 8
    duration_hours: int = 72
    time_step_minutes: int = 15
    scenario_difficulty: str = "medium"  # easy | medium | hard
    output_dir: Optional[str] = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SyntheticOperationalGenerator:
    """Generate temporal operational records with synthetic provenance."""

    def __init__(self, config: Optional[GeneratorConfig] = None):
        self.config = config or GeneratorConfig()
        self.rng = random.Random(self.config.seed)
        self.generated_at = _utc_now().isoformat()

    def _difficulty_params(self) -> Dict[str, float]:
        d = self.config.scenario_difficulty.lower()
        if d == "easy":
            return {"escalation_p": 0.05, "high_h2s_p": 0.08, "unavail_p": 0.02, "incident_p": 0.01}
        if d == "hard":
            return {"escalation_p": 0.18, "high_h2s_p": 0.25, "unavail_p": 0.08, "incident_p": 0.06}
        return {"escalation_p": 0.10, "high_h2s_p": 0.15, "unavail_p": 0.04, "incident_p": 0.03}

    def generate(self) -> Dict[str, Any]:
        cfg = self.config
        params = self._difficulty_params()
        base_ts = datetime(2026, 1, 1, 6, 0, 0, tzinfo=timezone.utc)
        n_steps = max(1, (cfg.duration_hours * 60) // cfg.time_step_minutes)

        zones = self._init_zones()
        workers = self._init_workers(zones)
        events: List[Dict[str, Any]] = []
        snapshots: List[Dict[str, Any]] = []

        for step in range(n_steps):
            ts = base_ts + timedelta(minutes=step * cfg.time_step_minutes)
            step_events = self._step(ts, zones, workers, params)
            events.extend(step_events)
            snapshots.append(self._snapshot(ts, zones, workers, step))

        payload = {
            "metadata": {
                "source": "synthetic",
                "generator_version": GENERATOR_VERSION,
                "generated_at": self.generated_at,
                "random_seed": cfg.seed,
                "n_workers": cfg.n_workers,
                "n_zones": cfg.n_zones,
                "duration_hours": cfg.duration_hours,
                "time_step_minutes": cfg.time_step_minutes,
                "scenario_difficulty": cfg.scenario_difficulty,
                "n_steps": n_steps,
                "n_events": len(events),
                "feature_schema_version": "phase15-v1",
                "synthetic_status": (
                    "SYNTHETIC OPERATIONAL DATA — NOT real workforce or site data. "
                    "For experimental Phase 15 predictive models only."
                ),
            },
            "zones_initial": [{k: v for k, v in z.items()} for z in zones],
            "workers_initial": [{k: v for k, v in w.items()} for w in workers],
            "events": events,
            "snapshots": snapshots,
        }
        if cfg.output_dir:
            self._write(payload, Path(cfg.output_dir))
        return payload

    def _init_zones(self) -> List[Dict[str, Any]]:
        zones = []
        for i in range(self.config.n_zones):
            zid = f"Z{i+1:02d}"
            neighbors = []
            if i > 0:
                neighbors.append(f"Z{i:02d}")
            if i < self.config.n_zones - 1:
                neighbors.append(f"Z{i+2:02d}")
            if self.config.n_zones > 3 and i % 3 == 0 and i + 3 < self.config.n_zones:
                neighbors.append(f"Z{i+4:02d}")
            risk = self.rng.choice(["NORMAL", "NORMAL", "ELEVATED", "HIGH"])
            h2s = {"NORMAL": 0.3, "ELEVATED": 2.0, "HIGH": 12.0, "CRITICAL": 80.0}[risk]
            h2s *= self.rng.uniform(0.6, 1.4)
            zones.append({
                "zone_id": zid,
                "name": f"Zone {i+1}",
                "zone_type": self.rng.choice(ZONE_TYPES),
                "risk_level": risk,
                "h2s_ppm": round(h2s, 2),
                "temperature_c": round(self.rng.uniform(22, 42), 1),
                "humidity_pct": round(self.rng.uniform(30, 85), 1),
                "ventilation_proxy": round(self.rng.uniform(0.3, 1.0), 2),
                "occupancy": 0,
                "deterioration_trend": round(self.rng.uniform(-0.05, 0.15), 3),
                "cleaning_state": self.rng.choice(["CLEAN", "CLEAN", "DUE", "OVERDUE"]),
                "last_cleaning_ts": None,
                "cleaning_duration_min": self.rng.choice([15, 30, 45, 60]),
                "neighboring_zones": neighbors,
                "permit_required": self.rng.random() < 0.3,
                "evacuation_status": "NONE",
                "unavailable": False,
            })
        return zones

    def _init_workers(self, zones: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        workers = []
        zone_ids = [z["zone_id"] for z in zones]
        for i in range(self.config.n_workers):
            wid = f"W{i+1:03d}"
            n_skills = self.rng.randint(1, 3)
            skills = self.rng.sample(SKILLS, n_skills)
            assigned = self.rng.choice(zone_ids) if self.rng.random() < 0.7 else None
            if assigned:
                for z in zones:
                    if z["zone_id"] == assigned:
                        z["occupancy"] = z.get("occupancy", 0) + 1
                        break
            workers.append({
                "worker_id": wid,
                "skills": skills,
                "role": self.rng.choice(ROLES),
                "department": self.rng.choice(DEPARTMENTS),
                "shift": self.rng.choice(["A", "B", "C"]),
                "availability": "AVAILABLE" if self.rng.random() > 0.05 else "UNAVAILABLE",
                "current_zone": assigned,
                "assigned_zone_id": assigned,
                "cumulative_workload": round(self.rng.uniform(0, 40), 1),
                "recent_task_count": self.rng.randint(0, 8),
                "recent_exposure": round(self.rng.uniform(0, 50), 2),
                "historical_exposure_trend": round(self.rng.uniform(-0.1, 0.2), 3),
                "rotation_count": self.rng.randint(0, 12),
                "recovery_rest_proxy": round(self.rng.uniform(0.2, 1.0), 2),
                "time_since_last_rotation_min": self.rng.randint(30, 480),
                "time_since_rest_min": self.rng.randint(0, 360),
                "qualification_status": "QUALIFIED" if self.rng.random() > 0.15 else "LIMITED",
            })
        return workers

    def _step(
        self,
        ts: datetime,
        zones: List[Dict[str, Any]],
        workers: List[Dict[str, Any]],
        params: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        ts_iso = ts.isoformat()

        # Zone evolution
        for z in zones:
            if z.get("unavailable"):
                continue
            # natural drift
            drift = z.get("deterioration_trend", 0) + self.rng.uniform(-0.02, 0.03)
            z["h2s_ppm"] = max(0.05, z["h2s_ppm"] * (1 + drift * 0.1) + self.rng.uniform(-0.3, 0.5))
            z["temperature_c"] = max(18, min(48, z["temperature_c"] + self.rng.uniform(-0.5, 0.8)))
            z["humidity_pct"] = max(20, min(95, z["humidity_pct"] + self.rng.uniform(-2, 2)))
            z["ventilation_proxy"] = max(0.1, min(1.0, z["ventilation_proxy"] + self.rng.uniform(-0.03, 0.02)))

            old_risk = z["risk_level"]
            z["risk_level"] = self._risk_from_h2s(z["h2s_ppm"])
            if z["risk_level"] != old_risk and RISK_LEVELS.index(z["risk_level"]) > RISK_LEVELS.index(old_risk):
                if self.rng.random() < params["escalation_p"]:
                    events.append({
                        "event_type": "zone_escalation",
                        "timestamp": ts_iso,
                        "zone_id": z["zone_id"],
                        "from_risk": old_risk,
                        "to_risk": z["risk_level"],
                        "h2s_ppm": round(z["h2s_ppm"], 2),
                    })
            elif RISK_LEVELS.index(z["risk_level"]) < RISK_LEVELS.index(old_risk):
                events.append({
                    "event_type": "zone_recovery",
                    "timestamp": ts_iso,
                    "zone_id": z["zone_id"],
                    "from_risk": old_risk,
                    "to_risk": z["risk_level"],
                    "h2s_ppm": round(z["h2s_ppm"], 2),
                })

            # Cleaning state aging
            if z["cleaning_state"] == "CLEAN" and self.rng.random() < 0.08:
                z["cleaning_state"] = "DUE"
            elif z["cleaning_state"] == "DUE" and self.rng.random() < 0.12:
                z["cleaning_state"] = "OVERDUE"

            # Occasional cleaning event
            if z["cleaning_state"] in ("DUE", "OVERDUE") and self.rng.random() < 0.15:
                z["cleaning_state"] = "CLEAN"
                z["last_cleaning_ts"] = ts_iso
                z["h2s_ppm"] = max(0.1, z["h2s_ppm"] * 0.4)
                z["risk_level"] = self._risk_from_h2s(z["h2s_ppm"])
                events.append({
                    "event_type": "cleaning_event",
                    "timestamp": ts_iso,
                    "zone_id": z["zone_id"],
                    "duration_min": z["cleaning_duration_min"],
                    "post_h2s_ppm": round(z["h2s_ppm"], 2),
                })

        # Worker exposure / workload
        for w in workers:
            if w["availability"] != "AVAILABLE":
                if self.rng.random() < 0.3:
                    w["availability"] = "AVAILABLE"
                continue
            zone = next((z for z in zones if z["zone_id"] == w.get("current_zone")), None)
            if zone:
                exposure_inc = zone["h2s_ppm"] * (self.config.time_step_minutes / 60.0) * self.rng.uniform(0.8, 1.2)
                w["recent_exposure"] = round(w["recent_exposure"] * 0.95 + exposure_inc, 2)
                w["cumulative_workload"] = round(w["cumulative_workload"] + self.rng.uniform(0.2, 1.5), 1)
                w["recent_task_count"] = min(20, w["recent_task_count"] + (1 if self.rng.random() < 0.3 else 0))
                w["time_since_last_rotation_min"] += self.config.time_step_minutes
                w["time_since_rest_min"] += self.config.time_step_minutes
                w["recovery_rest_proxy"] = max(0.05, w["recovery_rest_proxy"] - 0.01)
                events.append({
                    "event_type": "exposure_observation",
                    "timestamp": ts_iso,
                    "worker_id": w["worker_id"],
                    "zone_id": zone["zone_id"],
                    "exposure_delta": round(exposure_inc, 3),
                    "recent_exposure": w["recent_exposure"],
                    "zone_h2s_ppm": round(zone["h2s_ppm"], 2),
                })
                if self.rng.random() < 0.2:
                    events.append({
                        "event_type": "scan",
                        "timestamp": ts_iso,
                        "worker_id": w["worker_id"],
                        "zone_id": zone["zone_id"],
                        "h2s_ppm": round(zone["h2s_ppm"] * self.rng.uniform(0.9, 1.1), 2),
                    })

            # Unavailability
            if self.rng.random() < params["unavail_p"]:
                w["availability"] = "UNAVAILABLE"
                events.append({
                    "event_type": "worker_unavailability",
                    "timestamp": ts_iso,
                    "worker_id": w["worker_id"],
                    "reason": self.rng.choice(["fatigue", "shift_end", "medical", "other"]),
                })

            # Rotation
            if (
                w["availability"] == "AVAILABLE"
                and w["time_since_last_rotation_min"] > 90
                and self.rng.random() < 0.08
            ):
                candidates = [z for z in zones if not z.get("unavailable") and z["zone_id"] != w.get("current_zone")]
                if candidates:
                    target = self.rng.choice(candidates)
                    old = w.get("current_zone")
                    if old:
                        for z in zones:
                            if z["zone_id"] == old:
                                z["occupancy"] = max(0, z.get("occupancy", 1) - 1)
                    w["current_zone"] = target["zone_id"]
                    w["assigned_zone_id"] = target["zone_id"]
                    target["occupancy"] = target.get("occupancy", 0) + 1
                    w["rotation_count"] += 1
                    w["time_since_last_rotation_min"] = 0
                    w["recovery_rest_proxy"] = min(1.0, w["recovery_rest_proxy"] + 0.15)
                    events.append({
                        "event_type": "rotation",
                        "timestamp": ts_iso,
                        "worker_id": w["worker_id"],
                        "from_zone": old,
                        "to_zone": target["zone_id"],
                    })

        # Rare incident-like
        if self.rng.random() < params["incident_p"]:
            z = self.rng.choice([zz for zz in zones if not zz.get("unavailable")] or zones)
            z["h2s_ppm"] = max(z["h2s_ppm"], self.rng.uniform(40, 120))
            z["risk_level"] = self._risk_from_h2s(z["h2s_ppm"])
            events.append({
                "event_type": "incident_like",
                "timestamp": ts_iso,
                "zone_id": z["zone_id"],
                "h2s_ppm": round(z["h2s_ppm"], 2),
                "severity": self.rng.choice(["moderate", "high", "severe"]),
            })

        return events

    def _risk_from_h2s(self, ppm: float) -> str:
        if ppm >= 50:
            return "CRITICAL"
        if ppm >= 10:
            return "HIGH"
        if ppm >= 1.5:
            return "ELEVATED"
        return "NORMAL"

    def _snapshot(
        self,
        ts: datetime,
        zones: List[Dict[str, Any]],
        workers: List[Dict[str, Any]],
        step: int,
    ) -> Dict[str, Any]:
        return {
            "step": step,
            "timestamp": ts.isoformat(),
            "zones": [
                {
                    "zone_id": z["zone_id"],
                    "risk_level": z["risk_level"],
                    "h2s_ppm": round(z["h2s_ppm"], 2),
                    "temperature_c": z["temperature_c"],
                    "humidity_pct": z["humidity_pct"],
                    "ventilation_proxy": z["ventilation_proxy"],
                    "occupancy": z.get("occupancy", 0),
                    "cleaning_state": z["cleaning_state"],
                    "deterioration_trend": z.get("deterioration_trend", 0),
                    "last_cleaning_ts": z.get("last_cleaning_ts"),
                    "neighboring_zones": list(z.get("neighboring_zones") or []),
                    "unavailable": z.get("unavailable", False),
                    "evacuation_status": z.get("evacuation_status", "NONE"),
                }
                for z in zones
            ],
            "workers": [
                {
                    "worker_id": w["worker_id"],
                    "skills": list(w["skills"]),
                    "role": w["role"],
                    "availability": w["availability"],
                    "current_zone": w.get("current_zone"),
                    "cumulative_workload": w["cumulative_workload"],
                    "recent_task_count": w["recent_task_count"],
                    "recent_exposure": w["recent_exposure"],
                    "historical_exposure_trend": w["historical_exposure_trend"],
                    "rotation_count": w["rotation_count"],
                    "recovery_rest_proxy": w["recovery_rest_proxy"],
                    "time_since_last_rotation_min": w["time_since_last_rotation_min"],
                    "time_since_rest_min": w["time_since_rest_min"],
                    "qualification_status": w.get("qualification_status", "QUALIFIED"),
                }
                for w in workers
            ],
        }

    def _write(self, payload: Dict[str, Any], out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"synthetic_ops_seed{self.config.seed}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        meta_path = out_dir / "generator_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(payload["metadata"], f, indent=2)


def generate_default_dataset(
    seed: int = 42,
    n_workers: int = 16,
    n_zones: int = 6,
    duration_hours: int = 48,
    difficulty: str = "medium",
) -> Dict[str, Any]:
    gen = SyntheticOperationalGenerator(
        GeneratorConfig(
            seed=seed,
            n_workers=n_workers,
            n_zones=n_zones,
            duration_hours=duration_hours,
            scenario_difficulty=difficulty,
        )
    )
    return gen.generate()
