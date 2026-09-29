"""
Phase 11 — Meta WhatsApp Cloud API transport.

Demo mode and missing credentials never crash the app.
Does not claim delivery without a successful API response.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)
def _graph_base() -> str:
    ver = getattr(settings, "WHATSAPP_GRAPH_API_VERSION", None) or "v19.0"
    ver = str(ver).strip()
    if not ver.startswith("v"):
        ver = "v" + ver
    return f"https://graph.facebook.com/{ver}"


# In-process dedup of Meta message IDs
_seen_message_ids: set = set()
_SEEN_MAX = 5000


def meta_configured() -> bool:
    token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "") or ""
    phone_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "") or ""
    demo = bool(getattr(settings, "WHATSAPP_DEMO_MODE", True))
    return bool(token and phone_id) and not demo


def verify_meta_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """Validate X-Hub-Signature-256 = sha256=<hmac> using WHATSAPP_APP_SECRET."""
    secret = getattr(settings, "WHATSAPP_APP_SECRET", "") or ""
    if not secret:
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = signature_header.split("=", 1)[1].strip()
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, expected)


def parse_meta_inbound(body: dict) -> List[Dict[str, Any]]:
    """Extract text messages from Meta Cloud API webhook payload."""
    out: List[Dict[str, Any]] = []
    if not isinstance(body, dict):
        return out
    for entry in body.get("entry") or []:
        for change in (entry or {}).get("changes") or []:
            value = (change or {}).get("value") or {}
            messages = value.get("messages") or []
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                mtype = msg.get("type")
                if mtype != "text":
                    continue  # ignore status/media/unknown safely
                text_obj = msg.get("text") or {}
                text = text_obj.get("body") if isinstance(text_obj, dict) else ""
                mid = msg.get("id") or ""
                out.append({
                    "phone": msg.get("from") or "",
                    "text": text or "",
                    "message_id": mid,
                    "timestamp": msg.get("timestamp"),
                })
    return out


def is_duplicate_message(message_id: str) -> bool:
    if not message_id:
        return False
    if message_id in _seen_message_ids:
        return True
    _seen_message_ids.add(message_id)
    if len(_seen_message_ids) > _SEEN_MAX:
        # drop arbitrary half
        for i, k in enumerate(list(_seen_message_ids)):
            if i % 2 == 0:
                _seen_message_ids.discard(k)
    return False


def send_meta_text(to_phone: str, text: str) -> Dict[str, Any]:
    """Send text via Meta Cloud API. Returns safe result (no token exposure)."""
    if bool(getattr(settings, "WHATSAPP_DEMO_MODE", True)):
        return {"ok": False, "error": "demo_mode", "delivered": False}
    token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "") or ""
    phone_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "") or ""
    if not token or not phone_id:
        return {"ok": False, "error": "not_configured", "delivered": False}

    # Normalize to digits without +
    to = "".join(c for c in (to_phone or "") if c.isdigit())
    if not to:
        return {"ok": False, "error": "invalid_recipient", "delivered": False}

    url = f"{_graph_base()}/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": (text or "")[:4000]},
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, headers=headers, json=payload)
        if resp.status_code in (200, 201):
            return {"ok": True, "delivered": True, "status_code": resp.status_code}
        if resp.status_code in (401, 403):
            logger.warning("Meta WhatsApp auth failure status=%s", resp.status_code)
            return {"ok": False, "error": "auth_failed", "status_code": resp.status_code, "delivered": False}
        if resp.status_code == 429:
            logger.warning("Meta WhatsApp rate limited")
            return {"ok": False, "error": "rate_limited", "status_code": 429, "delivered": False}
        if resp.status_code >= 500:
            logger.warning("Meta WhatsApp server error status=%s", resp.status_code)
            return {"ok": False, "error": "provider_5xx", "status_code": resp.status_code, "delivered": False}
        logger.warning("Meta WhatsApp send failed status=%s", resp.status_code)
        return {"ok": False, "error": "send_failed", "status_code": resp.status_code, "delivered": False}
    except httpx.TimeoutException:
        logger.warning("Meta WhatsApp timeout")
        return {"ok": False, "error": "timeout", "delivered": False}
    except Exception as exc:
        logger.warning("Meta WhatsApp network error type=%s", type(exc).__name__)
        return {"ok": False, "error": "network_error", "delivered": False}


def build_outbound_payload(to_phone: str, text: str) -> dict:
    """Construct outbound payload (for tests; no network)."""
    to = "".join(c for c in (to_phone or "") if c.isdigit())
    phone_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "") or ""
    return {
        "url": f"{_graph_base()}/{phone_id}/messages",
        "json": {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": (text or "")[:4000]},
        },
    }
