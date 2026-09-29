"""
Shift and incident summary generation (grounded, read-only).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.services.ai.context_service import ContextService
from app.services.ai.llm_service import LLMService
from app.services.ai.prompt_service import SYSTEM_PROMPT, shift_summary_prompt, incident_summary_prompt


class SummaryService:
    def __init__(
        self,
        context_service: Optional[ContextService] = None,
        llm_service: Optional[LLMService] = None,
    ):
        self.context_svc = context_service or ContextService()
        self.llm_svc = llm_service or LLMService()

    def shift_summary(
        self,
        *,
        state: Optional[Dict[str, Any]] = None,
        role: str = "SUPERVISOR",
    ) -> Dict[str, Any]:
        ctx = self.context_svc.build_context(
            intent="shift_summary",
            entities={},
            question="Summarize this shift.",
            state=state,
            role=role,
        )
        user = shift_summary_prompt(ctx["facts"])
        raw = self.llm_svc.complete_raw(SYSTEM_PROMPT, user)
        text = raw.get("text") or ""
        if raw.get("error"):
            text = self._structured_shift(ctx["facts"])
        return {
            "summary": text,
            "summary_type": "shift",
            "evidence": ctx["evidence"],
            "sections_hint": ["OBSERVED", "PREDICTED", "PENDING ACTIONS"],
            "facts": {
                "observed": ctx["facts"].get("observed"),
                "predicted": ctx["facts"].get("predicted"),
            },
            "model": raw.get("model") or self.llm_svc.provider.model_name,
            "provider": raw.get("provider") or self.llm_svc.provider.provider_name,
            "demo_mode": bool(raw.get("demo_mode", self.llm_svc.demo_mode)),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "context_timestamp": ctx.get("context_timestamp"),
            "safety_boundary": "Read-only summary. Does not execute actions.",
        }

    def incident_summary(
        self,
        incident_id: Optional[str] = None,
        *,
        state: Optional[Dict[str, Any]] = None,
        role: str = "SUPERVISOR",
    ) -> Dict[str, Any]:
        entities: Dict[str, list] = {}
        if incident_id and incident_id.upper().startswith("INC-"):
            zid = incident_id.upper().replace("INC-", "")
            entities["zone_ids"] = [zid]
        ctx = self.context_svc.build_context(
            intent="incident_summary",
            entities=entities,
            question=f"Summarize incident {incident_id or ''}",
            state=state,
            role=role,
        )
        user = incident_summary_prompt(ctx["facts"])
        raw = self.llm_svc.complete_raw(SYSTEM_PROMPT, user)
        text = raw.get("text") or ""
        if raw.get("error"):
            text = str(ctx["facts"].get("incident") or "I don't have enough current SENTINEL data to answer that.")
        return {
            "summary": text,
            "summary_type": "incident",
            "incident_id": incident_id or (ctx["facts"].get("incident") or {}).get("incident_id"),
            "evidence": ctx["evidence"],
            "facts": ctx["facts"].get("incident"),
            "model": raw.get("model") or self.llm_svc.provider.model_name,
            "provider": raw.get("provider") or self.llm_svc.provider.provider_name,
            "demo_mode": bool(raw.get("demo_mode", self.llm_svc.demo_mode)),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "context_timestamp": ctx.get("context_timestamp"),
            "safety_boundary": "Read-only summary. Does not execute actions.",
        }

    def _structured_shift(self, facts: Dict[str, Any]) -> str:
        obs = facts.get("observed") or {}
        pred = facts.get("predicted") or {}
        return (
            "OBSERVED:\n"
            f"- Workers: {obs.get('n_workers')} ({obs.get('n_unavailable_workers')} unavailable)\n"
            f"- Zones: {obs.get('n_zones')} ({obs.get('n_critical_zones')} critical, "
            f"{obs.get('n_overdue_cleaning')} overdue cleaning)\n"
            f"- Risk levels: {obs.get('zone_risk_levels')}\n\n"
            "PREDICTED (synthetic-trained Phase 15 models):\n"
            f"- {pred.get('sample_zone_predictions')}\n\n"
            "PENDING ACTIONS:\n"
            "- Supervisor approval remains required for any execution via Phase 14.1.2 services."
        )
