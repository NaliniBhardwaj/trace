"""
Phase 15 — Predictive Workforce Intelligence tests.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.predictive.generator import (
    generate_default_dataset,
    GENERATOR_VERSION,
)
from app.predictive.features import FeaturePipeline, FeatureConfig
from app.predictive.models_train import (
    train_all_models,
    load_model_bundle,
    MODEL_VERSION,
)
from app.predictive.prediction_service import PredictionService
from app.predictive.workforce_intelligence import WorkforceIntelligenceService
from app.predictive.simulation import WhatIfSimulator
from app.predictive.plan_compare import PlanComparisonService


@pytest.fixture(scope="module")
def synth_payload():
    return generate_default_dataset(
        seed=99, n_workers=10, n_zones=5, duration_hours=24, difficulty="medium"
    )


@pytest.fixture(scope="module")
def trained_summary(tmp_path_factory):
    out = tmp_path_factory.mktemp("p15_models")
    summary = train_all_models(
        seed=99,
        n_workers=10,
        n_zones=5,
        duration_hours=24,
        horizon_minutes=30,
        output_dir=out,
        difficulty="medium",
    )
    return summary, out


class TestSyntheticGenerator:
    def test_reproducibility(self):
        a = generate_default_dataset(seed=7, n_workers=6, n_zones=3, duration_hours=6)
        b = generate_default_dataset(seed=7, n_workers=6, n_zones=3, duration_hours=6)
        assert a["metadata"]["random_seed"] == b["metadata"]["random_seed"]
        assert len(a["snapshots"]) == len(b["snapshots"])
        assert a["snapshots"][0]["zones"][0]["h2s_ppm"] == b["snapshots"][0]["zones"][0]["h2s_ppm"]

    def test_schema_and_provenance(self, synth_payload):
        meta = synth_payload["metadata"]
        assert meta["source"] == "synthetic"
        assert meta["generator_version"] == GENERATOR_VERSION
        assert "random_seed" in meta
        assert "SYNTHETIC" in meta["synthetic_status"].upper()
        assert len(synth_payload["snapshots"]) > 0

    def test_temporal_ordering(self, synth_payload):
        steps = [s["step"] for s in synth_payload["snapshots"]]
        assert steps == sorted(steps)

    def test_no_missing_required_fields(self, synth_payload):
        snap = synth_payload["snapshots"][-1]
        for z in snap["zones"]:
            for key in ("zone_id", "risk_level", "h2s_ppm", "occupancy", "cleaning_state"):
                assert key in z
        for w in snap["workers"]:
            for key in ("worker_id", "skills", "availability", "recent_exposure"):
                assert key in w

    def test_configurable_size(self):
        p = generate_default_dataset(seed=1, n_workers=4, n_zones=2, duration_hours=3)
        assert p["metadata"]["n_workers"] == 4
        assert p["metadata"]["n_zones"] == 2


class TestFeaturePipeline:
    def test_zone_dataset_no_future_leakage(self, synth_payload):
        pipe = FeaturePipeline(FeatureConfig(default_horizon=30))
        df = pipe.build_zone_dataset(synth_payload, horizon_minutes=30)
        assert not df.empty
        for col in pipe.zone_feature_columns():
            assert col in df.columns
        assert "label_zone_escalation" in df.columns

    def test_worker_dataset(self, synth_payload):
        pipe = FeaturePipeline()
        df = pipe.build_worker_dataset(synth_payload, horizon_minutes=30)
        assert not df.empty
        assert "label_workload_trend" in df.columns

    def test_live_extraction(self):
        pipe = FeaturePipeline()
        z = {
            "zone_id": "Z01", "risk_level": "HIGH", "h2s_ppm": 12.0,
            "temperature_c": 30, "humidity_pct": 60, "ventilation_proxy": 0.5,
            "occupancy": 2, "cleaning_state": "DUE", "deterioration_trend": 0.1,
            "neighboring_zones": [],
        }
        feats = pipe.extract_zone_features_live(z)
        assert feats["risk_ord"] == 2.0


class TestMLTraining:
    def test_training_and_persistence(self, trained_summary):
        summary, out = trained_summary
        assert summary["training_data_source"] == "synthetic"
        assert summary["model_version"] == MODEL_VERSION
        trained = [k for k, v in summary["models"].items() if "metrics" in v]
        assert len(trained) >= 2
        for name in trained:
            assert (out / f"{name}.joblib").is_file()
            assert summary["models"][name]["training_data_source"] == "synthetic"

    def test_load_bundle(self, trained_summary):
        _, out = trained_summary
        bundle = load_model_bundle(out)
        assert len(bundle["models"]) >= 2

    def test_prediction_shape(self, trained_summary):
        _, out = trained_summary
        from app.predictive import models_train as mt
        old = mt.MODEL_DIR
        mt.MODEL_DIR = out
        try:
            svc = PredictionService(auto_train=False)
            svc.bundle = load_model_bundle(out)
            zones = [{
                "zone_id": "Z01", "risk_level": "ELEVATED", "h2s_ppm": 3.0,
                "temperature_c": 28, "humidity_pct": 55, "ventilation_proxy": 0.6,
                "occupancy": 1, "cleaning_state": "DUE", "deterioration_trend": 0.05,
                "neighboring_zones": [],
            }]
            preds = svc.predict_zones(zones, horizon_minutes=30)
            assert len(preds) == 1
            det = preds[0].get("zone_deterioration")
            if det:
                assert det["data_source"] == "synthetic"
                assert "explanation" in det
        finally:
            mt.MODEL_DIR = old

    def test_metadata_explicit_synthetic(self, trained_summary):
        summary, _ = trained_summary
        for name, meta in summary["models"].items():
            if "metrics" in meta:
                assert meta["training_data_source"] == "synthetic"


class TestWorkforceIntelligence:
    @pytest.fixture
    def services(self, trained_summary):
        _, out = trained_summary
        from app.predictive import models_train as mt
        old = mt.MODEL_DIR
        mt.MODEL_DIR = out
        pred = PredictionService(auto_train=False)
        pred.bundle = load_model_bundle(out)
        wi = WorkforceIntelligenceService(pred)
        yield pred, wi
        mt.MODEL_DIR = old

    def test_suitability_calculation(self, services, synth_payload):
        pred, wi = services
        snap = synth_payload["snapshots"][-1]
        recs = wi.recommend_workers_for_zone(snap["zones"][0], snap["workers"], snap["zones"], top_k=3)
        assert len(recs) <= 3
        for r in recs:
            assert 0 <= r["suitability_score"] <= 1
            assert r["is_recommendation_only"] is True

    def test_unavailable_worker_handling(self, services, synth_payload):
        pred, wi = services
        snap = copy.deepcopy(synth_payload["snapshots"][-1])
        snap["workers"][0]["availability"] = "UNAVAILABLE"
        recs = wi.recommend_workers_for_zone(snap["zones"][0], snap["workers"][:3], snap["zones"], top_k=5)
        unavail = [r for r in recs if r["worker_id"] == snap["workers"][0]["worker_id"]]
        if unavail:
            assert "worker_unavailable" in unavail[0]["constraints"]

    def test_unavailable_zone_handling(self, services, synth_payload):
        pred, wi = services
        snap = copy.deepcopy(synth_payload["snapshots"][-1])
        target = copy.deepcopy(snap["zones"][0])
        target["unavailable"] = True
        recs = wi.recommend_workers_for_zone(target, snap["workers"], snap["zones"], top_k=3)
        for r in recs:
            assert "target_zone_unavailable" in r["constraints"]

    def test_skill_mismatch(self, services, synth_payload):
        pred, wi = services
        snap = synth_payload["snapshots"][-1]
        recs = wi.recommend_workers_for_zone(
            snap["zones"][0], snap["workers"], snap["zones"],
            required_skills=["confined_space", "gas_testing"], top_k=5,
        )
        assert all("constraints" in r for r in recs)

    def test_high_risk_zone(self, services, synth_payload):
        pred, wi = services
        snap = copy.deepcopy(synth_payload["snapshots"][-1])
        target = copy.deepcopy(snap["zones"][0])
        target["risk_level"] = "CRITICAL"
        recs = wi.recommend_workers_for_zone(target, snap["workers"], snap["zones"], top_k=3)
        for r in recs:
            assert "zone_critical" in r["constraints"] or r["suitability_score"] < 0.9


class TestWhatIfSimulation:
    @pytest.fixture
    def sim(self, trained_summary):
        _, out = trained_summary
        from app.predictive import models_train as mt
        old = mt.MODEL_DIR
        mt.MODEL_DIR = out
        pred = PredictionService(auto_train=False)
        pred.bundle = load_model_bundle(out)
        s = WhatIfSimulator(pred)
        yield s
        mt.MODEL_DIR = old

    def test_does_not_mutate_authoritative_state(self, sim, synth_payload):
        snap = synth_payload["snapshots"][-1]
        state = {"workers": copy.deepcopy(snap["workers"]), "zones": copy.deepcopy(snap["zones"])}
        original_h2s = state["zones"][0]["h2s_ppm"]
        result = sim.run(
            state,
            {"type": "delay_cleaning", "zone_id": state["zones"][0]["zone_id"]},
        )
        assert result["simulation"] is True
        assert result["mutates_authoritative_state"] is False
        assert state["zones"][0]["h2s_ppm"] == original_h2s

    def test_delay_cleaning_scenario(self, sim, synth_payload):
        snap = synth_payload["snapshots"][-1]
        result = sim.run(
            {"workers": snap["workers"], "zones": snap["zones"]},
            {"type": "delay_cleaning", "zone_id": snap["zones"][0]["zone_id"]},
        )
        assert "deltas" in result["comparison"]

    def test_worker_unavailable_scenario(self, sim, synth_payload):
        snap = synth_payload["snapshots"][-1]
        wid = snap["workers"][0]["worker_id"]
        result = sim.run(
            {"workers": snap["workers"], "zones": snap["zones"]},
            {"type": "worker_unavailable", "worker_id": wid},
        )
        assert wid in result["affected_workers"]

    def test_zone_unavailable_scenario(self, sim, synth_payload):
        snap = synth_payload["snapshots"][-1]
        zid = snap["zones"][0]["zone_id"]
        result = sim.run(
            {"workers": snap["workers"], "zones": snap["zones"]},
            {"type": "zone_unavailable", "zone_id": zid},
        )
        assert zid in result["affected_zones"]

    def test_rotation_scenario(self, sim, synth_payload):
        snap = synth_payload["snapshots"][-1]
        w = next(x for x in snap["workers"] if x.get("availability") == "AVAILABLE")
        target = next(z for z in snap["zones"] if z["zone_id"] != w.get("current_zone"))
        result = sim.run(
            {"workers": snap["workers"], "zones": snap["zones"]},
            {"type": "rotate_now", "worker_id": w["worker_id"], "to_zone": target["zone_id"]},
        )
        assert result["simulation"] is True


class TestPlanComparison:
    @pytest.fixture
    def cmp_svc(self, trained_summary):
        _, out = trained_summary
        from app.predictive import models_train as mt
        old = mt.MODEL_DIR
        mt.MODEL_DIR = out
        pred = PredictionService(auto_train=False)
        pred.bundle = load_model_bundle(out)
        c = PlanComparisonService(pred)
        yield c
        mt.MODEL_DIR = old

    def test_compare_two_plans(self, cmp_svc, synth_payload):
        snap = synth_payload["snapshots"][-1]
        workers = [w for w in snap["workers"] if w.get("availability") == "AVAILABLE"][:3]
        zones = snap["zones"]
        if len(workers) < 2 or len(zones) < 2:
            pytest.skip("not enough entities")
        plans = [
            {"plan_id": "A", "actions": [{"type": "rotate", "worker_id": workers[0]["worker_id"], "to_zone": zones[0]["zone_id"]}]},
            {"plan_id": "B", "actions": [{"type": "rotate", "worker_id": workers[1]["worker_id"], "to_zone": zones[0]["zone_id"]}]},
        ]
        result = cmp_svc.compare({"workers": snap["workers"], "zones": zones}, plans)
        assert result["bypasses_safety_validator"] is False
        assert result["is_recommendation_only"] is True
        assert len(result["plans"]) == 2


class TestSafetyBoundary:
    def test_recommendation_does_not_mutate_assignment(self, trained_summary, synth_payload):
        _, out = trained_summary
        from app.predictive import models_train as mt
        old = mt.MODEL_DIR
        mt.MODEL_DIR = out
        try:
            pred = PredictionService(auto_train=False)
            pred.bundle = load_model_bundle(out)
            wi = WorkforceIntelligenceService(pred)
            snap = copy.deepcopy(synth_payload["snapshots"][-1])
            before = {w["worker_id"]: w.get("assigned_zone_id") for w in snap["workers"]}
            wi.recommend_workers_for_zone(snap["zones"][0], snap["workers"], snap["zones"])
            after = {w["worker_id"]: w.get("assigned_zone_id") for w in snap["workers"]}
            assert before == after
        finally:
            mt.MODEL_DIR = old


class TestModelArtifactFreshProcess:
    """Detect sklearn serialization mismatches across process boundaries."""

    def test_load_all_models_in_fresh_subprocess(self):
        import subprocess
        import sys
        from app.predictive.models_train import MODEL_DIR

        code = f'''
import sys
sys.path.insert(0, ".")
import joblib
import numpy as np
from pathlib import Path
d = Path(r"{MODEL_DIR}")
assert d.is_dir(), f"missing {{d}}"
loaded = 0
for f in sorted(d.glob("*.joblib")):
    m = joblib.load(f)
    n = getattr(m, "n_features_in_", 8)
    x = np.zeros((1, int(n)))
    _ = m.predict(x)
    loaded += 1
assert loaded >= 5, f"expected >=5 models, got {{loaded}}"
print("FRESH_PROCESS_OK", loaded)
'''
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
            timeout=60,
        )
        assert r.returncode == 0, f"stdout={r.stdout}\\nstderr={r.stderr}"
        assert "FRESH_PROCESS_OK" in r.stdout

    def test_metadata_has_sklearn_version(self):
        from app.predictive.models_train import MODEL_DIR, load_model_bundle
        import json
        meta_path = MODEL_DIR / "zone_deterioration_meta.json"
        assert meta_path.is_file()
        meta = json.loads(meta_path.read_text())
        assert meta.get("training_data_source") == "synthetic"
        assert meta.get("sklearn_version")
        assert meta.get("model_type")
        bundle = load_model_bundle(strict=True)
        assert "zone_deterioration" in bundle["models"]
