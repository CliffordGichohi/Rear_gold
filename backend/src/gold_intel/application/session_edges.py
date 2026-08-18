from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.analytics.fundamentals import FundamentalState
from gold_intel.analytics.session_edges import (
    SESSION_EDGE_RULESET_VERSION,
    SESSION_EDGE_SUMMARY_VERSION,
    AsiaRange,
    BiasAlignment,
    PathOutcome,
    SessionEdgeBar,
    SessionEdgeConfig,
    Side,
    SweepAttempt,
    build_london_session_opportunities,
    opportunity_to_dict,
    summarize_session_opportunities,
)
from gold_intel.analytics.session_edges import (
    SessionOpportunity as CalculatedOpportunity,
)
from gold_intel.application.fundamentals import load_fundamental_inputs
from gold_intel.infrastructure.models import (
    PriceBar,
    SessionEdgeStudyRun,
    SessionOpportunity,
)

MAX_SOURCE_BARS = 800_000
WARMUP_DAYS = 45


async def execute_session_edge_study(
    session: AsyncSession,
    *,
    instrument: str,
    provider_code: str,
    start: datetime,
    end: datetime,
    include_fundamentals: bool,
    config: SessionEdgeConfig,
) -> tuple[SessionEdgeStudyRun, list[SessionOpportunity]]:
    _validate_request(start=start, end=end)
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    warmup_start = start_utc - timedelta(days=WARMUP_DAYS)
    predicates = (
        PriceBar.instrument_code == instrument,
        PriceBar.provider_code == provider_code,
        PriceBar.timeframe == "1m",
        PriceBar.open_time >= warmup_start,
        PriceBar.open_time < end_utc,
        PriceBar.available_at <= end_utc,
        PriceBar.is_complete.is_(True),
        PriceBar.is_synthetic.is_(False),
    )
    source_bar_count = int(
        await session.scalar(select(func.count()).select_from(PriceBar).where(*predicates)) or 0
    )
    if source_bar_count < 10_000:
        raise ValueError(
            "At least 10,000 observed one-minute bars are required. "
            "Ingest more IC Markets history first."
        )
    if source_bar_count > MAX_SOURCE_BARS:
        raise ValueError(
            f"This synchronous study is limited to {MAX_SOURCE_BARS:,} source bars. "
            "Split the period into chronological research runs."
        )

    query = (
        select(
            PriceBar.open_time,
            PriceBar.close_time,
            PriceBar.open,
            PriceBar.high,
            PriceBar.low,
            PriceBar.close,
            PriceBar.volume,
            PriceBar.available_at,
            PriceBar.spread_price,
            PriceBar.source_record_key,
        )
        .where(*predicates)
        .order_by(PriceBar.open_time, PriceBar.available_at)
    )
    bars: list[SessionEdgeBar] = []
    stream = await session.stream(query)
    async for row in stream:
        bars.append(
            SessionEdgeBar(
                open_time=row.open_time,
                close_time=row.close_time,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                tick_volume=float(row.volume) if row.volume is not None else None,
                available_at=row.available_at,
                spread_price=(float(row.spread_price) if row.spread_price is not None else None),
                source_record_key=row.source_record_key,
            )
        )

    fundamental_inputs = (
        await load_fundamental_inputs(session, as_of=end_utc) if include_fundamentals else None
    )
    fundamental_cache: dict[datetime, FundamentalState] = {}

    def fundamental_state_at(decision_time: datetime) -> FundamentalState:
        if fundamental_inputs is None:
            raise RuntimeError("Fundamental inputs were not loaded")
        state = fundamental_cache.get(decision_time)
        if state is None:
            state = fundamental_inputs.state_at(decision_time)
            fundamental_cache[decision_time] = state
        return state

    result = await asyncio.to_thread(
        build_london_session_opportunities,
        bars,
        start=start_utc,
        end=end_utc,
        config=config,
        fundamental_state_at=(fundamental_state_at if include_fundamentals else None),
    )
    parameters = {
        "include_fundamentals": include_fundamentals,
        "summary_version": SESSION_EDGE_SUMMARY_VERSION,
        **_canonical_json(asdict(config)),
    }
    fundamental_provenance = (
        fundamental_inputs.provenance_at(end_utc) if fundamental_inputs is not None else None
    )
    combined_hash = _run_hash(
        instrument=instrument,
        provider_code=provider_code,
        start=start_utc,
        end=end_utc,
        parameters=parameters,
        price_hash=str(result.provenance["price_data_hash_sha256"]),
        opportunity_hashes=[item.data_hash for item in result.opportunities],
        fundamental_hash=(
            fundamental_inputs.state_at(end_utc).data_hash
            if fundamental_inputs is not None
            else None
        ),
    )
    now = datetime.now(UTC)
    run = SessionEdgeStudyRun(
        id=uuid4(),
        strategy_name=result.strategy,
        strategy_version=SESSION_EDGE_RULESET_VERSION,
        instrument_code=instrument,
        provider_code=provider_code,
        start_time=start_utc,
        end_time=end_utc,
        status=("COMPLETED" if result.opportunities else "COMPLETED_NO_SESSIONS"),
        parameters=parameters,
        data_hash=combined_hash,
        source_bar_count=source_bar_count,
        session_count=len(result.opportunities),
        trigger_count=sum(item.setup_side is not None for item in result.opportunities),
        results=result.summary,
        provenance={
            **result.provenance,
            "instrument": instrument,
            "provider_code": provider_code,
            "requested_start": start_utc.isoformat(),
            "requested_end": end_utc.isoformat(),
            "warmup_start": warmup_start.isoformat(),
            "fundamental_evidence": fundamental_provenance,
            "combined_data_hash_sha256": combined_hash,
            "persistence_policy": (
                "Each run and its per-session ledger are append-only. Re-running "
                "the same period creates a separately auditable result."
            ),
        },
        completed_at=now,
    )
    session.add(run)
    await session.flush()

    persisted: list[SessionOpportunity] = []
    for item in result.opportunities:
        model = _opportunity_model(run.id, item)
        session.add(model)
        persisted.append(model)
    await session.flush()
    return run, persisted


