"""
LLM provider abstraction — OpenAI-compatible HTTP API + demo mode.

Never hard-codes credentials. If LLM_API_KEY is empty or LLM_MODE=demo,
operates in demo mode and never pretends responses came from a live model.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    @abstractmethod
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Return {text, model, provider, demo_mode, error?}"""

    @property
    @abstractmethod
    def demo_mode(self) -> bool:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...


class DemoLLMProvider(LLMProvider):
    """Deterministic template responses — clearly marked demo_mode=true."""

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        # Extract FACTS block if present for grounded demo answers
        facts_section = ""
        if "FACTS:" in user_prompt:
            try:
                facts_section = user_prompt.split("FACTS:", 1)[1].strip()
                if "QUESTION:" in facts_section:
                    facts_section = facts_section.split("QUESTION:")[0].strip()
            except Exception:
                facts_section = ""

        if facts_section and len(facts_section) > 20:
            text = (
                "[DEMO MODE — not a live LLM response]\n\n"
                "Based on the supplied SENTINEL operational facts:\n\n"
                f"{facts_section[:1200]}\n\n"
                "Interpretation: The above facts are the only operational data "
                "available for this answer. No additional workers, zones, or "
                "safety decisions were invented. For live natural-language "
                "phrasing, configure LLM_API_KEY and set LLM_MODE=live."
            )
        else:
            text = (
                "[DEMO MODE — not a live LLM response]\n\n"
                "I don't have enough current SENTINEL data to answer that fully. "
                "Configure a live LLM provider (LLM_API_KEY + LLM_MODE=live) for "
                "natural-language explanations grounded in retrieved context."
            )
        return {
            "text": text,
            "model": "demo-template",
            "provider": "demo",
            "demo_mode": True,
            "error": None,
        }

    @property
    def demo_mode(self) -> bool:
        return True

    @property
    def model_name(self) -> str:
        return "demo-template"

    @property
    def provider_name(self) -> str:
        return "demo"


class OpenAICompatibleProvider(LLMProvider):
    """Generic OpenAI-compatible chat completions API."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 30.0,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code >= 400:
                    logger.warning("LLM provider HTTP %s: %s", resp.status_code, resp.text[:300])
                    return {
                        "text": "",
                        "model": self.model,
                        "provider": "openai_compatible",
                        "demo_mode": False,
                        "error": f"provider_http_{resp.status_code}",
                    }
                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    return {
                        "text": "",
                        "model": self.model,
                        "provider": "openai_compatible",
                        "demo_mode": False,
                        "error": "empty_choices",
                    }
                text = (choices[0].get("message") or {}).get("content") or ""
                return {
                    "text": text.strip(),
                    "model": data.get("model") or self.model,
                    "provider": "openai_compatible",
                    "demo_mode": False,
                    "error": None,
                }
        except httpx.TimeoutException:
            return {
                "text": "",
                "model": self.model,
                "provider": "openai_compatible",
                "demo_mode": False,
                "error": "timeout",
            }
        except Exception as e:
            logger.exception("LLM provider failure")
            return {
                "text": "",
                "model": self.model,
                "provider": "openai_compatible",
                "demo_mode": False,
                "error": f"provider_error:{type(e).__name__}",
            }

    @property
    def demo_mode(self) -> bool:
        return False

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def provider_name(self) -> str:
        return "openai_compatible"


def get_llm_provider() -> LLMProvider:
    """Factory: demo unless live mode + non-empty API key."""
    mode = (settings.LLM_MODE or "demo").strip().lower()
    key = (settings.LLM_API_KEY or "").strip()
    if mode == "demo" or not key:
        return DemoLLMProvider()
    return OpenAICompatibleProvider(
        api_key=key,
        base_url=settings.LLM_BASE_URL or "https://api.openai.com/v1",
        model=settings.LLM_MODEL or "gpt-4o-mini",
        timeout=float(settings.LLM_TIMEOUT or 30.0),
        max_tokens=int(settings.LLM_MAX_TOKENS or 1024),
        temperature=float(settings.LLM_TEMPERATURE or 0.2),
    )
