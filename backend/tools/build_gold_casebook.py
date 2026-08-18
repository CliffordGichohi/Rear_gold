from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import hashlib
import io
import json
import shutil
import tempfile
from collections import Counter, defaultdict, deque
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path, PureWindowsPath
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.analytics.casebook import (
    CASEBOOK_SCHEMA_VERSION,
    CASEBOOK_VERSION,
    HOLDOUT_START,
    CaseBar,
    KnownLevel,
    build_session_case_specs,
    canonical_hash,
    compact_structure_evidence,
    finalize_record,
    json_ready,
    level_interactions,
    summarize_window,
    validate_casebook_period,
)
from gold_intel.analytics.fundamentals import FUNDAMENTAL_RULESET_VERSION
from gold_intel.analytics.structure import (
    STRUCTURE_RULESET_VERSION,
    AggregateBar,
    TimeframeStructure,
    analyze_timeframe_structure,
)
from gold_intel.application.fundamentals import (
    FUNDAMENTAL_SERIES_CODES,
    FundamentalInputs,
    load_fundamental_inputs,
)
from gold_intel.application.market_structure import IC_MARKETS_MT5_CONFIG
from gold_intel.infrastructure.database import session_factory
from gold_intel.infrastructure.models import (
    CotPosition,
    CotReport,
    EconomicEvent,
    EconomicRelease,
    EconomicSurprise,
    ForecastSnapshot,
    Observation,
    PolicyExpectationWindow,
    PolicyPathPoint,
)

CASE_START = datetime(2021, 8, 1, tzinfo=UTC)
CASE_END = HOLDOUT_START
PRICE_PROVIDER = "IC_MARKETS_MT5"
PRICE_INSTRUMENT = "XAUUSD"
PRICE_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
TIMEFRAME_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}
STRUCTURE_LOOKBACK_BARS = {
    "1m": 720,
    "5m": 720,
    "15m": 720,
    "1h": 720,
    "4h": 720,
    "1d": 500,
}
CROSS_DB_INSTRUMENTS = ("XAUUSD", "EURUSD", "XAGUSD", "US500")
CME_SYMBOLS = ("ZT.v.0", "ZN.v.0", "ZQ.v.0", "SR3.v.0")
CROSS_CHANGE_HORIZONS = {
    "5_MINUTES": timedelta(minutes=5),
    "1_HOUR": timedelta(hours=1),
    "4_HOURS": timedelta(hours=4),
    "1_DAY": timedelta(days=1),
    "5_DAYS": timedelta(days=5),
}
EVENT_HORIZONS = {
    "REFERENCE": timedelta(0),
    "1_MINUTE": timedelta(minutes=1),
    "5_MINUTES": timedelta(minutes=5),
    "15_MINUTES": timedelta(minutes=15),
    "1_HOUR": timedelta(hours=1),
    "4_HOURS": timedelta(hours=4),
}
NEW_YORK = ZoneInfo("America/New_York")

RAW_PRICE_SQL = text(
    """
    SELECT
        id,
        open_time,
        close_time,
        open,
        high,
        low,
        close,
        volume,
        volume_type,
        spread_points,
        spread_price,
        available_at,
        ingested_at,
        batch_id,
        source_record_key
    FROM market.price_bars
    WHERE provider_code = :provider
      AND instrument_code = :instrument
      AND timeframe = '1m'
      AND is_complete
      AND NOT is_synthetic
      AND open_time >= :start
      AND open_time < :end
      AND close_time <= :end
      AND available_at <= close_time
      AND available_at < :end
    ORDER BY open_time, available_at
    """
)

SUPPORT_START_SQL = text(
    """
    SELECT min(open_time) AS support_start
    FROM market.price_bars
    WHERE provider_code = :provider
      AND instrument_code = :instrument
      AND timeframe = '1m'
      AND is_complete
      AND NOT is_synthetic
      AND open_time < :case_start
      AND available_at < :end
    """
)

CROSS_PRICE_SQL = text(
    """
    SELECT DISTINCT ON (open_time)
        open_time,
        close_time,
        close,
        volume,
        volume_type,
        spread_points,
        spread_price,
        available_at,
        batch_id,
        source_record_key
    FROM market.price_bars
    WHERE provider_code = :provider
      AND instrument_code = :instrument
      AND timeframe = '1m'
      AND is_complete
      AND NOT is_synthetic
      AND open_time >= :start
      AND open_time < :end
      AND available_at <= close_time
      AND available_at < :end
    ORDER BY open_time, available_at
    """
)


@dataclass(frozen=True, slots=True)
class BarFact:
    record: dict[str, Any]
    record_id: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    spread_price: float | None
    complete: bool
    source_count: int
    source_hash: str
    trading_date: date | None = None

    def structure_bar(self) -> AggregateBar:
        return AggregateBar(
            open_time=self.open_time,
            close_time=self.close_time,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            complete=self.complete,
            source_ids=(self.record_id,),
        )

    def case_bar(self) -> CaseBar:
        return CaseBar(
            open_time=self.open_time,
            close_time=self.close_time,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            spread=self.spread_price,
            source_count=self.source_count,
            source_hash=self.source_hash,
        )


@dataclass(frozen=True, slots=True)
class RawSample:
    observed_at: datetime
    available_at: datetime
    close: float
    source_record_key: str
    source_locator: dict[str, Any]
    instrument_id: str | None = None
    volume: float | None = None
    spread_price: float | None = None


@dataclass(frozen=True, slots=True)
class ArtifactSummary:
    name: str
    path: str
    sha256: str
    bytes: int
    record_count: int
    record_type_counts: dict[str, int]


class JsonlArtifactWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.temporary_path = path.with_suffix(path.suffix + ".tmp")
        self._raw: io.BufferedWriter | None = None
        self._gzip: gzip.GzipFile | None = None
        self._text: io.TextIOWrapper | None = None
        self.record_count = 0
        self.record_type_counts: Counter[str] = Counter()

    def __enter__(self) -> JsonlArtifactWriter:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._raw = self.temporary_path.open("wb")
        self._gzip = gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=1,
            fileobj=self._raw,
            mtime=0,
        )
        self._text = io.TextIOWrapper(self._gzip, encoding="utf-8", newline="\n")
        return self

    def write(self, record: Mapping[str, Any]) -> None:
        if self._text is None:
            raise RuntimeError("writer is not open")
        if "record_hash" not in record:
            raise ValueError("casebook records must be finalized before writing")
        payload = json.dumps(
            json_ready(record),
            sort_keys=True,
            separators=(",", ":"),
        )
        self._text.write(payload + "\n")
        self.record_count += 1
        self.record_type_counts[str(record["record_type"])] += 1

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._text is not None:
            self._text.close()
        self._text = None
        self._gzip = None
        self._raw = None
        if exc_type is not None:
            self.temporary_path.unlink(missing_ok=True)
            return
        self.temporary_path.replace(self.path)

    def summary(self, relative_to: Path) -> ArtifactSummary:
        return ArtifactSummary(
            name=self.path.name,
            path=self.path.relative_to(relative_to).as_posix(),
            sha256=_sha256(self.path),
            bytes=self.path.stat().st_size,
            record_count=self.record_count,
            record_type_counts=dict(sorted(self.record_type_counts.items())),
        )


