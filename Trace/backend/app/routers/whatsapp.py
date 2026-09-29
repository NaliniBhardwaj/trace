"""Phase 11 — WhatsApp webhook (Meta Cloud API + demo)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_roles
from app import models
from app.config import settings
from app.whatsapp_service import (
    handle_command,
    provider_status,
    resolve_whatsapp_state,
    validate_inbound,
    verify_webhook_request,
    get_support_number,
)
from app.whatsapp_meta import (
    meta_configured,
    verify_meta_signature,
    parse_meta_inbound,
    is_duplicate_message,
    send_meta_text,
)

router = APIRouter(prefix="/integrations/whatsapp", tags=["whatsapp"])


class DemoInbound(BaseModel):
    phone: str = Field(..., min_length=1, max_length=32)
    text: str = Field("", max_length=2000)


@router.get("/status")
def wa_status():
    st = provider_status()
    support = get_support_number()
    st["support_number"] = support if support else None
    if not support:
        st["support_number_message"] = "WhatsApp support number is not configured."
    return st


@router.get("/webhook")
def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    expected = getattr(settings, "WHATSAPP_VERIFY_TOKEN", "") or ""
    if hub_mode == "subscribe" and hub_verify_token and expected and hub_verify_token == expected:
        return PlainTextResponse(content=str(hub_challenge or ""))
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def inbound_webhook(request: Request, db: Session = Depends(get_db)):
    status = provider_status()
    state = resolve_whatsapp_state()
    demo = state == "DEMO"
    raw = await request.body()
    sig = request.headers.get("X-Hub-Signature-256")

    if state == "NOT_CONFIGURED":
        raise HTTPException(status_code=503, detail="WhatsApp provider is not configured.")

    # META_CONFIGURED: require X-Hub-Signature-256
    if state == "META_CONFIGURED":
        if not verify_meta_signature(raw, sig):
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        body = await request.json()
    except Exception:
        # try parse raw
        import json
        try:
            body = json.loads(raw.decode("utf-8") if raw else "{}")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")

    # Meta envelope
    meta_msgs = parse_meta_inbound(body)
    if meta_msgs:
        results = []
        for m in meta_msgs:
            if is_duplicate_message(m.get("message_id") or ""):
                results.append({"ok": True, "duplicate": True, "message_id": m.get("message_id")})
                continue
            ok, err = validate_inbound(m.get("phone") or "", m.get("text") or "")
            if not ok:
                results.append({"ok": False, "error": err})
                continue
            result = handle_command(db, phone=m["phone"], text=m.get("text") or "HELLO")
            result["message_id"] = m.get("message_id")
            result["delivered_externally"] = False
            if not demo and meta_configured() and result.get("reply"):
                send_res = send_meta_text(m["phone"], result["reply"])
                result["delivered_externally"] = bool(send_res.get("delivered"))
                if not send_res.get("ok"):
                    result["delivery_error"] = send_res.get("error")
                    if send_res.get("error") in ("auth_failed", "timeout", "network_error", "provider_5xx", "rate_limited"):
                        result["reply"] = (
                            "WhatsApp support is temporarily unavailable. "
                            "Please use the SENTINEL in-app support/safety workflow."
                        )
            results.append(result)
        return {"ok": True, "results": results, "provider_status": status}

    # Structured demo / simple payload — ONLY in demo mode
    if not demo:
        # Real Meta mode: only Meta envelope is accepted
        raise HTTPException(
            status_code=400,
            detail="Real Meta mode requires Meta Cloud API webhook payload",
        )

    phone = body.get("phone") or body.get("from") or ""
    text = body.get("text") if "text" in body else body.get("message")
    if text is None:
        text = ""
    ok, err = validate_inbound(str(phone or ""), str(text))
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    result = handle_command(db, phone=str(phone), text=str(text))
    result["provider_status"] = status
    result["delivered_externally"] = False
    result["demo"] = True
    return result


@router.post("/demo/inbound")
def demo_inbound(
    body: DemoInbound,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles("SUPERVISOR", "MANAGER", "SAFETY_ADMIN", "ADMIN")),
):
    ok, err = validate_inbound(body.phone, body.text)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    result = handle_command(db, phone=body.phone, text=body.text)
    result["demo"] = True
    result["delivered_externally"] = False
    result["label"] = "DEMO / SIMULATION"
    return result
