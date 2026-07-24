from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.schemas import (
    AtlantaFedMptSyncResponse,
    CmeFedWatchSyncRequest,
    CmeFedWatchSyncResponse,
    OfficialCatalystSyncRequest,
    OfficialCatalystSyncResponse,
    PublicDataSyncRequest,
    PublicDataSyncResponse,
    TradingEconomicsSyncResponse,
    VintageMacroSyncResponse,
)
from gold_intel.application.atlanta_fed_mpt import sync_atlanta_fed_mpt
from gold_intel.application.cme_fedwatch import sync_cme_fedwatch
from gold_intel.application.ctrader_oauth import (
    get_ctrader_authorization_status,
    store_ctrader_authorization,
)
from gold_intel.application.official_catalysts import sync_official_catalysts
from gold_intel.application.public_data import sync_public_data
from gold_intel.application.trading_economics import (
    sync_trading_economics_calendar,
)
from gold_intel.application.vintage_macro import sync_vintage_macro
from gold_intel.config import get_settings
from gold_intel.infrastructure.database import get_session
from gold_intel.providers.ctrader import (
    CTraderOAuthClient,
    CTraderOAuthError,
    authorization_url,
)
from gold_intel.security import OAuthStateError, OAuthStateManager, TokenCipher

router = APIRouter(prefix="/providers", tags=["providers"])
logger = structlog.get_logger(__name__)
CTRADER_OAUTH_COOKIE = "gold_intel_ctrader_oauth_state"


class CTraderProviderHealth(BaseModel):
    provider: Literal["ctrader"] = "ctrader"
    configured: bool
    environment: str
    permission_scope: str
    connection_status: Literal["not_tested", "not_configured"]
    approval_required: bool
    note: str


class CTraderOAuthStatus(BaseModel):
    provider: Literal["ctrader"] = "ctrader"
    configured: bool
    environment: str
    permission_scope: str
    connection_status: Literal[
        "not_configured",
        "authorization_required",
        "authorized",
        "token_expired",
        "revoked",
    ]
    access_token_expires_at: datetime | None
    authorized_at: datetime | None
    last_refreshed_at: datetime | None
    next_step: str


class AlfredProviderHealth(BaseModel):
    provider: Literal["alfred"] = "alfred"
    configured: bool
    connection_status: Literal["not_tested", "not_configured"]
    series_count: int = 10
    registration_url: str = "https://fred.stlouisfed.org/docs/api/api_key.html"
    note: str


class TradingEconomicsProviderHealth(BaseModel):
    provider: Literal["trading_economics"] = "trading_economics"
    configured: bool
    connection_status: Literal["not_tested", "not_configured"]
    supported_component_count: int = 15
    registration_url: str = "https://developer.tradingeconomics.com/"
    pricing_url: str = "https://tradingeconomics.com/api/pricing.aspx"
    note: str


class CmeFedWatchProviderHealth(BaseModel):
    provider: Literal["cme_fedwatch"] = "cme_fedwatch"
    configured: bool
    connection_status: Literal["not_tested", "not_configured"]
    product_url: str = "https://www.cmegroup.com/market-data/market-data-api/fedwatch-api.html"
    note: str


class AtlantaFedMptProviderHealth(BaseModel):
    provider: Literal["atlanta_fed_mpt"] = "atlanta_fed_mpt"
    configured: Literal[True] = True
    connection_status: Literal["not_tested"] = "not_tested"
    historical_data_url: str = (
        "https://www.atlantafed.org/research-and-data/data/market-probability-tracker"
    )
    license_class: Literal["PERSONAL_EDUCATIONAL_ONLY"] = "PERSONAL_EDUCATIONAL_ONLY"
    note: str


class OfficialCatalystProviderHealth(BaseModel):
    provider: Literal["official_catalysts"] = "official_catalysts"
    configured: Literal[True] = True
    connection_status: Literal["not_tested"] = "not_tested"
    treasury_dataset_url: str = (
        "https://fiscaldata.treasury.gov/datasets/treasury-securities-auctions-data/"
    )
    federal_reserve_feeds_url: str = "https://www.federalreserve.gov/feeds/feeds.htm"
    note: str