async def main() -> None:
    args = _parser().parse_args()
    start = _parse_boundary(args.start)
    end = _parse_boundary(args.end)
    validate_casebook_period(start, end)
    output_dir = Path(args.output_dir)
    schema_path = Path(args.schema)
    cme_normalization = Path(args.cme_normalization)
    coverage_path = Path(args.coverage)
    if output_dir.exists():
        raise FileExistsError(
            f"{output_dir} already exists; immutable casebook bundles are never overwritten"
        )
    if not schema_path.is_file():
        raise FileNotFoundError(schema_path)
    if not cme_normalization.is_file():
        raise FileNotFoundError(cme_normalization)
    if not coverage_path.is_file():
        raise FileNotFoundError(coverage_path)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f"{output_dir.name}.building-"))
    try:
        result = await _build_bundle(
            start=start,
            end=end,
            staging_dir=staging_dir,
            schema_path=schema_path,
            cme_normalization=cme_normalization,
            coverage_path=coverage_path,
        )
        shutil.copytree(staging_dir, output_dir)
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    shutil.rmtree(staging_dir, ignore_errors=True)

    result["output_dir"] = str(output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


async def _build_bundle(
    *,
    start: datetime,
    end: datetime,
    staging_dir: Path,
    schema_path: Path,
    cme_normalization: Path,
    coverage_path: Path,
) -> dict[str, Any]:
    async with session_factory() as session:
        support_start = await _support_start(session, start=start, end=end)
        initial_five_minute = [
            fact.case_bar()
            async for fact in _iter_aggregate_bars(
                session,
                timeframe="5m",
                start=support_start,
                end=end,
            )
            if fact.complete and fact.open_time >= start
        ]
        initial_specs = build_session_case_specs(
            initial_five_minute,
            start=start,
            end=end,
        )
        source_data = await _load_source_data(
            session,
            support_start=support_start,
            end=end,
        )

    if not initial_specs:
        raise ValueError("No complete London or New York case was found")
    _progress(
        "SOURCE_INDEX_READY",
        session_cases=len(initial_specs),
        support_start=support_start.isoformat(),
    )
    structure_times = sorted(
        {
            timestamp
            for spec in initial_specs
            for timestamp in (spec.decision_at, spec.observation_end)
        }
    )
    cross_times = _cross_snapshot_times(
        initial_specs,
        source_data["events"],
        source_data["cot_reports"],
        end=end,
    )

    artifacts: list[ArtifactSummary] = []
    price_path = staging_dir / "price_bars.jsonl.gz"
    with JsonlArtifactWriter(price_path) as price_writer:
        (
            five_minute_facts,
            daily_facts,
            structure_parts,
        ) = await _export_price_and_calculate_structure(
            price_writer,
            start=support_start,
            end=end,
            structure_times=structure_times,
        )
    artifacts.append(price_writer.summary(staging_dir))
    _progress(
        "PRICE_AND_STRUCTURE_INPUTS_READY",
        price_records=price_writer.record_count,
        structure_clocks=len(structure_times),
    )

    actual_specs = build_session_case_specs(
        [
            fact.case_bar()
            for fact in five_minute_facts
            if fact.complete and fact.open_time >= start
        ],
        start=start,
        end=end,
    )
    _assert_specs_unchanged(initial_specs, actual_specs)

    structure_path = staging_dir / "structure_snapshots.jsonl.gz"
    structure_ids = _write_structure_records(
        structure_path,
        structure_times=structure_times,
        structure_parts=structure_parts,
    )
    artifacts.append(_writer_summary(structure_path, staging_dir))
    _progress("STRUCTURE_RECORDS_READY", records=len(structure_ids))

    db_samples: dict[str, dict[datetime, RawSample | None]] = {}
    async with session_factory() as session:
        for instrument in CROSS_DB_INSTRUMENTS:
            db_samples[instrument] = await _sample_database_instrument(
                session,
                instrument=instrument,
                request_times=cross_times,
                start=support_start,
                end=end,
            )
            _progress("BROKER_CROSS_MARKET_READY", instrument=instrument)
    cme_samples = _sample_cme_instruments(
        cme_normalization,
        request_times=cross_times,
        end=end,
    )
    _progress("CME_CROSS_MARKET_READY", symbols=len(cme_samples))
    cross_path = staging_dir / "cross_market_snapshots.jsonl.gz"
    cross_ids, cross_records = _write_cross_market_records(
        cross_path,
        request_times=cross_times,
        db_samples=db_samples,
        cme_samples=cme_samples,
    )
    artifacts.append(_writer_summary(cross_path, staging_dir))
    _progress("CROSS_MARKET_RECORDS_READY", records=len(cross_ids))

    positioning_path = staging_dir / "positioning.jsonl.gz"
    positioning_ids, positioning_records = _write_positioning_records(
        positioning_path,
        reports=source_data["cot_reports"],
        positions=source_data["cot_positions"],
        cross_records=cross_records,
        cross_ids=cross_ids,
    )
    artifacts.append(_writer_summary(positioning_path, staging_dir))
    _progress("POSITIONING_RECORDS_READY", records=len(positioning_records))

    events_path = staging_dir / "events.jsonl.gz"
    event_ids = _write_event_records(
        events_path,
        events=source_data["events"],
        releases=source_data["releases"],
        forecasts=source_data["forecasts"],
        surprises=source_data["surprises"],
        cross_records=cross_records,
        cross_ids=cross_ids,
        end=end,
    )
    artifacts.append(_writer_summary(events_path, staging_dir))
    _progress("EVENT_RECORDS_READY", records=len(event_ids))

    fundamentals_path = staging_dir / "fundamentals.jsonl.gz"
    fundamental_ids = _write_fundamental_records(
        fundamentals_path,
        decision_times=sorted({spec.decision_at for spec in actual_specs}),
        observations=source_data["observations"],
        policy_path_points=source_data["policy_path_points"],
        policy_expectations=source_data["policy_expectations"],
        inputs=source_data["fundamental_inputs"],
        positioning_ids=positioning_ids,
    )
    artifacts.append(_writer_summary(fundamentals_path, staging_dir))
    _progress("FUNDAMENTAL_RECORDS_READY", snapshots=len(fundamental_ids))

    sessions_path = staging_dir / "sessions.jsonl.gz"
    session_counts = _write_session_records(
        sessions_path,
        specs=actual_specs,
        five_minute_facts=five_minute_facts,
        daily_facts=daily_facts,
        structure_ids=structure_ids,
        cross_ids=cross_ids,
        fundamental_ids=fundamental_ids,
        positioning_ids=positioning_ids,
    )
    artifacts.append(_writer_summary(sessions_path, staging_dir))
    _progress("SESSION_RECORDS_READY", **session_counts)

    _progress("INTEGRITY_VERIFICATION_STARTED", artifacts=len(artifacts))
    validation = _verify_artifacts(staging_dir, artifacts, end=end)
    _progress(
        "INTEGRITY_VERIFICATION_PASSED",
        records=validation["record_hashes_verified"],
    )
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    normalization = json.loads(cme_normalization.read_text(encoding="utf-8"))
    manifest = {
        "contract": {
            "governing_document": "GOLD_CASEBOOK_RESEARCH_CONTRACT.md",
            "milestone": "2_IMMUTABLE_CASEBOOK",
            "case_start": start,
            "case_end_exclusive": end,
            "price_support_start": support_start,
            "locked_holdout": "calendar year 2025",
            "holdout_loaded": False,
            "execution_optimized": False,
            "profitability_calculated": False,
            "directional_outcome_calculated": False,
        },
        "casebook_version": CASEBOOK_VERSION,
        "schema_version": CASEBOOK_SCHEMA_VERSION,
        "schema": {
            "path": schema_path.as_posix(),
            "sha256": _sha256(schema_path),
        },
        "rulesets": {
            "market_structure": STRUCTURE_RULESET_VERSION,
            "fundamentals": FUNDAMENTAL_RULESET_VERSION,
        },
        "session_definition": {
            "asia": "10:05-16:00 Asia/Tokyo",
            "london": "08:00-12:00 Europe/London",
            "new_york": "08:00-12:00 America/New_York",
            "decision_clock": "session open",
            "observation_clock": "session close",
            "dst_policy": "IANA timezone database",
        },
        "record_counts": {
            **session_counts,
            "structure_snapshots": len(structure_ids),
            "fundamental_snapshots": len(fundamental_ids),
            "cross_market_snapshots": len(cross_ids),
            "positioning_reports": len(positioning_records),
            "event_cases": len(event_ids),
        },
        "artifacts": [asdict(item) for item in artifacts],
        "source_manifests": {
            "coverage": {
                "path": coverage_path.as_posix(),
                "declared_data_hash": coverage["data_hash"],
                "sha256": _sha256(coverage_path),
            },
            "cme_normalization": {
                "path": cme_normalization.as_posix(),
                "sha256": _sha256(cme_normalization),
                "declared_rows": normalization["total_rows"],
                "locked_holdout": normalization["locked_holdout"],
            },
        },
        "integrity": validation,
        "known_limits": [
            {
                "code": "NO_VERIFIED_HISTORICAL_PRE_EVENT_CALENDAR",
                "effect": (
                    "Historical event schedule and consensus are not used before "
                    "the release boundary."
                ),
            },
            {
                "code": "US500_INTRADAY_ENDS_2022_01_14",
                "effect": "Later US500 snapshots are marked STALE, never neutral.",
            },
            {
                "code": "CME_CONTINUOUS_FUTURES_ROLLS",
                "effect": (
                    "ZT/ZN/ZQ/SR3 changes crossing instrument_id rolls are UNKNOWN."
                ),
            },
            {
                "code": "NO_INTRADAY_COMEX_GOLD_OPEN_INTEREST",
                "effect": "Weekly CFTC open interest is retained; intraday OI is UNKNOWN.",
            },
            {
                "code": "NO_LICENSED_UNSCHEDULED_EVENT_HISTORY",
                "effect": "Unscheduled-event context remains UNKNOWN.",
            },
        ],
        "next_milestone": {
            "code": "3_CONSTANT_EXECUTION_BASELINE",
            "started": False,
        },
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    manifest_path = staging_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(json_ready(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "casebook_version": CASEBOOK_VERSION,
        "manifest_hash": manifest["manifest_hash"],
        "session_counts": session_counts,
        "holdout_loaded": False,
        "profitability_calculated": False,
    }


async def _support_start(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
) -> datetime:
    row = (
        await session.execute(
            SUPPORT_START_SQL,
            {
                "provider": PRICE_PROVIDER,
                "instrument": PRICE_INSTRUMENT,
                "case_start": start,
                "end": end,
            },
        )
    ).mappings().one()
    support_start = row["support_start"]
    if support_start is None:
        return start
    return min(start, support_start.astimezone(UTC))


async def _load_source_data(
    session: AsyncSession,
    *,
    support_start: datetime,
    end: datetime,
) -> dict[str, Any]:
    observations = list(
        (
            await session.scalars(
                select(Observation)
                .where(
                    Observation.series_code.in_(FUNDAMENTAL_SERIES_CODES),
                    Observation.available_at < end,
                    Observation.observation_time < end,
                    Observation.is_synthetic.is_(False),
                )
                .order_by(
                    Observation.series_code,
                    Observation.observation_time,
                    Observation.available_at,
                )
            )
        ).all()
    )
    policy_path_points = list(
        (
            await session.scalars(
                select(PolicyPathPoint)
                .where(
                    PolicyPathPoint.available_at < end,
                    PolicyPathPoint.snapshot_as_of < end,
                    PolicyPathPoint.is_synthetic.is_(False),
                )
                .order_by(
                    PolicyPathPoint.available_at,
                    PolicyPathPoint.meeting_date,
                    PolicyPathPoint.outcome_basis_points,
                )
            )
        ).all()
    )
    policy_expectations = list(
        (
            await session.scalars(
                select(PolicyExpectationWindow)
                .where(
                    PolicyExpectationWindow.available_at < end,
                    PolicyExpectationWindow.snapshot_as_of < end,
                    PolicyExpectationWindow.is_synthetic.is_(False),
                )
                .order_by(
                    PolicyExpectationWindow.available_at,
                    PolicyExpectationWindow.reference_start,
                )
            )
        ).all()
    )
    cot_reports = list(
        (
            await session.scalars(
                select(CotReport)
                .where(CotReport.publication_at < end)
                .order_by(CotReport.publication_at, CotReport.observation_date)
            )
        ).all()
    )
    report_ids = [report.id for report in cot_reports]
    cot_positions = (
        list(
            (
                await session.scalars(
                    select(CotPosition)
                    .where(CotPosition.report_id.in_(report_ids))
                    .order_by(CotPosition.report_id, CotPosition.category)
                )
            ).all()
        )
        if report_ids
        else []
    )
    events = list(
        (
            await session.scalars(
                select(EconomicEvent)
                .where(
                    EconomicEvent.scheduled_at >= support_start,
                    EconomicEvent.scheduled_at < end,
                    EconomicEvent.available_at < end,
                    EconomicEvent.is_synthetic.is_(False),
                )
                .order_by(
                    EconomicEvent.scheduled_at,
                    EconomicEvent.available_at,
                    EconomicEvent.event_code,
                )
            )
        ).all()
    )
    event_ids = [event.id for event in events]
    releases = (
        list(
            (
                await session.scalars(
                    select(EconomicRelease)
                    .where(
                        EconomicRelease.event_id.in_(event_ids),
                        EconomicRelease.available_at < end,
                        EconomicRelease.is_synthetic.is_(False),
                    )
                    .order_by(
                        EconomicRelease.released_at,
                        EconomicRelease.component_code,
                        EconomicRelease.available_at,
                    )
                )
            ).all()
        )
        if event_ids
        else []
    )
    forecasts = list(
        (
            await session.scalars(
                select(ForecastSnapshot)
                .where(
                    ForecastSnapshot.scheduled_at >= support_start,
                    ForecastSnapshot.scheduled_at < end,
                    ForecastSnapshot.available_at < end,
                    ForecastSnapshot.is_synthetic.is_(False),
                )
                .order_by(
                    ForecastSnapshot.scheduled_at,
                    ForecastSnapshot.component_code,
                    ForecastSnapshot.available_at,
                )
            )
        ).all()
    )
    surprises = (
        list(
            (
                await session.scalars(
                    select(EconomicSurprise)
                    .where(
                        EconomicSurprise.event_id.in_(event_ids),
                        EconomicSurprise.available_at < end,
                        EconomicSurprise.is_synthetic.is_(False),
                    )
                    .order_by(
                        EconomicSurprise.released_at,
                        EconomicSurprise.component_code,
                        EconomicSurprise.history_count,
                    )
                )
            ).all()
        )
        if event_ids
        else []
    )
    fundamental_inputs = await load_fundamental_inputs(
        session,
        as_of=end - timedelta(microseconds=1),
    )
    return {
        "observations": observations,
        "policy_path_points": policy_path_points,
        "policy_expectations": policy_expectations,
        "cot_reports": cot_reports,
        "cot_positions": cot_positions,
        "events": events,
        "releases": releases,
        "forecasts": forecasts,
        "surprises": surprises,
        "fundamental_inputs": fundamental_inputs,
    }


async def _export_price_and_calculate_structure(
    writer: JsonlArtifactWriter,
    *,
    start: datetime,
    end: datetime,
    structure_times: Sequence[datetime],
) -> tuple[list[BarFact], list[BarFact], dict[datetime, dict[str, Any]]]:
    five_minute: list[BarFact] = []
    daily: list[BarFact] = []
    parts: dict[datetime, dict[str, Any]] = defaultdict(dict)
    async with session_factory() as session:
        for timeframe in PRICE_TIMEFRAMES:
            history: deque[AggregateBar] = deque(
                maxlen=STRUCTURE_LOOKBACK_BARS[timeframe]
            )
            index = 0
            iterator = (
                _iter_raw_bars(session, start=start, end=end)
                if timeframe == "1m"
                else _iter_daily_bars(session, start=start, end=end)
                if timeframe == "1d"
                else _iter_aggregate_bars(
                    session,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                )
            )
            async for fact in iterator:
                while (
                    index < len(structure_times)
                    and structure_times[index] < fact.close_time
                ):
                    snapshot_at = structure_times[index]
                    parts[snapshot_at][timeframe] = _structure_part(
                        history,
                        timeframe=timeframe,
                        as_of=snapshot_at,
                    )
                    index += 1
                writer.write(fact.record)
                if fact.complete:
                    history.append(fact.structure_bar())
                if timeframe == "5m":
                    five_minute.append(fact)
                elif timeframe == "1d":
                    daily.append(fact)
                while (
                    index < len(structure_times)
                    and structure_times[index] == fact.close_time
                ):
                    snapshot_at = structure_times[index]
                    parts[snapshot_at][timeframe] = _structure_part(
                        history,
                        timeframe=timeframe,
                        as_of=snapshot_at,
                    )
                    index += 1
            while index < len(structure_times):
                snapshot_at = structure_times[index]
                parts[snapshot_at][timeframe] = _structure_part(
                    history,
                    timeframe=timeframe,
                    as_of=snapshot_at,
                )
                index += 1
    return five_minute, daily, parts


async def _iter_raw_bars(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
) -> AsyncIterator[BarFact]:
    result = await session.stream(
        RAW_PRICE_SQL,
        {
            "provider": PRICE_PROVIDER,
            "instrument": PRICE_INSTRUMENT,
            "start": start,
            "end": end,
        },
    )
    async for row in result.mappings():
        open_time = row["open_time"].astimezone(UTC)
        close_time = row["close_time"].astimezone(UTC)
        source_hash = canonical_hash(
            {
                "provider_code": PRICE_PROVIDER,
                "instrument_code": PRICE_INSTRUMENT,
                "id": row["id"],
                "batch_id": row["batch_id"],
                "source_record_key": row["source_record_key"],
                "open_time": open_time,
                "available_at": row["available_at"],
                "ohlc": [row["open"], row["high"], row["low"], row["close"]],
            }
        )
        record_id = f"BAR-XAUUSD-1m-{open_time:%Y%m%dT%H%M%SZ}-{str(row['id'])[:12]}"
        base = _record_base(
            record_type="PRICE_BAR",
            record_id=record_id,
            epistemic_status="OBSERVED",
        )
        record = finalize_record(
            {
                **base,
                "instrument_code": PRICE_INSTRUMENT,
                "provider_code": PRICE_PROVIDER,
                "timeframe": "1m",
                "open_time": open_time,
                "close_time": close_time,
                "ohlc": {
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                },
                "volume": row["volume"],
                "volume_type": row["volume_type"],
                "spread_points": row["spread_points"],
                "spread_price": row["spread_price"],
                "available_at": row["available_at"],
                "ingested_at": row["ingested_at"],
                "complete": True,
                "missing_source_minutes": 0,
                "source": {
                    "batch_id": row["batch_id"],
                    "source_record_key": row["source_record_key"],
                    "source_count": 1,
                    "source_hash": source_hash,
                },
                "calculation_version": "OBSERVED_SOURCE_ROW",
            }
        )
        yield BarFact(
            record=record,
            record_id=record_id,
            timeframe="1m",
            open_time=open_time,
            close_time=close_time,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]) if row["volume"] is not None else None,
            spread_price=(
                float(row["spread_price"])
                if row["spread_price"] is not None
                else None
            ),
            complete=True,
            source_count=1,
            source_hash=source_hash,
        )


async def _iter_aggregate_bars(
    session: AsyncSession,
    *,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> AsyncIterator[BarFact]:
    minutes = TIMEFRAME_MINUTES[timeframe]
    query = text(
        f"""
        WITH canonical AS (
            SELECT DISTINCT ON (open_time)
                id,
                open_time,
                close_time,
                open,
                high,
                low,
                close,
                volume,
                volume_type,
                spread_points,
                spread_price,
                available_at,
                ingested_at,
                batch_id,
                source_record_key
            FROM market.price_bars
            WHERE provider_code = :provider
              AND instrument_code = :instrument
              AND timeframe = '1m'
              AND is_complete
              AND NOT is_synthetic
              AND open_time >= :start
              AND open_time < :end
              AND close_time <= :end
              AND available_at <= close_time
              AND available_at < :end
            ORDER BY open_time, available_at
        )
        SELECT
            time_bucket(INTERVAL '{minutes} minutes', open_time) AS bucket,
            first(open, open_time) AS open,
            max(high) AS high,
            min(low) AS low,
            last(close, open_time) AS close,
            CASE WHEN count(volume) = count(*) THEN sum(volume) END AS volume,
            min(volume_type) AS volume_type,
            avg(spread_points) AS average_spread_points,
            max(spread_points) AS maximum_spread_points,
            avg(spread_price) AS average_spread_price,
            max(spread_price) AS maximum_spread_price,
            max(available_at) AS available_at,
            max(ingested_at) AS ingested_at,
            count(*) AS source_count,
            min(open_time) AS first_source_open,
            max(open_time) AS last_source_open,
            first(source_record_key, open_time) AS first_source_key,
            last(source_record_key, open_time) AS last_source_key,
            count(DISTINCT batch_id) AS source_batch_count,
            first(batch_id, open_time) AS first_batch_id,
            last(batch_id, open_time) AS last_batch_id
        FROM canonical
        GROUP BY 1
        ORDER BY 1
        """
    )
    result = await session.stream(
        query,
        {
            "provider": PRICE_PROVIDER,
            "instrument": PRICE_INSTRUMENT,
            "start": start,
            "end": end,
        },
    )
    async for row in result.mappings():
        bucket = row["bucket"].astimezone(UTC)
        close_time = bucket + timedelta(minutes=minutes)
        source_count = int(row["source_count"])
        expected_last = bucket + timedelta(minutes=minutes - 1)
        complete = (
            source_count == minutes
            and row["first_source_open"].astimezone(UTC) == bucket
            and row["last_source_open"].astimezone(UTC) == expected_last
            and row["available_at"] <= close_time
        )
        lineage = {
            "provider_code": PRICE_PROVIDER,
            "instrument_code": PRICE_INSTRUMENT,
            "source_timeframe": "1m",
            "target_timeframe": timeframe,
            "bucket": bucket,
            "source_count": source_count,
            "first_source_open": row["first_source_open"],
            "last_source_open": row["last_source_open"],
            "first_source_key": row["first_source_key"],
            "last_source_key": row["last_source_key"],
            "source_batch_count": row["source_batch_count"],
            "first_batch_id": row["first_batch_id"],
            "last_batch_id": row["last_batch_id"],
            "ohlc": [row["open"], row["high"], row["low"], row["close"]],
        }
        source_hash = canonical_hash(lineage)
        record_id = f"BAR-XAUUSD-{timeframe}-{bucket:%Y%m%dT%H%M%SZ}"
        record = finalize_record(
            {
                **_record_base(
                    record_type="PRICE_BAR",
                    record_id=record_id,
                    epistemic_status="CALCULATED",
                ),
                "instrument_code": PRICE_INSTRUMENT,
                "provider_code": PRICE_PROVIDER,
                "timeframe": timeframe,
                "open_time": bucket,
                "close_time": close_time,
                "ohlc": {
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                },
                "volume": row["volume"],
                "volume_type": row["volume_type"],
                "spread_points": {
                    "average": row["average_spread_points"],
                    "maximum": row["maximum_spread_points"],
                },
                "spread_price": {
                    "average": row["average_spread_price"],
                    "maximum": row["maximum_spread_price"],
                },
                "available_at": row["available_at"],
                "ingested_at": row["ingested_at"],
                "complete": complete,
                "missing_source_minutes": max(0, minutes - source_count),
                "source": {**lineage, "source_hash": source_hash},
                "calculation_version": "UTC_FIXED_BUCKET_V1",
            }
        )
        yield BarFact(
            record=record,
            record_id=record_id,
            timeframe=timeframe,
            open_time=bucket,
            close_time=close_time,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]) if row["volume"] is not None else None,
            spread_price=(
                float(row["average_spread_price"])
                if row["average_spread_price"] is not None
                else None
            ),
            complete=complete,
            source_count=source_count,
            source_hash=source_hash,
        )


