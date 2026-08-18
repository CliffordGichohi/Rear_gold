from __future__ import annotations

import asyncio
import csv
import io
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

NEW_YORK = ZoneInfo("America/New_York")
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
CFTC_COT_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
CFTC_GOLD_CONTRACT_CODE = "088691"


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    external_code: str
    internal_code: str
    name: str
    unit: str
    frequency: str
    expected_lag_seconds: int


FRED_MARKET_SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        "DGS2", "US_TREASURY_2Y", "United States 2-Year Treasury Yield", "PERCENT", "DAILY", 86_400
    ),
    SeriesSpec(
        "DGS10",
        "US_TREASURY_10Y",
        "United States 10-Year Treasury Yield",
        "PERCENT",
        "DAILY",
        86_400,
    ),
    SeriesSpec(
        "DFII10",
        "US_REAL_YIELD_10Y",
        "United States 10-Year TIPS Real Yield",
        "PERCENT",
        "DAILY",
        86_400,
    ),
    SeriesSpec(
        "T10YIE",
        "US_BREAKEVEN_10Y",
        "United States 10-Year Breakeven Inflation",
        "PERCENT",
        "DAILY",
        86_400,
    ),
    SeriesSpec(
        "DTWEXBGS",
        "USD_BROAD_NOMINAL",
        "Nominal Broad United States Dollar Index",
        "INDEX",
        "DAILY",
        172_800,
    ),
    SeriesSpec(
        "DFF", "US_FED_FUNDS_EFFECTIVE", "Effective Federal Funds Rate", "PERCENT", "DAILY", 86_400
    ),
    SeriesSpec("SP500", "US_EQUITY_PROXY", "S&P 500 Index", "INDEX", "DAILY", 86_400),
    SeriesSpec("VIXCLS", "US_VOLATILITY_INDEX", "CBOE Volatility Index", "INDEX", "DAILY", 86_400),
    SeriesSpec(
        "STLFSI4",
        "US_FINANCIAL_STRESS",
        "St. Louis Fed Financial Stress Index",
        "INDEX",
        "WEEKLY",
        604_800,
    ),
    SeriesSpec(
        "BAMLH0A0HYM2",
        "US_HIGH_YIELD_OAS",
        "US High Yield Option-Adjusted Spread",
        "PERCENT",
        "DAILY",
        86_400,
    ),
)
SERIES_BY_EXTERNAL = {spec.external_code: spec for spec in FRED_MARKET_SERIES}


@dataclass(frozen=True, slots=True)
class PublicObservation:
    series_code: str
    observation_time: datetime
    value: Decimal
    unit: str
    available_at: datetime
    vintage: str
    source_record_key: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PublicCotPosition:
    category: str
    long_contracts: int
    short_contracts: int
    spreading_contracts: int | None
    percent_open_interest_long: Decimal | None
    percent_open_interest_short: Decimal | None
    traders_long: int | None
    traders_short: int | None


@dataclass(frozen=True, slots=True)
class PublicCotReport:
    source_record_key: str
    observation_date: date
    publication_at: datetime
    availability_quality: str
    market_name: str
    open_interest: int
    positions: tuple[PublicCotPosition, ...]
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PublicDataBundle:
    observations: tuple[PublicObservation, ...]
    cot_reports: tuple[PublicCotReport, ...]