@router.get("/ctrader/health", response_model=CTraderProviderHealth)
async def ctrader_health() -> CTraderProviderHealth:
    settings = get_settings()
    configured = settings.ctrader_credentials_configured
    return CTraderProviderHealth(
        configured=configured,
        environment=settings.ctrader_environment,
        permission_scope=settings.ctrader_scope,
        connection_status="not_tested" if configured else "not_configured",
        approval_required=False,
        note=(
            "Application credentials are present; check OAuth status for account authorization."
            if configured
            else "Client ID and client secret are not configured."
        ),
    )


@router.get("/ctrader/oauth/status", response_model=CTraderOAuthStatus)
async def ctrader_oauth_status(
    session: AsyncSession = Depends(get_session),
) -> CTraderOAuthStatus:
    settings = get_settings()
    if not settings.ctrader_credentials_configured:
        return CTraderOAuthStatus(
            configured=False,
            environment=settings.ctrader_environment,
            permission_scope=settings.ctrader_scope,
            connection_status="not_configured",
            access_token_expires_at=None,
            authorized_at=None,
            last_refreshed_at=None,
            next_step="Configure the cTrader client ID and client secret.",
        )
    state = await get_ctrader_authorization_status(
        session,
        environment=settings.ctrader_environment,
    )
    next_step = {
        "authorization_required": "Open the read-only OAuth start endpoint.",
        "authorized": "Discover and select an authorized cTrader trading account.",
        "token_expired": "Refresh or repeat read-only account authorization.",
        "revoked": "Repeat read-only account authorization.",
    }.get(state.connection_status, "Inspect the provider connection.")
    return CTraderOAuthStatus(
        configured=True,
        environment=state.environment,
        permission_scope=state.scope,
        connection_status=state.connection_status,
        access_token_expires_at=state.access_token_expires_at,
        authorized_at=state.authorized_at,
        last_refreshed_at=state.last_refreshed_at,
        next_step=next_step,
    )


