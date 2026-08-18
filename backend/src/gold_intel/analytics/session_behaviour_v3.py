from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready

SCHEMA_VERSION = "gold-session-behaviour-v3-case-matrix-0.1.0"
TRANSFORM_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M2_TRANSFORM_V0_1"
CONTRACT_MANIFEST_HASH = (
    "79a74f81bce0b80ca6c5da6b420400479013484a4bb759684402546672fa140b"
)
TRACEABILITY_CATALOG_HASH = (
    "8707c39eb75bf3c74ce33908b0a3f4b0a1f679ee68848f1d10dce25e4bdf6bb4"
)
CASEBOOK_MANIFEST_HASH = (
    "d1241633b073cd7307f1da00a13a2d76c132f3dccefc52a076be2c641f06b85f"
)
M2_PRE_RESULT_MANIFEST_HASH = (
    "2838beaf2af0b3a74dca7ac1280591505cadd1eb0fb8b6dd1e5f06ff45b1d8d9"
)

CREATED_AND_SEALED_AT = "2026-07-30T07:57:23.645058+00:00"
DEVELOPMENT_START = datetime(2021, 8, 1, tzinfo=UTC)
DEVELOPMENT_END = datetime(2025, 1, 1, tzinfo=UTC)
MEASUREMENT_BAR_COUNT = 239
FIVE_MINUTE_POINT_COUNT = 48
DECIMAL_QUANTUM = Decimal("0.00000001")

REQUIRED_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
HORIZONS: tuple[tuple[str, int | None], ...] = (
    ("5m", 5),
    ("15m", 15),
    ("30m", 30),
    ("60m", 60),
    ("SESSION_CLOSE", None),
)

SERIES_MAPPING = {
    "cpi_core": "US_CPI_CORE",
    "cpi_headline": "US_CPI_HEADLINE",
    "equities": "US_EQUITY_PROXY",
    "fed_policy_rate": "US_FED_FUNDS_EFFECTIVE",
    "financial_stress": "US_FINANCIAL_STRESS",
    "gdp": "US_REAL_GDP",
    "high_yield_spread": "US_HIGH_YIELD_OAS",
    "initial_claims": "US_INITIAL_JOBLESS_CLAIMS",
    "payrolls": "US_NONFARM_PAYROLLS",
    "pce_core": "US_PCE_CORE",
    "pce_headline": "US_PCE_HEADLINE",
    "real_yield_10y": "US_REAL_YIELD_10Y",
    "retail_sales": "US_RETAIL_SALES",
    "treasury_10y": "US_TREASURY_10Y",
    "treasury_2y": "US_TREASURY_2Y",
    "unemployment": "US_UNEMPLOYMENT_RATE",
    "usd": "USD_BROAD_NOMINAL",
    "volatility": "US_VOLATILITY_INDEX",
    "wages": "US_AVERAGE_HOURLY_EARNINGS",
}

LEVEL_TYPES = {
    "ASIA_HIGH": "ASIA_HIGH",
    "ASIA_LOW": "ASIA_LOW",
    "PRIOR_SESSION_HIGH": "PRIOR_SESSION_HIGH",
    "PRIOR_SESSION_LOW": "PRIOR_SESSION_LOW",
    "PRIOR_SAME_SESSION_HIGH": "PRIOR_SESSION_HIGH",
    "PRIOR_SAME_SESSION_LOW": "PRIOR_SESSION_LOW",
    "PRIOR_DAY_HIGH": "PRIOR_DAY_HIGH",
    "PRIOR_DAY_LOW": "PRIOR_DAY_LOW",
    "PRIOR_TRADING_DAY_HIGH": "PRIOR_DAY_HIGH",
    "PRIOR_TRADING_DAY_LOW": "PRIOR_DAY_LOW",
    "PRIOR_WEEK_HIGH": "PRIOR_WEEK_HIGH",
    "PRIOR_WEEK_LOW": "PRIOR_WEEK_LOW",
}

QUALITY_MAP = {
    "READY": "VALID",
    "COMPLETE": "VALID",
    "ACTIVE": "VALID",
    "STALE": "STALE",
    "ROLL_CROSSING": "ROLL_CROSSING",
    "UNVERIFIED": "UNVERIFIED_AVAILABILITY",
    "UNKNOWN": "MISSING",
    "NOT_STARTED": "MISSING",
    "MISSING": "MISSING",
}

RESEARCH_POLICY = {
    "schema_purpose": "DESCRIPTIVE_SESSION_BEHAVIOUR_AND_POINT_IN_TIME_CONDITIONS",
    "decision_outcome_separated": True,
    "trade_direction_assigned": False,
    "candidate_or_relationship_label_present": False,
    "entry_or_exit_assumed": False,
    "stop_or_target_assigned": False,
    "position_size_assigned": False,
    "execution_optimized": False,
    "mfe_or_mae_calculated": False,
    "pnl_or_r_multiple_calculated": False,
    "account_return_calculated": False,
}

SWING_KINDS = {
    "SWING_HIGH",
    "SWING_LOW",
    "HIGHER_HIGH",
    "HIGHER_LOW",
    "LOWER_HIGH",
    "LOWER_LOW",
    "EQUAL_HIGH",
    "EQUAL_LOW",
}
BREAK_KINDS = {
    "BREAK_OF_STRUCTURE_BULLISH",
    "BREAK_OF_STRUCTURE_BEARISH",
}
SHIFT_KINDS = {
    "MARKET_STRUCTURE_SHIFT_BULLISH",
    "MARKET_STRUCTURE_SHIFT_BEARISH",
}
BREAK_STATE_TOKENS = ("BREAK", "ACCEPT", "REJECT", "TRAP", "RETEST")


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Naive timestamp is forbidden: {value}")
    return parsed.astimezone(UTC)


def sha256_file(path: Any) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decimal_value(value: Any) -> Decimal:
    return Decimal(str(value))


def published_decimal(value: Decimal) -> float:
    return float(value.quantize(DECIMAL_QUANTUM, rounding=ROUND_HALF_UP))


def quality_for(status: Any, *, fallback: str = "VALID") -> str:
    return QUALITY_MAP.get(str(status or "").upper(), fallback)


def source_ref(
    record: Mapping[str, Any],
    *,
    provider_code: str | None = None,
    source_key: str | None = None,
    available_at: str | None = None,
    vintage: str | None = None,
) -> dict[str, Any]:
    record_id = str(record["record_id"])
    record_hash = str(record["record_hash"])
    resolved_available = (
        available_at
        or record.get("available_at")
        or record.get("availability_at")
        or record.get("event_available_at")
        or record.get("publication_at")
        or record.get("released_at")
    )
    if not resolved_available:
        raise ValueError(f"Source record has no availability clock: {record_id}")
    resolved_provider = (
        provider_code
        or record.get("provider_code")
        or record.get("source", {}).get("provider_code")
        or "GOLD_CASEBOOK_V0_1"
    )
    resolved_key = (
        source_key
        or record.get("source_record_key")
        or record.get("source", {}).get("source_record_key")
        or record_id
    )
    return {
        "record_id": record_id,
        "record_hash": record_hash,
        "provider_code": str(resolved_provider),
        "source_key": str(resolved_key),
        "available_at": str(resolved_available),
        "vintage": vintage or record.get("vintage") or record.get("casebook_version"),
    }


def compact_bar_source_ref(bar: Mapping[str, Any]) -> dict[str, Any]:
    return source_ref(
        bar,
        provider_code=str(bar.get("provider_code", "IC_MARKETS_MT5")),
        source_key=str(
            bar.get("source_record_key")
            or bar.get("source", {}).get("source_record_key")
            or bar["record_id"]
        ),
        available_at=str(bar["available_at"]),
        vintage=str(bar.get("casebook_version", "GOLD_CASEBOOK_V0_1")),
    )


def fact(
    value: Any,
    *,
    epistemic_status: str,
    as_of: str | None,
    available_at: str | None,
    quality: str,
    explanation: str,
    unit: str | None = None,
    method: str | None = None,
    evidence: Iterable[str] = (),
    source_refs: Iterable[Mapping[str, Any]] = (),
    invalidation: str | None = None,
) -> dict[str, Any]:
    if epistemic_status == "UNKNOWN" and value is not None:
        raise ValueError("UNKNOWN facts must have null value")
    return {
        "value": json_ready(value),
        "unit": unit,
        "epistemic_status": epistemic_status,
        "as_of": as_of,
        "available_at": available_at,
        "quality": quality,
        "method": method,
        "explanation": explanation,
        "evidence": [str(item) for item in evidence],
        "source_refs": [dict(item) for item in source_refs],
        "invalidation": invalidation,
    }


def unknown_fact(
    explanation: str,
    *,
    quality: str = "MISSING",
    method: str | None = None,
) -> dict[str, Any]:
    return fact(
        None,
        epistemic_status="UNKNOWN",
        as_of=None,
        available_at=None,
        quality=quality,
        method=method,
        explanation=explanation,
    )


def record_fact(
    value: Any,
    record: Mapping[str, Any],
    *,
    epistemic_status: str,
    explanation: str,
    unit: str | None = None,
    method: str | None = None,
    as_of: str | None = None,
    available_at: str | None = None,
    quality: str = "VALID",
    evidence: Iterable[str] = (),
    invalidation: str | None = None,
) -> dict[str, Any]:
    resolved_available = str(
        available_at
        or record.get("available_at")
        or record.get("availability_at")
        or record.get("event_available_at")
        or record.get("publication_at")
        or record.get("released_at")
    )
    resolved_as_of = str(
        as_of
        or record.get("as_of")
        or record.get("observation_time")
        or record.get("observation_date")
        or record.get("released_at")
        or resolved_available
    )
    return fact(
        value,
        epistemic_status=epistemic_status,
        as_of=resolved_as_of,
        available_at=resolved_available,
        quality=quality,
        explanation=explanation,
        unit=unit,
        method=method,
        evidence=[record["record_id"], *evidence],
        source_refs=[source_ref(record, available_at=resolved_available)],
        invalidation=invalidation,
    )


def series_fact(
    code: str,
    snapshot: Mapping[str, Any],
    *,
    unknowns: list[dict[str, Any]] | None = None,
    field_path: str | None = None,
) -> dict[str, Any]:
    state = snapshot.get("series_state", {}).get(code)
    if not state or state.get("status") != "READY":
        if unknowns is not None and field_path:
            unknowns.append(
                {
                    "field_path": field_path,
                    "reason_code": "MISSING",
                    "required_action": f"Supply a point-in-time eligible {code} observation.",
                }
            )
        return unknown_fact(
            f"No point-in-time eligible {code} observation was available at the decision.",
            method="POINT_IN_TIME_LATEST_VINTAGE",
        )
    status = str(state.get("epistemic_status", "OBSERVED"))
    if status not in {"OBSERVED", "CALCULATED", "INFERRED"}:
        status = "OBSERVED"
    return fact(
        dict(state),
        epistemic_status=status,
        as_of=str(state["observation_time"]),
        available_at=str(state["available_at"]),
        quality=quality_for(state.get("status")),
        explanation=(
            f"{code} point-in-time state, including its level, vintage, "
            "direction and rate-of-change fields."
        ),
        unit=state.get("unit"),
        method="POINT_IN_TIME_LATEST_VINTAGE",
        evidence=[str(state.get("record_id")), str(snapshot["record_id"])],
        source_refs=[source_ref(snapshot)],
        invalidation="Superseded only by a later vintage after its own availability timestamp.",
    )


