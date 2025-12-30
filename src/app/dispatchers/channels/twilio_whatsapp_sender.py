"""
Twilio WhatsApp sender.

Responsibilities:
- Send WhatsApp messages via Twilio API
- Keep channel-specific logic isolated from dispatcher
"""

from __future__ import annotations

from typing import List, Optional

from twilio.rest import Client

from src.app.config.settings import settings
from src.app.logging.logger import setup_logger

logger = setup_logger(__name__)


class TwilioWhatsAppSender:
    def __init__(
        self,
        *,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        whatsapp_from: Optional[str] = None,
    ) -> None:
        self.account_sid = account_sid or settings.twilio_account_sid
        self.auth_token = auth_token or settings.twilio_auth_token
        self.whatsapp_from = whatsapp_from or settings.twilio_whatsapp_from

        if not self.account_sid:
            raise ValueError("TwilioWhatsAppSender: twilio_account_sid is missing")
        if not self.auth_token:
            raise ValueError("TwilioWhatsAppSender: twilio_auth_token is missing")
        if not self.whatsapp_from:
            raise ValueError("TwilioWhatsAppSender: twilio_whatsapp_from is missing")

        self._client = Client(self.account_sid, self.auth_token)

    def send_text(self, *, to: str, body: str) -> str:
        """
        Send a WhatsApp text message.

        Args:
            to: WhatsApp destination (e.g., "whatsapp:+9199...")
            body: message text

        Returns:
            message_sid (str)
        """
        if not to or not body:
            raise ValueError("TwilioWhatsAppSender: 'to' and 'body' are required")

        logger.info("Sending WhatsApp message via Twilio | to=%s", to)

        msg = self._client.messages.create(
            from_=self.whatsapp_from,
            to=to,
            body=body,
        )

        logger.info("Twilio send success | sid=%s | to=%s", msg.sid, to)
        return msg.sid

    def send_text_with_media(self, *, to: str, body: str, media_url: str | List[str]) -> str:
        """
        Send a WhatsApp message that includes media (audio/image/etc) plus an optional body.

        Twilio expects a publicly reachable URL for each media item.
        """
        if not to:
            raise ValueError("TwilioWhatsAppSender: 'to' is required")
        if not media_url:
            raise ValueError("TwilioWhatsAppSender: 'media_url' is required")

        urls = media_url if isinstance(media_url, list) else [media_url]

        logger.info("Sending WhatsApp media message via Twilio | to=%s | media_count=%s", to, len(urls))

        msg = self._client.messages.create(
            from_=self.whatsapp_from,
            to=to,
            body=body or "",
            media_url=urls,
        )

        logger.info("Twilio send success | sid=%s | to=%s", msg.sid, to)
        return msg.sid
