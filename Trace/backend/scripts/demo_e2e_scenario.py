#!/usr/bin/env python3
"""
SENTINEL Phase 17 — reproducible end-to-end demo scenario (synthetic data).

Uses real Phase 15 predictive services + Phase 16 AI explanation layer.
Does NOT mutate authoritative production state beyond in-memory clones.

Run from backend root:
  python scripts/demo_e2e_scenario.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure app package is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from app.predictive.generator import generate_default_dataset
    from app.predictive.prediction_service import PredictionService
    from app.predictive.workforce_intelligence import WorkforceIntelligenceService
    from app.predictive.simulation import WhatIfSimulator
    from app.predictive.plan_compare import PlanComparisonService
    from app.services.ai.explanation_service import ExplanationService

    print("=== SENTINEL E2E DEMO (synthetic) ===\n")

    # 1. Operational state
    payload = generate_default_dataset(
        seed=42, n_workers=10, n_zones=6, duration_hours=18, difficulty="medium"
    )
    snap = payload["snapshots"][-1]
    workers, zones = snap["workers"], snap["zones"]
    print(f"1. State: {len(workers)} workers, {len(zones)} zones (synthetic)")

    # 2–3. Risk / H2S
    high = [z for z in zones if z.get("risk_level") in ("HIGH", "CRITICAL", "ELEVATED")]
    print(f"2. Elevated/high/critical zones: {[z['zone_id'] for z in high] or 'none'}")

    # 4. Predictions
    pred = PredictionService(auto_train=True)
    zpreds = pred.predict_zones(zones, horizon_minutes=30)
    print(f"3. Zone predictions: {len(zpreds)} (Phase 15 synthetic-trained models)")

    # 5–6. Priority + workforce
    wi = WorkforceIntelligenceService(pred)
    target = zones[0]
    recs = wi.recommend_workers_for_zone(target, workers, zones, top_k=3)
    print(f"4. Recommendations for {target['zone_id']}: {len(recs)} (recommendation-only)")

    # 7. Safety boundary reminder
    print("5. Safety: deterministic validator remains authoritative (no AI execution)")

    # 8–9. Simulation (non-mutating)
    state = {"workers": workers, "zones": zones}
    before = json.dumps([z.get("h2s_ppm") for z in zones])
    sim = WhatIfSimulator(pred, wi)
    sim_result = sim.run(state, {"type": "delay_cleaning", "zone_id": target["zone_id"]})
    after = json.dumps([z.get("h2s_ppm") for z in zones])
    assert before == after, "simulation mutated authoritative state"
    print(f"6. What-if simulation_id={sim_result.get('simulation_id')} (mutates_authoritative_state=False)")

    # 10. Plan comparison
    avail = [w for w in workers if w.get("availability") == "AVAILABLE"]
    if len(avail) >= 2:
        plans = [
            {"plan_id": "A", "actions": [{"type": "rotate", "worker_id": avail[0]["worker_id"], "to_zone": target["zone_id"]}]},
            {"plan_id": "B", "actions": [{"type": "rotate", "worker_id": avail[1]["worker_id"], "to_zone": target["zone_id"]}]},
        ]
        cmp = PlanComparisonService(pred, wi).compare(state, plans)
        print(f"7. Plan comparison_id={cmp.get('comparison_id')} (no automatic winner)")

    # 11. AI explanation (demo mode unless LLM_API_KEY set)
    explainer = ExplanationService()
    ans = explainer.ask(
        f"Why is {target['zone_id']} the highest priority?",
        state=state,
        role="SUPERVISOR",
    )
    print(f"8. AI intent={ans.get('intent')} demo_mode={ans.get('demo_mode')}")
    print(f"   evidence_count={len(ans.get('evidence') or [])}")
    print(f"   safety_boundary={ans.get('safety_boundary', '')[:80]}...")

    print("\n=== DEMO COMPLETE — feature set frozen (Phase 17) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
