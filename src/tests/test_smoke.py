"""Smoke tests.

We keep early tests super simple to ensure:
- project imports work
- basic functions return expected placeholder values
"""

from src.app.services.twilio_service import build_twiml_message


def test_build_twiml_message_smoke():
    xml = build_twiml_message("hello")
    assert "<Message>hello</Message>" in xml
