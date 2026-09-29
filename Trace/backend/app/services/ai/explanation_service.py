"""
High-level explanation orchestration: intent → context → LLM answer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.ai.intent_service import IntentService
from app.services.ai.context_service import ContextService
from app.services.ai.llm_service import LLMService


class ExplanationService:
    def __init__(
        self,
        intent_service: Optional[IntentService] = None,
        context_service: Optional[ContextService] = None,
        llm_service: Optional[LLMService] = None,
    ):
        self.intent_svc = intent_service or IntentService()
        self.context_svc = context_service or ContextService()
        self.llm_svc = llm_service or LLMService()

    def ask(
        self,
        question: str,
        *,
        state: Optional[Dict[str, Any]] = None,
        role: str = "SUPERVISOR",
    ) -> Dict[str, Any]:
        if not (question or "").strip():
            return {
                "answer": "Please provide a question about current SENTINEL operations.",
                "intent": "unknown",
                "evidence": [],
                "model": self.llm_svc.provider.model_name,
                "provider": self.llm_svc.provider.provider_name,
                "demo_mode": self.llm_svc.demo_mode,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "context_timestamp": None,
            }

        detected = self.intent_svc.detect(question)
        intent = detected["intent"]
        entities = detected["entities"]

        ctx = self.context_svc.build_context(
            intent=intent,
            entities=entities,
            question=question,
            state=state,
            role=role,
        )

        result = self.llm_svc.answer(
            question=question,
            intent=intent,
            facts=ctx["facts"],
            evidence=ctx["evidence"],
        )
        result["context_timestamp"] = ctx.get("context_timestamp")
        result["entities"] = entities
        result["operational_source"] = ctx.get("operational_source")
        result["safety_boundary"] = (
            "LLM is read-only decision support. It cannot execute or approve operational actions."
        )
        return result