def session_edge_run_to_dict(
    run: SessionEdgeStudyRun,
    opportunities: list[SessionOpportunity] | None = None,
) -> dict[str, Any]:
    return {
        "id": run.id,
        "strategy_name": run.strategy_name,
        "strategy_version": run.strategy_version,
        "instrument": run.instrument_code,
        "provider_code": run.provider_code,
        "start": run.start_time,
        "end": run.end_time,
        "status": run.status,
        "parameters": run.parameters,
        "data_hash": run.data_hash,
        "source_bar_count": run.source_bar_count,
        "session_count": run.session_count,
        "trigger_count": run.trigger_count,
        "results": run.results,
        "provenance": run.provenance,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "opportunities": [session_opportunity_to_dict(item) for item in opportunities or []],
    }


def session_opportunity_to_dict(model: SessionOpportunity) -> dict[str, Any]:
    return {
        "id": model.id,
        "run_id": model.run_id,
        "session_date": model.session_date,
        "fundamental_freeze_time": model.fundamental_freeze_time,
        "level_freeze_time": model.level_freeze_time,
        "london_start_time": model.london_start_time,
        "london_end_time": model.london_end_time,
        "status": model.status,
        "no_trigger_reason": model.no_trigger_reason,
        "setup_side": model.setup_side,
        "signal_time": model.signal_time,
        "entry_time": model.entry_time,
        "bias_alignment": model.bias_alignment,
        "directional_score": (
            float(model.directional_score) if model.directional_score is not None else None
        ),
        "fundamental_confidence": (
            float(model.fundamental_confidence)
            if model.fundamental_confidence is not None
            else None
        ),
        "fundamental_coverage": (
            float(model.fundamental_coverage) if model.fundamental_coverage is not None else None
        ),
        "regime_label": model.regime_label,
        "dominant_driver": model.dominant_driver,
        "event_risk": model.event_risk,
        "asia_high": float(model.asia_high) if model.asia_high is not None else None,
        "asia_low": float(model.asia_low) if model.asia_low is not None else None,
        "asia_range_size": (
            float(model.asia_range_size) if model.asia_range_size is not None else None
        ),
        "asia_range_percentile": (
            float(model.asia_range_percentile) if model.asia_range_percentile is not None else None
        ),
        "asia_compression_state": model.asia_compression_state,
        "entry_reference_price": (
            float(model.entry_reference_price) if model.entry_reference_price is not None else None
        ),
        "invalidation_price": (
            float(model.invalidation_price) if model.invalidation_price is not None else None
        ),
        "risk_distance": (float(model.risk_distance) if model.risk_distance is not None else None),
        "facts": model.facts,
        "outcomes": model.outcomes,
        "evidence": model.evidence,
        "data_hash": model.data_hash,
        "created_at": model.created_at,
    }