async def _iter_daily_bars(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
) -> AsyncIterator[BarFact]:
    query = text(
        """
        WITH canonical AS (
            SELECT DISTINCT ON (open_time)
                open_time,
                close_time,
                open,
                high,
                low,
                close,
                volume,
                volume_type,
                spread_points,
                spread_price,
                available_at,
                ingested_at,
                batch_id,
                source_record_key,
                open_time AT TIME ZONE 'America/New_York' AS local_open
            FROM market.price_bars
            WHERE provider_code = :provider
              AND instrument_code = :instrument
              AND timeframe = '1m'
              AND is_complete
              AND NOT is_synthetic
              AND open_time >= :start
              AND open_time < :end
              AND close_time <= :end
              AND available_at <= close_time
              AND available_at < :end
            ORDER BY open_time, available_at
        ),
        assigned AS (
            SELECT
                *,
                CASE
                    WHEN local_open::time >= TIME '18:00'
                    THEN local_open::date + 1
                    ELSE local_open::date
                END AS trading_date
            FROM canonical
            WHERE NOT (
                local_open::time >= TIME '17:00'
                AND local_open::time < TIME '18:00'
            )
              AND NOT (
                local_open::time >= TIME '19:59'
                AND local_open::time < TIME '21:00'
            )
        )
        SELECT
            trading_date,
            first(open, open_time) AS open,
            max(high) AS high,
            min(low) AS low,
            last(close, open_time) AS close,
            CASE WHEN count(volume) = count(*) THEN sum(volume) END AS volume,
            min(volume_type) AS volume_type,
            avg(spread_points) AS average_spread_points,
            max(spread_points) AS maximum_spread_points,
            avg(spread_price) AS average_spread_price,
            max(spread_price) AS maximum_spread_price,
            max(available_at) AS available_at,
            max(ingested_at) AS ingested_at,
            count(*) AS source_count,
            min(open_time) AS first_source_open,
            max(open_time) AS last_source_open,
            first(source_record_key, open_time) AS first_source_key,
            last(source_record_key, open_time) AS last_source_key,
            count(DISTINCT batch_id) AS source_batch_count,
            first(batch_id, open_time) AS first_batch_id,
            last(batch_id, open_time) AS last_batch_id
        FROM assigned
        WHERE EXTRACT(ISODOW FROM trading_date) BETWEEN 1 AND 5
        GROUP BY trading_date
        ORDER BY trading_date
        """
    )
    result = await session.stream(
        query,
        {
            "provider": PRICE_PROVIDER,
            "instrument": PRICE_INSTRUMENT,
            "start": start,
            "end": end,
        },
    )
    async for row in result.mappings():
        trading_date = row["trading_date"]
        open_time, close_time, expected_count = _daily_boundaries(trading_date)
        if close_time > end:
            continue
        source_count = int(row["source_count"])
        complete = (
            source_count == expected_count
            and row["first_source_open"].astimezone(UTC) == open_time
            and row["last_source_open"].astimezone(UTC)
            == close_time - timedelta(minutes=1)
            and row["available_at"] <= close_time
        )
        lineage = {
            "provider_code": PRICE_PROVIDER,
            "instrument_code": PRICE_INSTRUMENT,
            "source_timeframe": "1m",
            "target_timeframe": "1d",
            "trading_date": trading_date,
            "source_count": source_count,
            "expected_source_count": expected_count,
            "first_source_open": row["first_source_open"],
            "last_source_open": row["last_source_open"],
            "first_source_key": row["first_source_key"],
            "last_source_key": row["last_source_key"],
            "source_batch_count": row["source_batch_count"],
            "first_batch_id": row["first_batch_id"],
            "last_batch_id": row["last_batch_id"],
            "ohlc": [row["open"], row["high"], row["low"], row["close"]],
        }
        source_hash = canonical_hash(lineage)
        record_id = f"BAR-XAUUSD-1d-{trading_date.isoformat()}"
        record = finalize_record(
            {
                **_record_base(
                    record_type="PRICE_BAR",
                    record_id=record_id,
                    epistemic_status="CALCULATED",
                ),
                "instrument_code": PRICE_INSTRUMENT,
                "provider_code": PRICE_PROVIDER,
                "timeframe": "1d",
                "trading_date": trading_date,
                "open_time": open_time,
                "close_time": close_time,
                "ohlc": {
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                },
                "volume": row["volume"],
                "volume_type": row["volume_type"],
                "spread_points": {
                    "average": row["average_spread_points"],
                    "maximum": row["maximum_spread_points"],
                },
                "spread_price": {
                    "average": row["average_spread_price"],
                    "maximum": row["maximum_spread_price"],
                },
                "available_at": row["available_at"],
                "ingested_at": row["ingested_at"],
                "complete": complete,
                "missing_source_minutes": max(0, expected_count - source_count),
                "source": {**lineage, "source_hash": source_hash},
                "calculation_version": "IC_MARKETS_NEW_YORK_TRADING_DAY_V1",
            }
        )
        yield BarFact(
            record=record,
            record_id=record_id,
            timeframe="1d",
            open_time=open_time,
            close_time=close_time,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]) if row["volume"] is not None else None,
            spread_price=(
                float(row["average_spread_price"])
                if row["average_spread_price"] is not None
                else None
            ),
            complete=complete,
            source_count=source_count,
            source_hash=source_hash,
            trading_date=trading_date,
        )


