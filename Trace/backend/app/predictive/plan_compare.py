"""
Deterministic plan comparison layer (Phase 15).

Compares candidate workforce plans with structured tradeoffs.
Does NOT pick an arbitrary AI winner. Does NOT bypass safety validation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.predictive.models_train import MODEL_VERSION
from app.predictive.prediction_service import PredictionService
from app.predictive.workforce_intelligence import WorkforceIntelligenceService

RISK_ORD = {"NORMAL": 0, "LOW": 0, "ELEVATED": 1, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}


class PlanComparisonService:
    def __init__(
        self,
        prediction_service: Optional[PredictionService] = None,
        workforce_service: Optional[WorkforceIntelligenceService] = None,
    ):
        self.pred = prediction_service or PredictionService()
        self.wi = workforce_service or WorkforceIntelligenceService(self.pred)

    def compare(
        self,
        state: Dict[str, Any],
        plans: List[Dict[str, Any]],
        horizon_minutes: int = 30,
    ) -> Dict[str, Any]:
        """
        plans: list of
          {
            "plan_id": "A",
            "actions": [
              {"type": "rotate", "worker_id": "W03", "to_zone": "Z04"},
              ...
            ]
          }
        """
        workers = state.get("workers") or []
        zones = state.get("zones") or []
        evaluations = []

        for plan in plans:
            ev = self._evaluate_plan(workers, zones, plan, horizon_minutes)
            evaluations.append(ev)

        return {
            "comparison_id": str(uuid.uuid4()),
            "horizon_minutes": horizon_minutes,
            "plans": evaluations,
            "tradeoffs": self._tradeoffs(evaluations),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_version": MODEL_VERSION,
            "data_source": "synthetic",
            "is_recommendation_only": True,
            "bypasses_safety_validator": False,
            "synthetic_training_notice": (
                "Plan comparison uses synthetic-trained models. "
                "Structured tradeoffs only — supervisor decides. "
                "All execution still requires safety validator + approval."
            ),
        }

    def _evaluate_plan(
        self,
        workers: List[Dict],
        zones: List[Dict],
        plan: Dict[str, Any],
        horizon_minutes: int,
    ) -> Dict[str, Any]:
        import copy
        w_clone = copy.deepcopy(workers)
        z_clone = copy.deepcopy(zones)
        constraints: List[str] = []
        safety_flags: List[str] = []

        for action in plan.get("actions") or []:
            atype = (action.get("type") or "").lower()
            if atype == "rotate":
                wid = action.get("worker_id")
                to_z = action.get("to_zone")
                w = next((x for x in w_clone if x.get("worker_id") == wid), None)
                z = next((x for x in z_clone if x.get("zone_id") == to_z), None)
                if not w:
                    constraints.append(f"unknown_worker:{wid}")
                    continue
                if w.get("availability") != "AVAILABLE":
                    constraints.append(f"worker_unavailable:{wid}")
                    continue
                if not z:
                    constraints.append(f"unknown_zone:{to_z}")
                    continue
                if z.get("unavailable"):
                    constraints.append(f"zone_unavailable:{to_z}")
                    safety_flags.append("ZONE_UNAVAILABLE")
                if z.get("evacuation_status") in ("EVACUATION_REQUIRED", "EVACUATED"):
                    constraints.append(f"zone_evacuation:{to_z}")
                    safety_flags.append("EVACUATION_ACTIVE")
                if RISK_ORD.get(z.get("risk_level"), 0) >= 3:
                    safety_flags.append("ZONE_CRITICAL")
                old = w.get("current_zone")
                if old:
                    for zz in z_clone:
                        if zz.get("zone_id") == old:
                            zz["occupancy"] = max(0, int(zz.get("occupancy") or 1) - 1)
                w["current_zone"] = to_z
                w["assigned_zone_id"] = to_z
                z["occupancy"] = int(z.get("occupancy") or 0) + 1
                w["time_since_last_rotation_min"] = 0
            elif atype == "clean":
                zid = action.get("zone_id")
                for z in z_clone:
                    if z.get("zone_id") == zid:
                        z["cleaning_state"] = "CLEAN"
                        z["h2s_ppm"] = max(0.1, float(z.get("h2s_ppm") or 1) * 0.4)
                        break

        zone_preds = self.pred.predict_zones(z_clone, horizon_minutes=horizon_minutes)
        worker_preds = self.pred.predict_workers(w_clone, z_clone, horizon_minutes)

        # suitability for primary rotation targets
        suitability_scores = []
        for action in plan.get("actions") or []:
            if (action.get("type") or "").lower() == "rotate":
                z = next((x for x in z_clone if x.get("zone_id") == action.get("to_zone")), None)
                w = next((x for x in w_clone if x.get("worker_id") == action.get("worker_id")), None)
                if z and w:
                    recs = self.wi.recommend_workers_for_zone(z, [w], z_clone, horizon_minutes=horizon_minutes, top_k=1)
                    if recs:
                        suitability_scores.append(recs[0]["suitability_score"])

        det = [zp["zone_deterioration"]["predicted_value"] for zp in zone_preds if zp.get("zone_deterioration")]
        exp = [zp["exposure_escalation"]["predicted_value"] for zp in zone_preds if zp.get("exposure_escalation")]
        clean = [zp["cleaning_urgency"]["predicted_value"] for zp in zone_preds if zp.get("cleaning_urgency")]
        wl = [wp["worker_workload_trend"]["predicted_value"] for wp in worker_preds if wp.get("worker_workload_trend")]
        wexp = [wp["worker_exposure_trend"]["predicted_value"] for wp in worker_preds if wp.get("worker_exposure_trend")]

        return {
            "plan_id": plan.get("plan_id") or str(uuid.uuid4()),
            "actions": plan.get("actions") or [],
            "metrics": {
                "mean_predicted_zone_deterioration": round(sum(det) / len(det), 4) if det else 0.0,
                "mean_predicted_exposure_escalation": round(sum(exp) / len(exp), 4) if exp else 0.0,
                "mean_predicted_cleaning_urgency": round(sum(clean) / len(clean), 4) if clean else 0.0,
                "mean_predicted_workload_trend": round(sum(wl) / len(wl), 4) if wl else 0.0,
                "mean_predicted_worker_exposure_trend": round(sum(wexp) / len(wexp), 4) if wexp else 0.0,
                "mean_suitability": round(sum(suitability_scores) / len(suitability_scores), 4) if suitability_scores else None,
            },
            "constraints": constraints,
            "safety_flags": list(dict.fromkeys(safety_flags)),
            "n_unavailable_zones": sum(1 for z in z_clone if z.get("unavailable")),
            "n_critical_zones": sum(1 for z in z_clone if RISK_ORD.get(z.get("risk_level"), 0) >= 3),
            "operational_impact": {
                "n_rotations": sum(1 for a in (plan.get("actions") or []) if (a.get("type") or "").lower() == "rotate"),
                "n_cleanings": sum(1 for a in (plan.get("actions") or []) if (a.get("type") or "").lower() == "clean"),
            },
        }

    def _tradeoffs(self, evaluations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Structured comparison without declaring a winner."""
        if not evaluations:
            return {}
        keys = [
            "mean_predicted_zone_deterioration",
            "mean_predicted_exposure_escalation",
            "mean_predicted_cleaning_urgency",
            "mean_predicted_workload_trend",
            "mean_predicted_worker_exposure_trend",
        ]
        ranking: Dict[str, List[str]] = {}
        for k in keys:
            sorted_plans = sorted(
                evaluations,
                key=lambda e: e["metrics"].get(k) if e["metrics"].get(k) is not None else 999,
            )
            ranking[k] = [e["plan_id"] for e in sorted_plans]

        return {
            "lower_is_better_ranking": ranking,
            "plans_with_safety_flags": [
                e["plan_id"] for e in evaluations if e.get("safety_flags")
            ],
            "plans_with_constraints": [
                e["plan_id"] for e in evaluations if e.get("constraints")
            ],
            "note": (
                "Rankings are metric-specific. No automatic winner. "
                "Supervisor must apply safety validation before any execution."
            ),
        }
