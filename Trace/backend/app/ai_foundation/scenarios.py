"""
Deterministic synthetic scenario engine (Phase 12).
Same (scenario_type, seed) → same scenario. Not AI predictions.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

SCENARIO_TYPES = [
    "NORMAL_OPERATION",
    "HIGH_RISK_ZONE",
    "CRITICAL_ZONE",
    "ZONE_EVACUATION",
    "MULTI_ZONE_CLEANING",
    "WORKER_HIGH_EXPOSURE",
    "WORKER_UNAVAILABLE",
    "LIMITED_SKILLED_WORKERS",
    "ASSIGNMENT_CONFLICT",
    "COMBINED_CRITICAL_EVENT",
    # Phase 12.2 — optimizer-focused scenarios
    "CLEANING_CRITICAL_SINGLE",
    "CLEANING_COMPETING_TASKS",
    "CLEANING_EVACUATED_CRITICAL",
    "CLEANING_HIGH_H2S_WORKERS_AVAILABLE",
    "CLEANING_HIGH_H2S_NO_QUALIFIED",
    "CLEANING_ADJACENT_HIGH_RISK",
    "CLEANING_LOW_RISK_LONG_DURATION",
    "CLEANING_TIED_TASKS",
    # Phase 13 — worker rotation optimizer scenarios
    "ROTATION_NORMAL",
    "ROTATION_HIGH_EXPOSURE",
    "ROTATION_CRITICAL_ZONE",
    "ROTATION_EVACUATION",
    "ROTATION_CLEANING_PRIORITY",
    "ROTATION_LIMITED_SKILLS",
    "ROTATION_NO_SAFE_DESTINATION",
    "ROTATION_PERMIT_CONFLICT",
    "ROTATION_LOCATION_MISMATCH",
    "ROTATION_MULTI_WORKER",
    "ROTATION_WORKLOAD_IMBALANCE",
    "ROTATION_COOLDOWN",
    "ROTATION_COMBINED_CRITICAL_EVENT",
    # Phase 14 — coordinated workforce
    "COORDINATED_NORMAL",
    "COORDINATED_HIGH_RISK",
    "COORDINATED_CRITICAL_CLEANING",
    "COORDINATED_EVACUATION",
    "COORDINATED_EVACUATION_WITH_REASSIGNMENT",
    "COORDINATED_HIGH_EXPOSURE",
    "COORDINATED_LIMITED_SKILLS",
    "COORDINATED_PERMIT_CONFLICT",
    "COORDINATED_VERTICAL_RISK",
    "COORDINATED_BLE_MISMATCH",
    "COORDINATED_WORKLOAD_IMBALANCE",
    "COORDINATED_MULTI_WORKER",
    "COORDINATED_NO_SAFE_DESTINATION",
    "COORDINATED_COMBINED_EVENT",
]

DEPARTMENTS = ["Operations", "Maintenance", "HSE", "Logistics"]
SKILLS = ["general", "confined_space", "hot_work", "gas_testing", "cleaning"]
ZONE_TYPES = ["PROCESSING", "STORAGE", "MECHANICAL", "CONTROL", "RESTRICTED"]


@dataclass
class SynWorker:
    worker_id: str
    employee_code: str
    department: str
    role: str
    skills: List[str]
    qualification_status: str
    physical_zone_id: Optional[str]
    assigned_zone_id: Optional[str]
    permit_status: str
    current_exposure_ppm_min: float
    cumulative_exposure_ppm_min: float
    shift_start: str
    shift_end: str
    availability: str
    rest_rotation_status: str
    is_synthetic: bool = True
    time_in_zone_seconds: int = 0
    exposure_duration_seconds: int = 0
    last_rotation_minutes_ago: Optional[float] = None


@dataclass
class SynZone:
    zone_id: str
    code: str
    name: str
    zone_type: str
    risk_level: str
    h2s_ppm: float
    capacity: int
    current_occupancy: int
    adjacent_zone_ids: List[str]
    permit_required: bool
    evacuation_status: str
    cleaning_required: bool
    cleaning_severity: str
    estimated_cleaning_duration_min: int
    is_synthetic: bool = True
    vertical_level: int = 0
    vertical_label: str = "GROUND"
    vertical_levels: Optional[list] = None


@dataclass
class SynScenario:
    scenario_id: str
    scenario_type: str
    seed: int
    workers: List[Dict[str, Any]] = field(default_factory=list)
    zones: List[Dict[str, Any]] = field(default_factory=list)
    locations: List[Dict[str, Any]] = field(default_factory=list)
    assignments: List[Dict[str, Any]] = field(default_factory=list)
    permits: List[Dict[str, Any]] = field(default_factory=list)
    h2s_readings: List[Dict[str, Any]] = field(default_factory=list)
    exposure_history: List[Dict[str, Any]] = field(default_factory=list)
    cleaning_tasks: List[Dict[str, Any]] = field(default_factory=list)
    evacuation_states: List[Dict[str, Any]] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def list_scenario_types() -> List[str]:
    return list(SCENARIO_TYPES)


def _risk_for_index(i: int, scenario_type: str, rng: random.Random) -> tuple:
    """Return (risk_level, h2s_ppm). Levels: LOW, MODERATE, ELEVATED, HIGH, CRITICAL."""
    if scenario_type in ("CRITICAL_ZONE", "ZONE_EVACUATION", "COMBINED_CRITICAL_EVENT",
                         "ROTATION_CRITICAL_ZONE", "ROTATION_EVACUATION",
                         "ROTATION_COMBINED_CRITICAL_EVENT",
                         "COORDINATED_EVACUATION", "COORDINATED_EVACUATION_WITH_REASSIGNMENT",
                         "COORDINATED_COMBINED_EVENT") and i == 0:
        return "CRITICAL", 150.0
    if scenario_type in ("COORDINATED_HIGH_RISK", "COORDINATED_CRITICAL_CLEANING") and i == 0:
        return "HIGH", 40.0
    if scenario_type == "COORDINATED_VERTICAL_RISK" and i == 0:
        return "HIGH", 35.0
    if scenario_type == "COORDINATED_HIGH_EXPOSURE" and i == 0:
        return "HIGH", 40.0
    if scenario_type == "COORDINATED_NO_SAFE_DESTINATION":
        if i == 0:
            return "HIGH", 45.0
        return "CRITICAL", 100.0 + i
    if scenario_type == "COORDINATED_MULTI_WORKER" and i < 3:
        return "HIGH", 30.0 + i * 5
    if scenario_type in ("HIGH_RISK_ZONE", "ROTATION_HIGH_EXPOSURE") and i == 0:
        return "HIGH", 40.0
    if scenario_type == "MULTI_ZONE_CLEANING" and i < 3:
        return "HIGH", 25.0 + i * 5
    # Phase 12.2 optimizer scenarios
    if scenario_type == "CLEANING_CRITICAL_SINGLE" and i == 0:
        return "CRITICAL", 120.0
    if scenario_type == "CLEANING_COMPETING_TASKS" and i < 4:
        levels = [("CRITICAL", 100.0), ("HIGH", 45.0), ("HIGH", 35.0), ("ELEVATED", 12.0)]
        return levels[i]
    if scenario_type == "CLEANING_EVACUATED_CRITICAL" and i == 0:
        return "CRITICAL", 160.0
    if scenario_type in ("CLEANING_HIGH_H2S_WORKERS_AVAILABLE", "CLEANING_HIGH_H2S_NO_QUALIFIED") and i == 0:
        return "HIGH", 55.0
    if scenario_type == "CLEANING_ADJACENT_HIGH_RISK":
        if i == 0:
            return "HIGH", 30.0
        if i in (1, 9):  # adjacent ring neighbors of zone-0
            return "HIGH", 28.0
    if scenario_type == "CLEANING_LOW_RISK_LONG_DURATION" and i == 0:
        return "MODERATE", 3.0
    if scenario_type == "CLEANING_TIED_TASKS" and i < 3:
        return "HIGH", 40.0  # identical H2S/risk for tie-break tests
    # Phase 13 rotation scenarios
    if scenario_type == "ROTATION_CLEANING_PRIORITY" and i == 0:
        return "HIGH", 35.0
    if scenario_type == "ROTATION_NO_SAFE_DESTINATION":
        # All zones high/critical or evacuated → no safe dest
        if i == 0:
            return "HIGH", 45.0
        return "CRITICAL", 100.0 + i
    if scenario_type == "ROTATION_MULTI_WORKER" and i < 3:
        return "HIGH", 30.0 + i * 5
    if scenario_type == "ROTATION_WORKLOAD_IMBALANCE" and i == 0:
        return "HIGH", 28.0
    # Ensure multi-level distribution across 10 zones
    table = [
        ("LOW", 0.2),
        ("LOW", 0.5),
        ("MODERATE", 1.5),
        ("ELEVATED", 5.0),
        ("HIGH", 15.0),
        ("HIGH", 20.0),
        ("MODERATE", 2.0),
        ("ELEVATED", 4.0),
        ("LOW", 0.1),
        ("MODERATE", 1.0),
    ]
    if i < len(table):
        return table[i]
    return "LOW", 0.2


def generate_scenario(scenario_type: str = "NORMAL_OPERATION", seed: int = 42) -> SynScenario:
    if scenario_type not in SCENARIO_TYPES:
        raise ValueError(f"Unknown scenario_type: {scenario_type}")
    rng = random.Random(seed)
    sid = f"{scenario_type}-{seed}"

    zones: List[SynZone] = []
    for i in range(10):
        risk, ppm = _risk_for_index(i, scenario_type, rng)
        code = f"Z-AI-{i:02d}"
        cleaning = risk in ("HIGH", "CRITICAL") or (
            scenario_type == "MULTI_ZONE_CLEANING" and i < 3
        )
        if scenario_type.startswith("CLEANING_") and i == 0:
            cleaning = True
        if scenario_type == "CLEANING_COMPETING_TASKS" and i < 4:
            cleaning = True
        if scenario_type == "CLEANING_TIED_TASKS" and i < 3:
            cleaning = True
        if scenario_type == "CLEANING_ADJACENT_HIGH_RISK" and i in (0, 1, 9):
            cleaning = True
        if scenario_type == "CLEANING_LOW_RISK_LONG_DURATION" and i == 0:
            cleaning = True

        # Phase 13.1: CRITICAL risk does NOT imply evacuation.
        # ROTATION_CRITICAL_ZONE → CRITICAL + NONE (rotation review, not evacuate).
        if risk == "CRITICAL" and scenario_type in (
            "ZONE_EVACUATION", "COMBINED_CRITICAL_EVENT", "CLEANING_EVACUATED_CRITICAL",
            "ROTATION_EVACUATION", "ROTATION_COMBINED_CRITICAL_EVENT",
            "COORDINATED_EVACUATION", "COORDINATED_EVACUATION_WITH_REASSIGNMENT",
            "COORDINATED_COMBINED_EVENT",
        ):
            evac = "EVACUATED"
        elif risk == "CRITICAL" and scenario_type in (
            "CRITICAL_ZONE", "CLEANING_CRITICAL_SINGLE",
        ):
            # Legacy Phase 12 scenarios keep EVACUATION_REQUIRED for critical cleaning/critical zone demos
            evac = "EVACUATION_REQUIRED"
        elif scenario_type == "ROTATION_CRITICAL_ZONE" and risk == "CRITICAL":
            # Explicit: CRITICAL + NONE — mandatory Phase 13.1 semantics
            evac = "NONE"
        elif scenario_type == "ROTATION_NO_SAFE_DESTINATION" and i > 0:
            evac = "EVACUATION_REQUIRED"
        else:
            evac = "NONE"

        if scenario_type == "CLEANING_LOW_RISK_LONG_DURATION" and i == 0:
            duration = 150
            severity = "HIGH"
        elif scenario_type == "CLEANING_TIED_TASKS" and i < 3:
            duration = 40  # identical duration → stable task_id tie-break
            severity = "HIGH"
        elif cleaning:
            duration = 30 + i * 10
            severity = "CRITICAL" if risk == "CRITICAL" else "HIGH"
        else:
            duration = 0
            severity = "NONE"

        permit_req = (ZONE_TYPES[i % len(ZONE_TYPES)] == "RESTRICTED" or risk == "CRITICAL")
        if scenario_type == "ROTATION_PERMIT_CONFLICT" and i == 0:
            permit_req = True
        if scenario_type == "ROTATION_CLEANING_PRIORITY" and i == 0:
            cleaning = True
            severity = "CRITICAL"
            duration = 60
        if scenario_type == "ROTATION_NO_SAFE_DESTINATION":
            cap = 1 if i > 0 else 4
        else:
            cap = 4 + (i % 3)

        zones.append(SynZone(
            zone_id=f"zone-{i}",
            code=code,
            name=f"Synthetic Zone {i}",
            zone_type=ZONE_TYPES[i % len(ZONE_TYPES)],
            risk_level=risk,
            h2s_ppm=ppm,
            capacity=cap,
            current_occupancy=0,
            adjacent_zone_ids=[f"zone-{(i-1)%10}", f"zone-{(i+1)%10}"],
            permit_required=permit_req,
            evacuation_status=evac,
            cleaning_required=cleaning,
            cleaning_severity=severity if cleaning else "NONE",
            estimated_cleaning_duration_min=duration,
        ))

    workers: List[SynWorker] = []
    for i in range(20):
        dept = DEPARTMENTS[i % len(DEPARTMENTS)]
        skills = [SKILLS[0]]
        if i % 4 == 0:
            skills.append("gas_testing")
        if i % 5 == 0:
            skills.append("cleaning")
        if i % 7 == 0:
            skills.append("confined_space")
        avail = "AVAILABLE"
        if scenario_type == "WORKER_UNAVAILABLE" and i == 0:
            avail = "UNAVAILABLE"
        if scenario_type == "LIMITED_SKILLED_WORKERS" and i > 2:
            skills = ["general"]
        if scenario_type == "CLEANING_HIGH_H2S_NO_QUALIFIED":
            # No cleaning skill / no qualification for restricted-like high H2S zone
            skills = ["general"]
        if scenario_type == "CLEANING_HIGH_H2S_WORKERS_AVAILABLE" and i < 5:
            skills = ["general", "cleaning"]
        # Phase 13 rotation skill constraints
        if scenario_type == "ROTATION_LIMITED_SKILLS" and i > 2:
            skills = ["general"]
        if scenario_type == "ROTATION_CLEANING_PRIORITY" and i < 4:
            skills = ["general", "cleaning"]
        cum_exp = float(rng.randint(0, 80))
        if scenario_type == "WORKER_HIGH_EXPOSURE" and i == 0:
            cum_exp = 250.0
        if scenario_type == "COMBINED_CRITICAL_EVENT" and i < 3:
            cum_exp = 180.0 + i * 10
        if scenario_type == "ROTATION_HIGH_EXPOSURE" and i == 0:
            cum_exp = 160.0
        if scenario_type == "COORDINATED_HIGH_EXPOSURE" and i == 0:
            cum_exp = 160.0
        if scenario_type == "COORDINATED_MULTI_WORKER" and i < 4:
            cum_exp = 120.0 + i * 15
        if scenario_type == "COORDINATED_COMBINED_EVENT" and i < 3:
            cum_exp = 170.0 + i * 10
        if scenario_type == "COORDINATED_LIMITED_SKILLS" and i > 2:
            skills = ["general"]
        if scenario_type == "COORDINATED_BLE_MISMATCH" and i == 0:
            assigned = "zone-0"
            physical = "zone-5"
        if scenario_type == "COORDINATED_PERMIT_CONFLICT" and i == 0:
            permit = "SUSPENDED"
            assigned = "zone-0"
            physical = "zone-0"
        if scenario_type == "ROTATION_MULTI_WORKER" and i < 4:
            cum_exp = 120.0 + i * 15
        if scenario_type == "ROTATION_COMBINED_CRITICAL_EVENT" and i < 3:
            cum_exp = 170.0 + i * 10
        if scenario_type == "ROTATION_WORKLOAD_IMBALANCE" and i == 0:
            cum_exp = 90.0
        z_idx = i % 10
        if scenario_type in ("ASSIGNMENT_CONFLICT", "ROTATION_LOCATION_MISMATCH", "COORDINATED_BLE_MISMATCH") and i == 0:
            assigned = "zone-0"
            physical = "zone-5"
        elif scenario_type == "ROTATION_HIGH_EXPOSURE" and i == 0:
            assigned = "zone-0"
            physical = "zone-0"
        elif scenario_type == "ROTATION_MULTI_WORKER" and i < 4:
            assigned = f"zone-{i}"
            physical = f"zone-{i}"
        else:
            assigned = f"zone-{z_idx}"
            physical = f"zone-{z_idx}"
        permit = "ACTIVE"
        if zones[z_idx].permit_required and i % 6 == 0:
            permit = "NONE"
        if scenario_type == "CLEANING_HIGH_H2S_WORKERS_AVAILABLE" and i < 5:
            permit = "ACTIVE"
        if scenario_type == "ROTATION_PERMIT_CONFLICT" and i == 0:
            permit = "SUSPENDED"
            assigned = "zone-0"
            physical = "zone-0"
            # force zone-0 to require permit
        if scenario_type == "ROTATION_NO_SAFE_DESTINATION" and i == 0:
            cum_exp = 90.0
            assigned = "zone-0"
            physical = "zone-0"
        qual = "QUALIFIED" if "confined_space" in skills or i % 3 != 0 else "BASIC"
        if scenario_type == "CLEANING_HIGH_H2S_NO_QUALIFIED":
            qual = "BASIC"
        if scenario_type == "CLEANING_HIGH_H2S_WORKERS_AVAILABLE" and i < 5:
            qual = "QUALIFIED"
        if scenario_type == "ROTATION_LIMITED_SKILLS" and i > 2:
            qual = "BASIC"

        time_in = 0
        last_rot = None
        if scenario_type == "ROTATION_HIGH_EXPOSURE" and i == 0:
            time_in = 2400
        if scenario_type == "ROTATION_COOLDOWN" and i == 0:
            cum_exp = 100.0
            time_in = 2000
            last_rot = 10.0  # within default 30 min cooldown
            assigned = "zone-0"
            physical = "zone-0"
        if scenario_type == "ROTATION_COMBINED_CRITICAL_EVENT" and i < 3:
            time_in = 2000 + i * 100
        if scenario_type == "ROTATION_CLEANING_PRIORITY" and i == 0:
            time_in = 1500
            assigned = "zone-0"
            physical = "zone-0"

        workers.append(SynWorker(
            worker_id=f"worker-{i}",
            employee_code=f"SYN-W{i:03d}",
            department=dept,
            role="WORKER",
            skills=skills,
            qualification_status=qual,
            physical_zone_id=physical,
            assigned_zone_id=assigned,
            permit_status=permit,
            current_exposure_ppm_min=float(rng.randint(0, 30)),
            cumulative_exposure_ppm_min=cum_exp,
            shift_start="06:00",
            shift_end="18:00",
            availability=avail,
            rest_rotation_status="ON_SHIFT" if avail == "AVAILABLE" else "OFF",
            time_in_zone_seconds=time_in,
            exposure_duration_seconds=time_in,
            last_rotation_minutes_ago=last_rot,
        ))

    # occupancy
    for w in workers:
        if w.physical_zone_id:
            zi = int(w.physical_zone_id.split("-")[1])
            zones[zi].current_occupancy += 1

    cleaning_tasks = []
    for z in zones:
        if z.cleaning_required:
            cleaning_tasks.append({
                "task_id": f"clean-{z.zone_id}",
                "zone_id": z.zone_id,
                "severity": z.cleaning_severity,
                "estimated_duration_min": z.estimated_cleaning_duration_min,
                "required_skills": ["cleaning"],
                "status": "REQUIRED",
                "assigned_workers": [],
            })

    assignments = [
        {
            "worker_id": w.worker_id,
            "zone_id": w.assigned_zone_id,
            "task": "operations",
            "status": "ACTIVE" if w.availability == "AVAILABLE" else "INACTIVE",
        }
        for w in workers
    ]
    permits = [
        {
            "worker_id": w.worker_id,
            "zone_id": w.assigned_zone_id,
            "status": w.permit_status,
        }
        for w in workers
    ]
    readings = [
        {"zone_id": z.zone_id, "h2s_ppm": z.h2s_ppm, "risk_level": z.risk_level}
        for z in zones
    ]
    exposure = [
        {
            "worker_id": w.worker_id,
            "zone_id": w.physical_zone_id,
            "cumulative_ppm_min": w.cumulative_exposure_ppm_min,
            "current_ppm_min": w.current_exposure_ppm_min,
        }
        for w in workers
    ]
    evacuations = [
        {"zone_id": z.zone_id, "status": z.evacuation_status}
        for z in zones if z.evacuation_status != "NONE"
    ]

    # Phase 14 vertical intelligence for COORDINATED_VERTICAL_RISK
    if scenario_type == "COORDINATED_VERTICAL_RISK" and zones:
        z0 = zones[0]
        z0.vertical_levels = [
            {"level": 1, "label": "L1", "risk_level": "MODERATE", "h2s_ppm": 5.0},
            {"level": 2, "label": "L2", "risk_level": "CRITICAL", "h2s_ppm": 120.0},
            {"level": 3, "label": "L3", "risk_level": "HIGH", "h2s_ppm": 25.0},
        ]
        z0.vertical_level = 2
        z0.vertical_label = "L2"
        z0.risk_level = "HIGH"  # aggregate horizontal still HIGH; L2 vertical CRITICAL
    if scenario_type == "COORDINATED_CRITICAL_CLEANING" and zones:
        zones[0].cleaning_required = True
        zones[0].cleaning_severity = "CRITICAL"
        zones[0].estimated_cleaning_duration_min = 60
    if scenario_type == "COORDINATED_NO_SAFE_DESTINATION":
        for i, z in enumerate(zones):
            if i > 0:
                z.capacity = 1
                if z.evacuation_status == "NONE" and z.risk_level != "CRITICAL":
                    z.evacuation_status = "EVACUATION_REQUIRED"

    return SynScenario(
        scenario_id=sid,
        scenario_type=scenario_type,
        seed=seed,
        workers=[asdict(w) for w in workers],
        zones=[asdict(z) for z in zones],
        locations=[{"worker_id": w.worker_id, "zone_id": w.physical_zone_id} for w in workers],
        assignments=assignments,
        permits=permits,
        h2s_readings=readings,
        exposure_history=exposure,
        cleaning_tasks=cleaning_tasks,
        evacuation_states=evacuations,
        constraints={
            "max_cumulative_exposure_ppm_min": 200.0,
            "dose_threshold_ppm_min": 50.0,
            "continuous_duration_seconds": 1800,
            "require_permit_for_restricted": True,
            "block_evacuated_zones": True,
        },
    )