def _structure_part(
    history: Iterable[AggregateBar],
    *,
    timeframe: str,
    as_of: datetime,
) -> dict[str, Any]:
    state = analyze_timeframe_structure(
        list(history),
        timeframe=timeframe,
        as_of=as_of,
        config=IC_MARKETS_MT5_CONFIG,
    )
    return compact_structure_evidence(_timeframe_structure_dict(state))


def _timeframe_structure_dict(value: TimeframeStructure) -> dict[str, Any]:
    raw = asdict(value)
    raw["detections"] = [asdict(item) for item in value.detections]
    return raw


def _write_structure_records(
    path: Path,
    *,
    structure_times: Sequence[datetime],
    structure_parts: Mapping[datetime, Mapping[str, Any]],
) -> dict[datetime, str]:
    ids: dict[datetime, str] = {}
    with JsonlArtifactWriter(path) as writer:
        for as_of in structure_times:
            missing = [
                timeframe
                for timeframe in PRICE_TIMEFRAMES
                if timeframe not in structure_parts[as_of]
            ]
            if missing:
                raise ValueError(
                    f"Missing structure timeframes at {as_of.isoformat()}: {missing}"
                )
            record_id = f"STRUCTURE-{as_of:%Y%m%dT%H%M%SZ}"
            record = finalize_record(
                {
                    **_record_base(
                        record_type="STRUCTURE_SNAPSHOT",
                        record_id=record_id,
                        epistemic_status="CALCULATED",
                    ),
                    "instrument_code": PRICE_INSTRUMENT,
                    "provider_code": PRICE_PROVIDER,
                    "as_of": as_of,
                    "available_at": as_of,
                    "ruleset_version": STRUCTURE_RULESET_VERSION,
                    "configuration": asdict(IC_MARKETS_MT5_CONFIG),
                    "lookback_bar_limits": STRUCTURE_LOOKBACK_BARS,
                    "timeframes": [
                        structure_parts[as_of][timeframe]
                        for timeframe in PRICE_TIMEFRAMES
                    ],
                    "point_in_time_assertion": (
                        "Every included bar closed and was available by as_of; pivot "
                        "timestamp and later detected_at remain separate."
                    ),
                }
            )
            writer.write(record)
            ids[as_of] = record_id
    return ids


def _cross_snapshot_times(
    specs: Sequence[Any],
    events: Sequence[EconomicEvent],
    reports: Sequence[CotReport],
    *,
    end: datetime,
) -> list[datetime]:
    output = {spec.decision_at for spec in specs}
    for event in events:
        released_at = event.released_at or event.scheduled_at
        for delta in EVENT_HORIZONS.values():
            timestamp = released_at + delta
            if timestamp < end:
                output.add(timestamp)
        daily_close = _event_daily_close(released_at)
        if daily_close < end:
            output.add(daily_close)
    output.update(
        report.publication_at
        for report in reports
        if report.publication_at < end
    )
    return sorted(output)


async def _sample_database_instrument(
    session: AsyncSession,
    *,
    instrument: str,
    request_times: Sequence[datetime],
    start: datetime,
    end: datetime,
) -> dict[datetime, RawSample | None]:
    lookup_times = _lookup_times(request_times)
    result = await session.stream(
        CROSS_PRICE_SQL,
        {
            "provider": PRICE_PROVIDER,
            "instrument": instrument,
            "start": start - timedelta(days=7),
            "end": end,
        },
    )
    iterator = result.mappings().__aiter__()
    row = await anext(iterator, None)
    latest: RawSample | None = None
    lookup: dict[datetime, RawSample | None] = {}
    for requested_at in lookup_times:
        while (
            row is not None
            and row["close_time"].astimezone(UTC) <= requested_at
            and row["available_at"].astimezone(UTC) <= requested_at
        ):
            latest = RawSample(
                observed_at=row["close_time"].astimezone(UTC),
                available_at=row["available_at"].astimezone(UTC),
                close=float(row["close"]),
                volume=(
                    float(row["volume"]) if row["volume"] is not None else None
                ),
                spread_price=(
                    float(row["spread_price"])
                    if row["spread_price"] is not None
                    else None
                ),
                source_record_key=str(row["source_record_key"]),
                source_locator={
                    "provider_code": PRICE_PROVIDER,
                    "batch_id": str(row["batch_id"]),
                    "volume_type": row["volume_type"],
                    "spread_points": row["spread_points"],
                },
            )
            row = await anext(iterator, None)
        lookup[requested_at] = latest
    return _compose_samples(
        instrument=instrument,
        request_times=request_times,
        lookup=lookup,
        source_type="BROKER_PRICE",
    )


def _sample_cme_instruments(
    normalization_path: Path,
    *,
    request_times: Sequence[datetime],
    end: datetime,
) -> dict[str, dict[datetime, RawSample | None]]:
    manifest = json.loads(normalization_path.read_text(encoding="utf-8"))
    if manifest.get("locked_holdout") != "2025 not loaded":
        raise ValueError("CME normalization manifest does not preserve the holdout lock")
    lookup_times = _lookup_times(request_times)
    indices = {symbol: 0 for symbol in CME_SYMBOLS}
    latest: dict[str, RawSample | None] = {symbol: None for symbol in CME_SYMBOLS}
    lookup: dict[str, dict[datetime, RawSample | None]] = {
        symbol: {} for symbol in CME_SYMBOLS
    }
    last_open: dict[str, datetime] = {}
    for file_entry in manifest["files"]:
        path = normalization_path.parent / PureWindowsPath(
            file_entry["normalized"]
        ).name
        actual_hash = _sha256(path)
        if actual_hash != file_entry["normalized_sha256"]:
            raise ValueError(f"CME normalized hash mismatch: {path.name}")
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                symbol = row["symbol"]
                if symbol not in lookup:
                    continue
                open_time = datetime.fromisoformat(row["open_time"]).astimezone(UTC)
                available_at = datetime.fromisoformat(row["available_at"]).astimezone(
                    UTC
                )
                if open_time >= end or available_at >= end:
                    raise ValueError(
                        f"CME row crosses holdout boundary: {open_time.isoformat()}"
                    )
                if symbol in last_open and open_time < last_open[symbol]:
                    raise ValueError(f"CME rows are not monotonic for {symbol}")
                last_open[symbol] = open_time
                index = indices[symbol]
                while (
                    index < len(lookup_times)
                    and lookup_times[index] < available_at
                ):
                    lookup[symbol][lookup_times[index]] = latest[symbol]
                    index += 1
                latest[symbol] = RawSample(
                    observed_at=available_at,
                    available_at=available_at,
                    close=float(row["close"]),
                    volume=float(row["volume"]) if row["volume"] else None,
                    spread_price=None,
                    source_record_key=(
                        f"{path.name}:{symbol}:{row['instrument_id']}:{row['open_time']}"
                    ),
                    source_locator={
                        "provider_code": "DATABENTO_GLBX_MDP3",
                        "normalized_file": path.name,
                        "normalized_file_sha256": actual_hash,
                        "open_time": open_time,
                    },
                    instrument_id=row["instrument_id"],
                )
                while (
                    index < len(lookup_times)
                    and lookup_times[index] == available_at
                ):
                    lookup[symbol][lookup_times[index]] = latest[symbol]
                    index += 1
                indices[symbol] = index
    for symbol in CME_SYMBOLS:
        index = indices[symbol]
        while index < len(lookup_times):
            lookup[symbol][lookup_times[index]] = latest[symbol]
            index += 1
    return {
        symbol: _compose_samples(
            instrument=symbol,
            request_times=request_times,
            lookup=lookup[symbol],
            source_type="CME_CONTINUOUS_FUTURES_PRICE",
        )
        for symbol in CME_SYMBOLS
    }


