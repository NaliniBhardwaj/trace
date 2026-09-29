"""
What-if simulation engine (Phase 15).

Clones/projects state — NEVER mutates authoritative operational state.
Every result has simulation=true.
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.predictive.models_train import MODEL_VERSION
from app.predictive.prediction_service import PredictionService
from app.predictive.workforce_intelligence import WorkforceIntelligenceService

RISK_ORD = {"NORMAL": 0, "LOW": 0, "ELEVATED": 1, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}


class WhatIfSimulator:
    """Compare hypothetical operational scenarios against a projected baseline."""

    def __init__(
        self,
        prediction_service: Optional[PredictionService] = None,
        workforce_service: Optional[WorkforceIntelligenceService] = None,
    ):
        self.pred = prediction_service or PredictionService()
        self.wi = workforce_service or WorkforceIntelligenceService(self.pred)

    def run(
        self,
        state: Dict[str, Any],
        scenario: Dict[str, Any],
        horizon_minutes: int = 30,
    ) -> Dict[str, Any]:
        """
        state: {"workers": [...], "zones": [...]}
        scenario examples:
          {"type": "delay_cleaning", "zone_id": "Z04", "delay_minutes": 30}
          {"type": "worker_unavailable", "worker_id": "W03"}
          {"type": "zone_unavailable", "zone_id": "Z07"}
          {"type": "rotate_now", "worker_id": "W03", "to_zone": "Z04"}
          {"type": "clean_now", "zone_id": "Z04"}
          {"type": "reject_rotation", "worker_id": "W03", "from_zone": "Z02", "to_zone": "Z04"}
        """
        baseline = self._project(copy.deepcopy(state), None, horizon_minutes)
        projected = self._project(copy.deepcopy(state), scenario, horizon_minutes)

        sim_id = str(uuid.uuid4())
        comparison = self._compare(baseline, projected, scenario)

        return {
            "simulation_id": sim_id,
            "simulation": True,
            "scenario": scenario,
            "horizon_minutes": horizon_minutes,
            "baseline": baseline,
            "projected": projected,
            "comparison": comparison,
            "affected_workers": comparison.get("affected_workers", []),
            "affected_zones": comparison.get("affected_zones", []),
            "expected_conflicts": comparison.get("expected_conflicts", []),
            "safety_constraint_notes": comparison.get("safety_constraint_notes", []),
            "recommended_action": comparison.get("recommended_action"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_version": MODEL_VERSION,
            "data_source": "synthetic",
            "synthetic_training_notice": (
                "Simulation uses synthetic-trained predictive models. "
                "Does NOT mutate authoritative state. Recommendation only."
            ),
            "mutates_authoritative_state": False,
        }

    def _project(
        self,
        state: Dict[str, Any],
        scenario: Optional[Dict[str, Any]],
        horizon_minutes: int,
    ) -> Dict[str, Any]:
        workers = copy.deepcopy(state.get("workers") or [])
        zones = copy.deepcopy(state.get("zones") or [])

        if scenario:
            self._apply_scenario_to_clone(workers, zones, scenario)

        zone_preds = self.pred.predict_zones(zones, horizon_minutes=horizon_minutes)
        worker_preds = self.pred.predict_workers(workers, zones, horizon_minutes)

        return {
            "workers": workers,
            "zones": zones,
            "zone_predictions": zone_preds,
            "worker_predictions": worker_preds,
            "summary": self._summarize(zone_preds, worker_preds, zones, workers),
        }

    def _apply_scenario_to_clone(
        self,
        workers: List[Dict],
        zones: List[Dict],
        scenario: Dict[str, Any],
    ) -> None:
        stype = (scenario.get("type") or "").lower()
        if stype == "delay_cleaning":
            zid = scenario.get("zone_id")
            for z in zones:
                if z.get("zone_id") == zid:
                    z["cleaning_state"] = "OVERDUE"
                    z["h2s_ppm"] = float(z.get("h2s_ppm") or 1) * 1.35
                    z["deterioration_trend"] = float(z.get("deterioration_trend") or 0) + 0.08
                    break
        elif stype == "worker_unavailable":
            wid = scenario.get("worker_id")
            for w in workers:
                if w.get("worker_id") == wid:
                    w["availability"] = "UNAVAILABLE"
                    break
        elif stype == "zone_unavailable":
            zid = scenario.get("zone_id")
            for z in zones:
                if z.get("zone_id") == zid:
                    z["unavailable"] = True
                    z["occupancy"] = 0
                    break
            for w in workers:
                if w.get("current_zone") == zid:
                    w["current_zone"] = None
                    w["assigned_zone_id"] = None
        elif stype == "rotate_now":
            wid = scenario.get("worker_id")
            to_z = scenario.get("to_zone")
            for w in workers:
                if w.get("worker_id") == wid and w.get("availability") == "AVAILABLE":
                    old = w.get("current_zone")
                    if old:
                        for z in zones:
                            if z.get("zone_id") == old:
                                z["occupancy"] = max(0, int(z.get("occupancy") or 1) - 1)
                    w["current_zone"] = to_z
                    w["assigned_zone_id"] = to_z
                    w["time_since_last_rotation_min"] = 0
                    for z in zones:
                        if z.get("zone_id") == to_z:
                            z["occupancy"] = int(z.get("occupancy") or 0) + 1
                    break
        elif stype == "clean_now":
            zid = scenario.get("zone_id")
            for z in zones:
                if z.get("zone_id") == zid:
                    z["cleaning_state"] = "CLEAN"
                    z["h2s_ppm"] = max(0.1, float(z.get("h2s_ppm") or 1) * 0.4)
                    z["deterioration_trend"] = max(-0.05, float(z.get("deterioration_trend") or 0) - 0.1)
                    break
        elif stype == "reject_rotation":
            # leave state as-is (rotation not applied); optionally bump exposure on source
            wid = scenario.get("worker_id")
            for w in workers:
                if w.get("worker_id") == wid:
                    w["recent_exposure"] = float(w.get("recent_exposure") or 0) * 1.1
                    w["time_since_last_rotation_min"] = int(w.get("time_since_last_rotation_min") or 0) + 30
                    break

    def _summarize(
        self,
        zone_preds: List[Dict],
        worker_preds: List[Dict],
        zones: List[Dict],
        workers: List[Dict],
    ) -> Dict[str, Any]:
        det_vals = []
        clean_vals = []
        exp_vals = []
        for zp in zone_preds:
            if zp.get("zone_deterioration"):
                det_vals.append(zp["zone_deterioration"]["predicted_value"])
            if zp.get("cleaning_urgency"):
                clean_vals.append(zp["cleaning_urgency"]["predicted_value"])
            if zp.get("exposure_escalation"):
                exp_vals.append(zp["exposure_escalation"]["predicted_value"])

        wl_vals = []
        for wp in worker_preds:
            if wp.get("worker_workload_trend"):
                wl_vals.append(wp["worker_workload_trend"]["predicted_value"])

        return {
            "mean_zone_deterioration": round(sum(det_vals) / len(det_vals), 4) if det_vals else 0.0,
            "mean_cleaning_urgency": round(sum(clean_vals) / len(clean_vals), 4) if clean_vals else 0.0,
            "mean_exposure_escalation": round(sum(exp_vals) / len(exp_vals), 4) if exp_vals else 0.0,
            "mean_workload_trend": round(sum(wl_vals) / len(wl_vals), 4) if wl_vals else 0.0,
            "n_unavailable_workers": sum(1 for w in workers if w.get("availability") != "AVAILABLE"),
            "n_unavailable_zones": sum(1 for z in zones if z.get("unavailable")),
            "n_critical_zones": sum(1 for z in zones if RISK_ORD.get(z.get("risk_level"), 0) >= 3),
        }

    def _compare(
        self,
        baseline: Dict[str, Any],
        projected: Dict[str, Any],
        scenario: Dict[str, Any],
    ) -> Dict[str, Any]:
        bsum = baseline["summary"]
        psum = projected["summary"]
        deltas = {
            "zone_deterioration_delta": round(psum["mean_zone_deterioration"] - bsum["mean_zone_deterioration"], 4),
            "cleaning_urgency_delta": round(psum["mean_cleaning_urgency"] - bsum["mean_cleaning_urgency"], 4),
            "exposure_escalation_delta": round(psum["mean_exposure_escalation"] - bsum["mean_exposure_escalation"], 4),
            "workload_trend_delta": round(psum["mean_workload_trend"] - bsum["mean_workload_trend"], 4),
        }

        affected_workers = []
        affected_zones = []
        stype = (scenario.get("type") or "").lower()
        if scenario.get("worker_id"):
            affected_workers.append(scenario["worker_id"])
        if scenario.get("zone_id"):
            affected_zones.append(scenario["zone_id"])
        if scenario.get("to_zone"):
            affected_zones.append(scenario["to_zone"])
        if scenario.get("from_zone"):
            affected_zones.append(scenario["from_zone"])

        conflicts = []
        safety_notes = []
        for z in projected["zones"]:
            if z.get("unavailable"):
                conflicts.append({"code": "ZONE_UNAVAILABLE", "zone_id": z.get("zone_id")})
            if RISK_ORD.get(z.get("risk_level"), 0) >= 3:
                safety_notes.append({
                    "code": "ZONE_CRITICAL",
                    "zone_id": z.get("zone_id"),
                    "note": "CRITICAL risk remains under deterministic safety validator authority; simulation does not authorize evacuation or entry.",
                })
            if z.get("evacuation_status") in ("EVACUATION_REQUIRED", "EVACUATED"):
                safety_notes.append({
                    "code": "EVACUATION_ACTIVE",
                    "zone_id": z.get("zone_id"),
                    "note": "Evacuation status is authoritative; predictive layer cannot override.",
                })

        for w in projected["workers"]:
            if w.get("availability") != "AVAILABLE":
                conflicts.append({"code": "WORKER_UNAVAILABLE", "worker_id": w.get("worker_id")})

        # recommended action (advisory)
        rec = "no_change"
        if stype == "delay_cleaning" and deltas["cleaning_urgency_delta"] > 0.05:
            rec = "prefer_clean_sooner"
        elif stype == "clean_now" and deltas["zone_deterioration_delta"] < -0.05:
            rec = "cleaning_reduces_predicted_risk"
        elif stype == "rotate_now" and deltas["exposure_escalation_delta"] < 0:
            rec = "rotation_may_reduce_exposure"
        elif stype == "worker_unavailable":
            rec = "plan_coverage_for_unavailable_worker"
        elif stype == "zone_unavailable":
            rec = "reassign_workers_from_unavailable_zone"

        return {
            "deltas": deltas,
            "affected_workers": list(dict.fromkeys(affected_workers)),
            "affected_zones": list(dict.fromkeys(affected_zones)),
            "expected_conflicts": conflicts,
            "safety_constraint_notes": safety_notes,
            "recommended_action": rec,
            "baseline_summary": bsum,
            "projected_summary": psum,
        }
