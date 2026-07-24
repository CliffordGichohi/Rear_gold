from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

CTRADER_AUTHORIZE_URL = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
CTRADER_TOKEN_URL = "https://openapi.ctrader.com/apps/token"


class CTraderOAuthError(ValueError):
    """A deliberately secret-free cTrader OAuth failure."""


@dataclass(frozen=True, slots=True)
class CTraderTokenBundle:
    access_token: str
    refresh_token: str
    token_type: str
    expires_in_seconds: int


def authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scope: str = "accounts",
) -> str:
    if not client_id or not redirect_uri or not state:
        raise ValueError("Client ID, redirect URI, and OAuth state are required.")
    if scope != "accounts":
        raise ValueError("This research platform permits only read-only cTrader account access.")
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "product": "web",
            "state": state,
        }
    )
    return f"{CTRADER_AUTHORIZE_URL}?{query}"


class CTraderOAuthClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
        token_url: str = CTRADER_TOKEN_URL,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("cTrader client ID and client secret are required.")
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0))
        self._transport = transport
        self._token_url = token_url

    async def exchange_code(self, *, code: str, redirect_uri: str) -> CTraderTokenBundle:
        if not code or not redirect_uri:
            raise ValueError("cTrader authorization code and redirect URI are required.")
        return await self._request_token(
            method="GET",
            params={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )

    async def refresh(self, *, refresh_token: str) -> CTraderTokenBundle:
        if not refresh_token:
            raise ValueError("cTrader refresh token is required.")
        return await self._request_token(
            method="POST",
            params={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )

    async def _request_token(
        self,
        *,
        method: str,
        params: dict[str, str],
    ) -> CTraderTokenBundle:
        request_params = {
            **params,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method,
                    self._token_url,
                    params=request_params,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            raise CTraderOAuthError("cTrader token service could not be reached.") from exc

        if response.status_code in {400, 401, 403}:
            raise CTraderOAuthError(
                "cTrader rejected or expired the authorization grant."
            )
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CTraderOAuthError("cTrader returned an invalid token response.") from exc
        if not isinstance(payload, dict):
            raise CTraderOAuthError("cTrader returned a non-object token response.")
        return _parse_token_payload(payload)


def _parse_token_payload(payload: dict[str, Any]) -> CTraderTokenBundle:
    error_code = payload.get("errorCode")
    if error_code:
        raise CTraderOAuthError("cTrader rejected or expired the authorization grant.")
    access_token = payload.get("accessToken")
    refresh_token = payload.get("refreshToken")
    token_type = payload.get("tokenType")
    expires_in = payload.get("expiresIn")
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(refresh_token, str)
        or not refresh_token
        or not isinstance(token_type, str)
        or token_type.lower() != "bearer"
        or not isinstance(expires_in, int)
        or isinstance(expires_in, bool)
        or not 60 <= expires_in <= 31_536_000
    ):
        raise CTraderOAuthError("cTrader token response was incomplete or invalid.")
    return CTraderTokenBundle(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type=token_type.lower(),
        expires_in_seconds=expires_in,
    )