def _compose_samples(
    *,
    instrument: str,
    request_times: Sequence[datetime],
    lookup: Mapping[datetime, RawSample | None],
    source_type: str,
) -> dict[datetime, Any]:
    output: dict[datetime, Any] = {}
    threshold = timedelta(days=1) if instrument == "US500" else timedelta(minutes=15)
    if instrument in CME_SYMBOLS:
        threshold = timedelta(hours=8)
    for requested_at in request_times:
        current = lookup[requested_at]
        if current is None:
            output[requested_at] = None
            continue
        staleness = requested_at - current.available_at
        status = "READY" if staleness <= threshold else "STALE"
        changes: dict[str, Any] = {}
        for code, delta in CROSS_CHANGE_HORIZONS.items():
            target = requested_at - delta
            previous = lookup[target]
            if previous is None:
                changes[code] = {
                    "status": "UNKNOWN",
                    "reason": "NO_ELIGIBLE_REFERENCE",
                    "epistemic_status": "UNKNOWN",
                }
                continue
            reference_staleness = target - previous.available_at
            if reference_staleness > timedelta(days=3):
                changes[code] = {
                    "status": "UNKNOWN",
                    "reason": "REFERENCE_STALE",
                    "reference_available_at": previous.available_at,
                    "epistemic_status": "UNKNOWN",
                }
                continue
            if (
                current.instrument_id is not None
                and previous.instrument_id is not None
                and current.instrument_id != previous.instrument_id
            ):
                changes[code] = {
                    "status": "UNKNOWN",
                    "reason": "CONTINUOUS_CONTRACT_ROLL",
                    "current_instrument_id": current.instrument_id,
                    "reference_instrument_id": previous.instrument_id,
                    "epistemic_status": "UNKNOWN",
                }
                continue
            absolute = current.close - previous.close
            changes[code] = {
                "status": "READY",
                "reference_at": previous.observed_at,
                "reference_available_at": previous.available_at,
                "reference_value": previous.close,
                "absolute_change": round(absolute, 8),
                "percent_change": (
                    round(100 * absolute / previous.close, 8)
                    if previous.close
                    else None
                ),
                "epistemic_status": "CALCULATED",
            }
        fact: dict[str, Any] = {
            "status": status,
            "requested_at": requested_at,
            "observed_at": current.observed_at,
            "available_at": current.available_at,
            "staleness_seconds": max(0, int(staleness.total_seconds())),
            "value": current.close,
            "volume": current.volume,
            "spread_price": current.spread_price,
            "instrument_id": current.instrument_id,
            "source_type": source_type,
            "source_record_key": current.source_record_key,
            "source_locator": current.source_locator,
            "epistemic_status": "OBSERVED",
            "changes": changes,
        }
        if instrument in {"ZQ.v.0", "SR3.v.0"}:
            fact["implied_rate_percent"] = round(100 - current.close, 8)
            fact["implied_rate_epistemic_status"] = "CALCULATED"
        output[requested_at] = fact
    return output


def _lookup_times(request_times: Sequence[datetime]) -> list[datetime]:
    return sorted(
        {
            timestamp
            for requested_at in request_times
            for timestamp in (
                requested_at,
                *(
                    requested_at - delta
                    for delta in CROSS_CHANGE_HORIZONS.values()
                ),
            )
        }
    )


def _write_cross_market_records(
    path: Path,
    *,
    request_times: Sequence[datetime],
    db_samples: Mapping[str, Mapping[datetime, Any]],
    cme_samples: Mapping[str, Mapping[datetime, Any]],
) -> tuple[dict[datetime, str], dict[datetime, dict[str, Any]]]:
    ids: dict[datetime, str] = {}
    records: dict[datetime, dict[str, Any]] = {}
    with JsonlArtifactWriter(path) as writer:
        for as_of in request_times:
            record_id = f"CROSS-{as_of:%Y%m%dT%H%M%SZ}"
            instruments = {
                instrument: db_samples[instrument][as_of]
                for instrument in CROSS_DB_INSTRUMENTS
            }
            instruments.update(
                {
                    symbol: cme_samples[symbol][as_of]
                    for symbol in CME_SYMBOLS
                }
            )
            ready = sum(
                item is not None and item["status"] == "READY"
                for item in instruments.values()
            )
            stale = sum(
                item is not None and item["status"] == "STALE"
                for item in instruments.values()
            )
            record = finalize_record(
                {
                    **_record_base(
                        record_type="CROSS_MARKET_SNAPSHOT",
                        record_id=record_id,
                        epistemic_status="CALCULATED",
                    ),
                    "as_of": as_of,
                    "available_at": as_of,
                    "instruments": instruments,
                    "quality": {
                        "ready_instruments": ready,
                        "stale_instruments": stale,
                        "unknown_instruments": len(instruments) - ready - stale,
                    },
                    "interpretation_policy": (
                        "Observed prices and transparent changes only. ZT/ZN are "
                        "futures-price proxies, not observed Treasury yields. "
                        "No directional conclusion is assigned."
                    ),
                }
            )
            writer.write(record)
            ids[as_of] = record_id
            records[as_of] = record
    return ids, records


def _write_positioning_records(
    path: Path,
    *,
    reports: Sequence[CotReport],
    positions: Sequence[CotPosition],
    cross_records: Mapping[datetime, Mapping[str, Any]],
    cross_ids: Mapping[datetime, str],
) -> tuple[dict[datetime, str], list[dict[str, Any]]]:
    by_report: dict[Any, dict[str, CotPosition]] = defaultdict(dict)
    for position in positions:
        by_report[position.report_id][position.category] = position
    ids: dict[datetime, str] = {}
    records: list[dict[str, Any]] = []
    managed_history: list[int] = []
    previous_report: CotReport | None = None
    previous_managed_net: int | None = None
    previous_net_change: int | None = None
    with JsonlArtifactWriter(path) as writer:
        for report in reports:
            categories = by_report[report.id]
            managed = categories.get("MANAGED_MONEY")
            producer = categories.get("PRODUCER_MERCHANT")
            if managed is None or producer is None:
                raise ValueError(f"COT report {report.id} lacks required categories")
            managed_net = managed.long_contracts - managed.short_contracts
            producer_net = producer.long_contracts - producer.short_contracts
            managed_history.append(managed_net)
            percentile = (
                100
                * sum(value <= managed_net for value in managed_history)
                / len(managed_history)
            )
            net_change = (
                managed_net - previous_managed_net
                if previous_managed_net is not None
                else None
            )
            acceleration = (
                net_change - previous_net_change
                if net_change is not None and previous_net_change is not None
                else None
            )
            crowding = (
                "CROWDED_LONGS"
                if percentile >= 90
                else "CROWDED_SHORTS"
                if percentile <= 10
                else "BALANCED"
            )
            xau_fact = cross_records[report.publication_at]["instruments"]["XAUUSD"]
            prior_xau_fact = (
                cross_records[previous_report.publication_at]["instruments"][
                    "XAUUSD"
                ]
                if previous_report is not None
                else None
            )
            price_change = (
                xau_fact["value"] - prior_xau_fact["value"]
                if xau_fact is not None
                and prior_xau_fact is not None
                and xau_fact["status"] == "READY"
                and prior_xau_fact["status"] == "READY"
                else None
            )
            open_interest_change = (
                report.open_interest - previous_report.open_interest
                if previous_report is not None
                else None
            )
            participation = _participation_inference(
                price_change,
                open_interest_change,
            )
            record_id = f"POSITIONING-COT-{report.observation_date.isoformat()}"
            category_records = {
                code: {
                    "long_contracts": value.long_contracts,
                    "short_contracts": value.short_contracts,
                    "net_contracts": value.long_contracts - value.short_contracts,
                    "spreading_contracts": value.spreading_contracts,
                    "percent_open_interest_long": value.percent_open_interest_long,
                    "percent_open_interest_short": value.percent_open_interest_short,
                    "traders_long": value.traders_long,
                    "traders_short": value.traders_short,
                    "epistemic_status": "OBSERVED",
                }
                for code, value in sorted(categories.items())
            }
            record = finalize_record(
                {
                    **_record_base(
                        record_type="POSITIONING_REPORT",
                        record_id=record_id,
                        epistemic_status="CALCULATED",
                    ),
                    "provider_code": report.provider_code,
                    "report_type": report.report_type,
                    "contract_market_code": report.contract_market_code,
                    "market_name": report.market_name,
                    "observation_date": report.observation_date,
                    "publication_at": report.publication_at,
                    "available_at": report.publication_at,
                    "ingested_at": report.ingested_at,
                    "availability_quality": report.availability_quality,
                    "open_interest": report.open_interest,
                    "categories": category_records,
                    "calculated": {
                        "managed_money_net": managed_net,
                        "managed_money_net_change": net_change,
                        "managed_money_net_change_acceleration": acceleration,
                        "managed_money_net_percentile": round(percentile, 4),
                        "percentile_history_count": len(managed_history),
                        "producer_net": producer_net,
                        "open_interest_change": open_interest_change,
                        "gold_price_change_between_publications": price_change,
                        "epistemic_status": "CALCULATED",
                    },
                    "inferred": {
                        "crowding_state": crowding,
                        "participation_state": participation,
                        "long_liquidation_risk": (
                            "ELEVATED" if crowding == "CROWDED_LONGS" else "NORMAL"
                        ),
                        "short_covering_risk": (
                            "ELEVATED" if crowding == "CROWDED_SHORTS" else "NORMAL"
                        ),
                        "epistemic_status": "INFERRED",
                        "warning": (
                            "CFTC categories are observed. Crowding, participation, "
                            "and liquidation motives are interpretations, not observed "
                            "institutional intent."
                        ),
                    },
                    "cross_market_snapshot_id": cross_ids[report.publication_at],
                    "source": {
                        "batch_id": report.batch_id,
                        "source_record_key": report.source_record_key,
                        "metadata": report.metadata_json,
                    },
                }
            )
            writer.write(record)
            ids[report.publication_at] = record_id
            records.append(record)
            previous_report = report
            previous_managed_net = managed_net
            previous_net_change = net_change
    return ids, records


