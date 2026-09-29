"""
Phase 16 — AI Decision Support API (READ-ONLY).

LLM cannot execute rotations, approve plans, evacuate, or mutate safety state.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_current_user, require_roles
from app import models
from app.config import settings
from app.services.ai.explanation_service import ExplanationService
from app.services.ai.summary_service import SummaryService
from app.services.ai.provider import get_llm_provider

router = APIRouter(prefix="/api/ai", tags=["ai-phase16"])

SUPERVISOR_PLUS = ("ADMIN", "SAFETY_ADMIN", "MANAGER", "SUPERVISOR")
MANAGER_PLUS = ("ADMIN", "SAFETY_ADMIN", "MANAGER")

_explainer: Optional[ExplanationService] = None
_summarizer: Optional[SummaryService] = None


def _services():
    global _explainer, _summarizer
    if _explainer is None:
        _explainer = ExplanationService()
        _summarizer = SummaryService(
            context_service=_explainer.context_svc,
            llm_service=_explainer.llm_svc,
        )
    return _explainer, _summarizer


class AskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    # Optional operational state override for tests / integrations
    workers: Optional[List[Dict[str, Any]]] = None
    zones: Optional[List[Dict[str, Any]]] = None


class IncidentBody(BaseModel):
    incident_id: Optional[str] = None
    workers: Optional[List[Dict[str, Any]]] = None
    zones: Optional[List[Dict[str, Any]]] = None


class ShiftBody(BaseModel):
    workers: Optional[List[Dict[str, Any]]] = None
    zones: Optional[List[Dict[str, Any]]] = None


def _state_from_body(workers, zones) -> Optional[Dict[str, Any]]:
    if workers is not None or zones is not None:
        return {"workers": workers or [], "zones": zones or [], "source": "request"}
    return None


@router.get("/health")
def ai_health(user: models.User = Depends(require_roles(*SUPERVISOR_PLUS))):
    provider = get_llm_provider()
    return {
        "status": "ok",
        "phase": "16",
        "demo_mode": provider.demo_mode,
        "provider": provider.provider_name,
        "model": provider.model_name,
        "llm_mode_config": settings.LLM_MODE,
        "safety_boundary": (
            "The LLM is a read-only decision-support and explanation layer. "
            "The LLM cannot directly execute or approve operational actions."
        ),
    }


@router.post("/ask")
def ai_ask(body: AskBody, user: models.User = Depends(require_roles(*SUPERVISOR_PLUS))):
    explainer, _ = _services()
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    result = explainer.ask(
        body.question,
        state=_state_from_body(body.workers, body.zones),
        role=role,
    )
    # Never leak secrets
    result.pop("system_prompt", None)
    return result


@router.post("/shift-summary")
def ai_shift_summary(body: ShiftBody = ShiftBody(), user: models.User = Depends(require_roles(*SUPERVISOR_PLUS))):
    _, summarizer = _services()
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    return summarizer.shift_summary(
        state=_state_from_body(body.workers, body.zones),
        role=role,
    )


@router.post("/incident-summary")
def ai_incident_summary(body: IncidentBody = IncidentBody(), user: models.User = Depends(require_roles(*MANAGER_PLUS))):
    _, summarizer = _services()
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    return summarizer.incident_summary(
        body.incident_id,
        state=_state_from_body(body.workers, body.zones),
        role=role,
    )
