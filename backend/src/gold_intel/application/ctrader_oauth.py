from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.infrastructure.models import (
    ProviderOAuthAuditEvent,
    ProviderOAuthConnection,
)
from gold_intel.providers.ctrader import CTraderTokenBundle
from gold_intel.security import TOKEN_FORMAT_VERSION, TokenCipher

CTRADER_PROVIDER_CODE = "CTRADER"


@dataclass(frozen=True, slots=True)
class CTraderAuthorizationStatus:
    connection_status: str
    environment: str
    scope: str
    access_token_expires_at: datetime | None
    authorized_at: datetime | None
    last_refreshed_at: datetime | None


async def store_ctrader_authorization(
    session: AsyncSession,
    *,
    environment: str,
    scope: str,
    tokens: CTraderTokenBundle,
    cipher: TokenCipher,
    now: datetime | None = None,
    event_type: str = "OAUTH_AUTHORIZED",
) -> CTraderAuthorizationStatus:
    if scope != "accounts":
        raise ValueError("Only read-only cTrader account scope may be persisted.")
    clock = (now or datetime.now(UTC)).astimezone(UTC)
    expires_at = clock + timedelta(seconds=tokens.expires_in_seconds)
    connection = (
        await session.execute(
            select(ProviderOAuthConnection)
            .where(
                ProviderOAuthConnection.provider_code == CTRADER_PROVIDER_CODE,
                ProviderOAuthConnection.environment == environment,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    access_ciphertext = cipher.encrypt(tokens.access_token, purpose="access")
    refresh_ciphertext = cipher.encrypt(tokens.refresh_token, purpose="refresh")
    if connection is None:
        connection = ProviderOAuthConnection(
            provider_code=CTRADER_PROVIDER_CODE,
            environment=environment,
            scope=scope,
            token_type=tokens.token_type,
            encryption_version=TOKEN_FORMAT_VERSION,
            access_token_ciphertext=access_ciphertext,
            refresh_token_ciphertext=refresh_ciphertext,
            access_token_expires_at=expires_at,
            status="AUTHORIZED",
            authorized_at=clock,
            last_refreshed_at=clock if event_type == "TOKEN_REFRESHED" else None,
            updated_at=clock,
        )
        session.add(connection)
        await session.flush()
    else:
        connection.scope = scope
        connection.token_type = tokens.token_type
        connection.encryption_version = TOKEN_FORMAT_VERSION
        connection.access_token_ciphertext = access_ciphertext
        connection.refresh_token_ciphertext = refresh_ciphertext
        connection.access_token_expires_at = expires_at
        connection.status = "AUTHORIZED"
        if event_type != "TOKEN_REFRESHED":
            connection.authorized_at = clock
        connection.last_refreshed_at = (
            clock if event_type == "TOKEN_REFRESHED" else connection.last_refreshed_at
        )
        connection.updated_at = clock

    session.add(
        ProviderOAuthAuditEvent(
            connection_id=connection.id,
            event_type=event_type,
            outcome="SUCCESS",
            detail={
                "environment": environment,
                "scope": scope,
                "access_token_expires_at": expires_at.isoformat(),
                "encryption_version": TOKEN_FORMAT_VERSION,
            },
        )
    )
    await session.flush()
    return _status(connection, now=clock)


async def get_ctrader_authorization_status(
    session: AsyncSession,
    *,
    environment: str,
    now: datetime | None = None,
) -> CTraderAuthorizationStatus:
    clock = (now or datetime.now(UTC)).astimezone(UTC)
    connection = (
        await session.execute(
            select(ProviderOAuthConnection).where(
                ProviderOAuthConnection.provider_code == CTRADER_PROVIDER_CODE,
                ProviderOAuthConnection.environment == environment,
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        return CTraderAuthorizationStatus(
            connection_status="authorization_required",
            environment=environment,
            scope="accounts",
            access_token_expires_at=None,
            authorized_at=None,
            last_refreshed_at=None,
        )
    return _status(connection, now=clock)


def _status(
    connection: ProviderOAuthConnection,
    *,
    now: datetime,
) -> CTraderAuthorizationStatus:
    if connection.status == "REVOKED":
        state = "revoked"
    elif connection.status == "EXPIRED" or connection.access_token_expires_at <= now:
        state = "token_expired"
    else:
        state = "authorized"
    return CTraderAuthorizationStatus(
        connection_status=state,
        environment=connection.environment,
        scope=connection.scope,
        access_token_expires_at=connection.access_token_expires_at,
        authorized_at=connection.authorized_at,
        last_refreshed_at=connection.last_refreshed_at,
    )