def cross_instrument_fact(
    code: str,
    cross_snapshot: Mapping[str, Any],
    *,
    explanation: str,
) -> dict[str, Any]:
    instrument = cross_snapshot.get("instruments", {}).get(code)
    if not instrument:
        return unknown_fact(f"{code} was unavailable in the decision-time snapshot.")
    if instrument.get("status") != "READY":
        reason = str(instrument.get("reason", instrument.get("status", "UNKNOWN")))
        quality = "STALE" if instrument.get("status") == "STALE" else "MISSING"
        return unknown_fact(f"{code} was not decision-ready: {reason}.", quality=quality)
    epistemic = str(instrument.get("epistemic_status", "OBSERVED"))
    return fact(
        dict(instrument),
        epistemic_status=epistemic,
        as_of=str(instrument.get("observed_at") or cross_snapshot["as_of"]),
        available_at=str(instrument["available_at"]),
        quality=quality_for(instrument.get("status")),
        explanation=explanation,
        unit="PRICE",
        method="POINT_IN_TIME_SYNCHRONIZED_MARKET_SNAPSHOT",
        evidence=[str(cross_snapshot["record_id"]), str(instrument.get("source_record_key"))],
        source_refs=[source_ref(cross_snapshot)],
        invalidation="Becomes stale or is replaced by a later observed market snapshot.",
    )


def compact_price_bar(bar: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "available_at": bar["available_at"],
        "close_time": bar["close_time"],
        "complete": bool(bar["complete"]),
        "epistemic_status": bar.get("epistemic_status", "OBSERVED"),
        "ohlc": dict(bar["ohlc"]),
        "open_time": bar["open_time"],
        "provider_code": bar.get("provider_code", "IC_MARKETS_MT5"),
        "record_hash": bar["record_hash"],
        "record_id": bar["record_id"],
        "source_record_key": (
            bar.get("source_record_key")
            or bar.get("source", {}).get("source_record_key")
            or bar["record_id"]
        ),
        "spread_points": bar.get("spread_points"),
        "spread_price": bar.get("spread_price"),
        "volume": bar.get("volume"),
        "volume_type": bar.get("volume_type"),
        "casebook_version": bar.get("casebook_version", "GOLD_CASEBOOK_V0_1"),
    }