@router.get("/ctrader/oauth/start", response_class=RedirectResponse)
async def ctrader_oauth_start() -> RedirectResponse:
    settings = get_settings()
    client_id, client_secret = _ctrader_credentials()
    _validate_ctrader_oauth_configuration()
    state_manager = OAuthStateManager(
        signing_key=client_secret,
        ttl_seconds=settings.oauth_state_ttl_seconds,
    )
    oauth_state = state_manager.issue()
    redirect_uri = settings.ctrader_redirect_uri
    response = RedirectResponse(
        authorization_url(
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=settings.ctrader_scope,
            state=oauth_state,
        ),
        status_code=status.HTTP_302_FOUND,
    )
    redirect = urlsplit(redirect_uri)
    response.set_cookie(
        CTRADER_OAUTH_COOKIE,
        oauth_state,
        max_age=settings.oauth_state_ttl_seconds,
        httponly=True,
        secure=redirect.scheme == "https",
        samesite="lax",
        path=_oauth_cookie_path(redirect.path),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    logger.info(
        "ctrader_oauth_started",
        environment=settings.ctrader_environment,
        scope=settings.ctrader_scope,
    )
    return response


@router.get("/ctrader/oauth/callback", response_class=HTMLResponse)
async def ctrader_oauth_callback(
    request: Request,
    code: str | None = Query(default=None, min_length=1, max_length=2048),
    oauth_state: str | None = Query(
        default=None,
        alias="state",
        min_length=1,
        max_length=512,
    ),
    error: str | None = Query(default=None, max_length=128),
    session: AsyncSession = Depends(get_session),
) -> Response:
    settings = get_settings()
    _, client_secret = _ctrader_credentials()
    _validate_ctrader_oauth_configuration()
    cookie_path = _oauth_cookie_path(urlsplit(settings.ctrader_redirect_uri).path)
    if error or not code:
        response = _oauth_html(
            status_code=status.HTTP_400_BAD_REQUEST,
            heading="cTrader authorization was not completed",
            message="No account token was stored. You can safely close this page and retry.",
        )
        response.delete_cookie(CTRADER_OAUTH_COOKIE, path=cookie_path)
        return response
    try:
        state_manager = OAuthStateManager(
            signing_key=client_secret,
            ttl_seconds=settings.oauth_state_ttl_seconds,
        )
        cookie_state = request.cookies.get(CTRADER_OAUTH_COOKIE)
        if oauth_state:
            state_manager.validate(oauth_state, cookie_state=cookie_state)
        else:
            # cTrader's published authorization contract does not document the
            # standard state parameter. Keep sending and validating it whenever
            # returned, while retaining a signed, expiring, HttpOnly browser
            # transaction if the provider omits it.
            state_manager.validate_cookie(cookie_state)
            logger.warning("ctrader_oauth_provider_state_omitted")
    except OAuthStateError:
        logger.warning("ctrader_oauth_state_rejected")
        response = _oauth_html(
            status_code=status.HTTP_400_BAD_REQUEST,
            heading="cTrader authorization could not be verified",
            message="The browser session was missing, changed, or expired. Start the link again.",
        )
        response.delete_cookie(CTRADER_OAUTH_COOKIE, path=cookie_path)
        return response

    try:
        tokens = await CTraderOAuthClient(
            client_id=_ctrader_credentials()[0],
            client_secret=client_secret,
        ).exchange_code(
            code=code,
            redirect_uri=settings.ctrader_redirect_uri,
        )
        key_material = settings.provider_token_key_material
        if not key_material:
            raise RuntimeError("Provider token encryption is not configured.")
        stored = await store_ctrader_authorization(
            session,
            environment=settings.ctrader_environment,
            scope=settings.ctrader_scope,
            tokens=tokens,
            cipher=TokenCipher(
                key_material=key_material,
                environment=settings.ctrader_environment,
            ),
        )
        await session.commit()
    except CTraderOAuthError:
        await session.rollback()
        logger.warning("ctrader_oauth_exchange_rejected")
        response = _oauth_html(
            status_code=status.HTTP_502_BAD_GATEWAY,
            heading="cTrader authorization could not be completed",
            message="The one-minute authorization code was rejected or expired. Start again.",
        )
        response.delete_cookie(CTRADER_OAUTH_COOKIE, path=cookie_path)
        return response
    except Exception:
        await session.rollback()
        logger.exception("ctrader_oauth_storage_failed")
        response = _oauth_html(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            heading="cTrader authorization could not be stored",
            message="No usable connection was created. Review the API health and retry.",
        )
        response.delete_cookie(CTRADER_OAUTH_COOKIE, path=cookie_path)
        return response

    logger.info(
        "ctrader_oauth_authorized",
        environment=stored.environment,
        scope=stored.scope,
        access_token_expires_at=stored.access_token_expires_at,
    )
    redirect_response = RedirectResponse(
        url=f"{cookie_path}/complete",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    redirect_response.headers["Cache-Control"] = "no-store"
    redirect_response.headers["Referrer-Policy"] = "no-referrer"
    redirect_response.delete_cookie(CTRADER_OAUTH_COOKIE, path=cookie_path)
    return redirect_response


@router.get("/ctrader/oauth/complete", response_class=HTMLResponse)
async def ctrader_oauth_complete() -> HTMLResponse:
    return _oauth_html(
        status_code=status.HTTP_200_OK,
        heading="Read-only cTrader access is connected",
        message=(
            "The tokens were encrypted and stored without being shown in the browser. "
            "You can close this page."
        ),
    )


def _ctrader_credentials() -> tuple[str, str]:
    settings = get_settings()
    if (
        not settings.ctrader_credentials_configured
        or settings.ctrader_client_id is None
        or settings.ctrader_client_secret is None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cTrader application credentials are not configured.",
        )
    return (
        settings.ctrader_client_id.get_secret_value(),
        settings.ctrader_client_secret.get_secret_value(),
    )


def _validate_ctrader_oauth_configuration() -> None:
    settings = get_settings()
    if settings.ctrader_scope != "accounts":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cTrader OAuth must use the read-only accounts scope.",
        )
    redirect = urlsplit(settings.ctrader_redirect_uri)
    if redirect.scheme not in {"http", "https"} or not redirect.netloc or redirect.fragment:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cTrader redirect URI is invalid.",
        )
    if settings.app_env.lower() == "production":
        if redirect.scheme != "https":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Production cTrader OAuth requires an HTTPS redirect URI.",
            )
        if not settings.provider_token_key_material:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Production provider-token encryption is not configured.",
            )


def _oauth_cookie_path(callback_path: str) -> str:
    parent, _, _ = callback_path.rpartition("/")
    return parent or "/"


