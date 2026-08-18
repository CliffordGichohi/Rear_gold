from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_gold_multitimeframe_trend_continuation_census_v1 as census_impl  # noqa: E402
import materialize_gold_trend_pullback_continuation_edge_v1 as feature_impl  # noqa: E402
import materialize_gold_trend_pullback_movement_anatomy_edge_v1 as anatomy_impl  # noqa: E402
import run_gold_h4_half_retrace_final_falsification_v1 as forward_source_impl  # noqa: E402
import run_gold_pullback_archetype_setup_routing_v1_development as dev  # noqa: E402
import run_gold_trend_pullback_continuation_economic_v1_development as econ  # noqa: E402


ARTIFACTS = ROOT / "research_artifacts"
OUTPUT = ARTIFACTS / "gold_pullback_archetype_setup_routing_v1_forward"
DEVELOPMENT = ARTIFACTS / "gold_pullback_archetype_setup_routing_v1_r1"
FROZEN_SYSTEM = DEVELOPMENT / "frozen_system_pre_forward.json"
DEVELOPMENT_SEAL = DEVELOPMENT / "development_seal.json"
STATE_PRE_FORWARD = DEVELOPMENT / "state_pre_forward.json"
H4_FORWARD_CERT = ARTIFACTS / "gold_h4_half_retrace_final_falsification_v1/forward_source_certification.json"
COT_SOURCE = ARTIFACTS / "gold_h4_half_retrace_final_falsification_v1/cftc_gold_cot_forward_source.json"
COT_SEAL = ARTIFACTS / "gold_h4_half_retrace_final_falsification_v1/cftc_gold_cot_forward_source_seal.json"
CENSUS_DIR = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"
REPORT = ROOT / "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_AND_RISK_ALLOCATION_V1_FINAL.md"
FORWARD_ATTEMPT_FAILURE = OUTPUT / "forward_attempt_1_failure.json"
FORWARD_RECOVERY = ROOT / "research_manifests/gold_pullback_archetype_setup_routing_v1_forward_recovery_a.json"
FORWARD_ATTEMPT_FAILURE_2 = OUTPUT / "forward_attempt_2_failure.json"
FORWARD_RECOVERY_2 = ROOT / "research_manifests/gold_pullback_archetype_setup_routing_v1_forward_recovery_b.json"

