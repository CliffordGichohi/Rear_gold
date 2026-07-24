from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from gold_intel.api.routes import providers as provider_routes
from gold_intel.config import Settings
from gold_intel.main import app
from gold_intel.providers.ctrader import (
    CTraderOAuthClient,
    CTraderOAuthError,
    authorization_url,
)
from gold_intel.security import (
    OAuthStateError,
    OAuthStateManager,
    TokenCipher,
    TokenDecryptionError,
)


def test_ctrader_authorization_url_is_read_only_and_contains_no_secret() -> None:
    url = authorization_url(
        client_id="public-client-id",
        redirect_uri="http://localhost:8000/api/v1/providers/ctrader/oauth/callback",
        state="signed-state",
    )
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)

    assert parsed.netloc == "id.ctrader.com"
    assert query["scope"] == ["accounts"]
    assert query["state"] == ["signed-state"]
    assert query["client_id"] == ["public-client-id"]
    assert "secret" not in query


def test_ctrader_authorization_url_rejects_trading_scope() -> None:
    with pytest.raises(ValueError, match="read-only"):
        authorization_url(
            client_id="public-client-id",
            redirect_uri="http://localhost/callback",
            state="signed-state",
            scope="trading",
        )


def test_oauth_state_is_browser_bound_signed_and_short_lived() -> None:
    manager = OAuthStateManager(signing_key="state-signing-secret", ttl_seconds=300)
    state = manager.issue(now=1_000)

    manager.validate(state, cookie_state=state, now=1_299)
    with pytest.raises(OAuthStateError):
        manager.validate(state, cookie_state=f"{state}changed", now=1_299)
    with pytest.raises(OAuthStateError, match="expired"):
        manager.validate(state, cookie_state=state, now=1_301)


def test_provider_tokens_are_authenticated_and_encrypted_at_rest() -> None:
    cipher = TokenCipher(key_material="independent-encryption-key", environment="demo")
    ciphertext = cipher.encrypt("sensitive-access-token", purpose="access")

    assert "sensitive-access-token" not in ciphertext
    assert cipher.decrypt(ciphertext, purpose="access") == "sensitive-access-token"
    with pytest.raises(TokenDecryptionError):
        cipher.decrypt(ciphertext, purpose="refresh")
    with pytest.raises(TokenDecryptionError):
        TokenCipher(
            key_material="wrong-encryption-key",
            environment="demo",
        ).decrypt(ciphertext, purpose="access")


@pytest.mark.asyncio
async def test_ctrader_token_exchange_and_refresh_follow_official_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "accessToken": f"access-{len(requests)}",
                "refreshToken": f"refresh-{len(requests)}",
                "tokenType": "bearer",
                "expiresIn": 2_628_000,
                "errorCode": None,
                "description": None,
            },
        )

    provider = CTraderOAuthClient(
        client_id="client-id",
        client_secret="client-secret",
        transport=httpx.MockTransport(handler),
    )
    issued = await provider.exchange_code(
        code="one-minute-code",
        redirect_uri="http://localhost:8000/api/v1/providers/ctrader/oauth/callback",
    )
    refreshed = await provider.refresh(refresh_token=issued.refresh_token)

    assert issued.access_token == "access-1"
    assert refreshed.access_token == "access-2"
    assert requests[0].method == "GET"
    assert requests[0].url.params["grant_type"] == "authorization_code"
    assert requests[0].url.params["code"] == "one-minute-code"
    assert requests[1].method == "POST"
    assert requests[1].url.params["grant_type"] == "refresh_token"
    assert requests[1].url.params["refresh_token"] == "refresh-1"


@pytest.mark.asyncio
async def test_ctrader_oauth_errors_do_not_echo_provider_secrets() -> None:
    provider = CTraderOAuthClient(
        client_id="client-id",
        client_secret="client-secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                401,
                json={
                    "errorCode": "INVALID_CLIENT",
                    "description": "client-secret should never be repeated",
                },
            )
        ),
    )

    with pytest.raises(CTraderOAuthError) as captured:
        await provider.exchange_code(
            code="sensitive-code",
            redirect_uri="http://localhost/callback",
        )

    assert "client-secret" not in str(captured.value)
    assert "sensitive-code" not in str(captured.value)


@pytest.mark.asyncio
async def test_oauth_start_sets_secure_session_boundary_without_exposing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        ctrader_client_id="public-client-id",
        ctrader_client_secret="private-client-secret",
        ctrader_scope="accounts",
        ctrader_redirect_uri=(
            "http://localhost:8000/api/v1/providers/ctrader/oauth/callback"
        ),
    )
    monkeypatch.setattr(provider_routes, "get_settings", lambda: settings)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        response = await client.get("/api/v1/providers/ctrader/oauth/start")

    assert response.status_code == 302
    assert response.headers["cache-control"] == "no-store"
    assert "private-client-secret" not in response.headers["location"]
    assert "scope=accounts" in response.headers["location"]
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


@pytest.mark.asyncio
async def test_oauth_callback_rejects_mismatched_state_before_token_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        ctrader_client_id="public-client-id",
        ctrader_client_secret="private-client-secret",
        ctrader_scope="accounts",
        ctrader_redirect_uri=(
            "http://localhost:8000/api/v1/providers/ctrader/oauth/callback"
        ),
    )
    monkeypatch.setattr(provider_routes, "get_settings", lambda: settings)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        start = await client.get("/api/v1/providers/ctrader/oauth/start")
        issued_state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        response = await client.get(
            "/api/v1/providers/ctrader/oauth/callback",
            params={"code": "unused-code", "state": f"{issued_state}changed"},
        )

    assert response.status_code == 400
    assert "could not be verified" in response.text
    assert "unused-code" not in response.text
