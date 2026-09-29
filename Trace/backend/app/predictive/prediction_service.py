"""
Predictive Workforce Intelligence — prediction service (READ-ONLY).

Consumes current state + model outputs → structured PredictionResult.
Never executes worker movement.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from app.predictive.features import FeaturePipeline
from app.predictive.models_train import (
    MODEL_VERSION,
    ensure_models_trained,
    load_model_bundle,
    MODEL_SPECS,
)

RISK_BANDS = [
    (0.0, 0.25, "LOW"),
    (0.25, 0.50, "MODERATE"),
    (0.50, 0.75, "HIGH"),
    (0.75, 1.01, "CRITICAL"),
]


def _risk_band(score: float) -> str:
    for lo, hi, name in RISK_BANDS:
        if lo <= score < hi:
            return name
    return "CRITICAL"


def _top_factors(importance: List[Dict], features: Dict[str, float], k: int = 5) -> List[Dict[str, Any]]:
    if not importance:
        # fallback: largest absolute feature values
        items = sorted(features.items(), key=lambda x: -abs(x[1]))[:k]
        return [{"feature": f, "value": float(v), "contribution": "elevated" if v > 0 else "reduced"} for f, v in items]
    ranked = sorted(importance, key=lambda x: -x.get("importance", 0))[:k]
    out = []
    for item in ranked:
        f = item["feature"]
        val = features.get(f, 0.0)
        out.append({
            "feature": f,
            "importance": item.get("importance", 0),
            "value": float(val),
            "direction": "elevated" if val > 0 else "near_baseline",
        })
    return out


class PredictionService:
    """Generate structured predictions from live or scenario state."""

    def __init__(self, auto_train: bool = True):
        if auto_train:
            ensure_models_trained()
        self.bundle = load_model_bundle()
        self.pipe = FeaturePipeline()
        self._audit: List[Dict[str, Any]] = []

    @property
    def model_version(self) -> str:
        return MODEL_VERSION

    def list_models(self) -> List[Dict[str, Any]]:
        out = []
        for name, meta in self.bundle.get("meta", {}).items():
            out.append({
                "model_id": name,
                "model_version": meta.get("model_version", MODEL_VERSION),
                "task": meta.get("task"),
                "description": meta.get("description"),
                "training_data_source": meta.get("training_data_source", "synthetic"),
                "horizon_minutes": meta.get("horizon_minutes"),
                "metrics": meta.get("metrics"),
                "synthetic_training_notice": meta.get("synthetic_training_notice"),
            })
        return out

    def model_metrics(self, model_id: str) -> Optional[Dict[str, Any]]:
        return self.bundle.get("meta", {}).get(model_id)

    def predict_zones(
        self,
        zones: List[Dict[str, Any]],
        history: Optional[Dict[str, List[Dict]]] = None,
        horizon_minutes: int = 30,
    ) -> List[Dict[str, Any]]:
        results = []
        models = self.bundle.get("models", {})
        meta = self.bundle.get("meta", {})
        history = history or {}

        for z in zones:
            zid = z.get("zone_id") or z.get("id")
            series = history.get(zid, [z])
            feats = self.pipe.extract_zone_features_live(z, series, zones)
            cols = self.pipe.zone_feature_columns()
            x = np.array([[feats.get(c, 0.0) for c in cols]])

            pred_block: Dict[str, Any] = {
                "zone_id": zid,
                "horizon_minutes": horizon_minutes,
                "features_snapshot": {c: feats.get(c, 0.0) for c in cols},
            }

            for model_name in ("zone_deterioration", "exposure_escalation", "cleaning_urgency"):
                model = models.get(model_name)
                mmeta = meta.get(model_name, {})
                if model is None:
                    pred_block[model_name] = None
                    continue
                value, confidence = self._predict_one(model, x, mmeta.get("task", "classification"))
                importance = mmeta.get("feature_importance") or []
                factors = _top_factors(importance, feats)
                explanation = self._explain_zone(model_name, feats, value, factors)

                pr = self._make_result(
                    prediction_type=model_name,
                    entity_type="zone",
                    entity_id=zid,
                    horizon_minutes=horizon_minutes,
                    predicted_value=value,
                    confidence=confidence,
                    risk_band=_risk_band(value if mmeta.get("task") == "classification" else min(1.0, max(0.0, value / 10.0))),
                    top_factors=factors,
                    explanation=explanation,
                )
                pred_block[model_name] = pr
                self._audit.append(pr)

            results.append(pred_block)
        return results

    def predict_workers(
        self,
        workers: List[Dict[str, Any]],
        zones: Optional[List[Dict[str, Any]]] = None,
        horizon_minutes: int = 30,
    ) -> List[Dict[str, Any]]:
        results = []
        models = self.bundle.get("models", {})
        meta = self.bundle.get("meta", {})
        zone_map = {z.get("zone_id") or z.get("id"): z for z in (zones or [])}

        for w in workers:
            wid = w.get("worker_id") or w.get("id")
            zone = zone_map.get(w.get("current_zone") or w.get("assigned_zone_id") or "", {})
            feats = self.pipe.extract_worker_features_live(w, zone)
            cols = self.pipe.worker_feature_columns()
            x = np.array([[feats.get(c, 0.0) for c in cols]])

            pred_block: Dict[str, Any] = {
                "worker_id": wid,
                "horizon_minutes": horizon_minutes,
                "features_snapshot": {c: feats.get(c, 0.0) for c in cols},
            }

            for model_name in ("worker_workload_trend", "worker_exposure_trend"):
                model = models.get(model_name)
                mmeta = meta.get(model_name, {})
                if model is None:
                    pred_block[model_name] = None
                    continue
                value, confidence = self._predict_one(model, x, mmeta.get("task", "regression"))
                importance = mmeta.get("feature_importance") or []
                factors = _top_factors(importance, feats)
                explanation = self._explain_worker(model_name, feats, value, factors)

                # normalize risk band for regression trends
                band_score = min(1.0, max(0.0, abs(value) / 20.0))
                pr = self._make_result(
                    prediction_type=model_name,
                    entity_type="worker",
                    entity_id=wid,
                    horizon_minutes=horizon_minutes,
                    predicted_value=value,
                    confidence=confidence,
                    risk_band=_risk_band(band_score),
                    top_factors=factors,
                    explanation=explanation,
                )
                pred_block[model_name] = pr
                self._audit.append(pr)

            results.append(pred_block)
        return results

    def predict_cleaning(
        self,
        zones: List[Dict[str, Any]],
        history: Optional[Dict[str, List[Dict]]] = None,
        horizon_minutes: int = 30,
    ) -> List[Dict[str, Any]]:
        zone_preds = self.predict_zones(zones, history, horizon_minutes)
        out = []
        for zp in zone_preds:
            cu = zp.get("cleaning_urgency")
            if cu:
                out.append(cu)
        return out

    def predict_exposure(
        self,
        zones: List[Dict[str, Any]],
        workers: Optional[List[Dict[str, Any]]] = None,
        horizon_minutes: int = 30,
    ) -> Dict[str, Any]:
        zone_preds = self.predict_zones(zones, horizon_minutes=horizon_minutes)
        worker_preds = self.predict_workers(workers or [], zones, horizon_minutes) if workers else []
        return {
            "zones": [zp.get("exposure_escalation") for zp in zone_preds if zp.get("exposure_escalation")],
            "workers": [wp.get("worker_exposure_trend") for wp in worker_preds if wp.get("worker_exposure_trend")],
            "horizon_minutes": horizon_minutes,
            "data_source": "synthetic_models",
            "synthetic_training_notice": (
                "Predictions from models trained on synthetic data only; "
                "not real-world calibrated."
            ),
        }

    def get_audit_log(self) -> List[Dict[str, Any]]:
        return list(self._audit)

    # ---- helpers ----

    def _predict_one(self, model, x: np.ndarray, task: str) -> tuple:
        try:
            if task == "classification":
                if hasattr(model, "predict_proba"):
                    proba = model.predict_proba(x)
                    if proba.shape[1] > 1:
                        value = float(proba[0, 1])
                    else:
                        value = float(proba[0, 0])
                    confidence = float(max(proba[0]))
                else:
                    pred = model.predict(x)
                    value = float(pred[0])
                    confidence = 0.6
            else:
                pred = model.predict(x)
                value = float(pred[0])
                confidence = 0.65  # regressors lack native confidence
            return value, confidence
        except Exception:
            return 0.0, 0.0

    def _make_result(
        self,
        prediction_type: str,
        entity_type: str,
        entity_id: str,
        horizon_minutes: int,
        predicted_value: float,
        confidence: float,
        risk_band: str,
        top_factors: List[Dict],
        explanation: List[str],
    ) -> Dict[str, Any]:
        return {
            "prediction_id": str(uuid.uuid4()),
            "prediction_type": prediction_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "horizon_minutes": horizon_minutes,
            "predicted_value": round(predicted_value, 4),
            "confidence": round(confidence, 4),
            "risk_band": risk_band,
            "top_factors": top_factors,
            "explanation": explanation,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_version": MODEL_VERSION,
            "data_source": "synthetic",
            "synthetic_training_notice": (
                "Experimental model trained on synthetic operational data. "
                "Metrics and predictions do not represent real-world site performance."
            ),
        }

    def _explain_zone(
        self,
        model_name: str,
        feats: Dict[str, float],
        value: float,
        factors: List[Dict],
    ) -> List[str]:
        lines = []
        if model_name == "zone_deterioration":
            if feats.get("h2s_slope_short", 0) > 0.1:
                lines.append("risk increased during previous short window")
            if feats.get("time_since_cleaning_proxy", 0) >= 2:
                lines.append("cleaning overdue or due")
            if feats.get("neighbor_max_risk", 0) >= 2:
                lines.append("neighboring zone elevated")
            if feats.get("ventilation_proxy", 1) < 0.5:
                lines.append("ventilation proxy deteriorating")
            if feats.get("hist_deterioration_rate", 0) > 0.05:
                lines.append("historical deterioration rate elevated")
        elif model_name == "cleaning_urgency":
            if feats.get("cleaning_state_ord", 0) >= 1:
                lines.append("cleaning state is due or overdue")
            if feats.get("h2s_ppm", 0) > 5:
                lines.append("current H2S elevated")
            if feats.get("risk_ord", 0) >= 2:
                lines.append("zone risk high or critical")
        elif model_name == "exposure_escalation":
            if feats.get("h2s_slope_medium", 0) > 0:
                lines.append("medium-term H2S trend rising")
            if feats.get("occupancy", 0) > 2:
                lines.append("occupancy elevated")
        if not lines and factors:
            top = factors[0]
            lines.append(f"primary factor: {top['feature']}={top.get('value', 0):.3f}")
        if not lines:
            lines.append("features near baseline; low predicted change")
        return lines

    def _explain_worker(
        self,
        model_name: str,
        feats: Dict[str, float],
        value: float,
        factors: List[Dict],
    ) -> List[str]:
        lines = []
        if feats.get("recent_exposure", 0) > 20:
            lines.append("elevated recent exposure")
        if feats.get("cumulative_workload", 0) > 25:
            lines.append("high current workload")
        if feats.get("recovery_rest_proxy", 1) < 0.4:
            lines.append("worker has not had recent recovery interval")
        if feats.get("zone_risk_ord", 0) >= 2:
            lines.append("current zone risk high")
        if feats.get("time_since_last_rotation_min", 0) > 240:
            lines.append("long interval since last rotation")
        if not lines and factors:
            top = factors[0]
            lines.append(f"primary factor: {top['feature']}={top.get('value', 0):.3f}")
        if not lines:
            lines.append("workload/exposure features near baseline")
        return lines
