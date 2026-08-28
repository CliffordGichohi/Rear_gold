#!/usr/bin/env python3
"""Materialize independently reproduced, outcome-hidden coherent-auction replay streams."""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import materialize_gold_annotated_replay_v3 as replay


ROOT = Path(__file__).resolve().parents[1]
CASEBOOK = ROOT / "research_artifacts" / "gold_casebook_v01"
OUT = ROOT / "research_artifacts" / "gold_coherent_auction_blind_validation_v1"
FREEZE = (
    ROOT
    / "research_manifests"
    / "gold_coherent_auction_blind_validation_v1_prevalue_freeze.json"
)
REGISTRY = OUT / "population_registry.private.json"
PRIMARY = OUT / "validation_streams.primary.jsonl.gz"
REFERENCE = OUT / "validation_streams.reference.jsonl.gz"
CERTIFICATION = OUT / "stream_materialization_certification.json"
STATE = OUT / "state_stream_materialization.json"

PRICE = CASEBOOK / "price_bars.jsonl.gz"
TIMEFRAMES = replay.TIMEFRAMES
SOURCE_TIMEFRAMES = replay.SOURCE_TIMEFRAMES
LIMITS = replay.LIMITS


def now() -> str:
    return datetime.now(UTC).isoformat()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": replay.sha256_file(path),
    }


def verify_freeze() -> tuple[dict[str, Any], dict[str, Any]]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "SEALED_BEFORE_VALIDATION_VALUE_MATERIALIZATION":
        raise RuntimeError("Coherent-auction prevalue freeze differs")
    for item in [*freeze["sealed_outputs"], *freeze["source_records"]]:
        path = ROOT / item["path"]
        if (
            not path.is_file()
            or path.stat().st_size != item["bytes"]
            or replay.sha256_file(path) != item["sha256"]
        ):
            raise RuntimeError(f"Frozen validation predecessor differs: {item['path']}")
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if (
        registry.get("case_count") != 50
        or registry.get("population_sha256") != freeze.get("population_sha256")
    ):
        raise RuntimeError("Frozen validation population differs")
    return freeze, registry


def load_prices_primary(maximum: datetime) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with gzip.open(PRICE, "rt", encoding="utf-8") as handle:
        for line in handle:
            source = json.loads(line)
            if (
                source.get("instrument_code") != "XAUUSD"
                or source.get("timeframe") not in SOURCE_TIMEFRAMES
                or not replay.display_eligible(source)
            ):
                continue
            close = replay.parse_time(str(source["close_time"]))
            if close > maximum:
                continue
            rows[str(source["timeframe"])].append(replay.price_record(source))
    for timeframe in rows:
        rows[timeframe].sort(key=lambda item: (item["close_at"], item["bar_id"]))
    return dict(rows)


def load_prices_reference(maximum: datetime) -> dict[str, list[dict[str, Any]]]:
    tuples: list[tuple[str, str, str, dict[str, Any]]] = []
    with gzip.GzipFile(filename=PRICE, mode="rb") as handle:
        for raw in handle:
            source = json.loads(raw.decode("utf-8"))
            timeframe = str(source.get("timeframe"))
            if (
                source.get("instrument_code") != "XAUUSD"
                or timeframe not in SOURCE_TIMEFRAMES
                or not replay.display_eligible(source)
            ):
                continue
            close = replay.parse_time(str(source["close_time"]))
            if close > maximum:
                continue
            record = replay.price_record(source)
            tuples.append((timeframe, record["close_at"], record["bar_id"], record))
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for timeframe, _, _, record in sorted(tuples, key=lambda item: item[:3]):
        output[timeframe].append(record)
    return dict(output)