def _write_event_records(
    path: Path,
    *,
    events: Sequence[EconomicEvent],
    releases: Sequence[EconomicRelease],
    forecasts: Sequence[ForecastSnapshot],
    surprises: Sequence[EconomicSurprise],
    cross_records: Mapping[datetime, Mapping[str, Any]],
    cross_ids: Mapping[datetime, str],
    end: datetime,
) -> dict[Any, str]:
    releases_by_event: dict[Any, list[EconomicRelease]] = defaultdict(list)
    for release in releases:
        releases_by_event[release.event_id].append(release)
    forecasts_by_key: dict[tuple[str, datetime], list[ForecastSnapshot]] = defaultdict(
        list
    )
    for forecast in forecasts:
        forecasts_by_key[(forecast.event_code, forecast.scheduled_at)].append(
            forecast
        )
    surprises_by_event: dict[Any, list[EconomicSurprise]] = defaultdict(list)
    for surprise in surprises:
        surprises_by_event[surprise.event_id].append(surprise)
    ids: dict[Any, str] = {}
    with JsonlArtifactWriter(path) as writer:
        for event in events:
            released_at = event.released_at or event.scheduled_at
            reaction_times = {
                code: released_at + delta
                for code, delta in EVENT_HORIZONS.items()
                if released_at + delta < end
            }
            daily_close = _event_daily_close(released_at)
            if daily_close < end:
                reaction_times["DAILY_CLOSE"] = daily_close
            reaction_snapshots = {
                code: {
                    "as_of": timestamp,
                    "cross_market_snapshot_id": cross_ids[timestamp],
                    "available_at": timestamp,
                    "decision_eligible_at_release": code == "REFERENCE",
                }
                for code, timestamp in reaction_times.items()
            }
            event_releases = releases_by_event[event.id]
            event_forecasts = forecasts_by_key[
                (event.event_code, event.scheduled_at)
            ]
            release_records = [
                {
                    "release_id": release.id,
                    "component_code": release.component_code,
                    "observation_period": release.observation_period,
                    "actual_value": release.actual_value,
                    "previous_value": release.previous_value,
                    "revised_previous_value": release.revised_previous_value,
                    "unit": release.unit,
                    "released_at": release.released_at,
                    "available_at": release.available_at,
                    "is_revision": release.is_revision,
                    "vintage": release.vintage,
                    "metadata": release.metadata_json,
                    "epistemic_status": "OBSERVED",
                }
                for release in event_releases
            ]
            forecast_records = [
                {
                    "forecast_id": forecast.id,
                    "component_code": forecast.component_code,
                    "forecast_value": forecast.forecast_value,
                    "unit": forecast.unit,
                    "forecast_as_of": forecast.forecast_as_of,
                    "available_at": forecast.available_at,
                    "provider_code": forecast.provider_code,
                    "vintage": forecast.vintage,
                    "pre_event_use_allowed": bool(
                        forecast.metadata_json.get("pre_event_use_allowed", False)
                    ),
                    "metadata": forecast.metadata_json,
                    "epistemic_status": "OBSERVED",
                }
                for forecast in event_forecasts
            ]
            raw_surprises = _raw_event_surprises(
                event_releases,
                event_forecasts,
            )
            standardized = [
                {
                    "surprise_id": surprise.id,
                    "release_id": surprise.release_id,
                    "component_code": surprise.component_code,
                    "released_at": surprise.released_at,
                    "available_at": surprise.available_at,
                    "raw_surprise": surprise.raw_surprise,
                    "standardized_surprise": surprise.standardized_surprise,
                    "gold_direction": surprise.gold_direction,
                    "strength": surprise.strength,
                    "confidence": surprise.confidence,
                    "history_count": surprise.history_count,
                    "method": surprise.method,
                    "epistemic_status": surprise.epistemic_status,
                    "ruleset_version": surprise.ruleset_version,
                    "data_hash": surprise.data_hash,
                }
                for surprise in surprises_by_event[event.id]
            ]
            reactions = _event_reactions(
                reaction_times,
                cross_records=cross_records,
            )
            schedule_verified_pre_event = (
                event.available_at < event.scheduled_at
                and "point_in_time_warning" not in event.metadata_json
            )
            record_id = (
                f"EVENT-{event.event_code}-{event.scheduled_at:%Y%m%dT%H%M%SZ}-"
                f"{str(event.id)[:12]}"
            )
            record = finalize_record(
                {
                    **_record_base(
                        record_type="EVENT_CASE",
                        record_id=record_id,
                        epistemic_status="CALCULATED",
                    ),
                    "event_id": event.id,
                    "event_code": event.event_code,
                    "name": event.name,
                    "event_type": event.event_type,
                    "importance": event.importance,
                    "is_scheduled": event.is_scheduled,
                    "status": event.status,
                    "scheduled_at": event.scheduled_at,
                    "released_at": event.released_at,
                    "event_available_at": event.available_at,
                    "provider_code": event.provider_code,
                    "source_event_key": event.source_event_key,
                    "schedule_verified_for_pre_event_use": schedule_verified_pre_event,
                    "pre_event_state": {
                        "schedule": (
                            "OBSERVED" if schedule_verified_pre_event else "UNKNOWN"
                        ),
                        "consensus": (
                            "OBSERVED"
                            if any(
                                item["pre_event_use_allowed"]
                                for item in forecast_records
                            )
                            else "UNKNOWN"
                        ),
                        "warning": (
                            "Release-boundary historical calendar data must not be "
                            "used as an upcoming catalyst or consensus before release."
                        ),
                    },
                    "releases": release_records,
                    "forecasts": forecast_records,
                    "raw_surprises": raw_surprises,
                    "standardized_surprises": standardized,
                    "reaction_snapshots": reaction_snapshots,
                    "fixed_horizon_reactions": reactions,
                    "complete_observation_available_at": max(
                        reaction_times.values(),
                        default=released_at,
                    ),
                    "source": {
                        "batch_id": event.batch_id,
                        "metadata": event.metadata_json,
                        "ingested_at": event.ingested_at,
                    },
                    "research_policy": {
                        "mfe_calculated": False,
                        "mae_calculated": False,
                        "execution_optimized": False,
                    },
                }
            )
            writer.write(record)
            ids[event.id] = record_id
    return ids


def _raw_event_surprises(
    releases: Sequence[EconomicRelease],
    forecasts: Sequence[ForecastSnapshot],
) -> list[dict[str, Any]]:
    forecast_by_component: dict[str, ForecastSnapshot] = {}
    for forecast in sorted(forecasts, key=lambda item: item.available_at):
        if forecast.available_at <= forecast.scheduled_at:
            forecast_by_component[forecast.component_code] = forecast
    output: list[dict[str, Any]] = []
    for release in releases:
        forecast = forecast_by_component.get(release.component_code)
        if forecast is None or forecast.available_at > release.available_at:
            output.append(
                {
                    "component_code": release.component_code,
                    "status": "UNKNOWN",
                    "reason": "NO_ELIGIBLE_FORECAST_AT_RELEASE",
                    "epistemic_status": "UNKNOWN",
                }
            )
            continue
        output.append(
            {
                "component_code": release.component_code,
                "actual_value": release.actual_value,
                "forecast_value": forecast.forecast_value,
                "raw_surprise": release.actual_value - forecast.forecast_value,
                "available_at": max(release.available_at, forecast.available_at),
                "pre_event_use_allowed": bool(
                    forecast.metadata_json.get("pre_event_use_allowed", False)
                ),
                "epistemic_status": "CALCULATED",
            }
        )
    return output


def _event_reactions(
    reaction_times: Mapping[str, datetime],
    *,
    cross_records: Mapping[datetime, Mapping[str, Any]],
) -> dict[str, Any]:
    reference_time = reaction_times.get("REFERENCE")
    if reference_time is None:
        return {}
    reference = cross_records[reference_time]["instruments"]
    output: dict[str, Any] = {}
    for code, timestamp in reaction_times.items():
        if code == "REFERENCE":
            continue
        horizon = cross_records[timestamp]["instruments"]
        instrument_results: dict[str, Any] = {}
        for instrument in ("XAUUSD", "EURUSD", "ZT.v.0", "ZN.v.0", "ZQ.v.0", "SR3.v.0"):
            start = reference[instrument]
            finish = horizon[instrument]
            if (
                start is None
                or finish is None
                or start["status"] != "READY"
                or finish["status"] != "READY"
            ):
                instrument_results[instrument] = {
                    "status": "UNKNOWN",
                    "reason": "REFERENCE_OR_HORIZON_UNAVAILABLE",
                    "epistemic_status": "UNKNOWN",
                }
                continue
            if (
                start["instrument_id"] is not None
                and finish["instrument_id"] is not None
                and start["instrument_id"] != finish["instrument_id"]
            ):
                instrument_results[instrument] = {
                    "status": "UNKNOWN",
                    "reason": "CONTINUOUS_CONTRACT_ROLL",
                    "epistemic_status": "UNKNOWN",
                }
                continue
            change = finish["value"] - start["value"]
            result = {
                "status": "READY",
                "reference_value": start["value"],
                "horizon_value": finish["value"],
                "absolute_change": round(change, 8),
                "percent_change": (
                    round(100 * change / start["value"], 8)
                    if start["value"]
                    else None
                ),
                "available_at": timestamp,
                "epistemic_status": "CALCULATED",
            }
            if instrument in {"ZQ.v.0", "SR3.v.0"}:
                result["implied_rate_change_basis_points"] = round(-100 * change, 6)
            instrument_results[instrument] = result
        output[code] = {
            "as_of": timestamp,
            "instruments": instrument_results,
        }
    first = output.get("1_MINUTE", {}).get("instruments", {}).get("XAUUSD")
    if first and first["status"] == "READY":
        first_direction = _sign_label(first["absolute_change"])
        output["first_move_assessment"] = {
            "first_move_direction": first_direction,
            "held_by_horizon": {
                code: (
                    _sign_label(item["instruments"]["XAUUSD"]["absolute_change"])
                    == first_direction
                    if item["instruments"]["XAUUSD"]["status"] == "READY"
                    else None
                )
                for code, item in output.items()
                if code != "first_move_assessment"
                and "instruments" in item
                and code != "1_MINUTE"
            },
            "epistemic_status": "CALCULATED",
        }
    return output