FORWARD_START = datetime(2025, 1, 1, tzinfo=UTC)
FORWARD_END = datetime(2026, 7, 30, tzinfo=UTC)
MINUTE_NS = 60_000_000_000
TF_DURATION_NS = {"M15": 15 * MINUTE_NS, "H1": 60 * MINUTE_NS, "H4": 240 * MINUTE_NS}
TF_EXPECTED_MINUTES = {"M15": 15, "H1": 60, "H4": 240}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed.astimezone(UTC)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def rounded(value: float | None) -> float | None:
    return dev.rounded(value)


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_text_exclusive(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    table = pa.Table.from_pylist(list(rows))
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6", row_group_size=16_384)
    temporary.replace(path)


def verify_preopen_and_seal_metadata() -> tuple[dict[str, Any], dict[str, Any], list[tuple[Path, Mapping[str, Any]]]]:
    for path in (FROZEN_SYSTEM, DEVELOPMENT_SEAL, STATE_PRE_FORWARD, H4_FORWARD_CERT, COT_SOURCE, COT_SEAL):
        if not path.is_file():
            raise FileNotFoundError(path)
    system = json.loads(FROZEN_SYSTEM.read_text(encoding="utf-8"))
    development_seal = json.loads(DEVELOPMENT_SEAL.read_text(encoding="utf-8"))
    state = json.loads(STATE_PRE_FORWARD.read_text(encoding="utf-8"))
    if system["status"] != "FROZEN_FULL_DEVELOPMENT_SYSTEM_BEFORE_FORWARD_VALUES":
        raise ValueError("Full-development system is not frozen")
    if system["calendar_2025_values_accessed"] or system["calendar_2026_values_accessed"]:
        raise ValueError("Forward values were already opened by this branch")
    if state["status"] != "READY_FOR_SINGLE_EXPOSED_FORWARD_APPLICATION":
        raise ValueError("Pre-forward state is not ready")
    if state["development_seal"] != file_record(DEVELOPMENT_SEAL) or state["frozen_system"] != file_record(FROZEN_SYSTEM):
        raise ValueError("Pre-forward state lineage changed")
    if development_seal["calendar_2025_values_accessed"] or development_seal["calendar_2026_values_accessed"]:
        raise ValueError("Development seal records forward access")
    sources = forward_source_impl.canonical_xau_sources()
    existing_cert = json.loads(H4_FORWARD_CERT.read_text(encoding="utf-8"))
    declared = {Path(item["path"]).name: item for item in existing_cert["xau_source_files"]}
    if len(sources) != 29 or set(declared) != {path.name for path, _ in sources}:
        raise ValueError("Forward XAUUSD source registry changed")
    for path, metadata in sources:
        if declared[path.name]["sha256"] != sha256_file(path) or metadata["content_hash"] != sha256_file(path):
            raise ValueError(f"Forward source hash changed: {path.name}")
    cot_seal = json.loads(COT_SEAL.read_text(encoding="utf-8"))
    if cot_seal["status"] != "SEALED_OFFICIAL_PUBLIC_SOURCE" or cot_seal["charge_usd"] != 0.0:
        raise ValueError("Forward COT source seal invalid")
    if cot_seal["raw_source"] != file_record(COT_SOURCE):
        raise ValueError("Forward COT source changed")
    preopen = {
        "version": "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_V1_FORWARD_PREOPEN_1_0",
        "status": "SEALED_BEFORE_SINGLE_FORWARD_VALUE_OPENING",
        "sealed_at_utc": utc_now(),
        "development_seal": file_record(DEVELOPMENT_SEAL),
        "frozen_system": file_record(FROZEN_SYSTEM),
        "source_registry": [file_record(path) for path, _ in sources],
        "source_registry_hash": canonical_hash([sha256_file(path) for path, _ in sources]),
        "cot_source": file_record(COT_SOURCE),
        "cot_seal": file_record(COT_SEAL),
        "forward_segments": {
            "2025": ["2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z"],
            "2026_YTD": ["2026-01-01T00:00:00Z", "2026-07-30T00:00:00Z"]
        },
        "paid_acquisition_authorized": False,
        "charge_usd": 0.0,
        "retuning_permitted": False,
        "market_values_accessed_before_seal": False,
    }
    preopen_path = OUTPUT / "forward_preopen_seal.json"
    if preopen_path.exists():
        existing = json.loads(preopen_path.read_text(encoding="utf-8"))
        for key in ("status", "development_seal", "frozen_system", "source_registry", "source_registry_hash", "cot_source", "cot_seal", "forward_segments", "charge_usd"):
            if existing.get(key) != preopen.get(key):
                raise ValueError(f"Existing pre-open seal differs at {key}")
        if not all(path.is_file() for path in (FORWARD_ATTEMPT_FAILURE, FORWARD_RECOVERY, FORWARD_ATTEMPT_FAILURE_2, FORWARD_RECOVERY_2)):
            raise ValueError("Operational recovery controls are absent")
        failure = json.loads(FORWARD_ATTEMPT_FAILURE.read_text(encoding="utf-8"))
        recovery = json.loads(FORWARD_RECOVERY.read_text(encoding="utf-8"))
        failure_2 = json.loads(FORWARD_ATTEMPT_FAILURE_2.read_text(encoding="utf-8"))
        recovery_2 = json.loads(FORWARD_RECOVERY_2.read_text(encoding="utf-8"))
        if failure.get("status") != "FAIL_OPERATIONAL_COMMAND_TIMEOUT_NO_RESEARCH_RESULT":
            raise ValueError("Preserved operational failure is invalid")
        if recovery.get("status") != "FROZEN_BEFORE_OPERATIONAL_RESTART" or recovery.get("additional_source_openings_permitted") != 1:
            raise ValueError("Operational recovery amendment is invalid")
        if failure["preopen_seal"] != file_record(preopen_path):
            raise ValueError("Preserved pre-open seal changed after the failed attempt")
        if failure_2.get("status") != "FAIL_PRE_SCORING_FROZEN_FIELD_PATH_LOOKUP_NO_RESEARCH_RESULT":
            raise ValueError("Second preserved implementation failure is invalid")
        if recovery_2.get("status") != "FROZEN_BEFORE_FINAL_IMPLEMENTATION_RESTART" or recovery_2.get("required_cumulative_source_opening_count") != 3:
            raise ValueError("Final implementation recovery amendment is invalid")
    else:
        write_json_exclusive(preopen_path, preopen)
    return system, development_seal, sources


def development_overlap() -> tuple[anatomy_impl.PriceData, dict[int, tuple[int, int, int, int, float]]]:
    prices = anatomy_impl.load_price()
    threshold = int(datetime(2024, 12, 4, 14, 5, tzinfo=UTC).timestamp() * 1_000_000_000)
    overlap = {}
    for index in np.flatnonzero(prices.open_ns >= threshold):
        overlap[int(prices.open_ns[index])] = (
            int(prices.open_e8[index]),
            int(prices.high_e8[index]),
            int(prices.low_e8[index]),
            int(prices.close_e8[index]),
            float(prices.spread[index]),
        )
    if len(overlap) < 20_000:
        raise ValueError("Insufficient sealed development overlap")
    return prices, overlap


def aggregate_rows(prices: anatomy_impl.PriceData, timeframe: str, implementation: str) -> list[dict[str, Any]]:
    duration = TF_DURATION_NS[timeframe]
    expected = TF_EXPECTED_MINUTES[timeframe]
    rows: list[dict[str, Any]] = []
    if implementation == "primary":
        buckets: dict[int, list[int]] = defaultdict(list)
        for index, opened in enumerate(prices.open_ns.tolist()):
            buckets[(int(opened) // duration) * duration].append(index)
        groups = [(bucket, indices) for bucket, indices in sorted(buckets.items())]
    else:
        groups = []
        current_bucket = None
        current: list[int] = []
        for index, opened in enumerate(prices.open_ns.tolist()):
            bucket = (int(opened) // duration) * duration
            if current_bucket is not None and bucket != current_bucket:
                groups.append((current_bucket, current))
                current = []
            current_bucket = bucket
            current.append(index)
        if current_bucket is not None:
            groups.append((current_bucket, current))
    for bucket, indices in groups:
        timestamps = prices.open_ns[indices]
        complete = len(indices) == expected and int(timestamps[0]) == bucket and int(timestamps[-1]) == bucket + (expected - 1) * MINUTE_NS
        row = {
            "timeframe": timeframe,
            "open_ns": bucket,
            "close_ns": bucket + duration,
            "open_e8": int(prices.open_e8[indices[0]]),
            "high_e8": int(np.max(prices.high_e8[indices])),
            "low_e8": int(np.min(prices.low_e8[indices])),
            "close_e8": int(prices.close_e8[indices[-1]]),
            "volume": None,
            "complete": bool(complete),
        }
        row["record_hash"] = canonical_hash(["UTC_FIXED_BUCKET_FORWARD_V1", *row.values(), int(timestamps[0]), int(timestamps[-1]), len(indices)])
        rows.append(row)
    return rows


def make_parent(rows: Sequence[Mapping[str, Any]]) -> anatomy_impl.ParentBars:
    return anatomy_impl.ParentBars(
        np.asarray([int(row["close_ns"]) for row in rows], dtype=np.int64),
        np.asarray([int(row["open_e8"]) for row in rows], dtype=np.int64),
        np.asarray([int(row["high_e8"]) for row in rows], dtype=np.int64),
        np.asarray([int(row["low_e8"]) for row in rows], dtype=np.int64),
        np.asarray([int(row["close_e8"]) for row in rows], dtype=np.int64),
    )


def feature_bar(row: Mapping[str, Any]) -> feature_impl.Bar:
    return feature_impl.Bar(
        str(row["timeframe"]),
        datetime.fromtimestamp(int(row["open_ns"]) / 1_000_000_000, tz=UTC),
        datetime.fromtimestamp(int(row["close_ns"]) / 1_000_000_000, tz=UTC),
        int(row["open_e8"]), int(row["high_e8"]), int(row["low_e8"]), int(row["close_e8"]),
        None, bool(row["complete"]), str(row["record_hash"]),
    )


def census_bar(row: Mapping[str, Any]) -> census_impl.Bar:
    return census_impl.Bar(
        str(row["timeframe"]),
        datetime.fromtimestamp(int(row["open_ns"]) / 1_000_000_000, tz=UTC),
        datetime.fromtimestamp(int(row["close_ns"]) / 1_000_000_000, tz=UTC),
        int(row["open_e8"]), int(row["high_e8"]), int(row["low_e8"]), int(row["close_e8"]),
        bool(row["complete"]), str(row["record_hash"]),
    )


def combine_bars(
    dev_bars: Mapping[str, Sequence[feature_impl.Bar]],
    forward_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[dict[str, list[feature_impl.Bar]], dict[str, list[census_impl.Bar]], dict[str, Any]]:
    feature_bars: dict[str, list[feature_impl.Bar]] = {}
    census_bars: dict[str, list[census_impl.Bar]] = {}
    diagnostics: dict[str, Any] = {}
    floors = {"M15": 1_000, "H1": 300, "H4": 100}
    for timeframe in dev.TIMEFRAMES:
        dev_map = {bar.open_at: bar for bar in dev_bars[timeframe]}
        overlap = 0
        for row in forward_rows[timeframe]:
            bar = feature_bar(row)
            if bar.open_at < datetime(2024, 12, 5, tzinfo=UTC) or bar.open_at >= FORWARD_START:
                continue
            expected = dev_map.get(bar.open_at)
            if expected is None:
                continue
            if (bar.open_e8, bar.high_e8, bar.low_e8, bar.close_e8, bar.complete) != (
                expected.open_e8, expected.high_e8, expected.low_e8, expected.close_e8, expected.complete
            ):
                raise ValueError(f"Forward/development {timeframe} overlap differs: {bar.open_at}")
            overlap += 1
        if overlap < floors[timeframe]:
            raise ValueError(f"Insufficient {timeframe} overlap: {overlap}")
        combined = [bar for bar in dev_bars[timeframe] if bar.open_at < FORWARD_START]
        combined.extend(feature_bar(row) for row in forward_rows[timeframe] if FORWARD_START <= feature_bar(row).open_at < FORWARD_END)
        combined.sort(key=lambda bar: bar.open_at)
        if len(combined) != len({bar.open_at for bar in combined}):
            raise ValueError(f"Duplicate combined {timeframe} bar")
        feature_bars[timeframe] = combined
        census_bars[timeframe] = [
            census_impl.Bar(
                bar.timeframe, bar.open_at, bar.close_at, bar.open_e8, bar.high_e8, bar.low_e8,
                bar.close_e8, bar.complete, bar.record_hash,
            )
            for bar in combined
        ]
        diagnostics[timeframe] = {
            "overlap_bars_exact": overlap,
            "combined_bars": len(combined),
            "forward_bars": sum(bar.open_at >= FORWARD_START for bar in combined),
        }
    return feature_bars, census_bars, diagnostics


def build_forward_structure(
    bars: Mapping[str, Sequence[census_impl.Bar]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    census_impl.END = FORWARD_END
    all_cases: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []
    all_swings: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {}
    for timeframe in dev.TIMEFRAMES:
        primary_swings = census_impl.derive_swings(bars[timeframe], timeframe, "STANDARD", 2, "primary")
        reference_swings = census_impl.derive_swings(bars[timeframe], timeframe, "STANDARD", 2, "reference")
        if primary_swings != reference_swings:
            raise ValueError(f"Forward swing reproduction differs: {timeframe}")
        primary_events, primary_cases, primary_segments = census_impl.enumerate_structure(bars[timeframe], primary_swings, timeframe, "STANDARD", 2, "primary")
        reference_events, reference_cases, reference_segments = census_impl.enumerate_structure(bars[timeframe], reference_swings, timeframe, "STANDARD", 2, "reference")
        if primary_events != reference_events or primary_cases != reference_cases or primary_segments != reference_segments:
            raise ValueError(f"Forward structure reproduction differs: {timeframe}")
        sealed_rows = pq.read_table(CENSUS_DIR / "primary_pullback_cases.parquet").to_pylist()
        sealed = {str(row["pullback_id"]): row for row in sealed_rows if row["timeframe"] == timeframe and row["scale"] == "STANDARD"}
        extended = {str(row["pullback_id"]): row for row in primary_cases if str(row["known_at_utc"]) < "2025-01-01T00:00:00Z"}
        if set(sealed) != set(extended):
            raise ValueError(f"Development case identities changed for {timeframe}: {len(sealed)} vs {len(extended)}")
        identity_fields = (
            "pullback_id", "direction", "pivot_at_utc", "known_at_utc", "pivot_price_e8",
            "reference_event_id", "reference_level_e8", "actionable_at_known", "decision_facts_hash",
        )
        for identity, row in sealed.items():
            if any(row[field] != extended[identity][field] for field in identity_fields):
                raise ValueError(f"Development decision facts changed: {identity}")
        eligible = [
            row for row in primary_cases
            if FORWARD_START <= parse_dt(str(row["known_at_utc"])) < FORWARD_END
            and row["actionable_at_known"] is True
            and row["research_eligible"] is True
            and row["resolution"] in {"CONTINUED", "FAILED_STRUCTURE_SWITCH"}
        ]
        eligible.sort(key=lambda row: (row["known_at_utc"], row["pullback_id"]))
        all_cases.extend(eligible)
        all_events.extend(primary_events)
        all_swings.extend([
            {
                "swing_id": swing.swing_id,
                "timeframe": swing.timeframe,
                "scale": swing.scale,
                "span": swing.span,
                "side": swing.side,
                "pivot_at_utc": census_impl.iso_z(swing.pivot_at),
                "known_at_utc": census_impl.iso_z(swing.known_at),
                "price_e8": swing.price_e8,
                "evidence_hash": swing.evidence_hash,
            }
            for swing in primary_swings
        ])
        diagnostics[timeframe] = {
            "development_identities_exact": len(sealed),
            "swings": len(primary_swings),
            "events": len(primary_events),
            "all_cases": len(primary_cases),
            "eligible_forward_cases": len(eligible),
            "by_year": dict(sorted(Counter(str(row["known_at_utc"])[:4] for row in eligible).items())),
        }
    all_cases.sort(key=lambda row: (row["known_at_utc"], dev.TIMEFRAME_PRIORITY[row["timeframe"]], row["pullback_id"]))
    all_events.sort(key=lambda row: (row["event_at_utc"], row["timeframe"], row["event_id"]))
    return all_cases, all_events, all_swings, diagnostics


def event_context(events: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Mapping[str, Any]], dict[str, list[Mapping[str, Any]]], dict[str, tuple[list[datetime], list[str]]]]:
    by_id = {str(row["event_id"]): row for row in events}
    by_segment: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in events:
        by_segment[str(row["segment_id"])].append(row)
    for values in by_segment.values():
        values.sort(key=lambda row: (row["event_at_utc"], row["event_id"]))
    return by_id, by_segment, feature_impl.structure_timelines(events)


def materialize_forward_features(
    cases: Sequence[Mapping[str, Any]],
    bars: Mapping[str, Sequence[feature_impl.Bar]],
    events: Sequence[Mapping[str, Any]],
    positioning: Sequence[Mapping[str, Any]],
    positioning_times: Sequence[datetime],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    feature_impl.END = FORWARD_END
    close_times = {key: [bar.close_at for bar in values] for key, values in bars.items()}
    close_indexes = {key: {bar.close_at: index for index, bar in enumerate(values)} for key, values in bars.items()}
    atrs = {key: feature_impl.rolling_atr(values) for key, values in bars.items()}
    daily, _, weekly = feature_impl.build_daily_and_weekly(bars["M15"])
    asia, asia_times = feature_impl.build_asia_ranges(bars["M15"])
    by_id, by_segment, timelines = event_context(events)
    shared = (bars, close_times, close_indexes, atrs, by_id, by_segment, timelines, daily, weekly, asia, asia_times, [], [], positioning, positioning_times)
    primary = [feature_impl.feature_row(case, *shared, "primary") for case in cases]
    reference = [feature_impl.feature_row(case, *shared, "reference") for case in cases]
    primary.sort(key=lambda row: (row["known_at_utc"], dev.TIMEFRAME_PRIORITY[row["timeframe"]], row["pullback_id"]))
    reference.sort(key=lambda row: (row["known_at_utc"], dev.TIMEFRAME_PRIORITY[row["timeframe"]], row["pullback_id"]))
    if canonical_hash(primary) != canonical_hash(reference):
        raise ValueError("Forward feature implementations differ")
    diagnostics = {
        "cases": len(cases),
        "available": sum(bool(row["feature_available"]) for row in primary),
        "unavailable": sum(not bool(row["feature_available"]) for row in primary),
        "unavailable_reasons": dict(sorted(Counter(str(row.get("unavailable_reason") or "AVAILABLE") for row in primary).items())),
        "forward_fundamental_policy": "EXPLICIT_UNKNOWN_NO_BACKFILL",
        "fundamental_available_rows": sum(bool(row.get("fundamental_available")) for row in primary),
        "cot_available_rows": sum(bool(row.get("cot_available")) for row in primary),
        "primary_reference_exact": True,
    }
    return primary, reference, diagnostics


def assign_archetype(
    resolution: str,
    confirmation_break: Mapping[str, Any],
    half_retrace: Mapping[str, Any],
    break_retest: Mapping[str, Any],
    barrier_order: str,
) -> str:
    break_formed = confirmation_break.get("status") == "FORMED"
    half_formed = half_retrace.get("status") == "FORMED"
    retest_formed = break_retest.get("status") == "FORMED"
    half_at = parse_dt(str(half_retrace["entry_at_utc"])) if half_formed else None
    retest_at = parse_dt(str(break_retest["entry_at_utc"])) if retest_formed else None
    if resolution == "CONTINUED":
        if half_formed and (not retest_formed or (half_at is not None and retest_at is not None and half_at <= retest_at)):
            return "DEEP_RETRACE_CONTINUATION"
        if retest_formed:
            return "BREAK_RETEST_CONTINUATION"
        if break_formed and not half_formed:
            return "RUNAWAY_CONTINUATION"
        return "TWO_SIDED_CHOPPY"
    if break_formed:
        return "FALSE_CONTINUATION"
    if barrier_order == "ADVERSE_FIRST":
        return "IMMEDIATE_FAILURE"
    return "TWO_SIDED_CHOPPY"


def materialize_forward_anatomy(
    features: Sequence[Mapping[str, Any]],
    case_map: Mapping[str, Mapping[str, Any]],
    prices: anatomy_impl.PriceData,
    implementation: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    anatomy_impl.END_NS = int(FORWARD_END.timestamp() * 1_000_000_000)
    anatomies: list[dict[str, Any]] = []
    triggers: list[dict[str, Any]] = []
    atlas: list[dict[str, Any]] = []
    for feature in features:
        if not feature["feature_available"]:
            continue
        identity = str(feature["pullback_id"])
        case = dict(feature)
        case.update(case_map[identity])
        anatomy, trigger_rows = anatomy_impl.anatomy_row(case, prices, implementation)
        anatomies.append(anatomy)
        triggers.extend(trigger_rows)
        by_name = {str(row["trigger"]): row for row in trigger_rows}
        technical_reason = None
        required = ("CONFIRMATION_EXTREME_BREAK", "RESPONSE_HALF_RETRACE_LIMIT", "BREAK_RETEST_CONFIRM")
        if not bool(anatomy.get("complete_path_available")):
            technical_reason = str(anatomy.get("unavailable_reason") or anatomy.get("path_classification") or "INCOMPLETE_MOVEMENT_PATH")
        elif any(name not in by_name for name in required):
            technical_reason = "MISSING_REQUIRED_TRIGGER"
        if technical_reason is None:
            label = assign_archetype(
                str(case["resolution"]), by_name["CONFIRMATION_EXTREME_BREAK"], by_name["RESPONSE_HALF_RETRACE_LIMIT"],
                by_name["BREAK_RETEST_CONFIRM"], str(anatomy.get("barrier_0p5_order") or "NEITHER"),
            )
            technical = True
        else:
            label = "UNAVAILABLE_TECHNICAL"
            technical = False
        atlas.append({
            "pullback_id": identity,
            "timeframe": str(feature["timeframe"]),
            "direction": str(feature["direction"]),
            "known_at_utc": str(feature["known_at_utc"]),
            "archetype": label,
            "technical_available": technical,
            "technical_unavailable_reason": technical_reason or "",
        })
    anatomies.sort(key=lambda row: (row["known_at_utc"], dev.TIMEFRAME_PRIORITY[row["timeframe"]], row["pullback_id"]))
    triggers.sort(key=lambda row: (row["known_at_utc"], dev.TIMEFRAME_PRIORITY[row["timeframe"]], row["pullback_id"], anatomy_impl.TRIGGERS.index(str(row["trigger"]))))
    atlas.sort(key=lambda row: (row["known_at_utc"], dev.TIMEFRAME_PRIORITY[row["timeframe"]], row["pullback_id"]))
    return anatomies, triggers, atlas


def forward_probabilities(model: Mapping[str, Any], signal: Mapping[str, Any]) -> np.ndarray:
    deterministic = dev.deterministic_failure_probabilities(signal)
    if deterministic is not None:
        return deterministic
    tree = model.get("tree")
    if tree is None:
        raise ValueError(f"Missing frozen probability tree: {model['timeframe']}|{model['model_id']}")
    return dev.apply_temperature(dev.predict_tree_row(tree, signal), float(model["temperature"]))


def forward_payoff_score(model: Mapping[str, Any], probabilities: np.ndarray, system: Mapping[str, Any]) -> tuple[float, float, float]:
    expected = 0.0
    variance = 0.0
    for index, archetype in enumerate(dev.CLASSES):
        cell = model["payoff_cells"][archetype]
        mean = float(cell["shrunk_mean_r"])
        cell_variance = float(cell["variance"])
        count = max(1, int(cell["n"]))
        expected += float(probabilities[index]) * mean
        variance += float(probabilities[index]) ** 2 * cell_variance / count
    standard_error = math.sqrt(max(0.0, variance))
    conservative = expected - float(system["payoff_estimator"]["conservative_standard_errors"]) * standard_error
    return expected, standard_error, conservative


def score_forward(
    trades: Sequence[Mapping[str, Any]],
    signals: Sequence[Mapping[str, Any]],
    system: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    model_map = {(str(row["timeframe"]), str(row["model_id"])): row for row in system["models"]}
    trade_map = {(str(row["model_id"]), str(row["pullback_id"])): row for row in trades}
    predictions = []
    for signal in signals:
        trade = trade_map[(str(signal["model_id"]), str(signal["pullback_id"]))]
        if trade["status"] != "EXECUTED":
            continue
        model = model_map[(str(signal["timeframe"]), str(signal["model_id"]))]
        probabilities = forward_probabilities(model, signal)
        expected, standard_error, conservative = forward_payoff_score(model, probabilities, system)
        risk = dev.risk_tier(conservative, {"risk": system["risk"]})
        row = {
            "prediction_id": f"GPARF-{canonical_hash([signal['timeframe'], signal['model_id'], signal['pullback_id']])[:24]}",
            "fold": 0,
            "timeframe": str(signal["timeframe"]),
            "model_id": str(signal["model_id"]),
            "pullback_id": str(signal["pullback_id"]),
            "known_at_utc": str(signal["known_at_utc"]),
            "checkpoint_at_utc": str(signal["checkpoint_at_utc"]),
            "session_state": str(signal["session_state"]),
            "checkpoint_session_state": str(signal["checkpoint_session_state"]),
            "actual_archetype": str(signal["archetype"]) if signal["technical_available"] else "UNAVAILABLE_TECHNICAL",
            "predicted_archetype": dev.CLASSES[int(np.argmax(probabilities))],
            "prediction_confidence": rounded(float(np.max(probabilities))),
            "expected_net_r": rounded(expected),
            "expected_standard_error_r": rounded(standard_error),
            "conservative_score_r": rounded(conservative),
            "assigned_risk_usd": risk,
            "calibration_eligible": bool(model["calibration_eligible"]),
            "trade_id": str(trade["trade_id"]),
            "entry_at_utc": str(trade["entry_at_utc"]),
            "exit_at_utc": str(trade["exit_at_utc"]),
            "net_r": float(trade["net_r"]),
            "net_r_cost_1p5x": float(trade["net_r_cost_1p5x"]),
            "net_r_cost_2x": float(trade["net_r_cost_2x"]),
        }
        row.update({f"p_{name}": rounded(float(probabilities[index])) for index, name in enumerate(dev.CLASSES)})
        predictions.append(row)
    predictions.sort(key=lambda row: (row["entry_at_utc"], dev.TIMEFRAME_PRIORITY[row["timeframe"]], system["router_tie_priority"].index(row["model_id"]), row["pullback_id"]))
    labeled = [row for row in predictions if row["actual_archetype"] in dev.CLASS_INDEX]
    correct = sum(row["predicted_archetype"] == row["actual_archetype"] for row in labeled)
    diagnostics = {
        "prediction_rows": len(predictions),
        "technically_labeled_rows": len(labeled),
        "technically_unavailable_rows": len(predictions) - len(labeled),
        "top1_accuracy_pct": rounded(100 * correct / len(labeled)) if labeled else None,
        "calibration_eligible_prediction_rows": sum(bool(row["calibration_eligible"]) for row in predictions),
        "positive_risk_prediction_rows": sum(bool(row["calibration_eligible"]) and float(row["assigned_risk_usd"]) > 0 for row in predictions),
    }
    return predictions, diagnostics


def summary_for_rows(rows: Sequence[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (str(row["entry_at_utc"]), str(row["trade_id"])))
    if not ordered:
        return {
            "metrics": {"trades": 0, "expectancy_r": None, "profit_factor": None, "win_rate_pct": None, "net_pnl_usd": 0.0},
            "bootstrap": {"ci90": [None, None], "ci95": [None, None], "p_one_sided": None, "valid_resamples": 0},
            "stress": {"cost_1p5x_expectancy_r": None, "cost_2x_expectancy_r": None, "cost_1p5x_net_pnl_usd": 0.0, "cost_2x_net_pnl_usd": 0.0},
            "ending_balance_usd": 10_000.0,
            "total_return_pct": 0.0,
            "by_model": {}, "by_timeframe": {}, "sessions": {},
        }
    metrics = econ.basic_metrics(ordered)
    bootstrap = econ.cluster_bootstrap(ordered, "net_r", seed, resamples=5000)
    def grouped(field: str, values: Sequence[str]) -> dict[str, Any]:
        output = {}
        for value in values:
            selected = [row for row in ordered if str(row[field]) == value]
            output[value] = {
                "trades": len(selected),
                "expectancy_r": rounded(dev.expectation(selected, "net_r")),
                "net_pnl_usd": rounded(sum(float(row["net_pnl_usd"]) for row in selected)),
            }
        return output
    pnl = sum(float(row["net_pnl_usd"]) for row in ordered)
    return {
        "metrics": metrics,
        "bootstrap": bootstrap,
        "stress": {
            "cost_1p5x_expectancy_r": rounded(dev.expectation(ordered, "net_r_cost_1p5x")),
            "cost_2x_expectancy_r": rounded(dev.expectation(ordered, "net_r_cost_2x")),
            "cost_1p5x_net_pnl_usd": rounded(sum(float(row["net_pnl_cost_1p5x_usd"]) for row in ordered)),
            "cost_2x_net_pnl_usd": rounded(sum(float(row["net_pnl_cost_2x_usd"]) for row in ordered)),
        },
        "ending_balance_usd": rounded(10_000 + pnl),
        "total_return_pct": rounded(pnl / 10_000 * 100),
        "by_model": grouped("model_id", sorted({str(row["model_id"]) for row in ordered})),
        "by_timeframe": grouped("timeframe", list(dev.TIMEFRAMES)),
        "sessions": grouped("session_state", sorted({str(row["session_state"]) for row in ordered})),
    }


def segmented_results(rows: Sequence[Mapping[str, Any]], base_seed: int) -> dict[str, Any]:
    return {
        "2025": summary_for_rows([row for row in rows if str(row["entry_at_utc"]).startswith("2025")], base_seed),
        "2026_YTD": summary_for_rows([row for row in rows if str(row["entry_at_utc"]).startswith("2026")], base_seed + 1),
        "combined": summary_for_rows(rows, base_seed + 2),
    }


def final_report(results: Mapping[str, Any], development: Mapping[str, Any]) -> str:
    lines = [
        "# Gold Pullback Archetype Setup Routing and Risk Allocation V1 — Final",
        "",
        f"Final status: **{results['final_verdict']}**",
        "",
        "The corrected 2021–2024 development system was frozen before the single 2025/2026 application. Both later periods are exposed historical robustness evidence and receive no independent-validation credit.",
        "",
        "## Corrected development result",
        "",
        "| Trades | Win rate | Expectancy | PF | Net PnL | Max DD | 95% CI |",
        "|---:|---:|---:|---:|---:|---:|---|",
    ]
    dm = development["variable_risk_router"]["metrics"]
    dci = development["variable_risk_router"]["bootstrap"]["ci95"]
    lines.append(f"| {dm.get('trades')} | {dm.get('win_rate_pct')}% | {dm.get('expectancy_r')}R | {dm.get('profit_factor')} | ${dm.get('net_pnl_usd')} | {dm.get('max_drawdown_pct')}% | {dci} |")
    lines += [
        "",
        "## Frozen router — exposed robustness",
        "",
        "| Segment | Trades | Win rate | Expectancy | PF | Net PnL | Return | Max DD | 1.5x costs |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for segment in ("2025", "2026_YTD", "combined"):
        item = results["variable_risk_router"][segment]
        metrics = item["metrics"]
        lines.append(
            f"| {segment} | {metrics.get('trades')} | {metrics.get('win_rate_pct')}% | {metrics.get('expectancy_r')}R | "
            f"{metrics.get('profit_factor')} | ${metrics.get('net_pnl_usd')} | {item.get('total_return_pct')}% | "
            f"{metrics.get('max_drawdown_pct')}% | {item['stress'].get('cost_1p5x_expectancy_r')}R |"
        )
    lines += [
        "",
        "## All-model equal-risk comparison",
        "",
        "| Segment | Trades | Win rate | Expectancy | PF | Net PnL |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for segment in ("2025", "2026_YTD", "combined"):
        item = results["equal_risk_all_model"][segment]
        metrics = item["metrics"]
        lines.append(f"| {segment} | {metrics.get('trades')} | {metrics.get('win_rate_pct')}% | {metrics.get('expectancy_r')}R | {metrics.get('profit_factor')} | ${metrics.get('net_pnl_usd')} |")
    lines += [
        "",
        "## Interpretation",
        "",
        "The six archetypes are useful descriptions of realised paths, but the frozen point-in-time routing and risk schedule did not convert them into an economically tradable portfolio. Risk variation reduced exposure; it did not reverse negative conditional expectancy.",
        "",
        "No paid data was acquired, no rule was retuned after development, and no live trading is authorized.",
        "",
    ]
    return "\n".join(lines)


def forward_classification_metrics(predictions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    labeled = [row for row in predictions if str(row["actual_archetype"]) in dev.CLASS_INDEX]
    confusion = {
        actual: {predicted: 0 for predicted in dev.CLASSES}
        for actual in dev.CLASSES
    }
    if not labeled:
        return {
            "rows": 0,
            "top1_accuracy_pct": None,
            "brier_score": None,
            "log_loss": None,
            "expected_calibration_error": None,
            "confusion_matrix": confusion,
            "calibration_bins": [],
        }
    actual_indices = np.asarray(
        [dev.CLASS_INDEX[str(row["actual_archetype"])] for row in labeled], dtype=np.int64
    )
    probabilities = np.asarray(
        [[float(row[f"p_{name}"]) for name in dev.CLASSES] for row in labeled], dtype=np.float64
    )
    predicted_indices = np.argmax(probabilities, axis=1)
    one_hot = np.eye(len(dev.CLASSES), dtype=np.float64)[actual_indices]
    confidence = np.max(probabilities, axis=1)
    correctness = (predicted_indices == actual_indices).astype(np.float64)
    for actual_index, predicted_index in zip(actual_indices.tolist(), predicted_indices.tolist()):
        confusion[dev.CLASSES[actual_index]][dev.CLASSES[predicted_index]] += 1
    bins = []
    ece = 0.0
    for index in range(10):
        lower = index / 10
        upper = (index + 1) / 10
        mask = (confidence >= lower) & (confidence <= upper if index == 9 else confidence < upper)
        count = int(np.sum(mask))
        if not count:
            continue
        average_confidence = float(np.mean(confidence[mask]))
        observed_accuracy = float(np.mean(correctness[mask]))
        ece += count / len(labeled) * abs(average_confidence - observed_accuracy)
        bins.append({
            "lower": lower,
            "upper": upper,
            "n": count,
            "average_confidence": rounded(average_confidence),
            "observed_accuracy": rounded(observed_accuracy),
        })
    return {
        "rows": len(labeled),
        "top1_accuracy_pct": rounded(100 * float(np.mean(correctness))),
        "brier_score": rounded(float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))),
        "log_loss": rounded(float(-np.mean(np.log(np.clip(probabilities[np.arange(len(labeled)), actual_indices], 1e-15, 1.0))))),
        "expected_calibration_error": rounded(ece),
        "confusion_matrix": confusion,
        "calibration_bins": bins,
    }


def payoff_matrix(
    trades: Sequence[Mapping[str, Any]],
    atlas_map: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for timeframe in dev.TIMEFRAMES:
        output[timeframe] = {}
        for model_id in [str(item["model_id"]) for item in json.loads(dev.PROTOCOL.read_text(encoding="utf-8"))["entry_models"]]:
            model_rows = [
                row for row in trades
                if row["timeframe"] == timeframe and row["model_id"] == model_id and row["status"] == "EXECUTED"
            ]
            cells = {}
            for archetype in dev.CLASSES:
                selected = [
                    row for row in model_rows
                    if atlas_map.get(str(row["pullback_id"]), {}).get("archetype") == archetype
                ]
                cells[archetype] = {
                    "trades": len(selected),
                    "win_rate_pct": rounded(100 * sum(float(row["net_r"]) > 0 for row in selected) / len(selected)) if selected else None,
                    "expectancy_r": rounded(dev.expectation(selected, "net_r")),
                    "profit_factor": rounded(econ.profit_factor(selected, "net_r")),
                    "average_mfe_r": rounded(float(np.mean([float(row["mfe_r"]) for row in selected]))) if selected else None,
                    "average_mae_r": rounded(float(np.mean([float(row["mae_r"]) for row in selected]))) if selected else None,
                }
            output[timeframe][model_id] = cells
    return output


def artifacts_exact(primary: Path, reference: Path) -> None:
    if sha256_file(primary) != sha256_file(reference):
        raise ValueError(f"Primary/reference artifact differs: {primary.name}")


def main() -> None:
    if REPORT.exists() or (OUTPUT / "final_seal.json").exists():
        raise FileExistsError("Forward result already exists; refusing a second completed application")
    if OUTPUT.exists():
        expected = {"forward_preopen_seal.json", "forward_attempt_1_failure.json", "forward_attempt_2_failure.json"}
        observed = {path.name for path in OUTPUT.iterdir()}
        if observed != expected:
            raise FileExistsError(f"Unexpected incomplete forward artifacts: {sorted(observed)}")
    else:
        OUTPUT.mkdir(parents=True, exist_ok=False)
    system, development_seal, sources = verify_preopen_and_seal_metadata()
    protocol = json.loads(dev.PROTOCOL.read_text(encoding="utf-8"))
    implementation = json.loads(dev.IMPLEMENTATION_FREEZE.read_text(encoding="utf-8"))
    development = json.loads((DEVELOPMENT / "development_results.json").read_text(encoding="utf-8"))

    development_prices, overlap = development_overlap()
    raw_prices, _, price_diagnostics = forward_source_impl.read_forward_minutes(sources, overlap)
    forward_rows: dict[str, list[dict[str, Any]]] = {}
    aggregation_diagnostics: dict[str, Any] = {}
    for timeframe in dev.TIMEFRAMES:
        primary_rows = aggregate_rows(raw_prices, timeframe, "primary")
        reference_rows = aggregate_rows(raw_prices, timeframe, "reference")
        if canonical_hash(primary_rows) != canonical_hash(reference_rows):
            raise ValueError(f"Primary/reference raw aggregation differs: {timeframe}")
        forward_rows[timeframe] = primary_rows
        aggregation_diagnostics[timeframe] = {
            "buckets": len(primary_rows),
            "complete_buckets": sum(bool(row["complete"]) for row in primary_rows),
            "primary_reference_exact": True,
        }

    original_feature_end = feature_impl.END
    feature_impl.END = FORWARD_START
    dev_bars, development_bar_diagnostics = feature_impl.load_bars()
    feature_impl.END = original_feature_end
    feature_bars, census_bars, combined_bar_diagnostics = combine_bars(dev_bars, forward_rows)
    parents = {timeframe: make_parent(rows) for timeframe, rows in forward_rows.items()}
    combined_parents = {
        timeframe: anatomy_impl.ParentBars(
            np.asarray([int(bar.close_at.timestamp() * 1_000_000_000) for bar in feature_bars[timeframe]], dtype=np.int64),
            np.asarray([int(bar.open_e8) for bar in feature_bars[timeframe]], dtype=np.int64),
            np.asarray([int(bar.high_e8) for bar in feature_bars[timeframe]], dtype=np.int64),
            np.asarray([int(bar.low_e8) for bar in feature_bars[timeframe]], dtype=np.int64),
            np.asarray([int(bar.close_e8) for bar in feature_bars[timeframe]], dtype=np.int64),
        )
        for timeframe in dev.TIMEFRAMES
    }
    del parents
    prices = anatomy_impl.PriceData(
        raw_prices.open_ns,
        raw_prices.open_e8,
        raw_prices.high_e8,
        raw_prices.low_e8,
        raw_prices.close_e8,
        raw_prices.spread,
        combined_parents,
        {**dict(raw_prices.diagnostics), "combined_parent_bars": combined_bar_diagnostics},
    )

    cases, events, swings, structure_diagnostics = build_forward_structure(census_bars)
    case_map = {str(row["pullback_id"]): row for row in cases}
    positioning, positioning_times, cot_diagnostics = forward_source_impl.load_cot()
    primary_features, reference_features, feature_diagnostics = materialize_forward_features(
        cases, feature_bars, events, positioning, positioning_times
    )
    if canonical_hash(primary_features) != canonical_hash(reference_features):
        raise ValueError("Forward feature payloads differ")
    feature_map_primary = {str(row["pullback_id"]): row for row in primary_features if row["feature_available"]}
    feature_map_reference = {str(row["pullback_id"]): row for row in reference_features if row["feature_available"]}

    primary_anatomy, primary_triggers, primary_atlas = materialize_forward_anatomy(
        primary_features, case_map, prices, "primary"
    )
    reference_anatomy, reference_triggers, reference_atlas = materialize_forward_anatomy(
        reference_features, case_map, prices, "reference"
    )
    if canonical_hash(primary_anatomy) != canonical_hash(reference_anatomy):
        raise ValueError("Forward anatomy implementations differ")
    if canonical_hash(primary_triggers) != canonical_hash(reference_triggers):
        raise ValueError("Forward trigger implementations differ")
    if canonical_hash(primary_atlas) != canonical_hash(reference_atlas):
        raise ValueError("Forward archetype implementations differ")

    def model_rows(
        atlas: list[dict[str, Any]],
        features: Mapping[str, dict[str, Any]],
        anatomy: list[dict[str, Any]],
        triggers: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], Mapping[str, dict[str, Any]], Mapping[str, dict[str, Any]], Mapping[tuple[str, str], dict[str, Any]], Mapping[str, dict[str, Any]]]:
        return (
            atlas,
            features,
            {str(row["pullback_id"]): row for row in anatomy},
            {(str(row["pullback_id"]), str(row["trigger"])): row for row in triggers},
            case_map,
        )

    reverse_delay = int(implementation["reverse_checkpoint_max_m1_delay_minutes"])
    primary_trades, primary_signals = dev.build_model_trades(
        "primary", protocol, model_rows(primary_atlas, feature_map_primary, primary_anatomy, primary_triggers),
        prices, {}, {}, reverse_delay,
    )
    reference_trades, reference_signals = dev.build_model_trades(
        "reference", protocol, model_rows(reference_atlas, feature_map_reference, reference_anatomy, reference_triggers),
        prices, {}, {}, reverse_delay,
    )
    if canonical_hash(primary_trades) != canonical_hash(reference_trades):
        raise ValueError("Forward execution implementations differ")
    if canonical_hash(primary_signals) != canonical_hash(reference_signals):
        raise ValueError("Forward checkpoint-signal implementations differ")

    primary_predictions, prediction_diagnostics = score_forward(primary_trades, primary_signals, system)
    reference_predictions, reference_prediction_diagnostics = score_forward(reference_trades, reference_signals, system)
    if canonical_hash(primary_predictions) != canonical_hash(reference_predictions) or prediction_diagnostics != reference_prediction_diagnostics:
        raise ValueError("Forward probability/risk implementations differ")
    trade_map = {str(row["trade_id"]): row for row in primary_trades}
    eligible = {
        f"{model['timeframe']}|{model['model_id']}": bool(model["calibration_eligible"])
        for model in system["models"]
    }
    primary_equal_decisions, primary_equal = dev.route_predictions(
        primary_predictions, trade_map, eligible, protocol, True
    )
    primary_router_decisions, primary_router = dev.route_predictions(
        primary_predictions, trade_map, eligible, protocol, False
    )
    reference_trade_map = {str(row["trade_id"]): row for row in reference_trades}
    reference_equal_decisions, reference_equal = dev.route_predictions(
        reference_predictions, reference_trade_map, eligible, protocol, True
    )
    reference_router_decisions, reference_router = dev.route_predictions(
        reference_predictions, reference_trade_map, eligible, protocol, False
    )
    for primary_payload, reference_payload, label in (
        (primary_equal_decisions, reference_equal_decisions, "equal-risk decisions"),
        (primary_equal, reference_equal, "equal-risk accepted trades"),
        (primary_router_decisions, reference_router_decisions, "router decisions"),
        (primary_router, reference_router, "router accepted trades"),
    ):
        if canonical_hash(primary_payload) != canonical_hash(reference_payload):
            raise ValueError(f"Forward {label} differ")

    atlas_map = {str(row["pullback_id"]): row for row in primary_atlas}
    matrix = payoff_matrix(primary_trades, atlas_map)
    classification = forward_classification_metrics(primary_predictions)
    results = {
        "version": "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_V1_FINAL_RESULTS_1_0",
        "status": "COMPLETE_SINGLE_EXPOSED_FORWARD_APPLICATION",
        "final_verdict": "REJECT_NOT_ECONOMICALLY_TRADABLE",
        "verdict_basis": "CORRECTED_DEVELOPMENT_ROUTER_FAILED_ALL_ECONOMIC_PASS_GATES; FORWARD_RESULTS_CANNOT_REVERSE_A_DEVELOPMENT_REJECTION",
        "development_verdict": development["verdict"],
        "forward_evidence_classification": "EXPOSED_HISTORICAL_ROBUSTNESS_NO_INDEPENDENT_VALIDATION_CREDIT",
        "calendar_2025_values_accessed": True,
        "calendar_2026_values_accessed": True,
        "cumulative_forward_source_opening_count": 3,
        "calendar_2026_cutoff_exclusive": "2026-07-30T00:00:00Z",
        "forward_cases": {
            "total": len(cases),
            "by_timeframe": dict(sorted(Counter(str(row["timeframe"]) for row in cases).items())),
            "technical_labels_available": sum(bool(row["technical_available"]) for row in primary_atlas),
            "technical_labels_unavailable": sum(not bool(row["technical_available"]) for row in primary_atlas),
        },
        "model_trade_rows": len(primary_trades),
        "executed_model_trade_rows": sum(row["status"] == "EXECUTED" for row in primary_trades),
        "prediction_diagnostics": prediction_diagnostics,
        "classification": classification,
        "variable_risk_router": segmented_results(primary_router, 861_117),
        "equal_risk_all_model": segmented_results(primary_equal, 861_217),
        "variable_risk_decisions": {
            "rows": len(primary_router_decisions),
            "accepted": len(primary_router),
            "status_counts": dict(sorted(Counter(str(row["portfolio_status"]) for row in primary_router_decisions).items())),
        },
        "equal_risk_decisions": {
            "rows": len(primary_equal_decisions),
            "accepted": len(primary_equal),
            "status_counts": dict(sorted(Counter(str(row["portfolio_status"]) for row in primary_equal_decisions).items())),
        },
        "source_and_construction_diagnostics": {
            "xauusd": price_diagnostics,
            "cot": cot_diagnostics,
            "development_bars": development_bar_diagnostics,
            "aggregation": aggregation_diagnostics,
            "combined_bars": combined_bar_diagnostics,
            "structure": structure_diagnostics,
            "features": feature_diagnostics,
        },
        "primary_reference_exact": True,
        "paid_acquisition_usd": 0.0,
        "live_trading_authorized": False,
    }

    source_certification = {
        "version": "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_V1_FORWARD_SOURCE_CERTIFICATION_1_0",
        "status": "PASS_EXISTING_SEALED_SOURCE_REUSE",
        "preopen_seal": file_record(OUTPUT / "forward_preopen_seal.json"),
        "preserved_attempt_1_failure": file_record(FORWARD_ATTEMPT_FAILURE),
        "operational_recovery_amendment": file_record(FORWARD_RECOVERY),
        "preserved_attempt_2_failure": file_record(FORWARD_ATTEMPT_FAILURE_2),
        "field_path_recovery_amendment": file_record(FORWARD_RECOVERY_2),
        "xauusd_source_files": [file_record(path) for path, _ in sources],
        "cot_source": file_record(COT_SOURCE),
        "price_diagnostics": price_diagnostics,
        "cot_diagnostics": cot_diagnostics,
        "charge_usd": 0.0,
    }

    pairs = {
        "forward_cases": (cases, cases),
        "forward_features": (primary_features, reference_features),
        "forward_movement_anatomy": (primary_anatomy, reference_anatomy),
        "forward_trigger_facts": (primary_triggers, reference_triggers),
        "forward_archetypes": (primary_atlas, reference_atlas),
        "forward_model_trades": (primary_trades, reference_trades),
        "forward_checkpoint_signals": (primary_signals, reference_signals),
        "forward_predictions": (primary_predictions, reference_predictions),
        "forward_equal_risk_decisions": (primary_equal_decisions, reference_equal_decisions),
        "forward_variable_risk_decisions": (primary_router_decisions, reference_router_decisions),
    }
    written: list[Path] = []
    for name, (primary_payload, reference_payload) in pairs.items():
        primary_path = OUTPUT / f"primary_{name}.parquet"
        reference_path = OUTPUT / f"reference_{name}.parquet"
        write_parquet_exclusive(primary_path, primary_payload)
        write_parquet_exclusive(reference_path, reference_payload)
        artifacts_exact(primary_path, reference_path)
        written.extend([primary_path, reference_path])
    results_path = OUTPUT / "final_results.json"
    matrix_path = OUTPUT / "forward_payoff_matrix.json"
    source_path = OUTPUT / "forward_source_certification.json"
    write_json_exclusive(results_path, results)
    write_json_exclusive(matrix_path, matrix)
    write_json_exclusive(source_path, source_certification)
    written.extend([
        results_path, matrix_path, source_path, OUTPUT / "forward_preopen_seal.json",
        FORWARD_ATTEMPT_FAILURE, FORWARD_RECOVERY, FORWARD_ATTEMPT_FAILURE_2, FORWARD_RECOVERY_2,
    ])

    ledger_path = OUTPUT / "prospective_paper_ledger.jsonl"
    genesis = {
        "version": "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_V1_PROSPECTIVE_LEDGER_1_0",
        "record_type": "GENESIS",
        "recorded_at_utc": utc_now(),
        "effective_after_utc": utc_now(),
        "status": "ACTIVE_PAPER_ONLY_RESEARCH_TRACKING_REJECTED_SYSTEM",
        "backfill_permitted": False,
        "live_trading_authorized": False,
        "development_verdict": development["verdict"],
        "final_system": file_record(FROZEN_SYSTEM),
        "rules": {
            "one_open_xauusd_position": True,
            "risk_schedule_usd": system["risk"]["variable_tiers"],
            "maximum_risk_usd": 100.0,
            "no_compounding": True,
        },
    }
    genesis["record_hash"] = canonical_hash(genesis)
    descriptor = os.open(ledger_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(genesis) + "\n")
    written.append(ledger_path)

    report_text = final_report(results, development)
    write_text_exclusive(REPORT, report_text)
    written.append(REPORT)
    artifacts = {str(path.relative_to(ROOT)).replace("\\", "/"): file_record(path) for path in sorted(written)}
    seal = {
        "version": "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_V1_FINAL_SEAL_1_0",
        "status": "REJECT_NOT_ECONOMICALLY_TRADABLE",
        "sealed_at_utc": utc_now(),
        "development_seal": file_record(DEVELOPMENT_SEAL),
        "frozen_system": file_record(FROZEN_SYSTEM),
        "calendar_2025_values_accessed_once": True,
        "calendar_2026_values_accessed_once": True,
        "cumulative_forward_source_opening_count": 3,
        "preserved_operational_failure": file_record(FORWARD_ATTEMPT_FAILURE),
        "operational_recovery_amendment": file_record(FORWARD_RECOVERY),
        "preserved_field_path_failure": file_record(FORWARD_ATTEMPT_FAILURE_2),
        "field_path_recovery_amendment": file_record(FORWARD_RECOVERY_2),
        "forward_evidence_classification": "EXPOSED_HISTORICAL_ROBUSTNESS_NO_INDEPENDENT_VALIDATION_CREDIT",
        "primary_reference_exact": True,
        "prospective_ledger_initialized": True,
        "paid_acquisition_usd": 0.0,
        "artifacts": artifacts,
        "artifact_set_hash": canonical_hash([artifacts[key]["sha256"] for key in sorted(artifacts)]),
    }
    write_json_exclusive(OUTPUT / "final_seal.json", seal)
    state = {
        "version": "GOLD_PULLBACK_ARCHETYPE_SETUP_ROUTING_V1_STATE_FINAL_1_0",
        "status": "COMPLETE_REJECTED_PROSPECTIVE_PAPER_TRACKING_INITIALIZED",
        "final_seal": file_record(OUTPUT / "final_seal.json"),
        "next_step": "DO_NOT_RETUNE_THIS_SYSTEM; APPEND_ONLY PROSPECTIVE OBSERVATION",
        "live_trading_authorized": False,
    }
    write_json_exclusive(OUTPUT / "state_final.json", state)
    print(canonical_json({
        "status": seal["status"],
        "forward_cases": len(cases),
        "executed_model_trade_rows": results["executed_model_trade_rows"],
        "router": results["variable_risk_router"],
        "equal_risk": results["equal_risk_all_model"],
        "seal": file_record(OUTPUT / "final_seal.json"),
    }))


if __name__ == "__main__":
    main()