async def compare_session_edge_studies(
    session: AsyncSession,
    *,
    run_ids: list[UUID],
) -> dict[str, Any]:
    if len(run_ids) < 2:
        raise ValueError("At least two session-edge run IDs are required.")
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("Session-edge comparison run IDs must be unique.")
    runs = list(
        (
            await session.scalars(
                select(SessionEdgeStudyRun).where(SessionEdgeStudyRun.id.in_(run_ids))
            )
        ).all()
    )
    by_id = {run.id: run for run in runs}
    missing = [str(run_id) for run_id in run_ids if run_id not in by_id]
    if missing:
        raise ValueError("Unknown session-edge run IDs: " + ", ".join(missing))
    ordered_runs = [by_id[run_id] for run_id in run_ids]
    first = ordered_runs[0]
    for run in ordered_runs[1:]:
        if (
            run.strategy_name != first.strategy_name
            or run.strategy_version != first.strategy_version
            or run.instrument_code != first.instrument_code
            or run.provider_code != first.provider_code
            or run.parameters != first.parameters
        ):
            raise ValueError(
                "Compared runs must use identical strategy, provider, instrument, "
                "and parameters."
            )
    rows = list(
        (
            await session.scalars(
                select(SessionOpportunity)
                .where(SessionOpportunity.run_id.in_(run_ids))
                .order_by(SessionOpportunity.session_date, SessionOpportunity.run_id)
            )
        ).all()
    )
    seen_dates: set[Any] = set()
    duplicates: list[str] = []
    for row in rows:
        if row.session_date in seen_dates:
            duplicates.append(row.session_date.isoformat())
        seen_dates.add(row.session_date)
    if duplicates:
        raise ValueError(
            "Compared runs overlap on session dates: "
            + ", ".join(sorted(set(duplicates))[:10])
        )
    opportunities = [_domain_opportunity(row) for row in rows]
    summary = summarize_session_opportunities(opportunities)
    comparison_hash = hashlib.sha256(
        json.dumps(
            {
                "run_ids": [str(run.id) for run in ordered_runs],
                "run_hashes": [run.data_hash for run in ordered_runs],
                "opportunity_hashes": [row.data_hash for row in rows],
                "summary_version": SESSION_EDGE_SUMMARY_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "run_ids": [run.id for run in ordered_runs],
        "strategy_name": first.strategy_name,
        "strategy_version": first.strategy_version,
        "summary_version": SESSION_EDGE_SUMMARY_VERSION,
        "instrument": first.instrument_code,
        "provider_code": first.provider_code,
        "periods": [
            {
                "run_id": str(run.id),
                "start": run.start_time.isoformat(),
                "end": run.end_time.isoformat(),
                "data_hash": run.data_hash,
            }
            for run in ordered_runs
        ],
        "session_count": len(rows),
        "trigger_count": sum(row.setup_side is not None for row in rows),
        "summary": summary,
        "data_hash": comparison_hash,
        "interpretation": (
            "This combines non-overlapping immutable opportunity ledgers that used "
            "identical parameters. It is still an observational event study, not "
            "an executable strategy backtest."
        ),
    }


def _opportunity_model(
    run_id: Any,
    opportunity: CalculatedOpportunity,
) -> SessionOpportunity:
    payload = opportunity_to_dict(opportunity)
    fundamental = opportunity.fundamental
    asia = opportunity.asia_range
    return SessionOpportunity(
        id=uuid4(),
        run_id=run_id,
        session_date=opportunity.session_date,
        fundamental_freeze_time=opportunity.fundamental_freeze_time,
        level_freeze_time=opportunity.level_freeze_time,
        london_start_time=opportunity.london_start_time,
        london_end_time=opportunity.london_end_time,
        status=opportunity.status,
        no_trigger_reason=opportunity.no_trigger_reason,
        setup_side=opportunity.setup_side,
        signal_time=opportunity.signal_time,
        entry_time=opportunity.entry_time,
        bias_alignment=opportunity.bias_alignment,
        directional_score=_optional_decimal(fundamental.get("directional_score")),
        fundamental_confidence=_optional_decimal(fundamental.get("confidence")),
        fundamental_coverage=_optional_decimal(fundamental.get("coverage")),
        regime_label=str(fundamental.get("regime_label") or "UNKNOWN"),
        dominant_driver=(
            str(fundamental["dominant_driver"])
            if fundamental.get("dominant_driver") is not None
            else None
        ),
        event_risk=str(fundamental.get("event_risk") or "UNKNOWN"),
        asia_high=_optional_decimal(asia.high),
        asia_low=_optional_decimal(asia.low),
        asia_range_size=_optional_decimal(asia.range_size),
        asia_range_percentile=_optional_decimal(opportunity.asia_range_percentile),
        asia_compression_state=opportunity.asia_compression_state,
        entry_reference_price=_optional_decimal(opportunity.entry_reference_price),
        invalidation_price=_optional_decimal(opportunity.invalidation_price),
        risk_distance=_optional_decimal(opportunity.risk_distance),
        facts={
            "asia_range": payload["asia_range"],
            "reference_levels": payload["reference_levels"],
            "fundamental": payload["fundamental"],
            "attempts": payload["attempts"],
        },
        outcomes=payload["outcomes"],
        evidence=payload["evidence"],
        data_hash=opportunity.data_hash,
    )


def _domain_opportunity(model: SessionOpportunity) -> CalculatedOpportunity:
    asia_payload = cast(dict[str, Any], model.facts["asia_range"])
    fundamental = cast(dict[str, Any], model.facts["fundamental"])
    reference_levels_payload = cast(
        dict[str, float | None],
        model.facts["reference_levels"],
    )
    attempts_payload = cast(list[dict[str, Any]], model.facts["attempts"])
    outcomes_payload = model.outcomes
    return CalculatedOpportunity(
        session_date=model.session_date,
        fundamental_freeze_time=model.fundamental_freeze_time,
        level_freeze_time=model.level_freeze_time,
        london_start_time=model.london_start_time,
        london_end_time=model.london_end_time,
        status=model.status,
        no_trigger_reason=model.no_trigger_reason,
        asia_range=AsiaRange(
            session_date=model.session_date,
            start_time=_parse_json_datetime(asia_payload["start_time"]),
            end_time=_parse_json_datetime(asia_payload["end_time"]),
            status=str(asia_payload["status"]),
            bar_count=int(asia_payload["bar_count"]),
            expected_bar_count=int(asia_payload["expected_bar_count"]),
            open=_optional_float(asia_payload.get("open")),
            high=_optional_float(asia_payload.get("high")),
            low=_optional_float(asia_payload.get("low")),
            close=_optional_float(asia_payload.get("close")),
            range_size=_optional_float(asia_payload.get("range_size")),
        ),
        asia_range_percentile=(
            float(model.asia_range_percentile)
            if model.asia_range_percentile is not None
            else None
        ),
        asia_compression_state=model.asia_compression_state,
        reference_levels={
            str(key): _optional_float(value)
            for key, value in reference_levels_payload.items()
        },
        fundamental=fundamental,
        attempts=tuple(_domain_attempt(item) for item in attempts_payload),
        setup_side=cast(Side | None, model.setup_side),
        signal_time=model.signal_time,
        entry_time=model.entry_time,
        entry_reference_price=_optional_float(model.entry_reference_price),
        invalidation_price=_optional_float(model.invalidation_price),
        risk_distance=_optional_float(model.risk_distance),
        bias_alignment=cast(BiasAlignment, model.bias_alignment),
        outcomes=tuple(_domain_outcome(item) for item in outcomes_payload),
        data_hash=model.data_hash,
        evidence=model.evidence,
    )


def _domain_attempt(payload: dict[str, Any]) -> SweepAttempt:
    return SweepAttempt(
        side=cast(Side, payload["side"]),
        level_code=str(payload["level_code"]),
        level=float(payload["level"]),
        sweep_time=_parse_json_datetime(payload["sweep_time"]),
        sweep_extreme=float(payload["sweep_extreme"]),
        depth_price=float(payload["depth_price"]),
        depth_atr=float(payload["depth_atr"]),
        qualified=bool(payload["qualified"]),
        qualification_reason=str(payload["qualification_reason"]),
        reclaim_time=_optional_json_datetime(payload.get("reclaim_time")),
        micro_structure_level=_optional_float(payload.get("micro_structure_level")),
        displacement_time=_optional_json_datetime(payload.get("displacement_time")),
        displacement_body_atr=_optional_float(payload.get("displacement_body_atr")),
        displacement_body_ratio=_optional_float(payload.get("displacement_body_ratio")),
        displacement_close_location=_optional_float(
            payload.get("displacement_close_location")
        ),
        tick_volume_percentile=_optional_float(payload.get("tick_volume_percentile")),
        spread_percentile=_optional_float(payload.get("spread_percentile")),
        triggered=bool(payload["triggered"]),
    )


def _domain_outcome(payload: dict[str, Any]) -> PathOutcome:
    target_payload = cast(dict[str, bool | None], payload["target_before_stop"])
    return PathOutcome(
        horizon_minutes=int(payload["horizon_minutes"]),
        status=str(payload["status"]),
        bar_count=int(payload["bar_count"]),
        expected_bar_count=int(payload["expected_bar_count"]),
        terminal_price=_optional_float(payload.get("terminal_price")),
        terminal_return_pct=_optional_float(payload.get("terminal_return_pct")),
        terminal_r=_optional_float(payload.get("terminal_r")),
        mfe_price=_optional_float(payload.get("mfe_price")),
        mae_price=_optional_float(payload.get("mae_price")),
        mfe_r=_optional_float(payload.get("mfe_r")),
        mae_r=_optional_float(payload.get("mae_r")),
        target_before_stop={
            str(key): value for key, value in target_payload.items()
        },
        gross_path_outcome_r_1r=_optional_float(
            payload.get("gross_path_outcome_r_1r")
        ),
    )


def _validate_request(*, start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must include a timezone")
    if start >= end:
        raise ValueError("start must precede end")
    if end - start > timedelta(days=640):
        raise ValueError("A synchronous session-edge run is limited to 640 calendar days.")


def _run_hash(
    *,
    instrument: str,
    provider_code: str,
    start: datetime,
    end: datetime,
    parameters: dict[str, Any],
    price_hash: str,
    opportunity_hashes: list[str],
    fundamental_hash: str | None,
) -> str:
    payload = {
        "instrument": instrument,
        "provider_code": provider_code,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "parameters": parameters,
        "price_hash": price_hash,
        "fundamental_hash": fundamental_hash,
        "opportunity_hashes": opportunity_hashes,
        "ruleset_version": SESSION_EDGE_RULESET_VERSION,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _canonical_json(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _optional_decimal(value: Any | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _optional_float(value: Any | None) -> float | None:
    return float(value) if value is not None else None


def _parse_json_datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Persisted session-edge datetime lacks a timezone.")
    return parsed


def _optional_json_datetime(value: Any | None) -> datetime | None:
    return _parse_json_datetime(value) if value is not None else None
