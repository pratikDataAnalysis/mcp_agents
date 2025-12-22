"""Twilio helpers.

Right now we only need to return TwiML for a simple WhatsApp reply.
Later we can add:
- outbound messages
- message status callbacks
- richer formatting
"""

from xml.sax.saxutils import escape


def build_twiml_message(text: str) -> str:
    """Create a minimal TwiML response for Twilio Messaging.

    We escape the text to avoid breaking XML.
    """
    safe_text = escape(text)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Message>{safe_text}</Message>
</Response>
"""
