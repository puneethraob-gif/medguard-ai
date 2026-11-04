from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_liveness_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_openapi_available():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]

def test_unhandled_error_shape():
    @app.get("/__test_error")
    def _error():
        raise RuntimeError("secret detail")
    response = TestClient(app, raise_server_exceptions=False).get("/__test_error")
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_server_error", "message": "An unexpected error occurred."}}
