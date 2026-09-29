"""
Worker suitability / rotation intelligence (Phase 15).

Produces WorkerRecommendation — NEVER mutates assignments.
Final flow remains: PREDICTION → RECOMMENDATION → SAFETY VALIDATOR
→ SUPERVISOR APPROVAL → EXECUTION SERVICE.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from app.predictive.models_train import MODEL_VERSION
from app.predictive.prediction_service import PredictionService

RISK_ORD = {"NORMAL": 0, "LOW": 0, "ELEVATED": 1, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}


class WorkforceIntelligenceService:
    """Predictive worker suitability for rotation / reassignment recommendations."""

    def __init__(self, prediction_service: Optional[PredictionService] = None):
        self.pred = prediction_service or PredictionService()

    def recommend_workers_for_zone(
        self,
        target_zone: Dict[str, Any],
        workers: List[Dict[str, Any]],
        zones: Optional[List[Dict[str, Any]]] = None,
        required_skills: Optional[List[str]] = None,
        horizon_minutes: int = 30,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        zones = zones or [target_zone]
        zone_preds = self.pred.predict_zones([target_zone], horizon_minutes=horizon_minutes)
        zone_pred = zone_preds[0] if zone_preds else {}
        det = zone_pred.get("zone_deterioration") or {}
        exp = zone_pred.get("exposure_escalation") or {}
        predicted_zone_risk = float(det.get("predicted_value") or 0)
        predicted_exposure_esc = float(exp.get("predicted_value") or 0)

        worker_preds = self.pred.predict_workers(workers, zones, horizon_minutes)
        pred_by_id = {wp["worker_id"]: wp for wp in worker_preds}

        req = set(required_skills or [])
        recommendations: List[Dict[str, Any]] = []

        for w in workers:
            wid = w.get("worker_id") or w.get("id")
            reasons: List[str] = []
            constraints: List[str] = []
            score = 0.5  # baseline

            # availability
            if w.get("availability") != "AVAILABLE":
                constraints.append("worker_unavailable")
                score = 0.0
            # skills
            skills = set(w.get("skills") or [])
            if req:
                missing = req - skills
                if missing:
                    constraints.append(f"skill_mismatch:{','.join(sorted(missing))}")
                    score -= 0.25
                else:
                    reasons.append("skills_compatible")
                    score += 0.1

            # zone constraints
            if target_zone.get("unavailable"):
                constraints.append("target_zone_unavailable")
                score = 0.0
            if target_zone.get("evacuation_status") in ("EVACUATION_REQUIRED", "EVACUATED"):
                constraints.append("zone_evacuation")
                score = min(score, 0.05)
            if RISK_ORD.get(target_zone.get("risk_level", "NORMAL"), 0) >= 3:
                constraints.append("zone_critical")
                # still allow recommendation but low score — safety validator is authority
                score -= 0.2

            # exposure / workload
            recent_exp = float(w.get("recent_exposure") or 0)
            workload = float(w.get("cumulative_workload") or 0)
            recovery = float(w.get("recovery_rest_proxy") or 0.5)

            if recent_exp > 30:
                reasons.append("elevated_recent_exposure")
                score -= 0.15
            elif recent_exp < 10:
                reasons.append("low_recent_exposure")
                score += 0.08

            if workload > 30:
                reasons.append("high_workload")
                score -= 0.1
            if recovery < 0.35:
                reasons.append("low_recovery")
                score -= 0.12
            else:
                score += 0.05

            # predictive adjustments
            wp = pred_by_id.get(wid, {})
            exp_trend = wp.get("worker_exposure_trend") or {}
            wl_trend = wp.get("worker_workload_trend") or {}
            pred_exp_change = float(exp_trend.get("predicted_value") or 0)
            pred_wl_change = float(wl_trend.get("predicted_value") or 0)

            if predicted_zone_risk > 0.6:
                score -= 0.1
                reasons.append("target_zone_predicted_to_deteriorate")
            if pred_exp_change > 5:
                score -= 0.08
                reasons.append("predicted_exposure_increase")
            if pred_wl_change > 5:
                score -= 0.05
                reasons.append("predicted_workload_increase")

            # current assignment preference
            if w.get("current_zone") == (target_zone.get("zone_id") or target_zone.get("id")):
                reasons.append("already_in_target_zone")
                score += 0.05

            # rotation history — prefer workers ready for rotation
            tsr = float(w.get("time_since_last_rotation_min") or 0)
            if tsr > 180:
                score += 0.05
                reasons.append("rotation_interval_satisfied")
            elif tsr < 60:
                score -= 0.1
                constraints.append("recent_rotation_cooldown")

            score = max(0.0, min(1.0, score))
            if constraints and score > 0.15 and any(
                c.startswith("worker_unavailable") or c.startswith("target_zone") or c == "zone_evacuation"
                for c in constraints
            ):
                score = min(score, 0.1)

            recommendations.append({
                "recommendation_id": str(uuid.uuid4()),
                "worker_id": wid,
                "target_zone": target_zone.get("zone_id") or target_zone.get("id"),
                "suitability_score": round(score, 4),
                "predicted_exposure_change": round(pred_exp_change, 4),
                "predicted_workload_change": round(pred_wl_change, 4),
                "predicted_zone_deterioration": round(predicted_zone_risk, 4),
                "predicted_zone_exposure_escalation": round(predicted_exposure_esc, 4),
                "reasons": reasons,
                "constraints": constraints,
                "model_version": MODEL_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "data_source": "synthetic",
                "synthetic_training_notice": (
                    "Suitability scores from synthetic-trained models; "
                    "recommendation only — does not execute assignment."
                ),
                "is_recommendation_only": True,
            })

        recommendations.sort(key=lambda r: (-r["suitability_score"], r["worker_id"]))
        return recommendations[:top_k]

    def suitability_matrix(
        self,
        workers: List[Dict[str, Any]],
        zones: List[Dict[str, Any]],
        horizon_minutes: int = 30,
    ) -> Dict[str, Any]:
        """Compute suitability for all worker-zone pairs (capped for large sets)."""
        matrix = []
        for z in zones[:12]:
            recs = self.recommend_workers_for_zone(
                z, workers, zones, horizon_minutes=horizon_minutes, top_k=len(workers)
            )
            matrix.append({
                "zone_id": z.get("zone_id") or z.get("id"),
                "recommendations": recs,
            })
        return {
            "matrix": matrix,
            "model_version": MODEL_VERSION,
            "horizon_minutes": horizon_minutes,
            "is_recommendation_only": True,
            "data_source": "synthetic",
        }