def _oauth_html(*, status_code: int, heading: str, message: str) -> HTMLResponse:
    response = HTMLResponse(
        content=(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{heading}</title></head><body>"
            f"<main><h1>{heading}</h1><p>{message}</p></main></body></html>"
        ),
        status_code=status_code,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    )
    return response


@router.get("/alfred/health", response_model=AlfredProviderHealth)
async def alfred_health() -> AlfredProviderHealth:
    settings = get_settings()
    configured = settings.fred_api_key_configured
    return AlfredProviderHealth(
        configured=configured,
        connection_status="not_tested" if configured else "not_configured",
        note=(
            "A FRED API key is configured for official ALFRED vintage requests."
            if configured
            else (
                "Add a free FRED_API_KEY to the root .env to sync CPI, PCE, "
                "growth, and labour vintages."
            )
        ),
    )


@router.get(
    "/trading-economics/health",
    response_model=TradingEconomicsProviderHealth,
)
async def trading_economics_health() -> TradingEconomicsProviderHealth:
    settings = get_settings()
    configured = settings.trading_economics_api_key_configured
    return TradingEconomicsProviderHealth(
        configured=configured,
        connection_status="not_tested" if configured else "not_configured",
        note=(
            "Credentials are present for the licensed point-in-time calendar."
            if configured
            else (
                "Add TRADING_ECONOMICS_API_KEY to the root .env. Manual event "
                "bundles remain available when no subscription is connected."
            )
        ),
    )


@router.get(
    "/cme-fedwatch/health",
    response_model=CmeFedWatchProviderHealth,
)
async def cme_fedwatch_health() -> CmeFedWatchProviderHealth:
    settings = get_settings()
    configured = settings.cme_fedwatch_credentials_configured
    return CmeFedWatchProviderHealth(
        configured=configured,
        connection_status="not_tested" if configured else "not_configured",
        note=(
            "Credentials are present for the official complete Fed probability path."
            if configured
            else (
                "CME FedWatch EOD is the preferred complete policy-path source. "
                "The existing versioned JSON upload remains available."
            )
        ),
    )


@router.get(
    "/atlanta-fed-mpt/health",
    response_model=AtlantaFedMptProviderHealth,
)
async def atlanta_fed_mpt_health() -> AtlantaFedMptProviderHealth:
    return AtlantaFedMptProviderHealth(
        note=(
            "No credential is required. The official historical workbook supplies "
            "real CME SOFR-options-implied quarterly distributions. It is not an "
            "exact meeting-by-meeting FedWatch feed and is permitted for personal "
            "and educational use only."
        )
    )


@router.get(
    "/official-catalysts/health",
    response_model=OfficialCatalystProviderHealth,
)
async def official_catalysts_health() -> OfficialCatalystProviderHealth:
    return OfficialCatalystProviderHealth(
        note=(
            "No credential is required. Treasury Fiscal Data supplies announced "
            "auction dates and exact Eastern-time competitive closes. Federal "
            "Reserve RSS supplies exact publication timestamps for released "
            "speeches and monetary-policy communications, not a forward speech "
            "calendar."
        )
    )


@router.post(
    "/public/sync",
    response_model=PublicDataSyncResponse,
    status_code=status.HTTP_201_CREATED,
)
async def public_data_sync(
    request: PublicDataSyncRequest,
    session: AsyncSession = Depends(get_session),
) -> PublicDataSyncResponse:
    settings = get_settings()
    try:
        result = await sync_public_data(
            session,
            raw_store_root=settings.raw_store_path,
            start=request.start,
            end=request.end,
        )
        await session.commit()
    except httpx.HTTPError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=502,
            detail=f"Official public-data provider request failed: {type(exc).__name__}",
        ) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise
    return PublicDataSyncResponse(**asdict(result))


@router.post(
    "/official-catalysts/sync",
    response_model=OfficialCatalystSyncResponse,
    status_code=status.HTTP_201_CREATED,
)
async def official_catalyst_sync(
    request: OfficialCatalystSyncRequest,
    session: AsyncSession = Depends(get_session),
) -> OfficialCatalystSyncResponse:
    settings = get_settings()
    try:
        result = await sync_official_catalysts(
            session,
            raw_store_root=settings.raw_store_path,
            start=request.start,
            end=request.end,
        )
        await session.commit()
    except httpx.HTTPError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=502,
            detail=f"Official catalyst provider request failed: {type(exc).__name__}",
        ) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise
    return OfficialCatalystSyncResponse(**asdict(result))


