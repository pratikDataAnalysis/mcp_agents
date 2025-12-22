"""
Twilio WhatsApp inbound handler (Input Layer)

Purpose:
- Own Twilio-specific inbound request handling (signature validation + form parsing)
- Normalize inbound message
- Call the supervisor/agent contract
- Return TwiML XML response back to Twilio
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from starlette.requests import Request
from starlette.responses import Response

from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

logger = logging.getLogger(__name__)

SupervisorFn = Callable[[Dict[str, Any]], Awaitable[str]]


def _build_twiml_response(message: str) -> Response:
    """
    Build a TwiML response for Twilio WhatsApp.
    """
    twiml = MessagingResponse()
    twiml.message(message)
    return Response(str(twiml), media_type="application/xml")


def _validate_twilio_signature(
    request: Request,
    form_data: Dict[str, Any],
    twilio_auth_token: str,
) -> bool:
    """
    Validate Twilio webhook signature.
    Twilio signs: full URL + POST form params.

    Returns True if valid, False otherwise.
    """
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)

    validator = RequestValidator(twilio_auth_token)
    return validator.validate(url, form_data, signature)


def _normalize_inbound_message(form_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert Twilio form payload into a normalized message dict.
    Keep it simple for now (no extra abstractions).
    """
    body = (form_data.get("Body") or "").strip()

    return {
        "channel": "whatsapp",
        "from_number": form_data.get("From", ""),
        "to_number": form_data.get("To"),
        "body": body,
        "message_sid": form_data.get("MessageSid"),
        "raw": dict(form_data),
    }


async def handle_twilio_whatsapp_inbound(
    request: Request,
    supervisor_fn: SupervisorFn,
    *,
    twilio_auth_token: str,
    validate_signature: bool = True,
    empty_message_reply: str = "Send a message and I’ll help.",
) -> Response:
    """
    Main entry point for Twilio WhatsApp inbound webhooks.

    Steps:
    1) Parse form payload sent by Twilio
    2) (Optional) Validate Twilio signature
    3) Normalize inbound message
    4) Call supervisor_fn(normalized_message)
    5) Return TwiML response to Twilio
    """
    client_host = request.client.host if request.client else "unknown"
    url = str(request.url)
    signature_present = bool(request.headers.get("X-Twilio-Signature"))

    logger.info(
        "Inbound WhatsApp webhook received | method=%s | url=%s | client=%s | twilio_sig=%s",
        request.method,
        url,
        client_host,
        signature_present,
    )

    # 1) Parse form payload
    form = await request.form()
    form_data: Dict[str, Any] = dict(form)

    # Helpful for confirming Twilio is truly hitting us
    logger.info(
        "Twilio payload summary | From=%s | To=%s | MessageSid=%s | BodyChars=%s",
        form_data.get("From"),
        form_data.get("To"),
        form_data.get("MessageSid"),
        len((form_data.get("Body") or "").strip()),
    )

    logger.debug("Inbound Twilio payload keys=%s", sorted(list(form_data.keys())))

    # 2) Validate signature (recommended in prod)
    if validate_signature:
        if not twilio_auth_token:
            # This prevents silent misconfig (otherwise signature always fails)
            logger.error("Twilio signature validation enabled but twilio_auth_token is missing")
            return Response("Server misconfigured", status_code=500)

        try:
            ok = _validate_twilio_signature(request, form_data, twilio_auth_token)
            if not ok:
                logger.warning(
                    "Twilio signature validation failed | url_used_for_validation=%s",
                    url,
                )
                return Response("Invalid signature", status_code=403)
            logger.info("Twilio signature validated")
        except Exception:
            logger.exception("Error during Twilio signature validation")
            return Response("Signature validation error", status_code=500)
    else:
        logger.warning("Twilio signature validation is DISABLED (local testing only)")

    # 3) Normalize message
    msg = _normalize_inbound_message(form_data)

    if not msg.get("from_number"):
        logger.warning("Inbound payload missing From number")

    if not msg.get("body"):
        logger.info("Empty inbound message received")
        return _build_twiml_response(empty_message_reply)

    logger.info(
        "Inbound message normalized | from=%s | sid=%s",
        msg.get("from_number"),
        msg.get("message_sid"),
    )

    # 4) Call supervisor
    try:
        reply_text = await supervisor_fn(msg)
    except Exception:
        logger.exception("Supervisor failed while handling inbound message")
        return _build_twiml_response("Something went wrong. Please try again.")

    # 5) Return TwiML to Twilio
    logger.info("Reply generated successfully | chars=%s", len(reply_text or ""))
    return _build_twiml_response(reply_text or "Done.")
