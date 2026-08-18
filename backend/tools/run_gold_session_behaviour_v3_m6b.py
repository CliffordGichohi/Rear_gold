from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.session_behaviour_v3 import sha256_file
from gold_intel.analytics.session_behaviour_v3_m6a import (
    M5_SHORTLIST_CODES,
    forward_candidate_registry,
    protocol_fingerprint,
)
from gold_intel.analytics.session_behaviour_v3_m6b import (
    M6B_CASE_VERSION,
    SEGMENTS,
    evaluate_segment,
    new_forward_case,
    overall_candidate_verdicts,
    validate_m6b_freeze,
)
from gold_intel.infrastructure.database import session_factory

RESULT_BUNDLE_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M6B_RESULT_BUNDLE_V0_1"
PROSPECTIVE_LEDGER_VERSION = (
    "GOLD_SESSION_BEHAVIOUR_V3_PROSPECTIVE_LEDGER_V0_1"
)
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
TOKYO = ZoneInfo("Asia/Tokyo")

PRICE_VALUE_SQL = """
SELECT
    bar.id::text AS record_id,
    bar.open_time,
    bar.close_time,
    bar.open::text AS open,
    bar.high::text AS high,
    bar.low::text AS low,
    bar.close::text AS close,
    bar.volume::text AS volume,
    bar.volume_type,
    bar.spread_points,
    bar.spread_price::text AS spread_price,
    bar.available_at,
    bar.batch_id::text AS batch_id,
    bar.source_record_key,
    bar.is_complete,
    bar.is_synthetic
FROM market.price_bars bar
WHERE bar.provider_code = 'IC_MARKETS_MT5'
  AND bar.instrument_code = 'XAUUSD'
  AND bar.timeframe = '1m'
  AND bar.open_time >= CAST(:start AS timestamptz)
  AND bar.open_time < CAST(:end AS timestamptz)
  AND bar.batch_id IN :batch_ids
ORDER BY bar.open_time, bar.available_at, bar.id
"""

OBSERVATION_VALUE_SQL = """
SELECT
    observation.id::text AS record_id,
    observation.observation_time,
    observation.series_code,
    observation.value::text AS value,
    observation.unit,
    observation.available_at,
    observation.vintage,
    observation.is_revision,
    observation.supersedes_id::text AS supersedes_id,
    observation.batch_id::text AS batch_id,
    observation.source_record_key,
    observation.is_synthetic
FROM market.observations observation
WHERE observation.series_code IN (
    'US_VOLATILITY_INDEX',
    'US_FINANCIAL_STRESS'
)
  AND observation.observation_time >= CAST(:source_start AS timestamptz)
  AND observation.available_at < CAST(:end AS timestamptz)
  AND observation.batch_id IN :batch_ids
ORDER BY
    observation.series_code,
    observation.observation_time,
    observation.available_at,
    observation.vintage,
    observation.id
"""


