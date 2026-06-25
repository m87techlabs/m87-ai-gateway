from fastapi.testclient import TestClient

from m87_gateway.main import app


def test_missing_auth_rejected():
    client = TestClient(app)
    response = client.post("/v1/chat/completions", json={"model": "auto", "messages": []})
    assert response.status_code == 401
