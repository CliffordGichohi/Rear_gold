from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import uuid4

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

CME_FEDWATCH_BASE_URL = "https://markets.api.cmegroup.com/fedwatch/v1"
CME_OAUTH_TOKEN_URL = "https://auth.cmegroup.com/as/token.oauth2"
CME_EOD_PUBLICATION_TIME = time(hour=1, minute=45, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class CmeFedWatchOutcome:
    meeting_date: date
    lower_basis_points: int
    upper_basis_points: int
    probability: float
    raw_payload: dict[str, Any]

    @property
    def expected_rate(self) -> float:
        """Target-range midpoint expressed as a percentage rate."""
        return (self.lower_basis_points + self.upper_basis_points) / 200


@dataclass(frozen=True, slots=True)
class CmeFedWatchSnapshot:
    reporting_date: date
    snapshot_as_of: datetime
    available_at: datetime
    outcomes: tuple[CmeFedWatchOutcome, ...]
    availability_quality: str


@dataclass(frozen=True, slots=True)
class CmeFedWatchPath:
    retrieved_at: datetime
    fetched_forecast_records: int
    snapshots: tuple[CmeFedWatchSnapshot, ...]


class CmeFedWatchProvider:
    """Official CME FedWatch end-of-day probability-path adapter.

    CME identifies a forecast vintage by ``reportingDt`` and documents that
    end-of-day forecasts are published on business days at 01:45 UTC. That
    official publication clock is used for both ``snapshot_as_of`` and
    ``available_at``. It is deliberately not replaced with the later ingestion
    time, so historical replay remains point-in-time correct.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        timeout_seconds: float = 45.0,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = CME_FEDWATCH_BASE_URL,
        token_url: str = CME_OAUTH_TOKEN_URL,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("CME FedWatch OAuth API ID and password are both required.")
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = httpx.Timeout(timeout_seconds, connect=15.0)
        self._transport = transport
        self._base_url = base_url.rstrip("/")
        self._token_url = token_url

    async def fetch(
        self,
        *,
        start: date,
        end: date,
        retrieved_at: datetime | None = None,
    ) -> CmeFedWatchPath:
        if start > end:
            raise ValueError("CME FedWatch start cannot follow end.")
        if end - start > timedelta(days=366):
            raise ValueError(
                "One CME FedWatch sync is limited to 367 calendar days "
                "to protect licensed API quotas."
            )
        retrieval_clock = (retrieved_at or datetime.now(UTC)).astimezone(UTC)
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            access_token = await self._access_token(client)
            meeting_dates = await self._meeting_dates(
                client,
                access_token=access_token,
                start=start,
                end=end,
                request_time=retrieval_clock,
            )
            if not meeting_dates:
                raise ValueError("CME FedWatch returned no FOMC meetings relevant to this period.")
            records: list[dict[str, Any]] = []
            reporting_dates = list(_date_range(start, end))
            for reporting_chunk in _chunks(reporting_dates, 20):
                for meeting_chunk in _chunks(meeting_dates, 20):
                    records.extend(
                        await self._forecast_records(
                            client,
                            access_token=access_token,
                            reporting_dates=reporting_chunk,
                            meeting_dates=meeting_chunk,
                            request_time=retrieval_clock,
                        )
                    )

        canonical: dict[tuple[date, date], dict[str, Any]] = {}
        for row in records:
            meeting_date = _parse_date(row.get("meetingDt"), "meetingDt")
            reporting_date = _parse_date(row.get("reportingDt"), "reportingDt")
            if not start <= reporting_date <= end:
                continue
            canonical[(reporting_date, meeting_date)] = row
        if not canonical:
            raise ValueError(
                "CME FedWatch returned no forecast distributions for the requested reporting dates."
            )

        by_reporting_date: dict[date, list[CmeFedWatchOutcome]] = {}
        for (reporting_date, meeting_date), row in sorted(canonical.items()):
            outcomes = _normalize_rate_ranges(
                row.get("rateRange"),
                meeting_date=meeting_date,
            )
            by_reporting_date.setdefault(reporting_date, []).extend(outcomes)

        snapshots: list[CmeFedWatchSnapshot] = []
        for reporting_date, outcomes in sorted(by_reporting_date.items()):
            _validate_meeting_distributions(outcomes)
            published_at = datetime.combine(
                reporting_date,
                CME_EOD_PUBLICATION_TIME,
            )
            snapshots.append(
                CmeFedWatchSnapshot(
                    reporting_date=reporting_date,
                    snapshot_as_of=published_at,
                    available_at=published_at,
                    outcomes=tuple(
                        sorted(
                            outcomes,
                            key=lambda item: (
                                item.meeting_date,
                                item.upper_basis_points,
                            ),
                        )
                    ),
                    availability_quality="OFFICIAL_EOD_PUBLICATION_SCHEDULE",
                )
            )
        return CmeFedWatchPath(
            retrieved_at=retrieval_clock,
            fetched_forecast_records=len(canonical),
            snapshots=tuple(snapshots),
        )

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def _access_token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            self._token_url,
            auth=httpx.BasicAuth(self._client_id, self._client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"},
        )
        if response.status_code in {400, 401, 403}:
            raise ValueError(
                "CME rejected the OAuth API ID/password or the API ID is not entitled."
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("CME OAuth returned a non-object response.")
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("CME OAuth response did not contain an access token.")
        return access_token

    async def _meeting_dates(
        self,
        client: httpx.AsyncClient,
        *,
        access_token: str,
        start: date,
        end: date,
        request_time: datetime,
    ) -> list[date]:
        rows: list[dict[str, Any]] = []
        for endpoint in ("/meetings/history", "/meetings/future"):
            rows.extend(
                await self._get_page(
                    client,
                    endpoint=endpoint,
                    access_token=access_token,
                    request_time=request_time,
                    params={"limit": 2_000},
                )
            )
        # A reporting snapshot normally carries probabilities for roughly the
        # next eight meetings. The 450-day window safely includes those while
        # keeping forecast requests bounded.
        upper_bound = end + timedelta(days=450)
        return sorted(
            {
                _parse_date(row.get("meetingDt"), "meetingDt")
                for row in rows
                if start <= _parse_date(row.get("meetingDt"), "meetingDt") <= upper_bound
            }
        )

    async def _forecast_records(
        self,
        client: httpx.AsyncClient,
        *,
        access_token: str,
        reporting_dates: list[date],
        meeting_dates: list[date],
        request_time: datetime,
    ) -> list[dict[str, Any]]:
        return await self._get_page(
            client,
            endpoint="/forecasts",
            access_token=access_token,
            request_time=request_time,
            params={
                "limit": 2_000,
                "meetingDt": ",".join(item.isoformat() for item in meeting_dates),
                "reportingDt": ",".join(item.isoformat() for item in reporting_dates),
            },
        )

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def _get_page(
        self,
        client: httpx.AsyncClient,
        *,
        endpoint: str,
        access_token: str,
        request_time: datetime,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        response = await client.get(
            f"{self._base_url}{endpoint}",
            params=params,
            headers={
                "Authorization": f"Bearer {access_token}",
                "CME-Application-Name": "Gold Market Intelligence Engine",
                "CME-Application-Vendor": "Proprietary",
                "CME-Application-Version": "0.1.0",
                "CME-Request-ID": str(uuid4()),
                "CME-Transact-Time": request_time.isoformat(),
                "User-Agent": "gold-market-intelligence-engine/0.1.0",
            },
        )
        if response.status_code in {401, 403}:
            raise ValueError(
                "CME rejected the bearer token or the API ID lacks FedWatch entitlement."
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"CME {endpoint} returned a non-object response.")
        rows = payload.get("payload")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"CME {endpoint} response has an invalid payload.")
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            total_pages = _integer(metadata.get("totalPages"), default=1)
            if total_pages > 1:
                raise ValueError(
                    f"CME {endpoint} response was paginated unexpectedly; reduce the sync interval."
                )
        return rows


def _normalize_rate_ranges(
    raw_ranges: Any,
    *,
    meeting_date: date,
) -> list[CmeFedWatchOutcome]:
    if not isinstance(raw_ranges, list) or not raw_ranges:
        raise ValueError(f"CME forecast for {meeting_date.isoformat()} has no rate-range outcomes.")
    outcomes: list[CmeFedWatchOutcome] = []
    for raw in raw_ranges:
        if not isinstance(raw, dict):
            raise ValueError("CME rateRange outcomes must be objects.")
        lower = _integer(raw.get("lowerRt"))
        upper = _integer(raw.get("upperRt"))
        probability = _probability(raw.get("probability"))
        if lower < 0 or upper <= lower or upper - lower > 100:
            raise ValueError(f"CME returned an invalid target range {lower}-{upper} basis points.")
        outcomes.append(
            CmeFedWatchOutcome(
                meeting_date=meeting_date,
                lower_basis_points=lower,
                upper_basis_points=upper,
                probability=probability,
                raw_payload=raw,
            )
        )
    return outcomes


def _validate_meeting_distributions(
    outcomes: list[CmeFedWatchOutcome],
) -> None:
    grouped: dict[date, float] = {}
    keys: set[tuple[date, int, int]] = set()
    for outcome in outcomes:
        key = (
            outcome.meeting_date,
            outcome.lower_basis_points,
            outcome.upper_basis_points,
        )
        if key in keys:
            raise ValueError("CME returned a duplicate meeting/rate-range outcome.")
        keys.add(key)
        grouped[outcome.meeting_date] = grouped.get(outcome.meeting_date, 0.0) + outcome.probability
    invalid = {
        meeting.isoformat(): total for meeting, total in grouped.items() if abs(total - 1.0) > 0.001
    }
    if invalid:
        raise ValueError("CME rate-range probabilities must sum to 1 per meeting: " + str(invalid))


def _date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _chunks(values: list[date], size: int) -> list[list[date]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _parse_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"CME {field_name} must be an ISO date.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"CME {field_name} must be an ISO date.") from exc


def _integer(value: Any, *, default: int | None = None) -> int:
    if value is None and default is not None:
        return default
    if isinstance(value, bool):
        raise ValueError("CME integer fields cannot be booleans.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("CME returned an invalid integer field.") from exc
    return parsed


def _probability(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        raise ValueError("CME probability cannot be a boolean.")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("CME returned an invalid probability.") from exc
    if not 0 <= parsed <= 1:
        raise ValueError("CME probability must be between 0 and 1.")
    return parsed