@router.post(
    "/alfred/sync",
    response_model=VintageMacroSyncResponse,
    status_code=status.HTTP_201_CREATED,
)
async def alfred_vintage_sync(
    request: PublicDataSyncRequest,
    session: AsyncSession = Depends(get_session),
) -> VintageMacroSyncResponse:
    settings = get_settings()
    if not settings.fred_api_key_configured or settings.fred_api_key is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "FRED_API_KEY is not configured. Register for the free official "
                "key, add it to the root .env, and restart the API."
            ),
        )
    try:
        result = await sync_vintage_macro(
            session,
            raw_store_root=settings.raw_store_path,
            start=request.start,
            end=request.end,
            api_key=settings.fred_api_key.get_secret_value(),
        )
        await session.commit()
    except httpx.HTTPError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=502,
            detail=f"ALFRED provider request failed: {type(exc).__name__}",
        ) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise
    return VintageMacroSyncResponse(**asdict(result))


@router.post(
    "/trading-economics/sync",
    response_model=TradingEconomicsSyncResponse,
    status_code=status.HTTP_201_CREATED,
)
async def trading_economics_sync(
    request: PublicDataSyncRequest,
    session: AsyncSession = Depends(get_session),
) -> TradingEconomicsSyncResponse:
    settings = get_settings()
    if (
        not settings.trading_economics_api_key_configured
        or settings.trading_economics_api_key is None
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "TRADING_ECONOMICS_API_KEY is not configured. Add a licensed "
                "API key to the root .env and restart the API."
            ),
        )
    try:
        result = await sync_trading_economics_calendar(
            session,
            raw_store_root=settings.raw_store_path,
            start=request.start,
            end=request.end,
            api_key=settings.trading_economics_api_key.get_secret_value(),
        )
        await session.commit()
    except httpx.HTTPError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=502,
            detail=(f"Trading Economics provider request failed: {type(exc).__name__}"),
        ) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise
    return TradingEconomicsSyncResponse(**asdict(result))


@router.post(
    "/cme-fedwatch/sync",
    response_model=CmeFedWatchSyncResponse,
    status_code=status.HTTP_201_CREATED,
)
async def cme_fedwatch_sync(
    request: CmeFedWatchSyncRequest,
    session: AsyncSession = Depends(get_session),
) -> CmeFedWatchSyncResponse:
    settings = get_settings()
    if (
        not settings.cme_fedwatch_credentials_configured
        or settings.cme_fedwatch_client_id is None
        or settings.cme_fedwatch_client_secret is None
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "CME_FEDWATCH_CLIENT_ID and CME_FEDWATCH_CLIENT_SECRET are not "
                "configured. Add an entitled OAuth API ID/password to the root "
                ".env and restart the API."
            ),
        )
    try:
        result = await sync_cme_fedwatch(
            session,
            raw_store_root=settings.raw_store_path,
            start=request.start,
            end=request.end,
            client_id=settings.cme_fedwatch_client_id.get_secret_value(),
            client_secret=settings.cme_fedwatch_client_secret.get_secret_value(),
        )
        await session.commit()
    except httpx.HTTPError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=502,
            detail=f"CME FedWatch provider request failed: {type(exc).__name__}",
        ) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise
    return CmeFedWatchSyncResponse(**asdict(result))


@router.post(
    "/atlanta-fed-mpt/sync",
    response_model=AtlantaFedMptSyncResponse,
    status_code=status.HTTP_201_CREATED,
)
async def atlanta_fed_mpt_sync(
    session: AsyncSession = Depends(get_session),
) -> AtlantaFedMptSyncResponse:
    settings = get_settings()
    try:
        result = await sync_atlanta_fed_mpt(
            session,
            raw_store_root=settings.raw_store_path,
        )
        await session.commit()
    except httpx.HTTPError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=502,
            detail=f"Atlanta Fed MPT download failed: {type(exc).__name__}",
        ) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise
    return AtlantaFedMptSyncResponse(**asdict(result))
