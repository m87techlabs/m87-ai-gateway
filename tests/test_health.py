from fastapi.testclient import TestClient

from m87_gateway.main import create_app
from m87_gateway.config import GatewaySettings


def test_health():
    with TestClient(create_app(GatewaySettings())) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
