import pytest
from httpx import ASGITransport, AsyncClient

from gold_intel.main import app


@pytest.mark.asyncio
async def test_liveness_is_dependency_free() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api", "checks": {}}
    assert response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_ctrader_health_never_exposes_credentials() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/providers/ctrader/health")

    assert response.status_code == 200
    body = response.json()
    assert "client_id" not in body
    assert "client_secret" not in body
    assert body["permission_scope"] == "accounts"
    assert body["environment"] == "demo"