def _write_fundamental_records(
    path: Path,
    *,
    decision_times: Sequence[datetime],
    observations: Sequence[Observation],
    policy_path_points: Sequence[PolicyPathPoint],
    policy_expectations: Sequence[PolicyExpectationWindow],
    inputs: FundamentalInputs,
    positioning_ids: Mapping[datetime, str],
) -> dict[datetime, str]:
    observation_ids: dict[Any, str] = {}
    by_series: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        by_series[observation.series_code].append(observation)
    positioning_times = sorted(positioning_ids)
    snapshot_ids: dict[datetime, str] = {}
    with JsonlArtifactWriter(path) as writer:
        for observation in observations:
            record_id = f"FUNDAMENTAL-OBS-{observation.id}"
            record = finalize_record(
                {
                    **_record_base(
                        record_type="FUNDAMENTAL_OBSERVATION",
                        record_id=record_id,
                        epistemic_status="OBSERVED",
                    ),
                    "series_code": observation.series_code,
                    "observation_time": observation.observation_time,
                    "value": observation.value,
                    "unit": observation.unit,
                    "available_at": observation.available_at,
                    "ingested_at": observation.ingested_at,
                    "vintage": observation.vintage,
                    "is_revision": observation.is_revision,
                    "supersedes_id": observation.supersedes_id,
                    "source": {
                        "batch_id": observation.batch_id,
                        "source_record_key": observation.source_record_key,
                    },
                }
            )
            writer.write(record)
            observation_ids[observation.id] = record_id
        for point in policy_path_points:
            record = finalize_record(
                {
                    **_record_base(
                        record_type="POLICY_PATH_POINT",
                        record_id=f"POLICY-PATH-{point.id}",
                        epistemic_status="OBSERVED",
                    ),
                    "provider_code": point.provider_code,
                    "snapshot_as_of": point.snapshot_as_of,
                    "meeting_date": point.meeting_date,
                    "outcome_basis_points": point.outcome_basis_points,
                    "probability": point.probability,
                    "expected_rate": point.expected_rate,
                    "available_at": point.available_at,
                    "ingested_at": point.ingested_at,
                    "source": {
                        "batch_id": point.batch_id,
                        "source_record_key": point.source_record_key,
                        "metadata": point.metadata_json,
                    },
                }
            )
            writer.write(record)
        for window in policy_expectations:
            record = finalize_record(
                {
                    **_record_base(
                        record_type="POLICY_EXPECTATION_WINDOW",
                        record_id=f"POLICY-WINDOW-{window.id}",
                        epistemic_status="OBSERVED",
                    ),
                    "provider_code": window.provider_code,
                    "observation_date": window.observation_date,
                    "snapshot_as_of": window.snapshot_as_of,
                    "reference_start": window.reference_start,
                    "reference_end": window.reference_end,
                    "target_lower_basis_points": window.target_lower_basis_points,
                    "target_upper_basis_points": window.target_upper_basis_points,
                    "rate_p25_basis_points": window.rate_p25_basis_points,
                    "rate_mean_basis_points": window.rate_mean_basis_points,
                    "rate_mode_basis_points": window.rate_mode_basis_points,
                    "rate_p75_basis_points": window.rate_p75_basis_points,
                    "probability_cut": window.probability_cut,
                    "probability_hike": window.probability_hike,
                    "probability_bins": window.probability_bins,
                    "distribution_probability_sum": window.distribution_probability_sum,
                    "available_at": window.available_at,
                    "availability_quality": window.availability_quality,
                    "ingested_at": window.ingested_at,
                    "source": {
                        "batch_id": window.batch_id,
                        "source_record_key": window.source_record_key,
                        "metadata": window.metadata_json,
                    },
                }
            )
            writer.write(record)
        for as_of in decision_times:
            series_state = {
                series_code: _series_state_at(
                    rows,
                    as_of=as_of,
                    observation_ids=observation_ids,
                )
                for series_code, rows in sorted(by_series.items())
            }
            state = inputs.state_at(as_of, compute_data_hash=False)
            state_payload = asdict(state)
            state_payload["data_hash"] = canonical_hash(
                {
                    "series_state": series_state,
                    "components": state_payload["components"],
                    "layers": state_payload["layers"],
                    "as_of": as_of,
                }
            )
            positioning_id = _latest_id(
                positioning_times,
                positioning_ids,
                as_of,
            )
            record_id = f"FUNDAMENTAL-SNAPSHOT-{as_of:%Y%m%dT%H%M%SZ}"
            record = finalize_record(
                {
                    **_record_base(
                        record_type="FUNDAMENTAL_SNAPSHOT",
                        record_id=record_id,
                        epistemic_status="CALCULATED",
                    ),
                    "as_of": as_of,
                    "available_at": as_of,
                    "series_state": series_state,
                    "engine_state": state_payload,
                    "positioning_record_id": positioning_id,
                    "provenance": inputs.provenance_at(as_of),
                    "ruleset_version": FUNDAMENTAL_RULESET_VERSION,
                    "interpretation_warning": (
                        "The transparent fundamental score is an inferred feature, "
                        "not a trade signal and not a measured outcome."
                    ),
                }
            )
            writer.write(record)
            snapshot_ids[as_of] = record_id
    return snapshot_ids


def _series_state_at(
    rows: Sequence[Observation],
    *,
    as_of: datetime,
    observation_ids: Mapping[Any, str],
) -> dict[str, Any]:
    eligible = [
        row
        for row in rows
        if row.available_at <= as_of and row.observation_time <= as_of
    ]
    if not eligible:
        return {
            "status": "UNKNOWN",
            "epistemic_status": "UNKNOWN",
            "reason": "NO_POINT_IN_TIME_ELIGIBLE_OBSERVATION",
        }
    canonical: dict[datetime, Observation] = {}
    for row in sorted(
        eligible,
        key=lambda item: (item.observation_time, item.available_at),
    ):
        canonical[row.observation_time] = row
    ordered = sorted(canonical.values(), key=lambda item: item.observation_time)
    current = ordered[-1]
    previous = ordered[-2] if len(ordered) >= 2 else None
    delta = (
        float(current.value - previous.value)
        if previous is not None
        else None
    )
    elapsed_days = (
        (current.observation_time - previous.observation_time).total_seconds()
        / 86_400
        if previous is not None
        else None
    )
    return {
        "status": "READY",
        "record_id": observation_ids[current.id],
        "observation_time": current.observation_time,
        "available_at": current.available_at,
        "value": current.value,
        "unit": current.unit,
        "vintage": current.vintage,
        "is_revision": current.is_revision,
        "staleness_seconds": max(
            0,
            int((as_of - current.available_at).total_seconds()),
        ),
        "previous_record_id": (
            observation_ids[previous.id] if previous is not None else None
        ),
        "previous_value": previous.value if previous is not None else None,
        "absolute_change": delta,
        "percent_change": (
            100 * delta / float(previous.value)
            if previous is not None and previous.value != 0 and delta is not None
            else None
        ),
        "change_per_day": (
            delta / elapsed_days
            if delta is not None and elapsed_days not in {None, 0}
            else None
        ),
        "epistemic_status": "OBSERVED",
        "change_epistemic_status": (
            "CALCULATED" if previous is not None else "UNKNOWN"
        ),
    }


def _write_session_records(
    path: Path,
    *,
    specs: Sequence[Any],
    five_minute_facts: Sequence[BarFact],
    daily_facts: Sequence[BarFact],
    structure_ids: Mapping[datetime, str],
    cross_ids: Mapping[datetime, str],
    fundamental_ids: Mapping[datetime, str],
    positioning_ids: Mapping[datetime, str],
) -> dict[str, int]:
    fact_by_open = {fact.open_time: fact for fact in five_minute_facts}
    complete_daily = sorted(
        (fact for fact in daily_facts if fact.complete),
        key=lambda item: item.close_time,
    )
    prior_weeks = _weekly_summaries(complete_daily)
    positioning_times = sorted(positioning_ids)
    counts: Counter[str] = Counter()
    previous_session_summary: dict[str, dict[str, Any]] = {}
    with JsonlArtifactWriter(path) as writer:
        for spec in sorted(
            specs,
            key=lambda item: (item.decision_at, item.session_code),
        ):
            decision_windows = {
                "asia": summarize_window(spec.asia, as_of=spec.decision_at),
                "london": summarize_window(spec.london, as_of=spec.decision_at),
                "new_york": (
                    summarize_window(spec.new_york, as_of=spec.decision_at)
                    if spec.new_york is not None
                    else None
                ),
            }
            observed_window = (
                spec.london if spec.session_code == "LONDON" else spec.new_york
            )
            if observed_window is None:
                raise ValueError(f"Missing observed window for {spec.case_id}")
            close_summary = summarize_window(
                observed_window,
                as_of=spec.observation_end,
            )
            prior_day = _prior_daily_summary(complete_daily, spec.decision_at)
            prior_week = _prior_week_summary(
                prior_weeks,
                session_date=spec.session_date,
                as_of=spec.decision_at,
            )
            known_levels = _known_levels(
                spec,
                decision_windows=decision_windows,
                prior_day=prior_day,
                prior_week=prior_week,
            )
            interactions = level_interactions(
                list(observed_window.bars),
                known_levels,
                decision_at=spec.decision_at,
                observation_end=spec.observation_end,
            )
            path_facts = [
                fact_by_open[bar.open_time]
                for bar in observed_window.bars
            ]
            path_hash = canonical_hash(
                [fact.record["record_hash"] for fact in path_facts]
            )
            positioning_id = _latest_id(
                positioning_times,
                positioning_ids,
                spec.decision_at,
            )
            record = finalize_record(
                {
                    **_record_base(
                        record_type="SESSION_CASE",
                        record_id=spec.case_id,
                        epistemic_status="CALCULATED",
                    ),
                    "session_date": spec.session_date,
                    "session_code": spec.session_code,
                    "session_timezone": spec.timezone,
                    "decision_at": spec.decision_at,
                    "availability_at": spec.decision_at,
                    "observation_end": spec.observation_end,
                    "decision_state": {
                        "windows": decision_windows,
                        "prior_same_session": previous_session_summary.get(
                            spec.session_code
                        ),
                        "prior_trading_day": prior_day,
                        "prior_week": prior_week,
                        "known_levels": [asdict(level) for level in known_levels],
                        "market_structure_snapshot_id": structure_ids[
                            spec.decision_at
                        ],
                        "fundamental_snapshot_id": fundamental_ids[
                            spec.decision_at
                        ],
                        "cross_market_snapshot_id": cross_ids[spec.decision_at],
                        "positioning_record_id": positioning_id,
                    },
                    "subsequent_observation": {
                        "decision_eligible": False,
                        "available_at": spec.observation_end,
                        "window": close_summary,
                        "market_structure_snapshot_id": structure_ids[
                            spec.observation_end
                        ],
                        "level_interactions": interactions,
                        "five_minute_path": [
                            {
                                "record_id": fact.record_id,
                                "record_hash": fact.record["record_hash"],
                                "open_time": fact.open_time,
                                "close_time": fact.close_time,
                                "ohlc": fact.record["ohlc"],
                                "volume": fact.volume,
                                "spread_price": fact.spread_price,
                            }
                            for fact in path_facts
                        ],
                        "path_source_hash": path_hash,
                        "one_minute_source_reference": {
                            "artifact": "price_bars.jsonl.gz",
                            "provider_code": PRICE_PROVIDER,
                            "instrument_code": PRICE_INSTRUMENT,
                            "timeframe": "1m",
                            "open_time_gte": spec.decision_at,
                            "close_time_lte": spec.observation_end,
                            "expected_complete_bar_count": int(
                                (
                                    spec.observation_end - spec.decision_at
                                ).total_seconds()
                                // 60
                            ),
                        },
                    },
                    "data_quality": {
                        "status": "COMPLETE",
                        "five_minute_bar_count": len(path_facts),
                        "one_minute_bar_count_implied": sum(
                            fact.source_count for fact in path_facts
                        ),
                        "historical_pre_event_calendar": "UNKNOWN",
                    },
                    "research_policy": {
                        "direction_label_assigned": False,
                        "return_calculated": False,
                        "mfe_calculated": False,
                        "mae_calculated": False,
                        "execution_optimized": False,
                    },
                }
            )
            writer.write(record)
            previous_session_summary[spec.session_code] = {
                "case_id": spec.case_id,
                "session_date": spec.session_date,
                "available_at": spec.observation_end,
                "window": close_summary,
            }
            counts[spec.session_code] += 1
    return {
        "session_cases": sum(counts.values()),
        "london_cases": counts["LONDON"],
        "new_york_cases": counts["NEW_YORK"],
    }


