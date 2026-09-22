from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok():
    response = TestClient(create_app()).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