def build_case(
    *,
    session: Mapping[str, Any],
    measurement_bars: Sequence[Mapping[str, Any]],
    structure: Mapping[str, Any],
    cross: Mapping[str, Any],
    fundamental: Mapping[str, Any],
    positioning: Mapping[str, Any] | None,
    recent_events: Sequence[Mapping[str, Any]],
    policy_windows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    decision_at = str(session["decision_at"])
    decision_dt = parse_timestamp(decision_at)
    observation_end = str(session["observation_end"])
    observation_dt = parse_timestamp(observation_end)

    if not DEVELOPMENT_START <= decision_dt < DEVELOPMENT_END:
        raise ValueError(f"Session outside V3 development partition: {session['record_id']}")
    if session.get("holdout_loaded") is not False:
        raise ValueError(f"Source session opened a holdout: {session['record_id']}")
    if len(measurement_bars) != MEASUREMENT_BAR_COUNT:
        raise ValueError(
            f"{session['record_id']} has {len(measurement_bars)} neutral bars; "
            f"expected {MEASUREMENT_BAR_COUNT}"
        )
    if any(not bar.get("complete") for bar in measurement_bars):
        raise ValueError(f"Incomplete neutral measurement bar: {session['record_id']}")

    neutral_start = decision_dt + timedelta(minutes=1)
    first = measurement_bars[0]
    if parse_timestamp(str(first["open_time"])) != neutral_start:
        raise ValueError(f"Neutral reference mismatch: {session['record_id']}")
    if parse_timestamp(str(measurement_bars[-1]["close_time"])) != observation_dt:
        raise ValueError(f"Neutral observation end mismatch: {session['record_id']}")

    unknowns = _base_unknowns()
    levels = _build_levels(session)
    events = [_build_event_state(event, decision_at) for event in recent_events]
    release_states = [
        release
        for event in events
        for release in event["release_components"]
    ]

    market_structure = _build_structure(structure, decision_at)
    layers = _build_layers(
        session=session,
        cross=cross,
        fundamental=fundamental,
        positioning=positioning,
        events=events,
        release_states=release_states,
        policy_windows=policy_windows,
        unknowns=unknowns,
    )
    market_mechanics = _build_market_mechanics(
        cross=cross,
        positioning=positioning,
        unknowns=unknowns,
    )
    synthesis = _build_synthesis(fundamental)
    subsequent_behaviour = _build_subsequent_behaviour(
        session=session,
        measurement_bars=measurement_bars,
    )

    source_records = _source_records_for_lineage(
        session=session,
        measurement_bars=measurement_bars,
        structure=structure,
        cross=cross,
        fundamental=fundamental,
        positioning=positioning,
        events=recent_events,
        policy_windows=policy_windows,
    )
    source_ids = sorted(str(item["record_id"]) for item in source_records)
    source_refs = _deduplicated_source_refs(
        [
            source_ref(session),
            source_ref(structure),
            source_ref(cross),
            source_ref(fundamental),
            *([source_ref(positioning)] if positioning else []),
            *(source_ref(event) for event in recent_events),
            *(source_ref(window) for window in policy_windows),
            compact_bar_source_ref(measurement_bars[0]),
            compact_bar_source_ref(measurement_bars[-1]),
        ]
    )

    case: dict[str, Any] = {
        "case_metadata": {
            "case_id": f"V3-{session['record_id']}",
            "schema_version": SCHEMA_VERSION,
            "case_revision": 1,
            "session_code": session["session_code"],
            "session_date": session["session_date"],
            "session_timezone": session["session_timezone"],
            "decision_at": decision_at,
            "observation_start": neutral_start.isoformat(),
            "observation_end": observation_end,
            "data_partition": "DEVELOPMENT_2021_2024",
            "access_class": "DEVELOPMENT",
            "created_at": CREATED_AND_SEALED_AT,
            "sealed_at": CREATED_AND_SEALED_AT,
        },
        "lineage": {
            "contract_manifest_hash": CONTRACT_MANIFEST_HASH,
            "traceability_catalog_hash": TRACEABILITY_CATALOG_HASH,
            "source_bundle_refs": [
                {
                    "manifest_path": "research_artifacts/gold_casebook_v01/manifest.json",
                    "manifest_hash": CASEBOOK_MANIFEST_HASH,
                    "role": "IMMUTABLE_DEVELOPMENT_SOURCE_BUNDLE",
                },
                {
                    "manifest_path": (
                        "research_manifests/"
                        "gold_session_behaviour_v3_m2_case_matrix_v01.json"
                    ),
                    "manifest_hash": M2_PRE_RESULT_MANIFEST_HASH,
                    "role": "FROZEN_PRE_RESULT_MEASUREMENT_MANIFEST",
                },
            ],
            "source_record_count": len(source_records),
            "source_record_ids_hash": canonical_hash(source_ids),
            "source_record_refs": source_refs,
            "case_transform_versions": {
                "case_transform": TRANSFORM_VERSION,
                "neutral_path": "NEUTRAL_08_01_TO_12_00_V0_1",
                "point_in_time": "AVAILABLE_AT_LTE_DECISION_V0_1",
                "structure": str(structure["ruleset_version"]),
                "fundamentals": str(fundamental["ruleset_version"]),
            },
        },
        "decision_state": {
            "decision_eligible": True,
            "as_of": decision_at,
            "market_mechanics": market_mechanics,
            "market_structure": market_structure,
            "levels": levels,
            "layers": layers,
            "synthesis": synthesis,
            "unknowns": _deduplicated_unknowns(unknowns),
        },
        "subsequent_behaviour": subsequent_behaviour,
        "quality": {
            "overall_state": "VALID",
            "decision_state_point_in_time_valid": True,
            "outcome_separation_check_passed": True,
            "dst_check_passed": True,
            "duplicate_key_check_passed": True,
            "one_minute_source_complete": True,
            "session_path_complete": True,
            "unknown_field_count": len(_deduplicated_unknowns(unknowns)),
            "issue_codes": [],
        },
        "research_policy": dict(RESEARCH_POLICY),
    }
    case["case_metadata"]["record_hash"] = case_record_hash(case)
    return case


def case_record_hash(case: Mapping[str, Any]) -> str:
    unhashed = json.loads(json.dumps(json_ready(case)))
    unhashed["case_metadata"].pop("record_hash", None)
    return canonical_hash(unhashed)


def _source_records_for_lineage(
    *,
    session: Mapping[str, Any],
    measurement_bars: Sequence[Mapping[str, Any]],
    structure: Mapping[str, Any],
    cross: Mapping[str, Any],
    fundamental: Mapping[str, Any],
    positioning: Mapping[str, Any] | None,
    events: Sequence[Mapping[str, Any]],
    policy_windows: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = [
        session,
        *measurement_bars,
        structure,
        cross,
        fundamental,
        *events,
        *policy_windows,
    ]
    if positioning:
        records.append(positioning)
    unique: dict[str, Mapping[str, Any]] = {}
    for record in records:
        unique[str(record["record_id"])] = record
    return list(unique.values())


def _deduplicated_source_refs(
    refs: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for ref in refs:
        unique[str(ref["record_id"])] = dict(ref)
    return [unique[key] for key in sorted(unique)]


def _base_unknowns() -> list[dict[str, Any]]:
    return [
        {
            "field_path": "decision_state.market_mechanics.comex_volume",
            "reason_code": "NOT_LICENSED",
            "required_action": "Add licensed point-in-time COMEX intraday volume.",
        },
        {
            "field_path": "decision_state.market_mechanics.depth",
            "reason_code": "NOT_LICENSED",
            "required_action": "Add licensed historical depth-of-book data.",
        },
        {
            "field_path": "decision_state.market_mechanics.resilience",
            "reason_code": "NOT_LICENSED",
            "required_action": "Add depth and replenishment observations.",
        },
        {
            "field_path": "decision_state.market_mechanics.price_impact",
            "reason_code": "NOT_LICENSED",
            "required_action": "Add trade/depth data sufficient for impact estimation.",
        },
        {
            "field_path": "decision_state.layers.positioning.etf_holdings_flows",
            "reason_code": "MISSING",
            "required_action": "Add point-in-time ETF holdings and flow history.",
        },
        {
            "field_path": "decision_state.layers.positioning.central_bank_demand",
            "reason_code": "MISSING",
            "required_action": "Add vintage-aware central-bank demand data.",
        },
        {
            "field_path": "decision_state.layers.positioning.options",
            "reason_code": "NOT_LICENSED",
            "required_action": "Add licensed point-in-time gold options data.",
        },
        {
            "field_path": "decision_state.layers.positioning.fast_slow_divergence",
            "reason_code": "MISSING",
            "required_action": "Add ETF/central-bank slow-money history.",
        },
        {
            "field_path": "decision_state.layers.catalysts.upcoming_events",
            "reason_code": "UNVERIFIED_AVAILABILITY",
            "required_action": "Add a schedule archive with first-publication timestamps.",
        },
        {
            "field_path": "decision_state.layers.catalysts.proximity_state",
            "reason_code": "UNVERIFIED_AVAILABILITY",
            "required_action": "Derive only after historical schedule availability is verified.",
        },
        {
            "field_path": "decision_state.layers.catalysts.unscheduled_event_context",
            "reason_code": "NOT_LICENSED",
            "required_action": "Add licensed timestamped news/event history.",
        },
        {
            "field_path": (
                "decision_state.layers.expectations.policy_path.meeting_probabilities"
            ),
            "reason_code": "MISSING",
            "required_action": "Add exact point-in-time FOMC meeting probability history.",
        },
        {
            "field_path": "decision_state.layers.expectations.policy_path.first_move",
            "reason_code": "MISSING",
            "required_action": "Add exact point-in-time meeting-path history.",
        },
        {
            "field_path": "decision_state.layers.expectations.policy_path.total_change",
            "reason_code": "MISSING",
            "required_action": "Add exact point-in-time meeting-path history.",
        },
        {
            "field_path": (
                "decision_state.layers.expectations.policy_path.destination_rate"
            ),
            "reason_code": "MISSING",
            "required_action": "Add exact point-in-time meeting-path history.",
        },
    ]


def _deduplicated_unknowns(
    values: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for value in values:
        key = (str(value["field_path"]), str(value["reason_code"]))
        unique[key] = dict(value)
    return [unique[key] for key in sorted(unique)]


def _build_levels(session: Mapping[str, Any]) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    for index, item in enumerate(session["decision_state"].get("known_levels", [])):
        code = str(item["code"])
        known_at = str(item["known_at"])
        source_hash = str(item["source_hash"])
        level_type = LEVEL_TYPES.get(code, "OTHER")
        timeframe = _level_timeframe(code)
        level_id = f"{session['record_id']}-LEVEL-{index:02d}-{code}"
        levels.append(
            {
                "level_id": level_id,
                "level_type": level_type,
                "timeframe": timeframe,
                "price": fact(
                    item["price"],
                    unit="USD_PER_TROY_OUNCE",
                    epistemic_status="CALCULATED",
                    as_of=known_at,
                    available_at=known_at,
                    quality="VALID",
                    method="PRE_SESSION_LEVEL_FROM_COMPLETE_BARS",
                    explanation=f"{code} was known at the session decision clock.",
                    evidence=[source_hash, code],
                    invalidation="Historical coordinate; not an execution level.",
                ),
                "detected_at": known_at,
                "available_at": known_at,
                "method": "SOURCE_SESSION_KNOWN_LEVEL",
                "confidence": 100,
                "epistemic_status": "CALCULATED",
                "evidence": [source_hash, str(session["record_id"])],
                "invalidation": "Historical coordinate; not an execution instruction.",
                "liquidity_zone_interpretation": unknown_fact(
                    "A price coordinate is observed/calculated; resting liquidity is not "
                    "directly observed from this feed.",
                    quality="NOT_LICENSED",
                ),
            }
        )
    return levels


def _level_timeframe(code: str) -> str:
    if "WEEK" in code:
        return "1d"
    if "DAY" in code:
        return "1d"
    if "SESSION" in code or "ASIA" in code:
        return "5m"
    return "1h"


def _build_structure(
    structure: Mapping[str, Any],
    decision_at: str,
) -> dict[str, Any]:
    if parse_timestamp(str(structure["available_at"])) > parse_timestamp(decision_at):
        raise ValueError(f"Future structure snapshot: {structure['record_id']}")
    source = source_ref(structure)
    timeframes: list[dict[str, Any]] = []
    for timeframe in structure["timeframes"]:
        code = str(timeframe["timeframe"])
        detections = list(timeframe.get("detections", []))
        for detection in detections:
            if parse_timestamp(str(detection["detected_at"])) > parse_timestamp(decision_at):
                raise ValueError(
                    f"Future structure detection in {structure['record_id']}: "
                    f"{detection['kind']}"
                )
        detection_facts = [
            _structure_detection_fact(detection, source)
            for detection in detections
        ]
        timeframes.append(
            {
                "timeframe": code,
                "source_bar_count": int(timeframe.get("source_bar_count", 0)),
                "source_bar_ids_hash": str(structure["record_hash"]),
                "swing_state": _structure_group_fact(
                    [item for item in detections if item.get("kind") in SWING_KINDS],
                    source,
                    structure,
                    "Confirmed swing sequence available at the decision.",
                ),
                "trend_state": _structure_summary_fact(
                    timeframe.get("trend"),
                    source,
                    structure,
                    "Deterministic trend state from confirmed structure.",
                    method="SOURCE_STRUCTURE_TREND_STATE",
                ),
                "range_state": _structure_summary_fact(
                    {
                        "range_high": timeframe.get("range_high"),
                        "range_low": timeframe.get("range_low"),
                        "last_close": timeframe.get("last_close"),
                        "atr14": timeframe.get("atr14"),
                    },
                    source,
                    structure,
                    "Decision-time range and volatility state.",
                    method="SOURCE_STRUCTURE_RANGE_STATE",
                ),
                "support": _structure_summary_fact(
                    timeframe.get("support"),
                    source,
                    structure,
                    "Deterministic support state from confirmed pivots.",
                    method="SOURCE_STRUCTURE_SUPPORT",
                ),
                "resistance": _structure_summary_fact(
                    timeframe.get("resistance"),
                    source,
                    structure,
                    "Deterministic resistance state from confirmed pivots.",
                    method="SOURCE_STRUCTURE_RESISTANCE",
                ),
                "break_of_structure": _structure_group_fact(
                    [item for item in detections if item.get("kind") in BREAK_KINDS],
                    source,
                    structure,
                    "Break-of-structure detections known at the decision.",
                ),
                "market_structure_shift": _structure_group_fact(
                    [item for item in detections if item.get("kind") in SHIFT_KINDS],
                    source,
                    structure,
                    "Market-structure-shift detections known at the decision.",
                ),
                "break_state": _structure_group_fact(
                    [
                        item
                        for item in detections
                        if any(token in str(item.get("kind")) for token in BREAK_STATE_TOKENS)
                    ],
                    source,
                    structure,
                    "Break, acceptance, rejection, trapped-breakout and retest detections.",
                ),
                "compression": _structure_named_state_fact(
                    timeframe,
                    detections,
                    source,
                    structure,
                    "COMPRESSION",
                    {"compression_ratio": timeframe.get("compression_ratio")},
                ),
                "expansion": _structure_named_state_fact(
                    timeframe,
                    detections,
                    source,
                    structure,
                    "EXPANSION",
                    {},
                ),
                "displacement": _structure_named_state_fact(
                    timeframe,
                    detections,
                    source,
                    structure,
                    "DISPLACEMENT",
                    {},
                ),
                "momentum": _structure_named_state_fact(
                    timeframe,
                    detections,
                    source,
                    structure,
                    "MOMENTUM",
                    {"momentum_atr": timeframe.get("momentum_atr")},
                ),
                "detections": detection_facts,
            }
        )
    actual = tuple(item["timeframe"] for item in timeframes)
    if len(timeframes) != 6 or set(actual) != set(REQUIRED_TIMEFRAMES):
        raise ValueError(
            f"Structure snapshot lacks required timeframes: {structure['record_id']} {actual}"
        )
    return {
        "ruleset_version": str(structure["ruleset_version"]),
        "snapshot_available_at": str(structure["available_at"]),
        "timeframes": timeframes,
    }


def _structure_detection_fact(
    detection: Mapping[str, Any],
    structure_source: Mapping[str, Any],
) -> dict[str, Any]:
    return fact(
        dict(detection),
        unit="USD_PER_TROY_OUNCE",
        epistemic_status=str(detection.get("epistemic_status", "CALCULATED")),
        as_of=str(detection["timestamp"]),
        available_at=str(detection["detected_at"]),
        quality="VALID",
        method=str(detection["detection_method"]),
        explanation=(
            f"{detection['kind']} on {detection['timeframe']}; the later detected_at "
            "timestamp, not the pivot timestamp, controls availability."
        ),
        evidence=[
            str(structure_source["record_id"]),
            canonical_hash(detection.get("evidence", {})),
        ],
        source_refs=[structure_source],
        invalidation=detection.get("invalidation_condition"),
    )


def _structure_group_fact(
    detections: Sequence[Mapping[str, Any]],
    structure_source: Mapping[str, Any],
    structure: Mapping[str, Any],
    explanation: str,
) -> dict[str, Any]:
    return fact(
        {
            "detected": bool(detections),
            "detections": [dict(item) for item in detections],
        },
        epistemic_status="CALCULATED",
        as_of=str(structure["as_of"]),
        available_at=str(structure["available_at"]),
        quality="VALID",
        method="FILTERED_SOURCE_STRUCTURE_DETECTIONS",
        explanation=explanation,
        evidence=[str(structure["record_id"])],
        source_refs=[structure_source],
        invalidation="Re-evaluated only after a later complete bar becomes available.",
    )


def _structure_summary_fact(
    value: Any,
    structure_source: Mapping[str, Any],
    structure: Mapping[str, Any],
    explanation: str,
    *,
    method: str,
) -> dict[str, Any]:
    return fact(
        value,
        epistemic_status="CALCULATED",
        as_of=str(structure["as_of"]),
        available_at=str(structure["available_at"]),
        quality="VALID",
        method=method,
        explanation=explanation,
        evidence=[str(structure["record_id"])],
        source_refs=[structure_source],
        invalidation="Re-evaluated only after a later complete bar becomes available.",
    )


def _structure_named_state_fact(
    timeframe: Mapping[str, Any],
    detections: Sequence[Mapping[str, Any]],
    structure_source: Mapping[str, Any],
    structure: Mapping[str, Any],
    token: str,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    matching = [item for item in detections if token in str(item.get("kind"))]
    value = {
        **summary,
        "detected": bool(matching),
        "detections": [dict(item) for item in matching],
    }
    return _structure_summary_fact(
        value,
        structure_source,
        structure,
        f"{token.title()} state and matching deterministic detections.",
        method=f"SOURCE_STRUCTURE_{token}_STATE",
    )


def _build_layers(
    *,
    session: Mapping[str, Any],
    cross: Mapping[str, Any],
    fundamental: Mapping[str, Any],
    positioning: Mapping[str, Any] | None,
    events: Sequence[Mapping[str, Any]],
    release_states: Sequence[Mapping[str, Any]],
    policy_windows: Sequence[Mapping[str, Any]],
    unknowns: list[dict[str, Any]],
) -> dict[str, Any]:
    series_states = {
        code: series_fact(
            code,
            fundamental,
            unknowns=unknowns,
            field_path=f"decision_state.layers.market_regime.series_states.{code}",
        )
        for code in sorted(fundamental.get("series_state", {}))
    }

    def sf(name: str, path: str) -> dict[str, Any]:
        return series_fact(
            SERIES_MAPPING[name],
            fundamental,
            unknowns=unknowns,
            field_path=path,
        )

    engine = fundamental["engine_state"]
    fund_source = source_ref(fundamental)
    policy_fact = _policy_repricing_fact(policy_windows)
    positioning_layer = _build_positioning_layer(positioning, session, unknowns)
    event_component = _engine_component(engine, "CATALYST_SURPRISE")
    nominal_component = _engine_component(engine, "NOMINAL_DECOMPOSITION")

    return {
        "market_regime": {
            "inflation": {
                "cpi_headline": sf(
                    "cpi_headline",
                    "decision_state.layers.market_regime.inflation.cpi_headline",
                ),
                "cpi_core": sf(
                    "cpi_core",
                    "decision_state.layers.market_regime.inflation.cpi_core",
                ),
                "pce_headline": sf(
                    "pce_headline",
                    "decision_state.layers.market_regime.inflation.pce_headline",
                ),
                "pce_core": sf(
                    "pce_core",
                    "decision_state.layers.market_regime.inflation.pce_core",
                ),
            },
            "labour": {
                "payrolls": sf(
                    "payrolls",
                    "decision_state.layers.market_regime.labour.payrolls",
                ),
                "unemployment": sf(
                    "unemployment",
                    "decision_state.layers.market_regime.labour.unemployment",
                ),
                "wages": sf(
                    "wages",
                    "decision_state.layers.market_regime.labour.wages",
                ),
                "claims": sf(
                    "initial_claims",
                    "decision_state.layers.market_regime.labour.claims",
                ),
            },
            "growth": {
                "gdp": sf(
                    "gdp",
                    "decision_state.layers.market_regime.growth.gdp",
                ),
                "retail_sales": sf(
                    "retail_sales",
                    "decision_state.layers.market_regime.growth.retail_sales",
                ),
            },
            "rates": {
                "fed_policy_rate": sf(
                    "fed_policy_rate",
                    "decision_state.layers.market_regime.rates.fed_policy_rate",
                ),
                "treasury_2y": sf(
                    "treasury_2y",
                    "decision_state.layers.market_regime.rates.treasury_2y",
                ),
                "treasury_10y": sf(
                    "treasury_10y",
                    "decision_state.layers.market_regime.rates.treasury_10y",
                ),
                "real_yield_10y": sf(
                    "real_yield_10y",
                    "decision_state.layers.market_regime.rates.real_yield_10y",
                ),
                "breakeven_10y": series_fact(
                    "US_BREAKEVEN_10Y",
                    fundamental,
                    unknowns=unknowns,
                    field_path=(
                        "decision_state.layers.market_regime.rates.breakeven_10y"
                    ),
                ),
                "yield_curve_2s10s": _yield_curve_fact(fundamental),
            },
            "usd": sf(
                "usd",
                "decision_state.layers.market_regime.usd",
            ),
            "risk": {
                "equities": sf(
                    "equities",
                    "decision_state.layers.market_regime.risk.equities",
                ),
                "volatility": sf(
                    "volatility",
                    "decision_state.layers.market_regime.risk.volatility",
                ),
                "high_yield_spread": sf(
                    "high_yield_spread",
                    "decision_state.layers.market_regime.risk.high_yield_spread",
                ),
                "financial_stress": sf(
                    "financial_stress",
                    "decision_state.layers.market_regime.risk.financial_stress",
                ),
            },
            "series_states": series_states,
            "regime_state": fact(
                {
                    "regime_label": engine.get("regime_label"),
                    "directional_score": engine.get("directional_score"),
                    "confidence": engine.get("confidence"),
                    "coverage": engine.get("coverage"),
                },
                epistemic_status="INFERRED",
                as_of=str(fundamental["as_of"]),
                available_at=str(fundamental["available_at"]),
                quality="VALID",
                method=str(fundamental["ruleset_version"]),
                explanation=(
                    "Transparent pre-existing regime interpretation preserved as a "
                    "decision condition; it is not a candidate or outcome."
                ),
                evidence=[str(fundamental["record_id"]), str(engine.get("data_hash"))],
                source_refs=[fund_source],
                invalidation="Changes only when later point-in-time inputs become available.",
            ),
            "reaction_function": fact(
                engine.get("reaction_function"),
                epistemic_status="INFERRED",
                as_of=str(fundamental["as_of"]),
                available_at=str(fundamental["available_at"]),
                quality="VALID",
                method="TRANSPARENT_REACTION_FUNCTION_CLASSIFIER",
                explanation=(
                    "Pre-existing reaction-function profile used to weight transparent "
                    "fundamental components at the decision."
                ),
                evidence=[str(fundamental["record_id"])],
                source_refs=[fund_source],
                invalidation="Reclassified only after later point-in-time inputs.",
            ),
        },
        "expectations": {
            "recent_releases": list(release_states),
            "policy_path": {
                "meeting_probabilities": unknown_fact(
                    "Exact historical FOMC meeting probabilities are unavailable."
                ),
                "first_move": unknown_fact(
                    "The exact first expected FOMC move is unavailable."
                ),
                "total_change": unknown_fact(
                    "The exact meeting-path total change is unavailable."
                ),
                "destination_rate": unknown_fact(
                    "The exact expected terminal/destination policy rate is unavailable."
                ),
                "repricing": policy_fact,
            },
        },
        "positioning": positioning_layer,
        "catalysts": {
            "upcoming_events": [],
            "recent_events": list(events),
            "proximity_state": unknown_fact(
                "Historical schedule first-publication timestamps are unverified.",
                quality="UNVERIFIED_AVAILABILITY",
            ),
            "unscheduled_event_context": unknown_fact(
                "No licensed point-in-time unscheduled-event archive is present.",
                quality="NOT_LICENSED",
            ),
            "event_impact_state": (
                _component_fact(event_component, fundamental)
                if event_component
                else unknown_fact(
                    "No point-in-time CATALYST_SURPRISE engine component was available."
                )
            ),
        },
        "sessions_and_liquidity": _build_session_layer(session),
        "cross_market": {
            "gold": cross_instrument_fact(
                "XAUUSD",
                cross,
                explanation=(
                    "Decision-time IC Markets XAUUSD broker price and transparent "
                    "pre-decision changes."
                ),
            ),
            "treasury_2y": sf(
                "treasury_2y",
                "decision_state.layers.cross_market.treasury_2y",
            ),
            "treasury_10y": sf(
                "treasury_10y",
                "decision_state.layers.cross_market.treasury_10y",
            ),
            "real_yield_10y": sf(
                "real_yield_10y",
                "decision_state.layers.cross_market.real_yield_10y",
            ),
            "breakeven_10y": series_fact(
                "US_BREAKEVEN_10Y",
                fundamental,
                unknowns=unknowns,
                field_path="decision_state.layers.cross_market.breakeven_10y",
            ),
            "usd": sf(
                "usd",
                "decision_state.layers.cross_market.usd",
            ),
            "equities": sf(
                "equities",
                "decision_state.layers.cross_market.equities",
            ),
            "volatility": sf(
                "volatility",
                "decision_state.layers.cross_market.volatility",
            ),
            "silver": cross_instrument_fact(
                "XAGUSD",
                cross,
                explanation=(
                    "Decision-time IC Markets XAGUSD broker price and transparent "
                    "pre-decision changes."
                ),
            ),
            "policy_expectations": policy_fact,
            "relationship_states": [],
            "rates_driver_state": (
                _component_fact(nominal_component, fundamental)
                if nominal_component
                else unknown_fact(
                    "No point-in-time NOMINAL_DECOMPOSITION engine component was available."
                )
            ),
        },
    }


def _yield_curve_fact(fundamental: Mapping[str, Any]) -> dict[str, Any]:
    two = fundamental.get("series_state", {}).get("US_TREASURY_2Y")
    ten = fundamental.get("series_state", {}).get("US_TREASURY_10Y")
    if not two or not ten or two.get("status") != "READY" or ten.get("status") != "READY":
        return unknown_fact("Two-year and ten-year yields were not both decision-ready.")
    available_at = max(str(two["available_at"]), str(ten["available_at"]))
    as_of = max(str(two["observation_time"]), str(ten["observation_time"]))
    value = published_decimal(decimal_value(ten["value"]) - decimal_value(two["value"]))
    return fact(
        value,
        unit="PERCENTAGE_POINTS",
        epistemic_status="CALCULATED",
        as_of=as_of,
        available_at=available_at,
        quality="VALID",
        method="US_TREASURY_10Y_MINUS_US_TREASURY_2Y",
        explanation="Point-in-time 2s10s Treasury curve slope.",
        evidence=[str(two["record_id"]), str(ten["record_id"])],
        source_refs=[source_ref(fundamental)],
        invalidation="Changes when a later eligible yield observation becomes available.",
    )


def _policy_repricing_fact(
    windows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not windows:
        return unknown_fact(
            "No eligible Atlanta Fed quarterly SOFR distribution was available.",
            method="LATEST_ELIGIBLE_OBSERVATION_DATE",
        )
    latest_date = max(str(item["observation_date"]) for item in windows)
    selected = [dict(item) for item in windows if str(item["observation_date"]) == latest_date]
    latest_available = max(str(item["available_at"]) for item in selected)
    refs = [source_ref(item) for item in selected]
    return fact(
        {
            "semantics": "ATLANTA_FED_QUARTERLY_SOFR_REFERENCE_WINDOW_DISTRIBUTIONS",
            "exact_fomc_meeting_probabilities": False,
            "observation_date": latest_date,
            "windows": selected,
        },
        epistemic_status="OBSERVED",
        as_of=max(str(item["snapshot_as_of"]) for item in selected),
        available_at=latest_available,
        quality="VALID",
        method="LATEST_ELIGIBLE_OBSERVATION_DATE_ALL_REFERENCE_WINDOWS",
        explanation=(
            "Observed Atlanta Fed quarterly SOFR reference-window distributions. "
            "They are not labelled as exact FOMC meeting probabilities."
        ),
        evidence=[str(item["record_id"]) for item in selected],
        source_refs=refs,
        invalidation="Superseded by a later eligible observation date.",
    )


def _build_positioning_layer(
    positioning: Mapping[str, Any] | None,
    session: Mapping[str, Any],
    unknowns: list[dict[str, Any]],
) -> dict[str, Any]:
    if positioning is None:
        for field in (
            "managed_money",
            "producer_merchant",
            "swap_dealer",
            "other_reportable",
            "open_interest",
            "price_open_interest_state",
        ):
            unknowns.append(
                {
                    "field_path": f"decision_state.layers.positioning.{field}",
                    "reason_code": "MISSING",
                    "required_action": "Supply a published point-in-time CFTC report.",
                }
            )
        missing = unknown_fact("No eligible CFTC positioning report was available.")
        return {
            "managed_money": missing,
            "producer_merchant": missing,
            "swap_dealer": missing,
            "other_reportable": missing,
            "open_interest": missing,
            "price_open_interest_state": missing,
            "inferred_states": [],
            "etf_holdings_flows": unknown_fact(
                "Point-in-time ETF flows are unavailable."
            ),
            "central_bank_demand": unknown_fact(
                "Vintage-aware central-bank demand is unavailable."
            ),
            "options": unknown_fact(
                "Licensed point-in-time gold options history is unavailable.",
                quality="NOT_LICENSED",
            ),
            "fast_slow_divergence": unknown_fact(
                "Fast/slow-money divergence requires missing ETF/central-bank data."
            ),
        }
    decision_dt = parse_timestamp(str(session["decision_at"]))
    if (
        parse_timestamp(str(positioning["publication_at"])) > decision_dt
        or parse_timestamp(str(positioning["available_at"])) > decision_dt
    ):
        raise ValueError(f"COT used before publication: {positioning['record_id']}")
    ref = source_ref(positioning)

    def category(code: str) -> dict[str, Any]:
        value = positioning.get("categories", {}).get(code)
        if not value:
            return unknown_fact(f"CFTC category {code} is unavailable.")
        return fact(
            value,
            unit="CONTRACTS",
            epistemic_status="OBSERVED",
            as_of=f"{positioning['observation_date']}T23:59:59+00:00",
            available_at=str(positioning["available_at"]),
            quality=(
                "UNVERIFIED_AVAILABILITY"
                if positioning.get("availability_quality") != "OBSERVED"
                else "VALID"
            ),
            method="CFTC_DISAGGREGATED_FUTURES_ONLY",
            explanation=(
                f"Published CFTC {code} category. Category holdings are observed; "
                "participant motive is not."
            ),
            evidence=[str(positioning["record_id"])],
            source_refs=[ref],
            invalidation="Superseded only after the next report publication.",
        )

    inferred = positioning.get("inferred") or {}
    inferred_facts = [
        fact(
            {"code": key, "state": value},
            epistemic_status="INFERRED",
            as_of=f"{positioning['observation_date']}T23:59:59+00:00",
            available_at=str(positioning["available_at"]),
            quality="UNVERIFIED_AVAILABILITY",
            method="TRANSPARENT_COT_POSITIONING_INFERENCE",
            explanation=(
                "Interpretation from published CFTC categories and price/open-interest "
                "changes; not observed institutional intent."
            ),
            evidence=[str(positioning["record_id"]), str(key)],
            source_refs=[ref],
            invalidation="Re-evaluated after the next published report.",
        )
        for key, value in sorted(inferred.items())
        if key not in {"epistemic_status", "warning"}
    ]
    price_oi_state = inferred.get("participation_state")
    return {
        "managed_money": category("MANAGED_MONEY"),
        "producer_merchant": category("PRODUCER_MERCHANT"),
        "swap_dealer": category("SWAP_DEALER"),
        "other_reportable": category("OTHER_REPORTABLE"),
        "open_interest": fact(
            positioning.get("open_interest"),
            unit="CONTRACTS",
            epistemic_status="OBSERVED",
            as_of=f"{positioning['observation_date']}T23:59:59+00:00",
            available_at=str(positioning["available_at"]),
            quality="UNVERIFIED_AVAILABILITY",
            method="CFTC_DISAGGREGATED_FUTURES_ONLY",
            explanation="Published weekly COMEX gold futures open interest.",
            evidence=[str(positioning["record_id"])],
            source_refs=[ref],
            invalidation="Superseded only after the next report publication.",
        ),
        "price_open_interest_state": fact(
            price_oi_state,
            epistemic_status="INFERRED",
            as_of=f"{positioning['observation_date']}T23:59:59+00:00",
            available_at=str(positioning["available_at"]),
            quality="UNVERIFIED_AVAILABILITY",
            method="PRICE_AND_WEEKLY_OPEN_INTEREST_CLASSIFICATION",
            explanation=(
                "Probable participation classification; it is an inference, not "
                "observed institutional activity."
            ),
            evidence=[str(positioning["record_id"])],
            source_refs=[ref],
            invalidation="Re-evaluated after the next report publication.",
        ),
        "inferred_states": inferred_facts,
        "etf_holdings_flows": unknown_fact(
            "Point-in-time ETF holdings and flows are unavailable."
        ),
        "central_bank_demand": unknown_fact(
            "Vintage-aware central-bank demand is unavailable."
        ),
        "options": unknown_fact(
            "Licensed point-in-time gold options history is unavailable.",
            quality="NOT_LICENSED",
        ),
        "fast_slow_divergence": unknown_fact(
            "Fast/slow-money divergence requires missing ETF/central-bank data."
        ),
    }


def _build_session_layer(session: Mapping[str, Any]) -> dict[str, Any]:
    decision_at = str(session["decision_at"])
    session_source = source_ref(session)
    windows = session["decision_state"].get("windows", {})

    def window_fact(code: str) -> dict[str, Any]:
        value = windows.get(code)
        if not value:
            return unknown_fact(f"{code} window was not available at the decision.")
        epistemic = str(value.get("epistemic_status", "CALCULATED"))
        if epistemic == "UNKNOWN":
            return unknown_fact(
                f"{code} window had not started or was not known at the decision."
            )
        return fact(
            value,
            epistemic_status=epistemic,
            as_of=str(value.get("as_of", decision_at)),
            available_at=str(value.get("as_of", decision_at)),
            quality=quality_for(value.get("status")),
            method="IANA_TIMEZONE_SESSION_WINDOW",
            explanation=f"{code} session state known at the decision clock.",
            evidence=[str(session["record_id"]), str(value.get("source_hash"))],
            source_refs=[session_source],
            invalidation="Updated only after another complete session bar.",
        )

    asia = window_fact("asia")
    london = window_fact("london")
    return {
        "clock_context": fact(
            {
                "session_code": session["session_code"],
                "session_date": session["session_date"],
                "session_timezone": session["session_timezone"],
                "decision_at": decision_at,
                "observation_end": session["observation_end"],
            },
            epistemic_status="CALCULATED",
            as_of=decision_at,
            available_at=decision_at,
            quality="VALID",
            method="IANA_TIMEZONE_DATABASE",
            explanation="DST-aware local session clock converted to UTC.",
            evidence=[str(session["record_id"])],
            source_refs=[session_source],
            invalidation=None,
        ),
        "asia_state": asia,
        "london_state": london,
        "handover_overlap_state": fact(
            {
                "session_code": session["session_code"],
                "new_york_window_at_decision": windows.get("new_york"),
            },
            epistemic_status="CALCULATED",
            as_of=decision_at,
            available_at=decision_at,
            quality="VALID",
            method="IANA_TIMEZONE_WINDOW_INTERSECTION",
            explanation=(
                "Clock-state representation only; no directional session relation "
                "is calculated."
            ),
            evidence=[str(session["record_id"])],
            source_refs=[session_source],
            invalidation=None,
        ),
        "benchmark_windows": unknown_fact(
            "LBMA benchmark-window microstructure is not separately licensed.",
            quality="NOT_LICENSED",
        ),
        "rollover_close_state": unknown_fact(
            "Daily rollover/close liquidity state is outside this 08:00 decision snapshot."
        ),
        "liquidity_quality": fact(
            {
                "asia_average_spread": windows.get("asia", {}).get("average_spread"),
                "asia_maximum_spread": windows.get("asia", {}).get("maximum_spread"),
                "asia_tick_volume": windows.get("asia", {}).get("tick_volume"),
            },
            epistemic_status="CALCULATED",
            as_of=decision_at,
            available_at=decision_at,
            quality="VALID",
            method="PRE_DECISION_COMPLETE_BAR_AGGREGATION",
            explanation=(
                "Available spread and tick-volume context; depth and resilience "
                "remain unknown."
            ),
            evidence=[str(session["record_id"])],
            source_refs=[session_source],
            invalidation="Updated after later observed bars.",
        ),
    }


def _build_market_mechanics(
    *,
    cross: Mapping[str, Any],
    positioning: Mapping[str, Any] | None,
    unknowns: list[dict[str, Any]],
) -> dict[str, Any]:
    xau = cross.get("instruments", {}).get("XAUUSD")
    xau_fact = cross_instrument_fact(
        "XAUUSD",
        cross,
        explanation="Decision-time IC Markets XAUUSD broker-feed state.",
    )
    if xau:
        spread = fact(
            xau.get("spread_price"),
            unit="USD_PER_TROY_OUNCE",
            epistemic_status="OBSERVED",
            as_of=str(xau.get("observed_at")),
            available_at=str(xau.get("available_at")),
            quality=quality_for(xau.get("status")),
            method="BROKER_FEED_SNAPSHOT",
            explanation="Observed IC Markets broker-feed spread at the decision.",
            evidence=[str(cross["record_id"])],
            source_refs=[source_ref(cross)],
            invalidation="Replaced by the next broker snapshot.",
        )
        tick_volume = fact(
            xau.get("volume"),
            unit="TICKS",
            epistemic_status="OBSERVED",
            as_of=str(xau.get("observed_at")),
            available_at=str(xau.get("available_at")),
            quality=quality_for(xau.get("status")),
            method="BROKER_FEED_SNAPSHOT",
            explanation="Observed broker tick volume; not centralized market volume.",
            evidence=[str(cross["record_id"])],
            source_refs=[source_ref(cross)],
            invalidation="Replaced by the next broker snapshot.",
        )
    else:
        spread = unknown_fact("XAUUSD spread was unavailable.")
        tick_volume = unknown_fact("XAUUSD tick volume was unavailable.")
        unknowns.extend(
            [
                {
                    "field_path": "decision_state.market_mechanics.spread",
                    "reason_code": "MISSING",
                    "required_action": "Supply a decision-time XAUUSD broker snapshot.",
                },
                {
                    "field_path": "decision_state.market_mechanics.tick_volume",
                    "reason_code": "MISSING",
                    "required_action": "Supply a decision-time XAUUSD broker snapshot.",
                },
            ]
        )
    participant_inferences: list[dict[str, Any]] = []
    if positioning and positioning.get("inferred"):
        participant_inferences.append(
            fact(
                dict(positioning["inferred"]),
                epistemic_status="INFERRED",
                as_of=f"{positioning['observation_date']}T23:59:59+00:00",
                available_at=str(positioning["available_at"]),
                quality="UNVERIFIED_AVAILABILITY",
                method="TRANSPARENT_WEEKLY_COT_INFERENCE",
                explanation=(
                    "Probable weekly positioning behavior. This is explicitly inferred "
                    "and not observed participant intent."
                ),
                evidence=[str(positioning["record_id"])],
                source_refs=[source_ref(positioning)],
                invalidation="Re-evaluated at the next report publication.",
            )
        )
    return {
        "instrument_identity": record_fact(
            {
                "instrument": "XAUUSD",
                "provider": "IC_MARKETS_MT5",
                "market_scope": "BROKER_CFD_FEED",
                "not_complete_otc_or_comex_market": True,
            },
            cross,
            epistemic_status="OBSERVED",
            explanation=(
                "IC Markets MT5 XAUUSD broker CFD/feed identity; it is not the complete "
                "OTC gold or COMEX market."
            ),
            method="SOURCE_IDENTITY",
        ),
        "xauusd_price": xau_fact,
        "spread": spread,
        "tick_volume": tick_volume,
        "comex_volume": unknown_fact(
            "Point-in-time COMEX intraday volume is not licensed.",
            quality="NOT_LICENSED",
        ),
        "depth": unknown_fact(
            "Historical depth-of-book is not licensed.",
            quality="NOT_LICENSED",
        ),
        "resilience": unknown_fact(
            "Order-book resilience cannot be calculated without depth/replenishment data.",
            quality="NOT_LICENSED",
        ),
        "price_impact": unknown_fact(
            "Market-impact measurement requires unavailable trade/depth data.",
            quality="NOT_LICENSED",
        ),
        "participant_activity_inferences": participant_inferences,
    }


def _engine_component(
    engine: Mapping[str, Any],
    code: str,
) -> Mapping[str, Any] | None:
    return next(
        (item for item in engine.get("components", []) if item.get("code") == code),
        None,
    )


def _component_fact(
    component: Mapping[str, Any],
    fundamental: Mapping[str, Any],
) -> dict[str, Any]:
    epistemic_status = str(component.get("epistemic_status", "INFERRED"))
    if epistemic_status == "UNKNOWN":
        return fact(
            None,
            epistemic_status="UNKNOWN",
            as_of=str(fundamental["as_of"]),
            available_at=str(fundamental["available_at"]),
            quality="MISSING",
            method="EXISTING_TRANSPARENT_ENGINE_COMPONENT",
            explanation=(
                f"Pre-existing {component['code']} component was explicitly UNKNOWN "
                f"at the decision: {component.get('explanation', 'no eligible input')}."
            ),
            evidence=[str(fundamental["record_id"]), str(component["code"])],
            source_refs=[source_ref(fundamental)],
            invalidation="Becomes known only when an eligible source input is available.",
        )
    return fact(
        dict(component),
        epistemic_status=epistemic_status,
        as_of=str(fundamental["as_of"]),
        available_at=str(fundamental["available_at"]),
        quality="VALID",
        method="EXISTING_TRANSPARENT_ENGINE_COMPONENT",
        explanation=(
            f"Pre-existing {component['code']} component preserved as a decision-time "
            "condition; it is not a discovered relationship or trade signal."
        ),
        evidence=[str(fundamental["record_id"]), str(component["code"])],
        source_refs=[source_ref(fundamental)],
        invalidation="Changes only when later point-in-time inputs become available.",
    )


def _build_synthesis(fundamental: Mapping[str, Any]) -> dict[str, Any]:
    engine = fundamental["engine_state"]
    score = float(engine.get("directional_score") or 0.0)
    bias_sign = 1 if score > 0 else -1 if score < 0 else 0
    supporting: list[dict[str, Any]] = [
        fact(
            {
                "code": "ENGINE_SUMMARY",
                "bias_label": engine.get("bias_label"),
                "directional_score": engine.get("directional_score"),
                "confidence": engine.get("confidence"),
                "coverage": engine.get("coverage"),
                "dominant_driver": engine.get("dominant_driver"),
                "main_contradiction": engine.get("main_contradiction"),
                "score_is_not_trade_signal": True,
            },
            epistemic_status="INFERRED",
            as_of=str(fundamental["as_of"]),
            available_at=str(fundamental["available_at"]),
            quality="VALID",
            method=str(fundamental["ruleset_version"]),
            explanation=(
                "Existing transparent engine summary preserved for case completeness; "
                "it is neither a V3 candidate nor an outcome."
            ),
            evidence=[
                str(fundamental["record_id"]),
                str(engine.get("data_hash")),
            ],
            source_refs=[source_ref(fundamental)],
            invalidation="Changes only when later point-in-time inputs become available.",
        )
    ]
    contradicting: list[dict[str, Any]] = []
    for component in engine.get("components", []):
        contribution = float(component.get("contribution") or 0.0)
        contribution_sign = 1 if contribution > 0 else -1 if contribution < 0 else 0
        wrapped = _component_fact(component, fundamental)
        if bias_sign and contribution_sign and contribution_sign != bias_sign:
            contradicting.append(wrapped)
        else:
            supporting.append(wrapped)
    return {
        "supporting_evidence": supporting,
        "contradicting_evidence": contradicting,
        "highest_risk_assumption": unknown_fact(
            "No independently verified highest-risk assumption field exists in the "
            "source engine; V3 does not invent one."
        ),
    }


def _build_event_state(
    event: Mapping[str, Any],
    decision_at: str,
) -> dict[str, Any]:
    decision_dt = parse_timestamp(decision_at)
    if parse_timestamp(str(event["event_available_at"])) > decision_dt:
        raise ValueError(f"Future event in decision state: {event['record_id']}")
    ref = source_ref(event)
    releases = [
        _build_release_state(event, release)
        for release in event.get("releases", [])
        if parse_timestamp(str(release["available_at"])) <= decision_dt
    ]
    reaction_facts: list[dict[str, Any]] = []
    for horizon, reaction in event.get("fixed_horizon_reactions", {}).items():
        if horizon == "first_move_assessment" or not isinstance(reaction, Mapping):
            continue
        xau = reaction.get("instruments", {}).get("XAUUSD")
        if not xau or not xau.get("available_at"):
            continue
        if parse_timestamp(str(xau["available_at"])) > decision_dt:
            continue
        reaction_facts.append(
            fact(
                {"horizon": horizon, "xauusd": dict(xau)},
                epistemic_status="CALCULATED",
                as_of=str(reaction.get("as_of", xau["available_at"])),
                available_at=str(xau["available_at"]),
                quality=quality_for(xau.get("status")),
                method="FIXED_HORIZON_EVENT_REACTION",
                explanation=(
                    "Historical XAUUSD event reaction that had fully completed before "
                    "the session decision."
                ),
                evidence=[str(event["record_id"]), str(horizon)],
                source_refs=[ref],
                invalidation=None,
            )
        )
    first_move = event.get("fixed_horizon_reactions", {}).get("first_move_assessment")
    complete_at = event.get("complete_observation_available_at")
    if (
        first_move
        and complete_at
        and parse_timestamp(str(complete_at)) <= decision_dt
    ):
        path_summary = fact(
            dict(first_move),
            epistemic_status="CALCULATED",
            as_of=str(complete_at),
            available_at=str(complete_at),
            quality="VALID",
            method="SOURCE_EVENT_FIRST_MOVE_ASSESSMENT",
            explanation="Completed first-move hold/reversal summary known before decision.",
            evidence=[str(event["record_id"])],
            source_refs=[ref],
            invalidation=None,
        )
    else:
        path_summary = unknown_fact(
            "The complete first-move assessment was not yet available at the decision."
        )
    return {
        "event_id": str(event["event_id"]),
        "event_code": str(event["event_code"]),
        "event_type": str(event["event_type"]),
        "scheduled_at": str(event["scheduled_at"]),
        "schedule_known_at": None,
        "importance": record_fact(
            event.get("importance"),
            event,
            epistemic_status="OBSERVED",
            explanation="Source event importance metadata available at release.",
            unit="ORDINAL_1_TO_5",
            method="SOURCE_EVENT_IMPORTANCE",
            as_of=str(event["released_at"]),
            available_at=str(event["event_available_at"]),
        ),
        "status": str(event.get("status", "RELEASED")),
        "release_components": releases,
        "reaction_snapshots": reaction_facts,
        "path_summary": path_summary,
    }


def _build_release_state(
    event: Mapping[str, Any],
    release: Mapping[str, Any],
) -> dict[str, Any]:
    component = str(release["component_code"])
    event_ref = source_ref(event)
    forecast = next(
        (
            item
            for item in event.get("forecasts", [])
            if item.get("component_code") == component
            and item.get("available_at")
            and parse_timestamp(str(item["available_at"]))
            <= parse_timestamp(str(release["released_at"]))
        ),
        None,
    )
    raw_surprise = next(
        (
            item
            for item in event.get("raw_surprises", [])
            if item.get("component_code") == component
        ),
        None,
    )
    standardized = next(
        (
            item
            for item in event.get("standardized_surprises", [])
            if item.get("component_code") == component
        ),
        None,
    )

    def observed_value(
        value: Any,
        label: str,
        *,
        epistemic: str = "OBSERVED",
    ) -> dict[str, Any]:
        return fact(
            value,
            unit=release.get("unit"),
            epistemic_status=epistemic,
            as_of=str(release["released_at"]),
            available_at=str(release["available_at"]),
            quality="VALID",
            method="SOURCE_RELEASE_VINTAGE",
            explanation=f"{label} for {component} at this release vintage.",
            evidence=[str(event["record_id"]), str(release["release_id"])],
            source_refs=[event_ref],
            invalidation="Original vintage is immutable; later revision is separate.",
        )

    if forecast:
        forecast_fact = fact(
            dict(forecast),
            unit=forecast.get("unit", release.get("unit")),
            epistemic_status=str(forecast.get("epistemic_status", "OBSERVED")),
            as_of=str(forecast.get("forecast_as_of", forecast.get("available_at"))),
            available_at=str(forecast["available_at"]),
            quality="VALID",
            method="POINT_IN_TIME_CONSENSUS",
            explanation=f"Consensus forecast for {component} available before release.",
            evidence=[str(event["record_id"])],
            source_refs=[event_ref],
            invalidation=None,
        )
    else:
        forecast_fact = unknown_fact(
            f"No point-in-time eligible consensus forecast for {component}.",
            quality="UNVERIFIED_AVAILABILITY",
        )
    if release.get("revised_previous_value") is None:
        revision_fact = unknown_fact(
            f"No revision was reported for {component}.",
            quality="NOT_APPLICABLE",
        )
    else:
        revision_fact = observed_value(
            release.get("revised_previous_value"),
            "Revised previous value",
        )
    surprise_payload = standardized or raw_surprise
    if surprise_payload and surprise_payload.get("epistemic_status") != "UNKNOWN":
        surprise_fact = fact(
            dict(surprise_payload),
            unit=release.get("unit"),
            epistemic_status="CALCULATED",
            as_of=str(release["released_at"]),
            available_at=str(release["available_at"]),
            quality="VALID",
            method="ACTUAL_MINUS_POINT_IN_TIME_FORECAST",
            explanation=f"Point-in-time surprise for {component}.",
            evidence=[str(event["record_id"])],
            source_refs=[event_ref],
            invalidation=None,
        )
    else:
        surprise_fact = unknown_fact(
            f"Surprise for {component} is unavailable without eligible consensus.",
            quality="UNVERIFIED_AVAILABILITY",
        )
    return {
        "component_code": component,
        "observation_period": release.get("observation_period"),
        "released_at": str(release["released_at"]),
        "vintage": str(release["vintage"]),
        "forecast": forecast_fact,
        "actual": observed_value(release.get("actual_value"), "Actual value"),
        "previous": observed_value(release.get("previous_value"), "Previous value"),
        "revision": revision_fact,
        "surprise": surprise_fact,
    }


def _build_subsequent_behaviour(
    *,
    session: Mapping[str, Any],
    measurement_bars: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    neutral_bar = measurement_bars[0]
    neutral_at = str(neutral_bar["open_time"])
    observation_end = str(session["observation_end"])
    neutral_price = decimal_value(neutral_bar["ohlc"]["open"])

    highs = [decimal_value(bar["ohlc"]["high"]) for bar in measurement_bars]
    lows = [decimal_value(bar["ohlc"]["low"]) for bar in measurement_bars]
    session_high = max(highs)
    session_low = min(lows)
    high_index = highs.index(session_high)
    low_index = lows.index(session_low)
    high_at = str(measurement_bars[high_index]["open_time"])
    low_at = str(measurement_bars[low_index]["open_time"])
    if high_index < low_index:
        extreme_order = "HIGH_FIRST"
    elif low_index < high_index:
        extreme_order = "LOW_FIRST"
    else:
        extreme_order = "SAME_BAR"

    close_bar = measurement_bars[-1]
    close_price = decimal_value(close_bar["ohlc"]["close"])
    signed_close = close_price - neutral_price
    absolute_close = abs(signed_close)
    maximum_up = session_high - neutral_price
    maximum_down = session_low - neutral_price
    session_range = session_high - session_low
    if session_range == 0:
        close_fraction: float | None = None
        close_state = "DEGENERATE"
        efficiency: float | None = None
    else:
        close_fraction_decimal = (close_price - session_low) / session_range
        close_fraction = float(
            close_fraction_decimal.quantize(DECIMAL_QUANTUM, rounding=ROUND_HALF_UP)
        )
        one_third = Decimal(1) / Decimal(3)
        two_thirds = Decimal(2) / Decimal(3)
        if close_fraction_decimal < one_third:
            close_state = "LOWER_THIRD"
        elif close_fraction_decimal > two_thirds:
            close_state = "UPPER_THIRD"
        else:
            close_state = "MIDDLE_THIRD"
        efficiency = float(
            (absolute_close / session_range).quantize(
                DECIMAL_QUANTUM,
                rounding=ROUND_HALF_UP,
            )
        )
    if signed_close > Decimal("0.01"):
        net_state = "UP"
    elif signed_close < Decimal("-0.01"):
        net_state = "DOWN"
    else:
        net_state = "FLAT"

    outcome_source = compact_bar_source_ref(close_bar)

    def outcome_fact(
        value: Any,
        explanation: str,
        *,
        unit: str | None = "USD_PER_TROY_OUNCE",
        method: str,
        evidence: Iterable[str] = (),
        source_refs: Iterable[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return fact(
            value,
            unit=unit,
            epistemic_status="CALCULATED",
            as_of=observation_end,
            available_at=observation_end,
            quality="VALID",
            method=method,
            explanation=explanation,
            evidence=[str(session["record_id"]), *evidence],
            source_refs=list(source_refs or [outcome_source]),
            invalidation=None,
        )

    bars_by_close = {
        parse_timestamp(str(bar["close_time"])): bar for bar in measurement_bars
    }
    fixed_horizons: list[dict[str, Any]] = []
    neutral_dt = parse_timestamp(neutral_at)
    for horizon, minutes in HORIZONS:
        end_dt = (
            parse_timestamp(observation_end)
            if minutes is None
            else neutral_dt + timedelta(minutes=minutes)
        )
        bar = bars_by_close.get(end_dt)
        if bar is None:
            raise ValueError(
                f"Missing {horizon} bar in {session['record_id']} at {end_dt.isoformat()}"
            )
        displacement = decimal_value(bar["ohlc"]["close"]) - neutral_price
        bar_ref = compact_bar_source_ref(bar)
        fixed_horizons.append(
            {
                "horizon": horizon,
                "horizon_end": end_dt.isoformat(),
                "signed_displacement": fact(
                    published_decimal(displacement),
                    unit="USD_PER_TROY_OUNCE",
                    epistemic_status="CALCULATED",
                    as_of=end_dt.isoformat(),
                    available_at=str(bar["available_at"]),
                    quality="VALID",
                    method="HORIZON_CLOSE_MINUS_NEUTRAL_REFERENCE",
                    explanation=(
                        "Neutral signed price displacement; no trade direction or "
                        "entry is assumed."
                    ),
                    evidence=[str(neutral_bar["record_id"]), str(bar["record_id"])],
                    source_refs=[compact_bar_source_ref(neutral_bar), bar_ref],
                    invalidation=None,
                ),
                "absolute_displacement": fact(
                    published_decimal(abs(displacement)),
                    unit="USD_PER_TROY_OUNCE",
                    epistemic_status="CALCULATED",
                    as_of=end_dt.isoformat(),
                    available_at=str(bar["available_at"]),
                    quality="VALID",
                    method="ABS_HORIZON_CLOSE_MINUS_NEUTRAL_REFERENCE",
                    explanation="Absolute neutral price displacement.",
                    evidence=[str(neutral_bar["record_id"]), str(bar["record_id"])],
                    source_refs=[compact_bar_source_ref(neutral_bar), bar_ref],
                    invalidation=None,
                ),
                "source_bar_id": str(bar["record_id"]),
            }
        )

    five_minute_path = session["subsequent_observation"]["five_minute_path"]
    if len(five_minute_path) != FIVE_MINUTE_POINT_COUNT:
        raise ValueError(f"Incomplete source 5m path: {session['record_id']}")
    path_points: list[dict[str, Any]] = []
    decision_dt = parse_timestamp(str(session["decision_at"]))
    for bar in five_minute_path:
        open_dt = parse_timestamp(str(bar["open_time"]))
        path_points.append(
            {
                "offset_minutes": int((open_dt - decision_dt).total_seconds() // 60),
                "timestamp": str(bar["open_time"]),
                "available_at": str(bar["close_time"]),
                "xauusd": fact(
                    {
                        "ohlc": dict(bar["ohlc"]),
                        "spread_price": bar.get("spread_price"),
                        "tick_volume": bar.get("volume"),
                    },
                    unit="USD_PER_TROY_OUNCE",
                    epistemic_status="OBSERVED",
                    as_of=str(bar["open_time"]),
                    available_at=str(bar["close_time"]),
                    quality="VALID",
                    method="SOURCE_FIVE_MINUTE_BAR",
                    explanation="Observed 5-minute session-path bar.",
                    evidence=[str(bar["record_id"]), str(bar["record_hash"])],
                    source_refs=[
                        {
                            "record_id": str(bar["record_id"]),
                            "record_hash": str(bar["record_hash"]),
                            "provider_code": "IC_MARKETS_MT5",
                            "source_key": str(bar["record_id"]),
                            "available_at": str(bar["close_time"]),
                            "vintage": "GOLD_CASEBOOK_V0_1",
                        }
                    ],
                    invalidation=None,
                ),
                "complete": True,
                "source_bar_id": str(bar["record_id"]),
            }
        )

    interactions = [
        _build_level_interaction(session, item)
        for item in session["subsequent_observation"].get("level_interactions", [])
    ]
    measurement_ids = [str(bar["record_id"]) for bar in measurement_bars]
    return {
        "decision_eligible": False,
        "observation_end": observation_end,
        "neutral_reference": {
            "method": "OPEN_OF_FIRST_COMPLETE_1M_BAR_AT_08_01_LOCAL",
            "timestamp": neutral_at,
            "price": fact(
                float(neutral_price),
                unit="USD_PER_TROY_OUNCE",
                epistemic_status="OBSERVED",
                as_of=neutral_at,
                available_at=str(neutral_bar["available_at"]),
                quality="VALID",
                method="OPEN_OF_FIRST_COMPLETE_1M_BAR_AT_08_01_LOCAL",
                explanation=(
                    "Neutral measurement coordinate only; it is not a trade entry."
                ),
                evidence=[str(neutral_bar["record_id"])],
                source_refs=[compact_bar_source_ref(neutral_bar)],
                invalidation=None,
            ),
            "source_bar_id": str(neutral_bar["record_id"]),
            "trade_entry_assumed": False,
        },
        "fixed_horizons": fixed_horizons,
        "neutral_excursions": {
            "signed_close_displacement": outcome_fact(
                published_decimal(signed_close),
                "Session-close minus neutral-reference displacement.",
                method="SESSION_CLOSE_MINUS_NEUTRAL_REFERENCE",
            ),
            "absolute_close_displacement": outcome_fact(
                published_decimal(absolute_close),
                "Absolute session-close displacement.",
                method="ABS_SESSION_CLOSE_MINUS_NEUTRAL_REFERENCE",
            ),
            "maximum_upward_displacement": outcome_fact(
                published_decimal(maximum_up),
                "Maximum observed high minus neutral reference; non-negative.",
                method="MAX_ONE_MINUTE_HIGH_MINUS_NEUTRAL_REFERENCE",
                evidence=[str(measurement_bars[high_index]["record_id"])],
                source_refs=[
                    compact_bar_source_ref(neutral_bar),
                    compact_bar_source_ref(measurement_bars[high_index]),
                ],
            ),
            "maximum_downward_displacement": outcome_fact(
                published_decimal(maximum_down),
                "Minimum observed low minus neutral reference; non-positive.",
                method="MIN_ONE_MINUTE_LOW_MINUS_NEUTRAL_REFERENCE",
                evidence=[str(measurement_bars[low_index]["record_id"])],
                source_refs=[
                    compact_bar_source_ref(neutral_bar),
                    compact_bar_source_ref(measurement_bars[low_index]),
                ],
            ),
            "session_range": outcome_fact(
                published_decimal(session_range),
                "Maximum one-minute high minus minimum one-minute low.",
                method="MAX_HIGH_MINUS_MIN_LOW",
                evidence=[
                    str(measurement_bars[high_index]["record_id"]),
                    str(measurement_bars[low_index]["record_id"]),
                ],
            ),
        },
        "extremes": {
            "session_high": outcome_fact(
                float(session_high),
                "Maximum one-minute high in the neutral observation window.",
                method="MAX_ONE_MINUTE_HIGH",
                evidence=[str(measurement_bars[high_index]["record_id"])],
                source_refs=[compact_bar_source_ref(measurement_bars[high_index])],
            ),
            "session_low": outcome_fact(
                float(session_low),
                "Minimum one-minute low in the neutral observation window.",
                method="MIN_ONE_MINUTE_LOW",
                evidence=[str(measurement_bars[low_index]["record_id"])],
                source_refs=[compact_bar_source_ref(measurement_bars[low_index])],
            ),
            "session_high_at": outcome_fact(
                high_at,
                "Earliest one-minute bar attaining the session high.",
                unit="TIMESTAMP",
                method="EARLIEST_MAXIMUM_TIE_BREAK",
                evidence=[str(measurement_bars[high_index]["record_id"])],
                source_refs=[compact_bar_source_ref(measurement_bars[high_index])],
            ),
            "session_low_at": outcome_fact(
                low_at,
                "Earliest one-minute bar attaining the session low.",
                unit="TIMESTAMP",
                method="EARLIEST_MINIMUM_TIE_BREAK",
                evidence=[str(measurement_bars[low_index]["record_id"])],
                source_refs=[compact_bar_source_ref(measurement_bars[low_index])],
            ),
            "extreme_order": outcome_fact(
                extreme_order,
                "Chronological order of the earliest high and low bars.",
                unit=None,
                method="EARLIEST_EXTREME_ORDER",
            ),
        },
        "level_interactions": interactions,
        "path": {
            "resolution": "5m",
            "complete": True,
            "five_minute_points": path_points,
            "one_minute_source_count": len(measurement_bars),
            "one_minute_source_ids_hash": canonical_hash(measurement_ids),
            "missing_one_minute_bars": 0,
        },
        "close_location": outcome_fact(
            {
                "fraction": close_fraction,
                "state": close_state,
                "formula": "(close-low)/(high-low)",
            },
            "Session close location inside the neutral session range.",
            unit="FRACTION",
            method="FROZEN_CLOSE_LOCATION_THIRDS",
        ),
        "path_classification": outcome_fact(
            {
                "net_state": net_state,
                "close_location_state": close_state,
                "extreme_order": extreme_order,
                "path_efficiency": efficiency,
            },
            "Neutral descriptive path classification; no side or trade is assigned.",
            unit=None,
            method="FROZEN_NEUTRAL_PATH_CLASSIFICATION_V0_1",
        ),
    }


def _build_level_interaction(
    session: Mapping[str, Any],
    interaction: Mapping[str, Any],
) -> dict[str, Any]:
    classification = str(interaction["classification"])
    available_at = str(session["observation_end"])
    session_ref = source_ref(session)
    touched = classification != "UNTOUCHED"
    breached = interaction.get("first_breach_at") is not None
    accepted = interaction.get("accepted_at") is not None
    rejected = classification == "REJECTED_BREACH"
    failed_break = classification == "FAILED_ACCEPTED_BREAK"
    retested = interaction.get("returned_inside_at") is not None

    def state_fact(value: bool, label: str) -> dict[str, Any]:
        return fact(
            value,
            epistemic_status="CALCULATED",
            as_of=available_at,
            available_at=available_at,
            quality="VALID",
            method=str(interaction["detection_method"]),
            explanation=f"{label} state for a decision-known level.",
            evidence=[
                str(session["record_id"]),
                str(interaction["level_source_hash"]),
                classification,
            ],
            source_refs=[session_ref],
            invalidation=None,
        )

    level_id = next(
        (
            f"{session['record_id']}-LEVEL-{index:02d}-{level['code']}"
            for index, level in enumerate(session["decision_state"].get("known_levels", []))
            if level["code"] == interaction["level_code"]
        ),
        f"{session['record_id']}-LEVEL-UNKNOWN-{interaction['level_code']}",
    )
    first_interaction = (
        interaction.get("first_breach_at")
        or interaction.get("first_close_beyond_at")
        or interaction.get("accepted_at")
        or interaction.get("returned_inside_at")
    )
    return {
        "level_id": level_id,
        "decision_known_level": True,
        "first_interaction_at": first_interaction,
        "touched": state_fact(touched, "Touch"),
        "breached": state_fact(breached, "Breach"),
        "accepted": state_fact(accepted, "Acceptance"),
        "rejected": state_fact(rejected, "Rejection"),
        "failed_break": state_fact(failed_break, "Failed-break"),
        "retested": state_fact(retested, "Retest/return-inside"),
    }


def validate_case_semantics(case: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    metadata = case.get("case_metadata", {})
    decision_at = metadata.get("decision_at")
    if not decision_at:
        return ["MISSING_DECISION_AT"]
    decision_dt = parse_timestamp(str(decision_at))
    if metadata.get("data_partition") != "DEVELOPMENT_2021_2024":
        errors.append("INVALID_PARTITION")
    if metadata.get("access_class") != "DEVELOPMENT":
        errors.append("INVALID_ACCESS_CLASS")
    if not DEVELOPMENT_START <= decision_dt < DEVELOPMENT_END:
        errors.append("DECISION_OUTSIDE_DEVELOPMENT")
    if case_record_hash(case) != metadata.get("record_hash"):
        errors.append("RECORD_HASH_MISMATCH")
    if case.get("research_policy") != RESEARCH_POLICY:
        errors.append("RESEARCH_POLICY_MISMATCH")
    if case.get("decision_state", {}).get("decision_eligible") is not True:
        errors.append("DECISION_STATE_NOT_ELIGIBLE")
    outcome = case.get("subsequent_behaviour", {})
    if outcome.get("decision_eligible") is not False:
        errors.append("OUTCOME_ELIGIBILITY_VIOLATION")
    path = outcome.get("path", {})
    if path.get("one_minute_source_count") != MEASUREMENT_BAR_COUNT:
        errors.append("ONE_MINUTE_COUNT_MISMATCH")
    if len(path.get("five_minute_points", [])) != FIVE_MINUTE_POINT_COUNT:
        errors.append("FIVE_MINUTE_COUNT_MISMATCH")
    horizons = [item.get("horizon") for item in outcome.get("fixed_horizons", [])]
    if horizons != [item[0] for item in HORIZONS]:
        errors.append("HORIZON_SET_OR_ORDER_MISMATCH")
    timeframes = [
        item.get("timeframe")
        for item in case.get("decision_state", {})
        .get("market_structure", {})
        .get("timeframes", [])
    ]
    if len(timeframes) != 6 or set(timeframes) != set(REQUIRED_TIMEFRAMES):
        errors.append("STRUCTURE_TIMEFRAME_MISMATCH")
    if _contains_forbidden_execution_key(case):
        errors.append("FORBIDDEN_EXECUTION_KEY")
    errors.extend(_validate_facts(case, decision_dt=decision_dt))
    errors.extend(_validate_source_availability(case, decision_dt=decision_dt))
    return sorted(set(errors))


def _validate_facts(value: Any, *, decision_dt: datetime, path: str = "") -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        required_fact_keys = {
            "value",
            "unit",
            "epistemic_status",
            "as_of",
            "available_at",
            "quality",
            "method",
            "explanation",
            "evidence",
            "source_refs",
            "invalidation",
        }
        if required_fact_keys.issubset(value):
            if value["epistemic_status"] == "UNKNOWN" and value["value"] is not None:
                errors.append(f"UNKNOWN_NON_NULL:{path}")
            in_outcome = path.startswith("subsequent_behaviour")
            available = value.get("available_at")
            if (
                available
                and not in_outcome
                and parse_timestamp(str(available)) > decision_dt
            ):
                errors.append(f"FUTURE_DECISION_FACT:{path}")
        for key, nested in value.items():
            child = f"{path}.{key}" if path else str(key)
            errors.extend(_validate_facts(nested, decision_dt=decision_dt, path=child))
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for index, nested in enumerate(value):
            errors.extend(
                _validate_facts(
                    nested,
                    decision_dt=decision_dt,
                    path=f"{path}[{index}]",
                )
            )
    return errors


def _validate_source_availability(
    case: Mapping[str, Any],
    *,
    decision_dt: datetime,
) -> list[str]:
    errors: list[str] = []
    decision = case["decision_state"]

    def walk(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            if {
                "record_id",
                "record_hash",
                "provider_code",
                "source_key",
                "available_at",
                "vintage",
            }.issubset(value) and parse_timestamp(
                str(value["available_at"])
            ) > decision_dt:
                errors.append(f"FUTURE_SOURCE_REF:{path}:{value['record_id']}")
            for key, nested in value.items():
                walk(nested, f"{path}.{key}")
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            for index, nested in enumerate(value):
                walk(nested, f"{path}[{index}]")

    walk(decision, "decision_state")
    return errors


def _contains_forbidden_execution_key(value: Any) -> bool:
    forbidden = {
        "trade_direction",
        "entry",
        "stop",
        "target",
        "position_size",
        "pnl",
        "r_multiple",
        "mfe",
        "mae",
        "account_return",
        "candidate_label",
        "relationship_label",
    }
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower()
            if normalized in forbidden:
                return True
            if _contains_forbidden_execution_key(nested):
                return True
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return any(_contains_forbidden_execution_key(item) for item in value)
    return False


def validate_json_schema(
    value: Any,
    schema: Mapping[str, Any],
) -> list[str]:
    """Validate the frozen V3 schema without adding a runtime dependency.

    The implementation intentionally supports only the JSON Schema keywords
    present in ``gold_session_behaviour_v3_case_matrix.schema.json``. Unknown
    keywords are annotations, not silently interpreted as validation rules.
    """

    errors: list[str] = []

    def resolve(reference: str) -> Mapping[str, Any]:
        if not reference.startswith("#/"):
            raise ValueError(f"Only local JSON Schema refs are supported: {reference}")
        node: Any = schema
        for token in reference[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            node = node[token]
        if not isinstance(node, Mapping):
            raise ValueError(f"Schema ref does not resolve to an object: {reference}")
        return node

    def matches(instance: Any, rule: Mapping[str, Any]) -> bool:
        local: list[str] = []
        walk(instance, rule, "$probe", local)
        return not local

    def walk(
        instance: Any,
        rule: Mapping[str, Any],
        path: str,
        target: list[str],
    ) -> None:
        if "$ref" in rule:
            walk(instance, resolve(str(rule["$ref"])), path, target)
            return
        for nested in rule.get("allOf", []):
            walk(instance, nested, path, target)
        conditional = rule.get("if")
        if isinstance(conditional, Mapping) and matches(instance, conditional):
            then_rule = rule.get("then")
            if isinstance(then_rule, Mapping):
                walk(instance, then_rule, path, target)
        alternatives = rule.get("anyOf")
        if isinstance(alternatives, Sequence):
            if not any(matches(instance, item) for item in alternatives):
                target.append(f"{path}:ANY_OF")
            return
        if "const" in rule and instance != rule["const"]:
            target.append(f"{path}:CONST")
        if "enum" in rule and instance not in rule["enum"]:
            target.append(f"{path}:ENUM")
        declared_type = rule.get("type")
        if declared_type and not _json_type_matches(instance, str(declared_type)):
            target.append(f"{path}:TYPE_{declared_type}")
            return
        if isinstance(instance, Mapping):
            required = rule.get("required", [])
            for key in required:
                if key not in instance:
                    target.append(f"{path}.{key}:REQUIRED")
            properties = rule.get("properties", {})
            if rule.get("additionalProperties") is False:
                extras = set(instance) - set(properties)
                for key in sorted(extras):
                    target.append(f"{path}.{key}:ADDITIONAL_PROPERTY")
            for key, nested in instance.items():
                child_rule = properties.get(key)
                if isinstance(child_rule, Mapping):
                    walk(nested, child_rule, f"{path}.{key}", target)
                elif isinstance(rule.get("additionalProperties"), Mapping):
                    walk(
                        nested,
                        rule["additionalProperties"],
                        f"{path}.{key}",
                        target,
                    )
        elif isinstance(instance, Sequence) and not isinstance(instance, str | bytes):
            if "minItems" in rule and len(instance) < int(rule["minItems"]):
                target.append(f"{path}:MIN_ITEMS")
            if rule.get("uniqueItems") and len(
                {json.dumps(json_ready(item), sort_keys=True) for item in instance}
            ) != len(instance):
                target.append(f"{path}:UNIQUE_ITEMS")
            item_rule = rule.get("items")
            if isinstance(item_rule, Mapping):
                for index, item in enumerate(instance):
                    walk(item, item_rule, f"{path}[{index}]", target)
        elif isinstance(instance, str):
            if "minLength" in rule and len(instance) < int(rule["minLength"]):
                target.append(f"{path}:MIN_LENGTH")
            if "pattern" in rule and not re.search(str(rule["pattern"]), instance):
                target.append(f"{path}:PATTERN")
            if rule.get("format") == "date-time":
                try:
                    parse_timestamp(instance)
                except (TypeError, ValueError):
                    target.append(f"{path}:FORMAT_DATE_TIME")
            elif rule.get("format") == "date":
                try:
                    datetime.fromisoformat(f"{instance}T00:00:00+00:00")
                except ValueError:
                    target.append(f"{path}:FORMAT_DATE")
        elif isinstance(instance, int | float) and not isinstance(instance, bool):
            if "minimum" in rule and instance < rule["minimum"]:
                target.append(f"{path}:MINIMUM")
            if "maximum" in rule and instance > rule["maximum"]:
                target.append(f"{path}:MAXIMUM")

    walk(value, schema, "$", errors)
    return errors


def _json_type_matches(value: Any, declared: str) -> bool:
    if declared == "object":
        return isinstance(value, Mapping)
    if declared == "array":
        return isinstance(value, Sequence) and not isinstance(value, str | bytes)
    if declared == "string":
        return isinstance(value, str)
    if declared == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if declared == "boolean":
        return isinstance(value, bool)
    if declared == "null":
        return value is None
    raise ValueError(f"Unsupported JSON Schema type: {declared}")
