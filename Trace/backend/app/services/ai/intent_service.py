"""
Deterministic intent detection for supervisor natural-language questions.

Does NOT use the LLM to guess database queries.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class Intent(str, Enum):
    ROTATION_EXPLANATION = "rotation_explanation"
    ZONE_PRIORITY = "zone_priority"
    WORKER_STATUS = "worker_status"
    ZONE_STATUS = "zone_status"
    PREDICTION_EXPLANATION = "prediction_explanation"
    ALERT_EXPLANATION = "alert_explanation"
    CLEANING_STATUS = "cleaning_status"
    SAFETY_BLOCK_REASON = "safety_block_reason"
    WHAT_IF = "what_if"
    PLAN_COMPARISON = "plan_comparison"
    SHIFT_SUMMARY = "shift_summary"
    INCIDENT_SUMMARY = "incident_summary"
    GENERAL = "general"
    UNKNOWN = "unknown"


# Entity extractors
_WORKER_RE = re.compile(r"\b(W\d{2,4}|worker\s*[#:]?\s*\w+)\b", re.I)
_ZONE_RE = re.compile(r"\b(Z\d{2,4}|zone\s*[#:]?\s*\w+)\b", re.I)
_PLAN_RE = re.compile(r"\b(plan\s*[ab]|plan\s*[#:]?\s*\w+)\b", re.I)


class IntentService:
    def detect(self, question: str) -> Dict[str, Any]:
        q = (question or "").strip().lower()
        entities = self._extract_entities(question or "")

        intent = Intent.UNKNOWN
        if self._match(q, ["what happens if", "what if", "what would happen", "if we delay", "if we leave"]):
            intent = Intent.WHAT_IF
        elif self._match(q, ["compare plan", "plan a", "plan b", "compare the plan", "trade.?off"]):
            intent = Intent.PLAN_COMPARISON
        elif self._match(q, ["shift summary", "summarize this shift", "summarize the shift", "end of shift"]):
            intent = Intent.SHIFT_SUMMARY
        elif self._match(q, ["incident summary", "summarize this incident", "summarize the incident"]):
            intent = Intent.INCIDENT_SUMMARY
        elif self._match(q, ["why.*rotat", "rotated", "rotation reason", "why was.*moved"]):
            intent = Intent.ROTATION_EXPLANATION
        elif self._match(q, ["highest priority", "why is.*priority", "priority zone", "why.*top priority"]):
            intent = Intent.ZONE_PRIORITY
        elif self._match(q, ["why.*block", "safety block", "why.*rejected", "why.*not allowed", "blocked"]):
            intent = Intent.SAFETY_BLOCK_REASON
        elif self._match(q, ["cleaning", "why.*clean", "overdue clean", "clean urgency"]):
            intent = Intent.CLEANING_STATUS
        elif self._match(q, ["prediction", "predicted", "why.*predict", "deterioration", "exposure escalation"]):
            intent = Intent.PREDICTION_EXPLANATION
        elif self._match(q, ["alert", "why.*alert", "what alert"]):
            intent = Intent.ALERT_EXPLANATION
        elif entities.get("worker_ids") and self._match(q, ["status", "where is", "what about", "exposure", "workload"]):
            intent = Intent.WORKER_STATUS
        elif entities.get("zone_ids") and self._match(q, ["status", "what is happening", "what about", "risk", "h2s"]):
            intent = Intent.ZONE_STATUS
        elif entities.get("worker_ids"):
            intent = Intent.WORKER_STATUS
        elif entities.get("zone_ids"):
            intent = Intent.ZONE_STATUS
        elif self._match(q, ["summary", "summarize"]):
            intent = Intent.SHIFT_SUMMARY
        else:
            intent = Intent.GENERAL

        return {
            "intent": intent.value,
            "entities": entities,
            "question": question,
        }

    def _extract_entities(self, question: str) -> Dict[str, List[str]]:
        workers = []
        for m in _WORKER_RE.finditer(question):
            raw = m.group(1)
            # normalize W03 style
            code = re.sub(r"(?i)worker\s*[#:]?\s*", "", raw).strip().upper()
            if not code.startswith("W") and code.isdigit():
                code = f"W{code.zfill(3)}"
            workers.append(code)
        zones = []
        for m in _ZONE_RE.finditer(question):
            raw = m.group(1)
            code = re.sub(r"(?i)zone\s*[#:]?\s*", "", raw).strip().upper()
            if not code.startswith("Z") and re.match(r"\d+", code):
                code = f"Z{code.zfill(2)}"
            zones.append(code)
        plans = [m.group(1).upper() for m in _PLAN_RE.finditer(question)]
        return {
            "worker_ids": list(dict.fromkeys(workers)),
            "zone_ids": list(dict.fromkeys(zones)),
            "plan_refs": list(dict.fromkeys(plans)),
        }

    def _match(self, q: str, patterns: List[str]) -> bool:
        for p in patterns:
            if re.search(p, q, re.I):
                return True
        return False
