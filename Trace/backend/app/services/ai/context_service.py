"""
Read-only context assembly for Phase 16.

The LLM never queries SQL directly. Context is assembled from approved
structured sources (Phase 15 predictive services + optional scenario state
passed by the caller). Authorization filtering is applied by the caller
based on role.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.predictive.generator import generate_default_dataset
from app.predictive.prediction_service import PredictionService
from app.predictive.workforce_intelligence import WorkforceIntelligenceService
from app.predictive.simulation import WhatIfSimulator
from app.predictive.plan_compare import PlanComparisonService


class ContextService:
    """Retrieve relevant operational slices for a detected intent."""

    def __init__(
        self,
        prediction_service: Optional[PredictionService] = None,
        workforce_service: Optional[WorkforceIntelligenceService] = None,
        simulator: Optional[WhatIfSimulator] = None,
        plan_compare: Optional[PlanComparisonService] = None,
    ):
        self.pred = prediction_service
        self.wi = workforce_service
        self.sim = simulator
        self.cmp = plan_compare
        self._demo_state: Optional[Dict[str, Any]] = None

    def _ensure_services(self) -> None:
        if self.pred is None:
            self.pred = PredictionService(auto_train=True)
        if self.wi is None:
            self.wi = WorkforceIntelligenceService(self.pred)
        if self.sim is None:
            self.sim = WhatIfSimulator(self.pred, self.wi)
        if self.cmp is None:
            self.cmp = PlanComparisonService(self.pred, self.wi)

    def get_operational_state(
        self,
        state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return workers/zones snapshot. Uses supplied state or synthetic demo state."""
        if state and (state.get("workers") or state.get("zones")):
            return {
                "workers": copy.deepcopy(state.get("workers") or []),
                "zones": copy.deepcopy(state.get("zones") or []),
                "source": state.get("source", "caller_supplied"),
                "context_timestamp": datetime.now(timezone.utc).isoformat(),
            }
        if self._demo_state is None:
            payload = generate_default_dataset(
                seed=42, n_workers=10, n_zones=6, duration_hours=18, difficulty="medium"
            )
            snap = payload["snapshots"][-1]
            self._demo_state = {
                "workers": snap["workers"],
                "zones": snap["zones"],
                "source": "synthetic_demo_snapshot",
                "events_sample": payload.get("events", [])[-15:],
                "context_timestamp": datetime.now(timezone.utc).isoformat(),
            }
        return copy.deepcopy(self._demo_state)

    def build_context(
        self,
        intent: str,
        entities: Dict[str, List[str]],
        question: str = "",
        state: Optional[Dict[str, Any]] = None,
        role: str = "SUPERVISOR",
    ) -> Dict[str, Any]:
        self._ensure_services()
        op = self.get_operational_state(state)
        workers = op["workers"]
        zones = op["zones"]
        evidence: List[Dict[str, Any]] = []
        facts: Dict[str, Any] = {
            "context_source": op.get("source"),
            "context_timestamp": op.get("context_timestamp"),
            "role": role,
        }

        # Role filter: workers get restricted view
        restricted = role.upper() == "WORKER"

        if intent in ("rotation_explanation", "worker_status", "general"):
            facts.update(self._worker_facts(workers, zones, entities.get("worker_ids") or [], evidence, restricted))

        if intent in ("zone_priority", "zone_status", "cleaning_status", "prediction_explanation", "general"):
            facts.update(self._zone_facts(zones, entities.get("zone_ids") or [], evidence, restricted))

        if intent in ("prediction_explanation", "zone_priority", "rotation_explanation"):
            facts.update(self._prediction_facts(zones, workers, entities, evidence))

        if intent == "zone_priority":
            facts.update(self._priority_facts(zones, evidence))

        if intent == "cleaning_status":
            facts.update(self._cleaning_facts(zones, evidence))

        if intent == "what_if":
            facts.update(self._what_if_facts(workers, zones, entities, question, evidence))

        if intent == "plan_comparison":
            facts.update(self._plan_compare_facts(workers, zones, evidence))

        if intent == "shift_summary":
            facts.update(self._shift_facts(workers, zones, op, evidence))

        if intent == "incident_summary":
            facts.update(self._incident_facts(workers, zones, op, entities, evidence))

        if intent == "safety_block_reason":
            facts.update(self._safety_facts(workers, zones, entities, evidence))

        if intent == "alert_explanation":
            facts.update(self._alert_facts(zones, evidence))

        if restricted:
            facts = self._restrict_for_worker(facts)

        return {
            "facts": facts,
            "evidence": evidence,
            "context_timestamp": op.get("context_timestamp"),
            "operational_source": op.get("source"),
        }

    # ---- fact builders ----

    def _worker_facts(
        self,
        workers: List[Dict],
        zones: List[Dict],
        worker_ids: List[str],
        evidence: List[Dict],
        restricted: bool,
    ) -> Dict[str, Any]:
        selected = workers
        if worker_ids:
            selected = [w for w in workers if w.get("worker_id") in worker_ids]
            if not selected:
                return {"workers_found": False, "requested_worker_ids": worker_ids}
        zone_map = {z.get("zone_id"): z for z in zones}
        out = []
        for w in selected[:8]:
            wid = w.get("worker_id")
            z = zone_map.get(w.get("current_zone") or "", {})
            item = {
                "worker_id": wid,
                "role": w.get("role"),
                "skills": w.get("skills"),
                "availability": w.get("availability"),
                "current_zone": w.get("current_zone"),
                "assigned_zone_id": w.get("assigned_zone_id"),
                "recent_exposure": w.get("recent_exposure"),
                "cumulative_workload": w.get("cumulative_workload"),
                "rotation_count": w.get("rotation_count"),
                "time_since_last_rotation_min": w.get("time_since_last_rotation_min"),
                "recovery_rest_proxy": w.get("recovery_rest_proxy"),
                "zone_risk": z.get("risk_level"),
                "zone_h2s_ppm": z.get("h2s_ppm"),
            }
            out.append(item)
            evidence.append({
                "type": "worker",
                "id": wid,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        return {"workers": out, "workers_found": len(out) > 0}

    def _zone_facts(
        self,
        zones: List[Dict],
        zone_ids: List[str],
        evidence: List[Dict],
        restricted: bool,
    ) -> Dict[str, Any]:
        selected = zones
        if zone_ids:
            selected = [z for z in zones if z.get("zone_id") in zone_ids]
            if not selected:
                return {"zones_found": False, "requested_zone_ids": zone_ids}
        out = []
        for z in selected[:8]:
            item = {
                "zone_id": z.get("zone_id"),
                "risk_level": z.get("risk_level"),
                "h2s_ppm": z.get("h2s_ppm"),
                "cleaning_state": z.get("cleaning_state"),
                "occupancy": z.get("occupancy"),
                "neighboring_zones": z.get("neighboring_zones"),
                "ventilation_proxy": z.get("ventilation_proxy"),
                "temperature_c": z.get("temperature_c"),
                "unavailable": z.get("unavailable", False),
                "evacuation_status": z.get("evacuation_status", "NONE"),
            }
            out.append(item)
            evidence.append({
                "type": "zone",
                "id": z.get("zone_id"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        return {"zones": out, "zones_found": len(out) > 0}

    def _prediction_facts(
        self,
        zones: List[Dict],
        workers: List[Dict],
        entities: Dict[str, List[str]],
        evidence: List[Dict],
    ) -> Dict[str, Any]:
        zids = entities.get("zone_ids") or []
        target_zones = [z for z in zones if not zids or z.get("zone_id") in zids][:6]
        zone_preds = self.pred.predict_zones(target_zones, horizon_minutes=30)
        preds_out = []
        for zp in zone_preds:
            for key in ("zone_deterioration", "exposure_escalation", "cleaning_urgency"):
                pr = zp.get(key)
                if not pr:
                    continue
                preds_out.append({
                    "prediction_type": key,
                    "entity_id": zp.get("zone_id"),
                    "predicted_value": pr.get("predicted_value"),
                    "confidence": pr.get("confidence"),
                    "risk_band": pr.get("risk_band"),
                    "horizon_minutes": pr.get("horizon_minutes"),
                    "model_version": pr.get("model_version"),
                    "top_factors": pr.get("top_factors"),
                    "explanation": pr.get("explanation"),
                    "data_source": pr.get("data_source"),
                    "synthetic_training_notice": pr.get("synthetic_training_notice"),
                })
                evidence.append({
                    "type": "prediction",
                    "id": pr.get("prediction_id"),
                    "timestamp": pr.get("generated_at"),
                })
        # workforce recommendations for first zone
        recs = []
        if target_zones:
            recs = self.wi.recommend_workers_for_zone(
                target_zones[0], workers, zones, top_k=3
            )
            for r in recs:
                evidence.append({
                    "type": "recommendation",
                    "id": r.get("recommendation_id"),
                    "timestamp": r.get("generated_at"),
                })
        return {
            "predictions": preds_out,
            "recommendations": [
                {
                    "worker_id": r.get("worker_id"),
                    "target_zone": r.get("target_zone"),
                    "suitability_score": r.get("suitability_score"),
                    "reasons": r.get("reasons"),
                    "constraints": r.get("constraints"),
                    "is_recommendation_only": True,
                }
                for r in recs
            ],
            "prediction_data_source": "synthetic",
        }

    def _priority_facts(self, zones: List[Dict], evidence: List[Dict]) -> Dict[str, Any]:
        zone_preds = self.pred.predict_zones(zones, horizon_minutes=30)
        ranked = []
        for zp in zone_preds:
            det = zp.get("zone_deterioration") or {}
            clean = zp.get("cleaning_urgency") or {}
            score = float(det.get("predicted_value") or 0) * 0.6 + float(clean.get("predicted_value") or 0) * 0.4
            zid = zp.get("zone_id")
            z = next((x for x in zones if x.get("zone_id") == zid), {})
            ranked.append({
                "zone_id": zid,
                "priority_score_composite": round(score, 4),
                "current_risk": z.get("risk_level"),
                "h2s_ppm": z.get("h2s_ppm"),
                "cleaning_state": z.get("cleaning_state"),
                "predicted_deterioration": det.get("predicted_value"),
                "predicted_cleaning_urgency": clean.get("predicted_value"),
                "occupancy": z.get("occupancy"),
                "neighboring_zones": z.get("neighboring_zones"),
                "factors": (det.get("explanation") or []) + (clean.get("explanation") or []),
            })
            if det.get("prediction_id"):
                evidence.append({"type": "prediction", "id": det["prediction_id"], "timestamp": det.get("generated_at")})
        ranked.sort(key=lambda x: -x["priority_score_composite"])
        return {
            "zone_priority_ranking": ranked,
            "highest_priority_zone": ranked[0] if ranked else None,
            "note": "Priority composite is derived from Phase 15 predictions; not a new LLM score.",
        }

    def _cleaning_facts(self, zones: List[Dict], evidence: List[Dict]) -> Dict[str, Any]:
        preds = self.pred.predict_cleaning(zones, horizon_minutes=30)
        items = []
        for p in preds:
            items.append({
                "zone_id": p.get("entity_id"),
                "predicted_urgency": p.get("predicted_value"),
                "risk_band": p.get("risk_band"),
                "explanation": p.get("explanation"),
            })
            evidence.append({"type": "prediction", "id": p.get("prediction_id"), "timestamp": p.get("generated_at")})
        states = [
            {"zone_id": z.get("zone_id"), "cleaning_state": z.get("cleaning_state"), "h2s_ppm": z.get("h2s_ppm")}
            for z in zones
        ]
        return {"cleaning_states": states, "cleaning_predictions": items}

    def _what_if_facts(
        self,
        workers: List[Dict],
        zones: List[Dict],
        entities: Dict[str, List[str]],
        question: str,
        evidence: List[Dict],
    ) -> Dict[str, Any]:
        scenario = self._infer_scenario(question, entities, zones, workers)
        result = self.sim.run(
            {"workers": workers, "zones": zones},
            scenario,
            horizon_minutes=30,
        )
        evidence.append({
            "type": "simulation",
            "id": result.get("simulation_id"),
            "timestamp": result.get("generated_at"),
        })
        return {
            "simulation": {
                "simulation_id": result.get("simulation_id"),
                "simulation": True,
                "scenario": result.get("scenario"),
                "comparison": result.get("comparison"),
                "affected_workers": result.get("affected_workers"),
                "affected_zones": result.get("affected_zones"),
                "recommended_action": result.get("recommended_action"),
                "mutates_authoritative_state": False,
                "baseline_summary": (result.get("baseline") or {}).get("summary"),
                "projected_summary": (result.get("projected") or {}).get("summary"),
            }
        }

    def _infer_scenario(
        self,
        question: str,
        entities: Dict[str, List[str]],
        zones: List[Dict],
        workers: List[Dict],
    ) -> Dict[str, Any]:
        q = (question or "").lower()
        zids = entities.get("zone_ids") or []
        wids = entities.get("worker_ids") or []
        if "unavailable" in q and zids:
            return {"type": "zone_unavailable", "zone_id": zids[0]}
        if "unavailable" in q and wids:
            return {"type": "worker_unavailable", "worker_id": wids[0]}
        if "delay" in q and "clean" in q:
            zid = zids[0] if zids else (zones[0]["zone_id"] if zones else "Z01")
            return {"type": "delay_cleaning", "zone_id": zid, "delay_minutes": 30}
        if "clean" in q and ("now" in q or "immediate" in q):
            zid = zids[0] if zids else (zones[0]["zone_id"] if zones else "Z01")
            return {"type": "clean_now", "zone_id": zid}
        if "rotat" in q and wids:
            to_z = zids[0] if zids else (zones[0]["zone_id"] if zones else "Z01")
            return {"type": "rotate_now", "worker_id": wids[0], "to_zone": to_z}
        if zids:
            return {"type": "zone_unavailable", "zone_id": zids[0]}
        if wids:
            return {"type": "worker_unavailable", "worker_id": wids[0]}
        return {"type": "delay_cleaning", "zone_id": zones[0]["zone_id"] if zones else "Z01"}

    def _plan_compare_facts(
        self,
        workers: List[Dict],
        zones: List[Dict],
        evidence: List[Dict],
    ) -> Dict[str, Any]:
        avail = [w for w in workers if w.get("availability") == "AVAILABLE"]
        if len(avail) < 2 or len(zones) < 1:
            return {"plan_comparison_available": False}
        plans = [
            {
                "plan_id": "A",
                "actions": [{"type": "rotate", "worker_id": avail[0]["worker_id"], "to_zone": zones[0]["zone_id"]}],
            },
            {
                "plan_id": "B",
                "actions": [{"type": "rotate", "worker_id": avail[1]["worker_id"], "to_zone": zones[0]["zone_id"]}],
            },
        ]
        result = self.cmp.compare({"workers": workers, "zones": zones}, plans)
        evidence.append({
            "type": "plan_comparison",
            "id": result.get("comparison_id"),
            "timestamp": result.get("generated_at"),
        })
        return {
            "plan_comparison": {
                "comparison_id": result.get("comparison_id"),
                "plans": result.get("plans"),
                "tradeoffs": result.get("tradeoffs"),
                "is_recommendation_only": True,
                "bypasses_safety_validator": False,
            }
        }

    def _shift_facts(
        self,
        workers: List[Dict],
        zones: List[Dict],
        op: Dict[str, Any],
        evidence: List[Dict],
    ) -> Dict[str, Any]:
        n_unavail_w = sum(1 for w in workers if w.get("availability") != "AVAILABLE")
        n_crit = sum(1 for z in zones if z.get("risk_level") == "CRITICAL")
        n_overdue = sum(1 for z in zones if z.get("cleaning_state") == "OVERDUE")
        zone_preds = self.pred.predict_zones(zones[:6], horizon_minutes=30)
        evidence.append({"type": "shift_snapshot", "id": "SHIFT-DEMO", "timestamp": op.get("context_timestamp")})
        return {
            "observed": {
                "n_workers": len(workers),
                "n_unavailable_workers": n_unavail_w,
                "n_zones": len(zones),
                "n_critical_zones": n_crit,
                "n_overdue_cleaning": n_overdue,
                "zone_risk_levels": {z.get("zone_id"): z.get("risk_level") for z in zones},
            },
            "predicted": {
                "sample_zone_predictions": [
                    {
                        "zone_id": zp.get("zone_id"),
                        "deterioration": (zp.get("zone_deterioration") or {}).get("predicted_value"),
                        "cleaning_urgency": (zp.get("cleaning_urgency") or {}).get("predicted_value"),
                    }
                    for zp in zone_preds[:4]
                ],
                "data_source": "synthetic",
            },
            "pending_actions": {
                "note": "Pending supervisor approvals are tracked by Phase 14 execution services; not mutated by AI.",
            },
        }

    def _incident_facts(
        self,
        workers: List[Dict],
        zones: List[Dict],
        op: Dict[str, Any],
        entities: Dict[str, List[str]],
        evidence: List[Dict],
    ) -> Dict[str, Any]:
        # Use highest-risk zone as proxy incident if no real incident store
        crit = [z for z in zones if z.get("risk_level") in ("HIGH", "CRITICAL")]
        z = crit[0] if crit else (zones[0] if zones else {})
        evidence.append({
            "type": "incident_proxy",
            "id": f"INC-{z.get('zone_id', 'UNKNOWN')}",
            "timestamp": op.get("context_timestamp"),
        })
        return {
            "incident": {
                "incident_id": f"INC-{z.get('zone_id', 'UNKNOWN')}",
                "zone_id": z.get("zone_id"),
                "risk_level": z.get("risk_level"),
                "h2s_ppm": z.get("h2s_ppm"),
                "evacuation_status": z.get("evacuation_status"),
                "note": "Derived from current high-risk zone state; no separate incident table in demo context.",
            },
            "related_workers": [
                w.get("worker_id") for w in workers if w.get("current_zone") == z.get("zone_id")
            ],
        }

    def _safety_facts(
        self,
        workers: List[Dict],
        zones: List[Dict],
        entities: Dict[str, List[str]],
        evidence: List[Dict],
    ) -> Dict[str, Any]:
        blocks = []
        for z in zones:
            if z.get("unavailable"):
                blocks.append({"code": "ZONE_UNAVAILABLE", "zone_id": z.get("zone_id")})
            if z.get("evacuation_status") in ("EVACUATION_REQUIRED", "EVACUATED"):
                blocks.append({"code": "EVACUATION_ACTIVE", "zone_id": z.get("zone_id")})
            if z.get("risk_level") == "CRITICAL":
                blocks.append({"code": "ZONE_CRITICAL", "zone_id": z.get("zone_id"),
                               "note": "CRITICAL does not auto-evacuate; safety validator remains authority."})
        for w in workers:
            if w.get("availability") != "AVAILABLE":
                blocks.append({"code": "WORKER_UNAVAILABLE", "worker_id": w.get("worker_id")})
        evidence.append({"type": "safety_snapshot", "id": "SAFETY-CTX", "timestamp": datetime.now(timezone.utc).isoformat()})
        return {
            "safety_constraints": blocks,
            "authority": "Phase 14.1.2 deterministic safety validator — AI cannot override.",
        }

    def _alert_facts(self, zones: List[Dict], evidence: List[Dict]) -> Dict[str, Any]:
        alerts = []
        for z in zones:
            if z.get("risk_level") in ("HIGH", "CRITICAL"):
                aid = f"ALERT-{z.get('zone_id')}-{z.get('risk_level')}"
                alerts.append({
                    "alert_id": aid,
                    "severity": z.get("risk_level"),
                    "zone_id": z.get("zone_id"),
                    "h2s_ppm": z.get("h2s_ppm"),
                    "status": "OPEN",
                })
                evidence.append({"type": "alert", "id": aid, "timestamp": datetime.now(timezone.utc).isoformat()})
        return {"alerts": alerts, "alerts_found": len(alerts) > 0}

    def _restrict_for_worker(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        """Strip privileged operational detail for WORKER role."""
        allowed_keys = {"workers", "zones", "context_source", "context_timestamp", "role"}
        return {k: v for k, v in facts.items() if k in allowed_keys}