async def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    preopen_path = (root / args.preopen_manifest).resolve()
    output_dir = (root / args.output_dir).resolve()
    _assert_within(root, preopen_path)
    _assert_within(root, output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("M6B result output directory is not empty")

    preopen = _verify_preopen(root=root, path=preopen_path)
    source_path = (root / preopen["source_snapshot"]["path"]).resolve()
    source_snapshot = _load_json(source_path)
    if _embedded_hash(source_snapshot, "source_snapshot_hash") != (
        source_snapshot["source_snapshot_hash"]
    ):
        raise ValueError("M6B source snapshot embedded hash mismatch")
    if source_snapshot["source_snapshot_hash"] != preopen["source_snapshot"][
        "source_snapshot_hash"
    ]:
        raise ValueError("M6B source snapshot lineage mismatch")
    if source_snapshot["source_integrity"] != {
        "duplicate_observation_natural_keys": 0,
        "duplicate_price_natural_keys": 0,
    }:
        raise ValueError("M6B final source integrity gates failed")

    lineage = source_snapshot["lineage"]["batch_records"]
    price_batch_ids = tuple(
        UUID(item["batch_id"])
        for item in lineage
        if item["provider_code"] == "IC_MARKETS_MT5"
    )
    observation_batch_ids = tuple(
        UUID(item["batch_id"])
        for item in lineage
        if item["provider_code"] == "FRED_PUBLIC"
    )
    batch_hash_by_id = {
        str(item["batch_id"]): str(item["content_hash"]) for item in lineage
    }
    if not price_batch_ids or not observation_batch_ids:
        raise ValueError("M6B final source snapshot lacks required batch lineage")

    output_dir.mkdir(parents=True, exist_ok=True)
    segment_results: list[dict[str, Any]] = []
    segment_manifests: list[dict[str, Any]] = []
    for segment in SEGMENTS:
        segment_code = str(segment["segment_code"])
        cases, source_integrity = await _open_segment_once(
            segment=segment,
            price_batch_ids=price_batch_ids,
            observation_batch_ids=observation_batch_ids,
            batch_hash_by_id=batch_hash_by_id,
        )
        expected_counts = _expected_case_counts(
            root=root,
            preopen=preopen,
            segment_code=segment_code,
        )
        actual_counts = {
            session: sum(
                item["session_code"] == session for item in cases
            )
            for session in ("LONDON", "NEW_YORK")
        }
        if actual_counts != expected_counts:
            raise ValueError(
                f"{segment_code} case count differs from sealed readiness: "
                f"actual={actual_counts}, expected={expected_counts}"
            )
        result = evaluate_segment(
            cases,
            segment_code=segment_code,
            source_integrity=source_integrity,
        )
        segment_dir = output_dir / segment_code.lower()
        manifest = _seal_segment(
            segment_dir=segment_dir,
            segment=segment,
            cases=cases,
            result=result,
            preopen=preopen,
            source_snapshot=source_snapshot,
        )
        segment_results.append(result)
        segment_manifests.append(manifest)

    prospective = _initialize_prospective_ledger(
        output_dir / "prospective_2026_post_freeze",
        preopen=preopen,
    )
    overall = overall_candidate_verdicts(segment_results)
    bundle: dict[str, Any] = {
        "bundle_version": RESULT_BUNDLE_VERSION,
        "milestone": "V3_M6B_ONE_TIME_FORWARD_VALUE_EVALUATION",
        "created_at": datetime.now(UTC).isoformat(),
        "preopen_manifest": {
            "path": _portable(preopen_path),
            "manifest_hash": preopen["manifest_hash"],
            "file_sha256": sha256_file(preopen_path),
        },
        "source_snapshot": {
            "path": preopen["source_snapshot"]["path"],
            "source_snapshot_hash": source_snapshot["source_snapshot_hash"],
            "file_sha256": preopen["source_snapshot"]["file_sha256"],
        },
        "segment_reporting_order": [
            "EXPOSED_CALENDAR_2025",
            "LOCKED_2026_YTD",
        ],
        "segment_manifests": [
            {
                "segment_code": manifest["segment"]["segment_code"],
                "path": manifest["manifest_path"],
                "manifest_hash": manifest["manifest_hash"],
                "file_sha256": manifest["manifest_file_sha256"],
            }
            for manifest in segment_manifests
        ],
        "overall_candidate_verdicts": overall,
        "prospective_ledger": prospective,
        "research_boundary": {
            "exposed_2025_independent_validation_credit": False,
            "locked_2026_ytd_independent_validation_credit": True,
            "both_candidates_evaluated_in_both_segments": all(
                len(result["candidate_results"]) == 2
                for result in segment_results
            ),
            "candidate_definitions_changed": False,
            "new_variables_or_candidates": 0,
            "thresholds_retuned": False,
            "execution_variants": 0,
            "trades_or_returns": 0,
            "cot_used_as_pass_gate": False,
            "rejected_candidates_or_zn_rules_reopened": False,
            "prospective_decisions_backfilled": 0,
        },
        "bundle_hash": "",
    }
    bundle["bundle_hash"] = _embedded_hash(
        bundle,
        "bundle_hash",
        excluded=("created_at",),
    )
    bundle_path = output_dir / "result_bundle.json"
    _write_json(bundle_path, bundle)
    final_manifest: dict[str, Any] = {
        "manifest_version": RESULT_BUNDLE_VERSION,
        "milestone": "V3_M6B_ONE_TIME_FORWARD_VALUE_EVALUATION",
        "created_at": bundle["created_at"],
        "artifacts": [
            _artifact(bundle_path),
            *[
                {
                    "path": item["manifest_path"],
                    "bytes": (root / item["manifest_path"]).stat().st_size,
                    "sha256": item["manifest_file_sha256"],
                }
                for item in segment_manifests
            ],
            {
                "path": prospective["manifest_path"],
                "bytes": (root / prospective["manifest_path"]).stat().st_size,
                "sha256": prospective["manifest_file_sha256"],
            },
        ],
        "bundle_hash": bundle["bundle_hash"],
        "overall_candidate_verdicts": overall,
        "verdict": "PASS_V3_MILESTONE_6B_RESULTS_BUILT_PENDING_INDEPENDENT_REPRODUCTION",
        "manifest_hash": "",
    }
    final_manifest["manifest_hash"] = _embedded_hash(
        final_manifest,
        "manifest_hash",
    )
    final_manifest_path = output_dir / "manifest.json"
    _write_json(final_manifest_path, final_manifest)
    print(
        json.dumps(
            {
                "bundle_hash": bundle["bundle_hash"],
                "manifest_hash": final_manifest["manifest_hash"],
                "segment_results": [
                    {
                        "segment_code": result["segment"]["segment_code"],
                        "candidate_verdicts": {
                            item["candidate_code"]: item["segment_verdict"]
                            for item in result["candidate_results"]
                        },
                    }
                    for result in segment_results
                ],
                "overall_candidate_verdicts": {
                    item["candidate_code"]: item["overall_verdict"]
                    for item in overall
                },
                "prospective_ledger_records": 0,
                "trades_or_returns": 0,
                "verdict": final_manifest["verdict"],
            },
            indent=2,
            sort_keys=True,
        )
    )


async def _open_segment_once(
    *,
    segment: Mapping[str, Any],
    price_batch_ids: Sequence[UUID],
    observation_batch_ids: Sequence[UUID],
    batch_hash_by_id: Mapping[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    segment_code = str(segment["segment_code"])
    start_date = date.fromisoformat(
        str(segment["session_date_start_inclusive"])
    )
    end_date = date.fromisoformat(
        str(segment["session_date_end_inclusive"])
    )
    start = datetime.combine(start_date, time(), tzinfo=UTC)
    end = datetime.combine(end_date + timedelta(days=1), time(), tzinfo=UTC)
    expected_timestamps = _all_required_timestamps(start_date, end_date)
    price_statement = text(PRICE_VALUE_SQL).bindparams(
        bindparam("batch_ids", expanding=True)
    )
    observation_statement = text(OBSERVATION_VALUE_SQL).bindparams(
        bindparam("batch_ids", expanding=True)
    )
    price_by_open: dict[datetime, dict[str, Any]] = {}
    duplicate_price_rows = 0
    observations: list[dict[str, Any]] = []
    async with session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        price_stream = await session.stream(
            price_statement.execution_options(yield_per=5000),
            {
                "start": start,
                "end": end,
                "batch_ids": list(price_batch_ids),
            },
        )
        async for row in price_stream.mappings():
            open_time = row["open_time"].astimezone(UTC)
            if open_time not in expected_timestamps:
                continue
            normalized = {
                str(key): json_ready(value) for key, value in row.items()
            }
            if open_time in price_by_open:
                duplicate_price_rows += 1
            else:
                price_by_open[open_time] = normalized
        observation_rows = (
            await session.execute(
                observation_statement,
                {
                    "source_start": datetime(2024, 1, 1, tzinfo=UTC),
                    "end": end,
                    "batch_ids": list(observation_batch_ids),
                },
            )
        ).mappings().all()
        observations = [
            {str(key): json_ready(value) for key, value in row.items()}
            for row in observation_rows
        ]
        await session.rollback()

    observation_keys = [
        (
            item["series_code"],
            item["observation_time"],
            item["available_at"],
            item["vintage"],
        )
        for item in observations
    ]
    duplicate_observations = len(observation_keys) - len(set(observation_keys))
    source_integrity = {
        "duplicate_price_natural_keys": duplicate_price_rows,
        "duplicate_observation_natural_keys": duplicate_observations,
        "source_snapshot_price_batch_count": len(price_batch_ids),
        "source_snapshot_observation_batch_count": len(observation_batch_ids),
    }
    if duplicate_price_rows or duplicate_observations:
        raise ValueError(f"{segment_code} source duplicate gate failed")
    cases = _build_segment_cases(
        segment_code=segment_code,
        start_date=start_date,
        end_date=end_date,
        price_by_open=price_by_open,
        observations=observations,
        batch_hash_by_id=batch_hash_by_id,
    )
    return cases, source_integrity


def _build_segment_cases(
    *,
    segment_code: str,
    start_date: date,
    end_date: date,
    price_by_open: Mapping[datetime, Mapping[str, Any]],
    observations: Sequence[Mapping[str, Any]],
    batch_hash_by_id: Mapping[str, str],
) -> list[dict[str, Any]]:
    observations_by_series: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in observations:
        observations_by_series[str(item["series_code"])].append(item)
    for values in observations_by_series.values():
        values.sort(
            key=lambda item: (
                str(item["observation_time"]),
                str(item["available_at"]),
                str(item["record_id"]),
            )
        )
    candidates = {
        str(item["session_code"]): item
        for item in forward_candidate_registry()
    }
    output: list[dict[str, Any]] = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            asia_complete = _window_complete(
                price_by_open,
                session_date=current,
                timezone=TOKYO,
                start=time(10, 5),
                end=time(16, 0),
            )
            london_complete = _window_complete(
                price_by_open,
                session_date=current,
                timezone=LONDON,
                start=time(8, 0),
                end=time(12, 0),
            )
            new_york_complete = _window_complete(
                price_by_open,
                session_date=current,
                timezone=NEW_YORK,
                start=time(8, 0),
                end=time(12, 0),
            )
            eligible = {
                "LONDON": asia_complete and london_complete,
                "NEW_YORK": (
                    asia_complete and london_complete and new_york_complete
                ),
            }
            for session_code in ("LONDON", "NEW_YORK"):
                if not eligible[session_code]:
                    continue
                timezone = LONDON if session_code == "LONDON" else NEW_YORK
                decision_at = datetime.combine(
                    current,
                    time(8, 0),
                    tzinfo=timezone,
                ).astimezone(UTC)
                observation_end = datetime.combine(
                    current,
                    time(12, 0),
                    tzinfo=timezone,
                ).astimezone(UTC)
                measurement_times = [
                    decision_at + timedelta(minutes=offset)
                    for offset in range(1, 240)
                ]
                bars = [price_by_open[item] for item in measurement_times]
                candidate = candidates[session_code]
                state, signature, feature_sources = _feature_at(
                    observations_by_series[
                        str(candidate["source_series_code"])
                    ],
                    decision_at=decision_at,
                )
                sixty_bar = price_by_open[
                    decision_at + timedelta(minutes=60)
                ]
                high_bar = min(
                    bars,
                    key=lambda item: (
                        -Decimal(str(item["high"])),
                        str(item["open_time"]),
                    ),
                )
                low_bar = min(
                    bars,
                    key=lambda item: (
                        Decimal(str(item["low"])),
                        str(item["open_time"]),
                    ),
                )
                bar_payloads = [_bar_hash_payload(item) for item in bars]
                batch_hashes = [
                    batch_hash_by_id[str(item["batch_id"])] for item in bars
                ]
                output.append(
                    new_forward_case(
                        segment_code=segment_code,
                        session_code=session_code,
                        session_date=current,
                        decision_at=decision_at,
                        observation_end=observation_end,
                        feature_id=str(candidate["feature_id"]),
                        feature_state=state,
                        feature_source_signature=signature,
                        feature_source_records=feature_sources,
                        neutral_reference_open=Decimal(str(bars[0]["open"])),
                        sixty_minute_close=Decimal(
                            str(sixty_bar["close"])
                        ),
                        session_close=Decimal(str(bars[-1]["close"])),
                        session_high=Decimal(str(high_bar["high"])),
                        session_high_at=datetime.fromisoformat(
                            str(high_bar["open_time"])
                        ),
                        session_low=Decimal(str(low_bar["low"])),
                        session_low_at=datetime.fromisoformat(
                            str(low_bar["open_time"])
                        ),
                        measurement_bar_count=len(bars),
                        measurement_bar_ids_hash=canonical_hash(
                            [item["record_id"] for item in bars]
                        ),
                        measurement_bar_payload_hash=canonical_hash(
                            bar_payloads
                        ),
                        price_batch_content_hashes=batch_hashes,
                    )
                )
        current += timedelta(days=1)
    return sorted(
        output,
        key=lambda item: (
            item["session_date"],
            0 if item["session_code"] == "LONDON" else 1,
        ),
    )


def _feature_at(
    rows: Sequence[Mapping[str, Any]],
    *,
    decision_at: datetime,
) -> tuple[str, str, list[dict[str, Any]]]:
    eligible = [
        item
        for item in rows
        if datetime.fromisoformat(str(item["available_at"])) <= decision_at
        and datetime.fromisoformat(str(item["observation_time"])) <= decision_at
        and not bool(item["is_synthetic"])
    ]
    canonical: dict[str, Mapping[str, Any]] = {}
    for item in eligible:
        canonical[str(item["observation_time"])] = item
    ordered = sorted(
        canonical.values(),
        key=lambda item: str(item["observation_time"]),
    )
    if len(ordered) < 2:
        return "UNKNOWN", "UNKNOWN", []
    previous, current = ordered[-2:]
    change = Decimal(str(current["value"])) - Decimal(str(previous["value"]))
    state = "RISING" if change > 0 else "FALLING" if change < 0 else "UNCHANGED"
    previous_id = f"OBSERVATION-{previous['record_id']}"
    current_id = f"OBSERVATION-{current['record_id']}"
    signature = canonical_hash(
        {
            "absolute_change": float(change),
            "previous_record_id": previous_id,
            "record_id": current_id,
        }
    )
    sources = [
        {
            "record_id": f"OBSERVATION-{item['record_id']}",
            "source_record_key": item["source_record_key"],
            "series_code": item["series_code"],
            "observation_time": item["observation_time"],
            "available_at": item["available_at"],
            "value": float(Decimal(str(item["value"]))),
            "unit": item["unit"],
            "vintage": item["vintage"],
            "is_revision": item["is_revision"],
            "batch_id": item["batch_id"],
        }
        for item in (previous, current)
    ]
    return state, signature, sources


def _window_complete(
    price_by_open: Mapping[datetime, Mapping[str, Any]],
    *,
    session_date: date,
    timezone: ZoneInfo,
    start: time,
    end: time,
) -> bool:
    start_at = datetime.combine(
        session_date,
        start,
        tzinfo=timezone,
    ).astimezone(UTC)
    end_at = datetime.combine(
        session_date,
        end,
        tzinfo=timezone,
    ).astimezone(UTC)
    expected = int((end_at - start_at).total_seconds() // 60)
    for offset in range(expected):
        timestamp = start_at + timedelta(minutes=offset)
        row = price_by_open.get(timestamp)
        if (
            row is None
            or not bool(row["is_complete"])
            or bool(row["is_synthetic"])
            or datetime.fromisoformat(str(row["available_at"]))
            > datetime.fromisoformat(str(row["close_time"]))
        ):
            return False
    return True


def _all_required_timestamps(start: date, end: date) -> set[datetime]:
    output: set[datetime] = set()
    current = start
    while current <= end:
        if current.weekday() < 5:
            for timezone, start_time, end_time in (
                (TOKYO, time(10, 5), time(16, 0)),
                (LONDON, time(8, 0), time(12, 0)),
                (NEW_YORK, time(8, 0), time(12, 0)),
            ):
                start_at = datetime.combine(
                    current,
                    start_time,
                    tzinfo=timezone,
                ).astimezone(UTC)
                end_at = datetime.combine(
                    current,
                    end_time,
                    tzinfo=timezone,
                ).astimezone(UTC)
                cursor = start_at
                while cursor < end_at:
                    output.add(cursor)
                    cursor += timedelta(minutes=1)
        current += timedelta(days=1)
    return output


def _bar_hash_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in (
            "record_id",
            "open_time",
            "close_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "volume_type",
            "spread_points",
            "spread_price",
            "available_at",
            "batch_id",
            "source_record_key",
            "is_complete",
            "is_synthetic",
        )
    }


def _seal_segment(
    *,
    segment_dir: Path,
    segment: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    result: Mapping[str, Any],
    preopen: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    if segment_dir.exists() and any(segment_dir.iterdir()):
        raise FileExistsError(f"Segment already sealed: {segment_dir}")
    segment_dir.mkdir(parents=True, exist_ok=True)
    cases_path = segment_dir / "cases.jsonl"
    with cases_path.open("w", encoding="utf-8", newline="\n") as stream:
        for case in cases:
            stream.write(
                json.dumps(
                    json_ready(case),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
    result_path = segment_dir / "result.json"
    _write_json(result_path, result)
    manifest: dict[str, Any] = {
        "manifest_version": RESULT_BUNDLE_VERSION,
        "milestone": "V3_M6B_SEGMENT_EVALUATION",
        "sealed_at": datetime.now(UTC).isoformat(),
        "segment": dict(segment),
        "preopen_manifest_hash": preopen["manifest_hash"],
        "source_snapshot_hash": source_snapshot["source_snapshot_hash"],
        "case_artifact": {
            "path": _portable(cases_path),
            "case_count": len(cases),
            "case_version": M6B_CASE_VERSION,
            "file_sha256": sha256_file(cases_path),
            "bytes": cases_path.stat().st_size,
        },
        "result_artifact": {
            "path": _portable(result_path),
            "segment_hash": result["segment_hash"],
            "file_sha256": sha256_file(result_path),
            "bytes": result_path.stat().st_size,
        },
        "opened_and_evaluated_once": True,
        "independent_validation_credit": bool(
            segment["positive_validation_credit"]
        ),
        "research_boundary": dict(result["research_boundary"]),
        "verdict": "PASS_M6B_SEGMENT_BUILT_AND_SEALED",
        "manifest_hash": "",
    }
    manifest["manifest_hash"] = _embedded_hash(manifest, "manifest_hash")
    manifest_path = segment_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    return {
        **manifest,
        "manifest_path": _portable(manifest_path),
        "manifest_file_sha256": sha256_file(manifest_path),
    }


def _initialize_prospective_ledger(
    directory: Path,
    *,
    preopen: Mapping[str, Any],
) -> dict[str, Any]:
    if directory.exists() and any(directory.iterdir()):
        raise FileExistsError("Prospective ledger already initialized")
    directory.mkdir(parents=True, exist_ok=True)
    ledger_path = directory / "prospective_decisions.jsonl"
    ledger_path.touch(exist_ok=False)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Gold V3 M6B prospective decision record",
        "type": "object",
        "required": [
            "candidate_code",
            "protocol_hash",
            "session_date",
            "session_code",
            "decision_clock",
            "decision_as_of",
            "candidate_state_or_unknown",
            "source_record_ids",
            "source_available_at_timestamps",
            "source_hashes",
            "decision_record_hash",
            "sealed_at",
            "eligibility",
            "missing_reason",
            "append_only_neutral_outcome",
        ],
        "additionalProperties": False,
    }
    schema_path = directory / "prospective_decision.schema.json"
    _write_json(schema_path, schema)
    manifest: dict[str, Any] = {
        "ledger_version": PROSPECTIVE_LEDGER_VERSION,
        "initialized_at": datetime.now(UTC).isoformat(),
        "protocol_fingerprint": protocol_fingerprint(),
        "preopen_manifest_hash": preopen["manifest_hash"],
        "calendar": {
            "start_session_date": "2026-07-31",
            "end_session_date": "2026-12-31",
            "next_eligible_session_date_at_initialization": "2026-07-31",
        },
        "ledger": {
            "path": _portable(ledger_path),
            "record_count": 0,
            "file_sha256": sha256_file(ledger_path),
            "append_only": True,
        },
        "schema": {
            "path": _portable(schema_path),
            "file_sha256": sha256_file(schema_path),
        },
        "policy": {
            "decision_must_be_sealed_before_08_01_local": True,
            "missed_decision_backfill_permitted": False,
            "interim_inferential_testing_permitted": False,
            "outcome_added_only_after_observation_end": True,
        },
        "backfilled_decisions": 0,
        "manifest_hash": "",
    }
    manifest["manifest_hash"] = _embedded_hash(manifest, "manifest_hash")
    manifest_path = directory / "manifest.json"
    _write_json(manifest_path, manifest)
    return {
        "manifest_path": _portable(manifest_path),
        "manifest_hash": manifest["manifest_hash"],
        "manifest_file_sha256": sha256_file(manifest_path),
        "ledger_path": _portable(ledger_path),
        "ledger_file_sha256": sha256_file(ledger_path),
        "record_count": 0,
        "backfilled_decisions": 0,
        "next_eligible_session_date": "2026-07-31",
    }


def _expected_case_counts(
    *,
    root: Path,
    preopen: Mapping[str, Any],
    segment_code: str,
) -> dict[str, int]:
    readiness_path = (root / preopen["metadata_readiness"]["path"]).resolve()
    readiness = _load_json(readiness_path)
    assessments = readiness["partitions"][segment_code][
        "candidate_assessments"
    ]
    return {
        str(item["session_code"]): int(
            item["potential_complete_session_cases"]
        )
        for item in assessments
    }


def _verify_preopen(*, root: Path, path: Path) -> dict[str, Any]:
    preopen = _load_json(path)
    if _embedded_hash(preopen, "manifest_hash") != preopen.get("manifest_hash"):
        raise ValueError("M6B pre-open manifest embedded hash mismatch")
    if preopen.get("protocol_fingerprint") != protocol_fingerprint():
        raise ValueError("M6B pre-open protocol fingerprint mismatch")
    if validate_m6b_freeze():
        raise ValueError(f"M6B frozen design failed: {validate_m6b_freeze()}")
    for relative, expected in preopen["implementation_freeze"].items():
        implementation_path = (root / relative).resolve()
        _assert_within(root, implementation_path)
        if sha256_file(implementation_path) != expected:
            raise ValueError(f"M6B implementation seal mismatch: {relative}")
    source_path = (root / preopen["source_snapshot"]["path"]).resolve()
    readiness_path = (
        root / preopen["metadata_readiness"]["path"]
    ).resolve()
    if sha256_file(source_path) != preopen["source_snapshot"]["file_sha256"]:
        raise ValueError("M6B source snapshot file seal mismatch")
    if sha256_file(readiness_path) != preopen["metadata_readiness"][
        "file_sha256"
    ]:
        raise ValueError("M6B readiness file seal mismatch")
    if list(M5_SHORTLIST_CODES) != preopen["research_boundary"][
        "candidate_codes"
    ]:
        raise ValueError("M6B pre-open candidate inventory mismatch")
    return preopen


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": _portable(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _embedded_hash(
    document: Mapping[str, Any],
    field: str,
    *,
    excluded: Sequence[str] = (),
) -> str:
    return canonical_hash(
        {
            key: value
            for key, value in document.items()
            if key != field and key not in set(excluded)
        }
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_ready(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _portable(path: Path) -> str:
    return str(path).replace("\\", "/")


def _assert_within(root: Path, path: Path) -> None:
    if path != root and root not in path.parents:
        raise ValueError(f"Path must remain inside repository root: {path}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Open and seal the 2025 and 2026-YTD V3 M6B segments once in "
            "the frozen order, then initialize the empty prospective ledger."
        )
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--preopen-manifest",
        default=(
            "research_manifests/"
            "gold_session_behaviour_v3_m6b_preopen_v01.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=(
            "research_artifacts/"
            "gold_session_behaviour_v3_m6b_results_v01"
        ),
    )
    return parser


if __name__ == "__main__":
    asyncio.run(main())