def timeline_for_case(
    case: dict[str, Any],
    prices: dict[str, list[dict[str, Any]]],
    contexts: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    alias = case["case_alias"]
    start = replay.parse_time(case["start_inclusive"])
    end = replay.parse_time(case["end_inclusive"])
    sources = {**prices, "1w": replay.weekly_rows(prices.get("1d", []))}
    timelines: dict[str, list[dict[str, Any]]] = {}
    for timeframe in TIMEFRAMES:
        rows = sources.get(timeframe, [])
        before = [
            row
            for row in rows
            if replay.parse_time(row["close_at"]) <= start
            and replay.parse_time(row["available_at"]) <= start
        ]
        during = [
            row
            for row in rows
            if start < replay.parse_time(row["close_at"]) <= end
            and replay.parse_time(row["available_at"]) <= end
        ]
        selected = [*before[-LIMITS[timeframe] :], *during]
        ordered = sorted(selected, key=lambda row: (row["close_at"], row["bar_id"]))
        if selected != ordered:
            raise RuntimeError(f"Timeline order failure: {alias} {timeframe}")
        if len({row["bar_id"] for row in selected}) != len(selected):
            raise RuntimeError(f"Duplicate bar identity: {alias} {timeframe}")
        timelines[timeframe] = selected

    m1_session = [
        row
        for row in timelines["1m"]
        if start < replay.parse_time(row["close_at"]) <= end
    ]
    if len(m1_session) != int(case["observed_m1_closes"]):
        raise RuntimeError(
            f"M1 validation-session count differs: {alias} {len(m1_session)} "
            f"!= {case['observed_m1_closes']}"
        )

    event_rows: list[dict[str, Any]] = []
    for row in contexts["events"]:
        released = replay.parse_time(str(row["released_at"]))
        scheduled = replay.parse_time(str(row.get("scheduled_at") or row["released_at"]))
        if start <= released <= end or (
            row.get("schedule_verified_for_pre_event_use") and start <= scheduled <= end
        ):
            event_rows.append(replay.safe_event(row))
    session_rows = [
        replay.safe_session(row)
        for row in contexts["sessions"]
        if str(row.get("session_date")) == case["trading_date_utc"]
        and row.get("session_code") in {"LONDON", "NEW_YORK"}
    ]
    context_timeline = {
        "fundamentals": [
            replay.safe_fundamental(row)
            for row in replay.latest_plus_day(
                contexts["fundamentals"], timestamp_key="available_at", start=start, end=end
            )
        ],
        "structure": [
            replay.safe_structure(row)
            for row in replay.latest_plus_day(
                contexts["structure"], timestamp_key="available_at", start=start, end=end
            )
        ],
        "cross_market": [
            replay.safe_cross_market(row)
            for row in replay.latest_plus_day(
                contexts["cross_market"], timestamp_key="available_at", start=start, end=end
            )
        ],
        "positioning": [
            replay.safe_positioning(row)
            for row in replay.latest_plus_day(
                contexts["positioning"], timestamp_key="available_at", start=start, end=end
            )
        ],
        "events": sorted(event_rows, key=lambda row: row["released_at"]),
        "sessions": sorted(session_rows, key=lambda row: row["decision_at"]),
    }
    body = {
        "version": "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_STREAM_1_0",
        "case_alias": alias,
        "mode": "BLIND_HISTORICAL_ROBUSTNESS",
        "mode_sequence": case["mode_sequence"],
        "session_code": case["session_code"],
        "trading_date_utc": case["trading_date_utc"],
        "start_inclusive": case["start_inclusive"],
        "end_exclusive": case["end_inclusive"],
        "initial_cursor_at": case["start_inclusive"],
        "maximum_cursor_at": case["end_inclusive"],
        "research_credit": "HISTORICAL_BLIND_ROBUSTNESS_ONLY",
        "timeframes": timelines,
        "context_timeline": context_timeline,
        "source_lineage": {
            "population_sha256": case["observed_identity_sha256"],
            "source_case_alias": case["source_case_alias"],
            "source_session_record_hash": case["source_session_record_hash"],
            "price_casebook_sha256": replay.sha256_file(PRICE),
        },
    }
    body["stream_sha256"] = replay.canonical_hash(body)
    return body


def build_streams(
    registry: dict[str, Any], loader: Callable[[datetime], dict[str, list[dict[str, Any]]]]
) -> list[dict[str, Any]]:
    maximum = max(replay.parse_time(row["end_inclusive"]) for row in registry["cases"])
    prices = loader(maximum)
    contexts = replay.build_contexts()
    return [timeline_for_case(case, prices, contexts) for case in registry["cases"]]


def main() -> int:
    for path in (PRIMARY, REFERENCE, CERTIFICATION, STATE):
        if path.exists():
            raise RuntimeError(f"Append-only validation output exists: {path.relative_to(ROOT)}")
    freeze, registry = verify_freeze()
    primary = build_streams(registry, load_prices_primary)
    reference = build_streams(registry, load_prices_reference)
    if primary != reference:
        raise RuntimeError("Primary/reference validation streams differ")
    replay.write_gzip_new(PRIMARY, primary)
    replay.write_gzip_new(REFERENCE, reference)

    forbidden_event_keys = {
        "fixed_horizon_reactions",
        "reaction_snapshots",
        "complete_observation_available_at",
    }
    gates = {
        "prevalue_freeze_verified": True,
        "exact_50_cases": len(primary) == 50,
        "aliases_exact": [row["case_alias"] for row in primary]
        == [f"GAV-2022-{index:03d}" for index in range(1, 51)],
        "exact_25_london_and_25_new_york": sum(
            row["session_code"] == "LONDON" for row in primary
        )
        == 25
        and sum(row["session_code"] == "NEW_YORK" for row in primary) == 25,
        "all_rows_historical_blind_robustness": all(
            row["mode"] == "BLIND_HISTORICAL_ROBUSTNESS"
            and row["research_credit"] == "HISTORICAL_BLIND_ROBUSTNESS_ONLY"
            for row in primary
        ),
        "m1_counts_match_frozen_metadata": all(
            len(
                [
                    bar
                    for bar in row["timeframes"]["1m"]
                    if row["start_inclusive"] < bar["close_at"] <= row["end_exclusive"]
                ]
            )
            == int(registry["cases"][index]["observed_m1_closes"])
            for index, row in enumerate(primary)
        ),
        "all_bars_ordered_unique": all(
            bars == sorted(bars, key=lambda bar: (bar["close_at"], bar["bar_id"]))
            and len({bar["bar_id"] for bar in bars}) == len(bars)
            for row in primary
            for bars in row["timeframes"].values()
        ),
        "no_bar_available_after_case_horizon": all(
            bar["available_at"] <= row["end_exclusive"]
            for row in primary
            for bars in row["timeframes"].values()
            for bar in bars
        ),
        "event_outcome_fields_absent": all(
            forbidden_event_keys.isdisjoint(event)
            for row in primary
            for event in row["context_timeline"]["events"]
        ),
        "session_outcomes_absent": all(
            "subsequent_observation" not in session
            for row in primary
            for session in row["context_timeline"]["sessions"]
        ),
        "primary_reference_structures_exact": primary == reference,
        "primary_reference_bytes_exact": replay.sha256_file(PRIMARY)
        == replay.sha256_file(REFERENCE),
        "calendar_2025_2026_not_opened": True,
        "no_outcomes_calculated": True,
        "no_acquisition_or_charge": True,
    }
    if not all(gates.values()):
        raise RuntimeError(f"Validation stream certification gate failed: {gates}")
    timeframe_counts = {
        timeframe: {
            "minimum": min(len(row["timeframes"][timeframe]) for row in primary),
            "maximum": max(len(row["timeframes"][timeframe]) for row in primary),
        }
        for timeframe in TIMEFRAMES
    }
    certification = {
        "version": "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_STREAM_CERTIFICATION_1_0",
        "completed_at": now(),
        "verdict": "PASS_BLIND_VALIDATION_STREAM_MATERIALIZATION",
        "case_count": len(primary),
        "population_sha256": freeze["population_sha256"],
        "primary_sha256": replay.sha256_file(PRIMARY),
        "reference_sha256": replay.sha256_file(REFERENCE),
        "complete_stream_set_sha256": replay.canonical_hash(primary),
        "timeframe_counts": timeframe_counts,
        "gates": gates,
        "outcomes_calculated": False,
        "aggregate_results": "LOCKED_UNTIL_ALL_50_COMPLETE",
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "acquisition_performed": False,
        "charge_usd": 0.0,
    }
    replay.write_new_json(CERTIFICATION, certification)
    state = {
        "version": "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_STREAM_STATE_1_0",
        "recorded_at": now(),
        "status": "PASS_STREAMS_READY_APPLICATION_CLOSED_PENDING_CERTIFICATION",
        "prevalue_freeze": file_record(FREEZE),
        "stream_certification": file_record(CERTIFICATION),
        "primary_stream": file_record(PRIMARY),
        "reference_stream": file_record(REFERENCE),
        "decisions_collected": 0,
        "aggregate_results": "LOCKED",
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    replay.write_new_json(STATE, state)
    print(
        json.dumps(
            {
                "verdict": certification["verdict"],
                "cases": len(primary),
                "primary_sha256": certification["primary_sha256"],
                "timeframe_counts": timeframe_counts,
                "gates": gates,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
