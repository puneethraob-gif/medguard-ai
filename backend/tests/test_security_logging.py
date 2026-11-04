import asyncio
import json
import logging
from types import SimpleNamespace

from app.main import unhandled_exception_handler


def test_unhandled_exception_log_is_structured_and_does_not_include_exception_text(caplog):
    request = SimpleNamespace(
        method="POST",
        scope={"route": SimpleNamespace(path="/api/v1/consultations/{consultation_id}/recording")},
    )
    caplog.set_level(logging.ERROR)
    asyncio.run(unhandled_exception_handler(request, RuntimeError("Authorization: Bearer synthetic-sensitive-value")))
    payload = json.loads(caplog.records[-1].getMessage())
    assert payload == {
        "event": "api.unhandled_exception",
        "method": "POST",
        "route": "/api/v1/consultations/{consultation_id}/recording",
        "error_type": "RuntimeError",
    }
    assert "synthetic-sensitive-value" not in caplog.text
