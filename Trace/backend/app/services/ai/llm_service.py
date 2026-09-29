"""
LLM orchestration — grounded completion with hallucination safeguards.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.ai.provider import LLMProvider, get_llm_provider
from app.services.ai.prompt_service import SYSTEM_PROMPT, build_user_prompt


class LLMService:
    def __init__(self, provider: Optional[LLMProvider] = None):
        self.provider = provider or get_llm_provider()

    @property
    def demo_mode(self) -> bool:
        return self.provider.demo_mode

    def answer(
        self,
        question: str,
        intent: str,
        facts: Dict[str, Any],
        evidence: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        # Insufficient context short-circuit
        if self._insufficient(facts, intent):
            return {
                "answer": "I don't have enough current SENTINEL data to answer that.",
                "intent": intent,
                "evidence": evidence,
                "model": self.provider.model_name,
                "provider": self.provider.provider_name,
                "demo_mode": self.provider.demo_mode,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "grounded": True,
                "insufficient_context": True,
            }

        user_prompt = build_user_prompt(question, intent, facts, evidence)
        result = self.provider.complete(SYSTEM_PROMPT, user_prompt)

        text = result.get("text") or ""
        error = result.get("error")

        if error:
            text = (
                f"AI provider unavailable ({error}). "
                "Falling back to structured facts only:\n\n"
                + self._facts_fallback(facts)
            )

        # Basic claim validation — strip invented worker/zone IDs not in context
        text = self._sanitize_claims(text, facts, evidence)

        return {
            "answer": text,
            "intent": intent,
            "evidence": evidence,
            "model": result.get("model") or self.provider.model_name,
            "provider": result.get("provider") or self.provider.provider_name,
            "demo_mode": bool(result.get("demo_mode", self.provider.demo_mode)),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "grounded": True,
            "provider_error": error,
            "insufficient_context": False,
        }

    def complete_raw(self, system: str, user: str) -> Dict[str, Any]:
        return self.provider.complete(system, user)

    def _insufficient(self, facts: Dict[str, Any], intent: str) -> bool:
        if intent == "rotation_explanation" and facts.get("workers_found") is False:
            return True
        if intent in ("zone_status", "zone_priority") and facts.get("zones_found") is False:
            return True
        if intent == "worker_status" and facts.get("workers_found") is False:
            return True
        return False

    def _facts_fallback(self, facts: Dict[str, Any]) -> str:
        lines = []
        for k, v in list(facts.items())[:15]:
            lines.append(f"- {k}: {v}")
        return "\n".join(lines) if lines else "(no facts)"

    def _sanitize_claims(
        self,
        text: str,
        facts: Dict[str, Any],
        evidence: List[Dict[str, Any]],
    ) -> str:
        """Reject obviously invented entity IDs not present in facts/evidence."""
        known: set = set()
        for e in evidence:
            if e.get("id"):
                known.add(str(e["id"]).upper())
        for w in facts.get("workers") or []:
            if isinstance(w, dict) and w.get("worker_id"):
                known.add(str(w["worker_id"]).upper())
        for z in facts.get("zones") or []:
            if isinstance(z, dict) and z.get("zone_id"):
                known.add(str(z["zone_id"]).upper())
        for p in facts.get("predictions") or []:
            if isinstance(p, dict) and p.get("entity_id"):
                known.add(str(p["entity_id"]).upper())

        # If text references W### or Z## not in known set, append disclaimer
        mentioned_w = set(re.findall(r"\bW\d{2,4}\b", text, re.I))
        mentioned_z = set(re.findall(r"\bZ\d{2,4}\b", text, re.I))
        unknown = set()
        for m in mentioned_w | mentioned_z:
            if m.upper() not in known and known:
                unknown.add(m.upper())
        if unknown:
            text += (
                "\n\n[Grounding note: the following identifiers were not present "
                f"in retrieved SENTINEL context and should be disregarded: {', '.join(sorted(unknown))}]"
            )
        return text