def _weekly_summaries(
    daily_facts: Sequence[BarFact],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[BarFact]] = defaultdict(list)
    for fact in daily_facts:
        if fact.trading_date is None:
            continue
        iso = fact.trading_date.isocalendar()
        grouped[(iso.year, iso.week)].append(fact)
    output: list[dict[str, Any]] = []
    for (year, week), facts in sorted(grouped.items()):
        ordered = sorted(facts, key=lambda item: item.trading_date or date.min)
        output.append(
            {
                "iso_year": year,
                "iso_week": week,
                "start_date": ordered[0].trading_date,
                "end_date": ordered[-1].trading_date,
                "available_at": max(item.close_time for item in ordered),
                "daily_bar_count": len(ordered),
                "open": ordered[0].open,
                "high": max(item.high for item in ordered),
                "low": min(item.low for item in ordered),
                "close": ordered[-1].close,
                "range": max(item.high for item in ordered)
                - min(item.low for item in ordered),
                "source_hash": canonical_hash(
                    [item.record["record_hash"] for item in ordered]
                ),
                "epistemic_status": "CALCULATED",
            }
        )
    return output


def _prior_daily_summary(
    daily_facts: Sequence[BarFact],
    as_of: datetime,
) -> dict[str, Any] | None:
    eligible = [fact for fact in daily_facts if fact.close_time <= as_of]
    if not eligible:
        return None
    fact = eligible[-1]
    return {
        "record_id": fact.record_id,
        "trading_date": fact.trading_date,
        "available_at": fact.close_time,
        "open": fact.open,
        "high": fact.high,
        "low": fact.low,
        "close": fact.close,
        "range": fact.high - fact.low,
        "source_hash": fact.source_hash,
        "epistemic_status": "CALCULATED",
    }


def _prior_week_summary(
    weeks: Sequence[dict[str, Any]],
    *,
    session_date: date,
    as_of: datetime,
) -> dict[str, Any] | None:
    current = session_date.isocalendar()
    eligible = [
        item
        for item in weeks
        if (item["iso_year"], item["iso_week"]) < (current.year, current.week)
        and item["available_at"] <= as_of
    ]
    return eligible[-1] if eligible else None


def _known_levels(
    spec: Any,
    *,
    decision_windows: Mapping[str, Any],
    prior_day: Mapping[str, Any] | None,
    prior_week: Mapping[str, Any] | None,
) -> list[KnownLevel]:
    output: list[KnownLevel] = []

    def add_pair(code: str, value: Mapping[str, Any]) -> None:
        if value.get("high") is None or value.get("low") is None:
            return
        known_at = value.get("available_at") or value.get("end")
        source_hash = value.get("source_hash") or canonical_hash(value)
        output.extend(
            (
                KnownLevel(
                    code=f"{code}_HIGH",
                    price=float(value["high"]),
                    side="UPPER",
                    known_at=known_at,
                    source_hash=source_hash,
                ),
                KnownLevel(
                    code=f"{code}_LOW",
                    price=float(value["low"]),
                    side="LOWER",
                    known_at=known_at,
                    source_hash=source_hash,
                ),
            )
        )

    add_pair("ASIA", decision_windows["asia"])
    if (
        spec.session_code == "NEW_YORK"
        and decision_windows["london"] is not None
        and decision_windows["london"]["status"] == "COMPLETE"
    ):
        add_pair("LONDON", decision_windows["london"])
    if prior_day is not None:
        add_pair("PRIOR_DAY", prior_day)
    if prior_week is not None:
        add_pair("PRIOR_WEEK", prior_week)
    return output


def _daily_boundaries(trading_date: date) -> tuple[datetime, datetime, int]:
    start_hour = (
        IC_MARKETS_MT5_CONFIG.monday_session_start_hour_new_york
        if trading_date.weekday() == 0
        else IC_MARKETS_MT5_CONFIG.daily_session_start_hour_new_york
    )
    start_local = datetime.combine(
        trading_date - timedelta(days=1),
        time(start_hour),
        tzinfo=NEW_YORK,
    )
    end_local = datetime.combine(
        trading_date,
        time(IC_MARKETS_MT5_CONFIG.daily_session_end_hour_new_york),
        tzinfo=NEW_YORK,
    )
    start_at = start_local.astimezone(UTC)
    end_at = end_local.astimezone(UTC)
    expected = 0
    current = start_at
    while current < end_at:
        local = current.astimezone(NEW_YORK)
        minute_of_day = local.hour * 60 + local.minute
        pause_start = IC_MARKETS_MT5_CONFIG.daily_pause_start_minute_new_york
        pause_end = IC_MARKETS_MT5_CONFIG.daily_pause_end_minute_new_york
        in_pause = pause_start <= minute_of_day < pause_end
        if not in_pause:
            expected += 1
        current += timedelta(minutes=1)
    return start_at, end_at, expected


def _participation_inference(
    price_change: float | None,
    open_interest_change: int | None,
) -> str:
    if price_change is None or open_interest_change is None:
        return "UNKNOWN"
    if price_change > 0 and open_interest_change > 0:
        return "PROBABLE_FRESH_BULLISH_PARTICIPATION"
    if price_change > 0 and open_interest_change < 0:
        return "PROBABLE_SHORT_COVERING"
    if price_change < 0 and open_interest_change > 0:
        return "PROBABLE_FRESH_BEARISH_PARTICIPATION"
    if price_change < 0 and open_interest_change < 0:
        return "PROBABLE_LONG_LIQUIDATION"
    return "INDETERMINATE"


def _event_daily_close(value: datetime) -> datetime:
    local = value.astimezone(NEW_YORK)
    candidate_date = local.date()
    candidate = datetime.combine(candidate_date, time(17), tzinfo=NEW_YORK)
    if local >= candidate:
        candidate_date += timedelta(days=1)
    while candidate_date.weekday() >= 5:
        candidate_date += timedelta(days=1)
    return datetime.combine(candidate_date, time(17), tzinfo=NEW_YORK).astimezone(
        UTC
    )


def _latest_id(
    available_times: Sequence[datetime],
    identifiers: Mapping[datetime, str],
    as_of: datetime,
) -> str | None:
    eligible = [timestamp for timestamp in available_times if timestamp <= as_of]
    return identifiers[eligible[-1]] if eligible else None


def _sign_label(value: float) -> str:
    return "UP" if value > 0 else "DOWN" if value < 0 else "FLAT"


def _assert_specs_unchanged(
    initial: Sequence[Any],
    actual: Sequence[Any],
) -> None:
    first = [
        (item.case_id, item.decision_at, item.observation_end)
        for item in initial
    ]
    second = [
        (item.case_id, item.decision_at, item.observation_end)
        for item in actual
    ]
    if first != second:
        raise ValueError("Session case membership changed during materialization")


def _record_base(
    *,
    record_type: str,
    record_id: str,
    epistemic_status: str,
) -> dict[str, Any]:
    return {
        "record_type": record_type,
        "record_id": record_id,
        "casebook_version": CASEBOOK_VERSION,
        "schema_version": CASEBOOK_SCHEMA_VERSION,
        "epistemic_status": epistemic_status,
        "holdout_loaded": False,
    }


def _verify_artifacts(
    root: Path,
    artifacts: Sequence[ArtifactSummary],
    *,
    end: datetime,
) -> dict[str, Any]:
    record_ids: set[str] = set()
    verified = 0
    forbidden_time_fields = {
        "open_time",
        "close_time",
        "decision_at",
        "observation_end",
        "as_of",
        "available_at",
        "availability_at",
        "scheduled_at",
        "released_at",
        "publication_at",
        "observation_time",
        "event_available_at",
        "forecast_as_of",
        "snapshot_as_of",
        "complete_observation_available_at",
    }
    for artifact in artifacts:
        path = root / artifact.path
        count = 0
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                expected_hash = record.pop("record_hash")
                if canonical_hash(record) != expected_hash:
                    raise ValueError(
                        f"Record hash mismatch in {artifact.path} line {count + 1}"
                    )
                record["record_hash"] = expected_hash
                record_id = record["record_id"]
                if record_id in record_ids:
                    raise ValueError(f"Duplicate casebook record_id: {record_id}")
                record_ids.add(record_id)
                if record.get("holdout_loaded") is not False:
                    raise ValueError(f"Holdout flag violated: {record_id}")
                if record.get("schema_version") != CASEBOOK_SCHEMA_VERSION:
                    raise ValueError(f"Schema version mismatch: {record_id}")
                _guard_market_timestamps(
                    record,
                    end=end,
                    field_names=forbidden_time_fields,
                )
                count += 1
        if count != artifact.record_count:
            raise ValueError(
                f"Record count mismatch for {artifact.path}: {count} "
                f"!= {artifact.record_count}"
            )
        if _sha256(path) != artifact.sha256:
            raise ValueError(f"Artifact hash mismatch: {artifact.path}")
        verified += count
    return {
        "record_hashes_verified": verified,
        "unique_record_ids": len(record_ids),
        "artifact_hashes_verified": len(artifacts),
        "holdout_boundary_verified": True,
        "schema_version_verified": True,
    }


def _guard_market_timestamps(
    value: Any,
    *,
    end: datetime,
    field_names: set[str],
    current_key: str | None = None,
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _guard_market_timestamps(
                item,
                end=end,
                field_names=field_names,
                current_key=str(key),
            )
        return
    if isinstance(value, list):
        for item in value:
            _guard_market_timestamps(
                item,
                end=end,
                field_names=field_names,
                current_key=current_key,
            )
        return
    if current_key not in field_names or not isinstance(value, str):
        return
    try:
        timestamp = datetime.fromisoformat(value).astimezone(UTC)
    except ValueError:
        return
    crosses_boundary = timestamp > end or (
        timestamp == end and current_key != "close_time"
    )
    if crosses_boundary:
        raise ValueError(
            f"Locked holdout timestamp encountered in {current_key}: {value}"
        )


def _writer_summary(path: Path, relative_to: Path) -> ArtifactSummary:
    count = 0
    types: Counter[str] = Counter()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            count += 1
            types[record["record_type"]] += 1
    return ArtifactSummary(
        name=path.name,
        path=path.relative_to(relative_to).as_posix(),
        sha256=_sha256(path),
        bytes=path.stat().st_size,
        record_count=count,
        record_type_counts=dict(sorted(types.items())),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _progress(stage: str, **details: Any) -> None:
    print(
        json.dumps(
            {
                "casebook_stage": stage,
                **details,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _parse_boundary(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the immutable, descriptive, pre-2025 Gold casebook. "
            "No profitability or execution outcome is calculated."
        )
    )
    parser.add_argument("--start", default=CASE_START.isoformat())
    parser.add_argument("--end", default=CASE_END.isoformat())
    parser.add_argument(
        "--output-dir",
        default="/workspace/research_artifacts/gold_casebook_v01",
    )
    parser.add_argument(
        "--schema",
        default="/workspace/research_schemas/gold_casebook_v01.schema.json",
    )
    parser.add_argument(
        "--coverage",
        default="/workspace/research_artifacts/gold_casebook_coverage_v01.json",
    )
    parser.add_argument(
        "--cme-normalization",
        default=(
            "/workspace/data/raw/databento_cme_pre2025/"
            "GLBX-20260728-3SHU3737P8/normalized/normalization.json"
        ),
    )
    return parser


if __name__ == "__main__":
    asyncio.run(main())