class PublicDataProvider:
    """Official/public, read-only adapters with conservative availability clocks."""

    def __init__(self, *, timeout_seconds: float = 45.0) -> None:
        self._timeout = httpx.Timeout(timeout_seconds, connect=15.0)

    async def fetch(self, *, start: date, end: date) -> PublicDataBundle:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
        ) as client:
            fred_results, cot_results = await asyncio.gather(
                self._fetch_fred(client, start=start, end=end),
                self._fetch_cot(client, start=start, end=end),
            )
        return PublicDataBundle(
            observations=tuple(
                sorted(
                    fred_results,
                    key=lambda item: (item.series_code, item.observation_time),
                )
            ),
            cot_reports=tuple(sorted(cot_results, key=lambda item: item.observation_date)),
        )

    async def _fetch_fred(
        self, client: httpx.AsyncClient, *, start: date, end: date
    ) -> list[PublicObservation]:
        # FRED's public graph endpoint is intentionally low-volume. Serializing
        # this small multi-series batch avoids burst throttling while CFTC still
        # runs in parallel with the whole FRED leg.
        output: list[PublicObservation] = []
        for specification in FRED_MARKET_SERIES:
            output.extend(
                await self._fetch_fred_series(
                    client,
                    spec=specification,
                    start=start,
                    end=end,
                )
            )
        return output

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, ValueError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def _fetch_fred_series(
        self,
        client: httpx.AsyncClient,
        *,
        spec: SeriesSpec,
        start: date,
        end: date,
    ) -> list[PublicObservation]:
        response = await client.get(
            FRED_CSV_URL,
            params={
                "id": spec.external_code,
                "cosd": start.isoformat(),
                "coed": end.isoformat(),
            },
        )
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text))
        if reader.fieldnames != ["observation_date", spec.external_code]:
            raise ValueError(
                f"Unexpected FRED schema for {spec.external_code}: {reader.fieldnames}"
            )
        output: list[PublicObservation] = []
        for row in reader:
            raw_value = (row.get(spec.external_code) or "").strip()
            if not raw_value or raw_value == ".":
                continue
            observation_date = date.fromisoformat(str(row["observation_date"]))
            # The graph endpoint can ignore cosd/coed for a discontinued or
            # lagged series and return its complete archive. Enforce the
            # provider contract locally so an ingestion batch never claims a
            # narrower source range than the records it contains.
            if observation_date < start or observation_date > end:
                continue
            observed_at = datetime.combine(
                observation_date, time(16, 0), tzinfo=NEW_YORK
            ).astimezone(UTC)
            # These market-derived daily values are not used during their own
            # observation day. The conservative T+1 clock prevents a London
            # backtest from seeing the same day's closing value.
            available_at = datetime.combine(
                observation_date + timedelta(days=1),
                time(0, 0),
                tzinfo=NEW_YORK,
            ).astimezone(UTC)
            source_key = f"{spec.external_code}:{observation_date.isoformat()}"
            output.append(
                PublicObservation(
                    series_code=spec.internal_code,
                    observation_time=observed_at,
                    value=Decimal(raw_value),
                    unit=spec.unit,
                    available_at=available_at,
                    vintage="FRED_MARKET_CLOSE_T1_V1",
                    source_record_key=source_key,
                    payload={
                        "provider": "FRED_PUBLIC",
                        "external_series_code": spec.external_code,
                        "observation_date": observation_date.isoformat(),
                        "value": raw_value,
                        "availability_policy": "NEXT_CALENDAR_DAY_00_ET",
                        "retrieval_endpoint": FRED_CSV_URL,
                    },
                )
            )
        return output

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, ValueError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def _fetch_cot(
        self, client: httpx.AsyncClient, *, start: date, end: date
    ) -> list[PublicCotReport]:
        fields = (
            "id,market_and_exchange_names,report_date_as_yyyy_mm_dd,"
            "cftc_contract_market_code,open_interest_all,"
            "prod_merc_positions_long,prod_merc_positions_short,"
            "swap_positions_long_all,swap__positions_short_all,"
            "swap__positions_spread_all,m_money_positions_long_all,"
            "m_money_positions_short_all,m_money_positions_spread,"
            "other_rept_positions_long,other_rept_positions_short,"
            "other_rept_positions_spread,pct_of_oi_prod_merc_long,"
            "pct_of_oi_prod_merc_short,pct_of_oi_swap_long_all,"
            "pct_of_oi_swap_short_all,pct_of_oi_m_money_long_all,"
            "pct_of_oi_m_money_short_all,pct_of_oi_other_rept_long,"
            "pct_of_oi_other_rept_short,traders_prod_merc_long_all,"
            "traders_prod_merc_short_all,traders_swap_long_all,"
            "traders_swap_short_all,traders_m_money_long_all,"
            "traders_m_money_short_all,traders_other_rept_long_all,"
            "traders_other_rept_short"
        )
        where = (
            f"cftc_contract_market_code='{CFTC_GOLD_CONTRACT_CODE}' "
            f"AND report_date_as_yyyy_mm_dd between "
            f"'{start.isoformat()}T00:00:00' and '{end.isoformat()}T23:59:59'"
        )
        response = await client.get(
            CFTC_COT_URL,
            params={
                "$select": fields,
                "$where": where,
                "$order": "report_date_as_yyyy_mm_dd asc",
                "$limit": "5000",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("Unexpected CFTC response schema")
        return [self._parse_cot_row(row) for row in payload]

    def _parse_cot_row(self, row: dict[str, Any]) -> PublicCotReport:
        observed = datetime.fromisoformat(
            str(row["report_date_as_yyyy_mm_dd"]).replace("Z", "+00:00")
        ).date()
        publication_at, quality = cot_publication_at(observed)
        positions = (
            _cot_position(
                row,
                category="PRODUCER_MERCHANT",
                long_field="prod_merc_positions_long",
                short_field="prod_merc_positions_short",
                spread_field=None,
                pct_long_field="pct_of_oi_prod_merc_long",
                pct_short_field="pct_of_oi_prod_merc_short",
                traders_long_field="traders_prod_merc_long_all",
                traders_short_field="traders_prod_merc_short_all",
            ),
            _cot_position(
                row,
                category="SWAP_DEALER",
                long_field="swap_positions_long_all",
                short_field="swap__positions_short_all",
                spread_field="swap__positions_spread_all",
                pct_long_field="pct_of_oi_swap_long_all",
                pct_short_field="pct_of_oi_swap_short_all",
                traders_long_field="traders_swap_long_all",
                traders_short_field="traders_swap_short_all",
            ),
            _cot_position(
                row,
                category="MANAGED_MONEY",
                long_field="m_money_positions_long_all",
                short_field="m_money_positions_short_all",
                spread_field="m_money_positions_spread",
                pct_long_field="pct_of_oi_m_money_long_all",
                pct_short_field="pct_of_oi_m_money_short_all",
                traders_long_field="traders_m_money_long_all",
                traders_short_field="traders_m_money_short_all",
            ),
            _cot_position(
                row,
                category="OTHER_REPORTABLE",
                long_field="other_rept_positions_long",
                short_field="other_rept_positions_short",
                spread_field="other_rept_positions_spread",
                pct_long_field="pct_of_oi_other_rept_long",
                pct_short_field="pct_of_oi_other_rept_short",
                traders_long_field="traders_other_rept_long_all",
                traders_short_field="traders_other_rept_short",
            ),
        )
        return PublicCotReport(
            source_record_key=str(row["id"]),
            observation_date=observed,
            publication_at=publication_at,
            availability_quality=quality,
            market_name=str(row["market_and_exchange_names"]),
            open_interest=int(row["open_interest_all"]),
            positions=positions,
            payload={
                **row,
                "publication_at": publication_at.isoformat(),
                "availability_quality": quality,
            },
        )


def _cot_position(
    row: dict[str, Any],
    *,
    category: str,
    long_field: str,
    short_field: str,
    spread_field: str | None,
    pct_long_field: str,
    pct_short_field: str,
    traders_long_field: str,
    traders_short_field: str,
) -> PublicCotPosition:
    return PublicCotPosition(
        category=category,
        long_contracts=int(row[long_field]),
        short_contracts=int(row[short_field]),
        spreading_contracts=_optional_int(row, spread_field),
        percent_open_interest_long=_optional_decimal(row, pct_long_field),
        percent_open_interest_short=_optional_decimal(row, pct_short_field),
        traders_long=_optional_int(row, traders_long_field),
        traders_short=_optional_int(row, traders_short_field),
    )


def _optional_int(row: dict[str, Any], field: str | None) -> int | None:
    if field is None or row.get(field) in (None, ""):
        return None
    return int(row[field])


def _optional_decimal(row: dict[str, Any], field: str) -> Decimal | None:
    if row.get(field) in (None, ""):
        return None
    return Decimal(str(row[field]))


# Exact 2026 schedule published by the CFTC, including holiday-shifted dates.
_CFTC_2026_PUBLICATION_DATES = tuple(
    date(2026, month, day)
    for month, days in (
        (1, (5, 9, 16, 23, 30)),
        (2, (6, 13, 20, 27)),
        (3, (6, 13, 20, 27)),
        (4, (3, 10, 17, 24)),
        (5, (1, 8, 15, 22, 29)),
        (6, (5, 12, 22, 26)),
        (7, (6, 10, 17, 24, 31)),
        (8, (7, 14, 21, 28)),
        (9, (4, 11, 18, 25)),
        (10, (2, 9, 16, 23, 30)),
        (11, (6, 16, 20, 30)),
        (12, (4, 11, 18, 28)),
    )
    for day in days
)


def cot_publication_at(observation_date: date) -> tuple[datetime, str]:
    if observation_date.year == 2026:
        eligible = [
            item
            for item in _CFTC_2026_PUBLICATION_DATES
            if observation_date < item <= observation_date + timedelta(days=7)
        ]
        if not eligible:
            raise ValueError(f"No exact 2026 CFTC publication date for report {observation_date}")
        publication_date = min(eligible)
        quality = "EXACT_OFFICIAL_SCHEDULE"
    else:
        days_to_friday = (4 - observation_date.weekday()) % 7
        publication_date = observation_date + timedelta(
            days=days_to_friday if days_to_friday else 7
        )
        quality = "ESTIMATED_STANDARD_FRIDAY"
    publication_at = datetime.combine(publication_date, time(15, 30), tzinfo=NEW_YORK).astimezone(
        UTC
    )
    return publication_at, quality
