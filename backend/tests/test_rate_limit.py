from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.main as main_module
from app.core.config import Settings, settings


class _Limiter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.keys = []

    def consume(self, key, window_seconds):
        self.keys.append((key, window_seconds))
        if self.error:
            raise self.error
        return self.result


def test_auth_endpoint_rate_limit_is_enforced_and_ip_is_not_stored(monkeypatch):
    limiter = _Limiter(result=settings.auth_rate_limit_per_minute + 1)
    monkeypatch.setattr(main_module, "auth_rate_limiter", limiter)

    response = TestClient(main_module.app).post(
        "/api/v1/auth/login", json={"email": "x@example.test", "password": "not-a-real-password"}
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == str(settings.auth_rate_limit_window_seconds)
    assert limiter.keys and "testclient" not in limiter.keys[0][0]


def test_auth_endpoint_fails_closed_when_rate_limiter_is_unavailable(monkeypatch):
    monkeypatch.setattr(main_module, "auth_rate_limiter", _Limiter(error=RuntimeError("private redis detail")))

    response = TestClient(main_module.app).post(
        "/api/v1/auth/login", json={"email": "x@example.test", "password": "not-a-real-password"}
    )

    assert response.status_code == 503
    assert "private redis detail" not in response.text


def test_cookie_auth_rejects_wildcard_cors_origin():
    try:
        Settings(cors_origins="*")
    except ValidationError:
        pass
    else:
        raise AssertionError("wildcard CORS origins must not be accepted with credentialed requests")
