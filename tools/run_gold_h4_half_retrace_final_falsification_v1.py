from __future__ import annotations

import bisect
import csv
import gc
import gzip
import hashlib
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

import build_gold_multitimeframe_trend_continuation_census_v1 as census_impl  # noqa: E402
import discover_gold_trend_pullback_movement_anatomy_edge_v1 as discovery_impl  # noqa: E402
import materialize_gold_trend_pullback_continuation_edge_v1 as feature_impl  # noqa: E402
import materialize_gold_trend_pullback_movement_anatomy_edge_v1 as anatomy_impl  # noqa: E402
import run_gold_conditional_movement_policy_edge_v1 as model_impl  # noqa: E402
from zoneinfo import ZoneInfo


OUTPUT = ROOT / "research_artifacts" / "gold_h4_half_retrace_final_falsification_v1"
CONTRACT = ROOT / "GOLD_H4_HALF_RETRACE_FINAL_FALSIFICATION_V1.md"
MODEL = OUTPUT / "full_development_model.json"
MODEL_SEAL = OUTPUT / "pre_forward_model_seal.json"
COT_RAW = OUTPUT / "cftc_gold_cot_forward_source.json"
COT_SEAL = OUTPUT / "cftc_gold_cot_forward_source_seal.json"
ATTEMPT_FAILURE = OUTPUT / "attempt_01_preapplication_failure.json"
CORRECTION = OUTPUT / "implementation_correction_v1.json"
CORRECTION_SEAL = OUTPUT / "implementation_correction_v1_seal.json"
ATTEMPT_FAILURE_2 = OUTPUT / "attempt_02_pretrade_failure.json"
CORRECTION_2 = OUTPUT / "implementation_correction_v2.json"
CORRECTION_SEAL_2 = OUTPUT / "implementation_correction_v2_seal.json"
SOURCE_SNAPSHOT = ROOT / "research_artifacts" / "gold_session_behaviour_v3_m6b_source_snapshot_v01" / "source_snapshot.json"
SOURCE_SNAPSHOT_MANIFEST = SOURCE_SNAPSHOT.parent / "manifest.json"
CASEBOOK = ROOT / "research_artifacts" / "gold_casebook_v01"
CASEBOOK_MANIFEST = CASEBOOK / "manifest.json"
DEV_CENSUS = ROOT / "research_artifacts" / "gold_multitimeframe_trend_continuation_census_v1_v02"
MOVEMENT_FREEZE = ROOT / "research_manifests" / "gold_trend_pullback_movement_anatomy_edge_v1_design_freeze.json"
DEV_MATRIX = ROOT / "research_artifacts" / "gold_trend_pullback_movement_anatomy_edge_v1_v01" / "trade_matrix_checkpoint_h4.npz"

CASES_PRIMARY = OUTPUT / "primary_forward_decisions.parquet"
CASES_REFERENCE = OUTPUT / "reference_forward_decisions.parquet"
TRADES_PRIMARY = OUTPUT / "primary_forward_trades.parquet"
TRADES_REFERENCE = OUTPUT / "reference_forward_trades.parquet"
RESULTS_PRIMARY = OUTPUT / "primary_forward_results.json"
RESULTS_REFERENCE = OUTPUT / "reference_forward_results.json"
SOURCE_CERT = OUTPUT / "forward_source_certification.json"
REPORT = ROOT / "GOLD_H4_HALF_RETRACE_FINAL_FALSIFICATION_V1_RESULT.md"
FINAL_SEAL = OUTPUT / "final_seal.json"
FINAL_STATE = OUTPUT / "state_final.json"

CANDIDATE = "CMP::H4::RESPONSE_HALF_RETRACE_LIMIT::PIVOT_BUFFER_0P05_ATR::FIXED_2P0_R::TIME_8_PARENT_BARS"
EXECUTION = "RESPONSE_HALF_RETRACE_LIMIT::PIVOT_BUFFER_0P05_ATR::FIXED_2P0_R::TIME_8_PARENT_BARS"
FORWARD_START = datetime(2025, 1, 1, tzinfo=UTC)
FORWARD_END = datetime(2026, 7, 30, tzinfo=UTC)
MINUTE_NS = 60_000_000_000
H4_NS = 14_400_000_000_000
SCALE = 100_000_000
NY = ZoneInfo("America/New_York")
_CFTC_2026_PUBLICATION_DATES = tuple(
    date(2026, month, day)
    for month, days in (
        (1, (5, 9, 16, 23, 30)), (2, (6, 13, 20, 27)), (3, (6, 13, 20, 27)),
        (4, (3, 10, 17, 24)), (5, (1, 8, 15, 22, 29)), (6, (5, 12, 22, 26)),
        (7, (6, 10, 17, 24, 31)), (8, (7, 14, 21, 28)), (9, (4, 11, 18, 25)),
        (10, (2, 9, 16, 23, 30)), (11, (6, 16, 20, 30)), (12, (4, 11, 18, 28)),
    )
    for day in days
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed.astimezone(UTC)


def ns_dt(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC)


def ns_iso(value: int) -> str:
    return ns_dt(value).isoformat().replace("+00:00", "Z")


def cot_publication_at(observation_date: date) -> tuple[datetime, str]:
    """Exact copy of the frozen CFTC_PUBLIC availability policy without importing optional HTTP code."""
    if observation_date.year == 2026:
        eligible = [item for item in _CFTC_2026_PUBLICATION_DATES if observation_date < item <= observation_date + timedelta(days=7)]
        if not eligible:
            raise ValueError(f"No exact 2026 CFTC publication date for report {observation_date}")
        publication_date = min(eligible)
        quality = "EXACT_OFFICIAL_SCHEDULE"
    else:
        days_to_friday = (4 - observation_date.weekday()) % 7
        publication_date = observation_date + timedelta(days=days_to_friday if days_to_friday else 7)
        quality = "ESTIMATED_STANDARD_FRIDAY"
    return datetime.combine(publication_date, time(15, 30), tzinfo=NY).astimezone(UTC), quality


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def rounded(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    output = round(float(value), 12)
    return 0.0 if output == 0 else output


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
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
        row_group_size=16_384,
    )
    temporary.replace(path)


def verify_controls() -> tuple[dict[str, Any], dict[str, Any]]:
    for path in (CONTRACT, MODEL, MODEL_SEAL, COT_RAW, COT_SEAL, ATTEMPT_FAILURE, CORRECTION, CORRECTION_SEAL, ATTEMPT_FAILURE_2, CORRECTION_2, CORRECTION_SEAL_2, SOURCE_SNAPSHOT, SOURCE_SNAPSHOT_MANIFEST, CASEBOOK_MANIFEST):
        if not path.is_file():
            raise FileNotFoundError(path)
    seal = json.loads(MODEL_SEAL.read_text(encoding="utf-8"))
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    if seal["status"] != "FROZEN_FULL_DEVELOPMENT_MODEL_BEFORE_FORWARD_VALUES" or seal["forward_values_accessed"] is not False:
        raise ValueError("Pre-forward model seal invalid")
    if record(MODEL) != seal["model_artifact"] or canonical_hash(model) != seal["model_content_hash"]:
        raise ValueError("Sealed full-development model changed")
    if model["candidate_id"] != CANDIDATE or model["execution"] != EXECUTION or model["tree_hash"] != canonical_hash(model["tree"]):
        raise ValueError("Candidate, execution, or tree changed")
    for item in seal["sources"].values():
        path = ROOT / item["path"]
        if not path.is_file() or record(path) != item:
            raise ValueError(f"Predecessor changed: {item['path']}")
    cot_seal = json.loads(COT_SEAL.read_text(encoding="utf-8"))
    if cot_seal["status"] != "SEALED_OFFICIAL_PUBLIC_SOURCE" or cot_seal["charge_usd"] != 0.0 or record(COT_RAW) != cot_seal["raw_source"]:
        raise ValueError("Forward COT source seal invalid")
    if record(MODEL_SEAL) != cot_seal["model_seal"]:
        raise ValueError("COT source is not bound to the sealed model")
    correction_seal = json.loads(CORRECTION_SEAL.read_text(encoding="utf-8"))
    if correction_seal["status"] != "SEALED_PREAPPLICATION_IMPLEMENTATION_CORRECTION":
        raise ValueError("Implementation correction seal invalid")
    for key, path in (("attempt_failure", ATTEMPT_FAILURE), ("correction", CORRECTION)):
        if record(path) != correction_seal[key]:
            raise ValueError(f"Implementation correction input changed: {key}")
    correction_seal_2 = json.loads(CORRECTION_SEAL_2.read_text(encoding="utf-8"))
    if correction_seal_2["status"] != "SEALED_PRETRADE_IMPLEMENTATION_CORRECTION" or record(CORRECTION_SEAL) != correction_seal_2["predecessor_correction_seal"]:
        raise ValueError("Second implementation correction seal invalid")
    for key, path in (("attempt_failure", ATTEMPT_FAILURE_2), ("correction", CORRECTION_2), ("evaluator", Path(__file__))):
        if record(path) != correction_seal_2[key]:
            raise ValueError(f"Second implementation correction input changed: {key}")
    return model, seal


def verify_development_execution() -> tuple[dict[str, Any], dict[int, tuple[int, int, int, int, float]]]:
    movement_freeze = json.loads(MOVEMENT_FREEZE.read_text(encoding="utf-8"))
    cases_by_tf, _, _ = discovery_impl.load_cases(movement_freeze)
    cases = cases_by_tf["H4"]
    triggers = discovery_impl.load_trigger_map()
    prices = anatomy_impl.load_price()
    specifications = [discovery_impl.spec_code(*item) for item in discovery_impl.full_specs()]
    column = specifications.index(EXECUTION)
    with np.load(DEV_MATRIX, allow_pickle=False) as payload:
        expected_ids = [str(item) for item in payload["case_ids"].tolist()]
        expected = {name: np.array(payload[name][:, column], copy=True) for name in ("net", "stress", "pnl", "gross")}
    if expected_ids != [str(case["pullback_id"]) for case in cases]:
        raise ValueError("Development H4 identities changed")
    observed = {name: np.full(len(cases), np.nan) for name in expected}
    for index, case in enumerate(cases):
        trigger = triggers.get((str(case["pullback_id"]), "RESPONSE_HALF_RETRACE_LIMIT"))
        primary = discovery_impl.simulate_core(
            case, trigger, "PIVOT_BUFFER_0P05_ATR", "FIXED_2P0_R", prices, {}, {}, "primary"
        )[8]
        reference = discovery_impl.simulate_core(
            case, trigger, "PIVOT_BUFFER_0P05_ATR", "FIXED_2P0_R", prices, {}, {}, "reference"
        )[8]
        if canonical_json(primary) != canonical_json(reference):
            raise ValueError(f"Development primary/reference execution mismatch: {case['pullback_id']}")
        if primary["status"] == "EXECUTED":
            observed["net"][index] = float(primary["net_r"])
            observed["stress"][index] = float(primary["net_r_cost_1p5x"])
            observed["pnl"][index] = float(primary["net_pnl_usd"])
            observed["gross"][index] = float(primary["gross_r"])
    for name in expected:
        if not np.array_equal(observed[name], expected[name], equal_nan=True):
            raise ValueError(f"Frozen development execution did not reproduce: {name}")

    overlap: dict[int, tuple[int, int, int, int, float]] = {}
    threshold = int(datetime(2024, 12, 4, 14, 5, tzinfo=UTC).timestamp() * 1_000_000_000)
    for index in np.flatnonzero(prices.open_ns >= threshold):
        overlap[int(prices.open_ns[index])] = (
            int(prices.open_e8[index]), int(prices.high_e8[index]), int(prices.low_e8[index]), int(prices.close_e8[index]), float(prices.spread[index])
        )
    diagnostic = {
        "status": "PASS_EXACT_FROZEN_DEVELOPMENT_EXECUTION_REPRODUCTION",
        "h4_cases": len(cases),
        "executable_rows": int(np.isfinite(observed["net"]).sum()),
        "matrix_column": column,
        "execution": EXECUTION,
        "checkpoint": record(DEV_MATRIX),
        "overlap_m1_rows_retained_for_source_equivalence": len(overlap),
    }
    del prices, cases_by_tf, cases, triggers
    gc.collect()
    return diagnostic, overlap


def canonical_xau_sources() -> list[tuple[Path, Mapping[str, Any]]]:
    manifest = json.loads(SOURCE_SNAPSHOT_MANIFEST.read_text(encoding="utf-8"))
    declared = next(item for item in manifest["artifacts"] if Path(item["path"]).name == SOURCE_SNAPSHOT.name)
    if sha256_file(SOURCE_SNAPSHOT) != declared["sha256"] or SOURCE_SNAPSHOT.stat().st_size != declared["bytes"]:
        raise ValueError("Forward source snapshot changed")
    snapshot = json.loads(SOURCE_SNAPSHOT.read_text(encoding="utf-8"))
    records = [item for item in snapshot["lineage"]["batch_records"] if item["dataset_code"] == "XAUUSD_1M"]
    if len(records) != 29:
        raise ValueError(f"Expected 29 sealed XAUUSD batches, found {len(records)}")
    output = []
    for item in records:
        path = ROOT / "data" / "mt5" / Path(str(item["raw_object_path"])).name
        if not path.is_file() or sha256_file(path) != item["content_hash"]:
            raise ValueError(f"Sealed XAUUSD source missing or changed: {path.name}")
        output.append((path, item))
    if len({path.name for path, _ in output}) != 29:
        raise ValueError("Duplicate canonical XAUUSD path")
    return sorted(output, key=lambda item: item[0].name)


def read_forward_minutes(
    sources: Sequence[tuple[Path, Mapping[str, Any]]], overlap: Mapping[int, tuple[int, int, int, int, float]]
) -> tuple[anatomy_impl.PriceData, list[census_impl.Bar], dict[str, Any]]:
    values: dict[int, tuple[int, int, int, int, float, float | None, str]] = {}
    provider_rows = duplicates = 0
    per_file = []
    first_allowed = int(datetime(2024, 12, 4, 0, 0, tzinfo=UTC).timestamp() * 1_000_000_000)
    end_ns = int(FORWARD_END.timestamp() * 1_000_000_000)
    for path, metadata in sources:
        count = 0
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                count += 1
                opened_dt = parse_dt(str(row["open_time"]))
                closed_dt = parse_dt(str(row["close_time"]))
                available_dt = parse_dt(str(row["available_at"]))
                opened = int(opened_dt.timestamp() * 1_000_000_000)
                if closed_dt != opened_dt + timedelta(minutes=1) or available_dt > closed_dt:
                    raise ValueError(f"Invalid MT5 timestamp semantics: {path.name}:{count}")
                if not (first_allowed <= opened < end_ns):
                    continue
                o, high, low, close = (anatomy_impl.scaled(row[key]) for key in ("open", "high", "low", "close"))
                if not (low <= min(o, close) <= max(o, close) <= high):
                    raise ValueError(f"Invalid OHLC: {path.name}:{count}")
                spread_points = float(row["spread_points"]) if row.get("spread_points") not in (None, "") else math.nan
                spread = spread_points * 0.01 if math.isfinite(spread_points) else math.nan
                volume = float(row["volume"]) if row.get("volume") not in (None, "") else None
                candidate = (o, high, low, close, spread, volume, str(metadata["content_hash"]))
                if opened in values:
                    duplicates += 1
                    if values[opened][:-1] != candidate[:-1]:
                        raise ValueError(f"Conflicting duplicate MT5 minute: {ns_iso(opened)}")
                else:
                    values[opened] = candidate
        if count != int(metadata["record_count"]):
            raise ValueError(f"Provider row-count mismatch: {path.name}")
        provider_rows += count
        per_file.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "rows": count, "sha256": metadata["content_hash"]})
    ordered = sorted(values)
    if not ordered or any(right <= left for left, right in zip(ordered, ordered[1:])):
        raise ValueError("Canonical forward minute ordering failed")
    overlap_checked = spread_checked = 0
    for timestamp, expected in overlap.items():
        current = values.get(timestamp)
        if current is None:
            continue
        if current[:4] != expected[:4]:
            raise ValueError(f"Raw/casebook M1 price mismatch: {ns_iso(timestamp)}")
        if math.isfinite(expected[4]) and not math.isclose(current[4], expected[4], rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"Raw/casebook spread conversion mismatch: {ns_iso(timestamp)}")
        overlap_checked += 1
        spread_checked += int(math.isfinite(expected[4]))
    if overlap_checked < 20_000 or spread_checked < 20_000:
        raise ValueError("Insufficient raw/casebook overlap equivalence")

    open_ns = np.asarray(ordered, dtype=np.int64)
    open_e8 = np.asarray([values[item][0] for item in ordered], dtype=np.int64)
    high_e8 = np.asarray([values[item][1] for item in ordered], dtype=np.int64)
    low_e8 = np.asarray([values[item][2] for item in ordered], dtype=np.int64)
    close_e8 = np.asarray([values[item][3] for item in ordered], dtype=np.int64)
    spreads = np.asarray([values[item][4] for item in ordered], dtype=np.float64)

    primary_buckets: dict[int, list[int]] = defaultdict(list)
    for index, opened in enumerate(ordered):
        primary_buckets[(opened // H4_NS) * H4_NS].append(index)
    primary_rows = []
    for bucket in sorted(primary_buckets):
        indices = primary_buckets[bucket]
        primary_rows.append(_aggregate_bucket(bucket, indices, ordered, values))

    reference_rows = []
    bucket = None
    indices: list[int] = []
    for index, opened in enumerate(ordered):
        current_bucket = (opened // H4_NS) * H4_NS
        if bucket is not None and current_bucket != bucket:
            reference_rows.append(_aggregate_bucket(bucket, indices, ordered, values))
            indices = []
        bucket = current_bucket
        indices.append(index)
    if bucket is not None:
        reference_rows.append(_aggregate_bucket(bucket, indices, ordered, values))
    if primary_rows != reference_rows:
        raise ValueError("Independent H4 aggregation differs")

    parent = anatomy_impl.ParentBars(
        np.asarray([item["close_ns"] for item in primary_rows], dtype=np.int64),
        np.asarray([item["open_e8"] for item in primary_rows], dtype=np.int64),
        np.asarray([item["high_e8"] for item in primary_rows], dtype=np.int64),
        np.asarray([item["low_e8"] for item in primary_rows], dtype=np.int64),
        np.asarray([item["close_e8"] for item in primary_rows], dtype=np.int64),
    )
    prices = anatomy_impl.PriceData(
        open_ns, open_e8, high_e8, low_e8, close_e8, spreads, {"H4": parent},
        {"canonical_rows": len(ordered), "duplicates": duplicates, "source_files": len(sources)},
    )
    h4_bars = [
        census_impl.Bar(
            "H4", ns_dt(item["open_ns"]), ns_dt(item["close_ns"]), item["open_e8"], item["high_e8"],
            item["low_e8"], item["close_e8"], item["complete"], item["record_hash"]
        )
        for item in primary_rows
    ]
    diagnostics = {
        "provider_rows": provider_rows,
        "canonical_unique_minutes": len(ordered),
        "exact_adjacent_duplicates": duplicates,
        "first_minute": ns_iso(ordered[0]),
        "last_minute": ns_iso(ordered[-1]),
        "h4_buckets": len(primary_rows),
        "complete_h4_buckets": sum(item["complete"] for item in primary_rows),
        "raw_casebook_overlap_rows_exact": overlap_checked,
        "raw_casebook_spread_rows_exact": spread_checked,
        "source_files": per_file,
        "primary_reference_aggregation_exact": True,
    }
    return prices, h4_bars, diagnostics


def _aggregate_bucket(
    bucket: int, indices: Sequence[int], ordered: Sequence[int], values: Mapping[int, tuple[int, int, int, int, float, float | None, str]]
) -> dict[str, Any]:
    timestamps = [ordered[index] for index in indices]
    records = [values[item] for item in timestamps]
    volumes = [item[5] for item in records]
    complete = len(timestamps) == 240 and timestamps[0] == bucket and timestamps[-1] == bucket + 239 * MINUTE_NS
    row = {
        "open_ns": bucket,
        "close_ns": bucket + H4_NS,
        "open_e8": records[0][0],
        "high_e8": max(item[1] for item in records),
        "low_e8": min(item[2] for item in records),
        "close_e8": records[-1][3],
        "volume": sum(float(item) for item in volumes) if all(item is not None for item in volumes) else None,
        "complete": complete,
    }
    row["record_hash"] = canonical_hash(["UTC_FIXED_BUCKET_V1", *row.values(), timestamps[0], timestamps[-1], len(timestamps)])
    return row


def append_forward_h4(dev_bars: Sequence[census_impl.Bar], forward_bars: Sequence[census_impl.Bar]) -> tuple[list[census_impl.Bar], dict[str, Any]]:
    dev_map = {item.open_at: item for item in dev_bars}
    comparable = 0
    for item in forward_bars:
        if item.open_at < datetime(2024, 12, 4, 16, tzinfo=UTC) or item.open_at >= FORWARD_START:
            continue
        expected = dev_map.get(item.open_at)
        if expected is None:
            raise ValueError(f"Missing overlapping casebook H4 bar: {item.open_at}")
        if (item.open_e8, item.high_e8, item.low_e8, item.close_e8, item.component_complete) != (
            expected.open_e8, expected.high_e8, expected.low_e8, expected.close_e8, expected.component_complete
        ):
            raise ValueError(f"Raw/casebook H4 mismatch: {item.open_at}")
        comparable += 1
    if comparable < 100:
        raise ValueError("Insufficient H4 overlap equivalence")
    combined = [item for item in dev_bars if item.open_at < FORWARD_START]
    combined.extend(item for item in forward_bars if FORWARD_START <= item.open_at < FORWARD_END)
    combined.sort(key=lambda item: item.open_at)
    if len({item.open_at for item in combined}) != len(combined):
        raise ValueError("Duplicate combined H4 bar")
    return combined, {"overlap_h4_buckets_exact": comparable, "combined_h4_bars": len(combined)}


def build_forward_cases(h4: Sequence[census_impl.Bar]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    census_impl.END = FORWARD_END
    primary_swings = census_impl.derive_swings(h4, "H4", "STANDARD", 2, "primary")
    reference_swings = census_impl.derive_swings(h4, "H4", "STANDARD", 2, "reference")
    if primary_swings != reference_swings:
        raise ValueError("Forward swing reproduction failed")
    primary_events, primary_cases, primary_segments = census_impl.enumerate_structure(h4, primary_swings, "H4", "STANDARD", 2, "primary")
    reference_events, reference_cases, reference_segments = census_impl.enumerate_structure(h4, reference_swings, "H4", "STANDARD", 2, "reference")
    if primary_events != reference_events or primary_cases != reference_cases or primary_segments != reference_segments:
        raise ValueError("Forward structure reproduction failed")

    sealed = pq.read_table(DEV_CENSUS / "primary_pullback_cases.parquet").to_pylist()
    sealed = {str(item["pullback_id"]): item for item in sealed if item["timeframe"] == "H4" and item["scale"] == "STANDARD"}
    extended = {str(item["pullback_id"]): item for item in primary_cases if str(item["known_at_utc"]) < "2025-01-01T00:00:00Z"}
    if set(sealed) != set(extended):
        raise ValueError(f"Development structure identities changed: sealed={len(sealed)} extended={len(extended)}")
    identity_fields = ("pullback_id", "direction", "pivot_at_utc", "known_at_utc", "pivot_price_e8", "reference_event_id", "reference_level_e8", "actionable_at_known", "decision_facts_hash")
    for key in sealed:
        if any(sealed[key][field] != extended[key][field] for field in identity_fields):
            raise ValueError(f"Development decision facts changed: {key}")

    eligible = [
        item for item in primary_cases
        if FORWARD_START <= parse_dt(str(item["known_at_utc"])) < FORWARD_END
        and item["actionable_at_known"] is True
        and item["resolution"] in {"CONTINUED", "FAILED_STRUCTURE_SWITCH"}
    ]
    eligible.sort(key=lambda item: (item["known_at_utc"], item["pullback_id"]))
    events_by_id = {str(item["event_id"]): item for item in primary_events}
    diagnostics = {
        "swings": len(primary_swings),
        "events": len(primary_events),
        "all_pullbacks": len(primary_cases),
        "forward_actionable_resolved_cases": len(eligible),
        "forward_cases_by_year": dict(sorted(Counter(str(item["known_at_utc"])[:4] for item in eligible).items())),
        "development_decision_identities_exact": len(sealed),
        "primary_reference_structure_exact": True,
    }
    return eligible, list(events_by_id.values()), diagnostics


def load_cot() -> tuple[list[dict[str, Any]], list[datetime], dict[str, Any]]:
    dev_rows = []
    last_net = None
    with gzip.open(CASEBOOK / "positioning.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            available = parse_dt(str(row["available_at"]))
            calculated = row["calculated"]
            net = int(calculated["managed_money_net"])
            net_change_raw = calculated.get("managed_money_net_change")
            dev_rows.append({
                "available_at": available,
                "net_change": None if net_change_raw is None else float(net_change_raw),
                "net": net,
                "record_hash": str(row["record_hash"]),
                "availability_quality": str(row["availability_quality"]),
            })
            last_net = net
    if last_net is None:
        raise ValueError("No development COT baseline")
    raw_rows = json.loads(COT_RAW.read_text(encoding="utf-8"))
    forward_rows = []
    previous = last_net
    for row in raw_rows:
        observed = date.fromisoformat(str(row["report_date_as_yyyy_mm_dd"])[:10])
        available, quality = cot_publication_at(observed)
        net = int(row["m_money_positions_long_all"]) - int(row["m_money_positions_short_all"])
        forward_rows.append({
            "available_at": available,
            "net_change": float(net - previous),
            "net": net,
            "record_hash": canonical_hash(row),
            "availability_quality": quality,
            "observation_date": observed.isoformat(),
        })
        previous = net
    rows = sorted([*dev_rows, *forward_rows], key=lambda item: (item["available_at"], item["record_hash"]))
    times = [item["available_at"] for item in rows]
    diagnostics = {
        "development_reports": len(dev_rows),
        "forward_reports": len(forward_rows),
        "first_forward_observation": forward_rows[0]["observation_date"],
        "last_forward_observation": forward_rows[-1]["observation_date"],
        "estimated_standard_friday_reports": sum(item["availability_quality"] == "ESTIMATED_STANDARD_FRIDAY" for item in forward_rows),
        "exact_official_schedule_reports": sum(item["availability_quality"] == "EXACT_OFFICIAL_SCHEDULE" for item in forward_rows),
        "point_in_time_join": "LATEST_PUBLICATION_AT_OR_BEFORE_DECISION_WITH_MAX_14_DAY_AGE",
    }
    return rows, times, diagnostics


def reference_geometry(bar: census_impl.Bar, direction: str) -> tuple[float | None, float | None]:
    width = bar.high_e8 - bar.low_e8
    if width == 0:
        return None, None
    if direction == "UP":
        close_location = (bar.close_e8 - bar.low_e8) / width
        rejection = (min(bar.open_e8, bar.close_e8) - bar.low_e8) / width
    else:
        close_location = (bar.high_e8 - bar.close_e8) / width
        rejection = (bar.high_e8 - max(bar.open_e8, bar.close_e8)) / width
    return close_location, rejection


def predictor_rows(
    cases: Sequence[Mapping[str, Any]], h4: Sequence[census_impl.Bar], cot: Sequence[Mapping[str, Any]], cot_times: Sequence[datetime], model: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    close_index = {item.close_at: index for index, item in enumerate(h4)}
    atrs = feature_impl.rolling_atr(h4)
    primary = []
    reference = []
    cot_missing = cot_stale = 0
    for case in cases:
        decision = parse_dt(str(case["known_at_utc"]))
        pivot_at = parse_dt(str(case["pivot_at_utc"]))
        known_index = close_index.get(decision)
        pivot_index = close_index.get(pivot_at)
        if known_index is None or pivot_index is None or atrs[known_index] is None:
            raise ValueError(f"Forward feature bar/ATR unavailable: {case['pullback_id']}")
        sign = 1 if case["direction"] == "UP" else -1
        pivot_geo = feature_impl.candle_geometry(h4[pivot_index], h4[pivot_index - 1] if pivot_index else None, str(case["direction"]), atrs[known_index])
        confirmation_geo = feature_impl.candle_geometry(h4[known_index], h4[known_index - 1] if known_index else None, str(case["direction"]), atrs[known_index])
        ref_pivot_close, ref_pivot_rejection = reference_geometry(h4[pivot_index], str(case["direction"]))
        ref_confirm_close, _ = reference_geometry(h4[known_index], str(case["direction"]))
        if (pivot_geo["close_location"], pivot_geo["rejection_wick"], confirmation_geo["close_location"]) != (
            ref_pivot_close, ref_pivot_rejection, ref_confirm_close
        ):
            raise ValueError(f"Independent candle geometry differs: {case['pullback_id']}")
        cot_index = bisect.bisect_right(cot_times, decision) - 1
        cot_row = cot[cot_index] if cot_index >= 0 else None
        age = (decision - cot_row["available_at"]).total_seconds() / 86_400 if cot_row else None
        if age is None or age < 0 or age > 14:
            cot_row = None
            cot_stale += int(age is not None and age > 14)
        cot_change = sign * float(cot_row["net_change"]) if cot_row and cot_row.get("net_change") is not None else None
        cot_missing += int(cot_row is None)
        base = {field: None for field in model["predictor_registry"]["numeric"]}
        base.update({field: None for field in model["predictor_registry"]["categorical"]})
        base.update({
            "pullback_id": str(case["pullback_id"]),
            "known_at_utc": str(case["known_at_utc"]),
            "direction": str(case["direction"]),
            "pivot_close_location_trend": pivot_geo["close_location"],
            "pivot_rejection_wick_fraction": pivot_geo["rejection_wick"],
            "confirmation_close_location_trend": confirmation_geo["close_location"],
            "cot_managed_money_net_change_aligned": cot_change,
            "atr14_e8": float(atrs[known_index]),
            "pivot_price_e8": int(case["pivot_price_e8"]),
            "reference_level_e8": int(case["reference_level_e8"]),
            "resolution": str(case["resolution"]),
            "resolution_hash": str(case["resolution_hash"]),
            "decision_facts_hash": str(case["decision_facts_hash"]),
            "feature_lineage_hash": canonical_hash([
                case["decision_facts_hash"], h4[pivot_index].record_hash, h4[known_index].record_hash,
                cot_row["record_hash"] if cot_row else None,
                pivot_geo["close_location"], pivot_geo["rejection_wick"], confirmation_geo["close_location"], cot_change,
            ]),
            "cot_available": cot_row is not None,
            "cot_age_days": age if cot_row else None,
            "unused_predictor_disposition": "NOT_CONSULTED_BY_SEALED_TREE",
        })
        reference_row = dict(base)
        reference_row["pivot_close_location_trend"] = ref_pivot_close
        reference_row["pivot_rejection_wick_fraction"] = ref_pivot_rejection
        reference_row["confirmation_close_location_trend"] = ref_confirm_close
        reference_row["feature_lineage_hash"] = base["feature_lineage_hash"]
        primary.append(base)
        reference.append(reference_row)
    if canonical_hash(primary) != canonical_hash(reference):
        raise ValueError("Independent forward predictor rows differ")
    return primary, reference, {
        "rows": len(primary),
        "cot_available_rows": len(primary) - cot_missing,
        "cot_unavailable_rows_training_median_imputed": cot_missing,
        "cot_stale_rows": cot_stale,
        "materialized_tree_split_features": model["split_features"],
        "non_split_registry_fields": "PRESERVED_IN_REGISTRY_NOT_CONSULTED_BY_SEALED_TREE",
        "primary_reference_predictors_exact": True,
    }


def reference_half_retrace_trigger(case: Mapping[str, Any], prices: anatomy_impl.PriceData) -> dict[str, Any]:
    parent = prices.parents["H4"]
    known_ns = int(parse_dt(str(case["known_at_utc"])).timestamp() * 1_000_000_000)
    confirmation_index = int(np.searchsorted(parent.close_ns, known_ns, side="left"))
    if confirmation_index >= len(parent.close_ns) or int(parent.close_ns[confirmation_index]) != known_ns:
        return {"status": "UNAVAILABLE_ANATOMY", "reason": "MISSING_CONFIRMATION_PARENT_BAR"}
    anchor = int(np.searchsorted(prices.open_ns, known_ns, side="left"))
    if anchor >= len(prices.open_ns) or int(prices.open_ns[anchor]) - known_ns > 5 * MINUTE_NS:
        return {"status": "UNAVAILABLE_ANATOMY", "reason": "MISSING_M1_ANCHOR"}
    trigger_parent_index = confirmation_index + 4
    deadline = int(parent.close_ns[trigger_parent_index]) if trigger_parent_index < len(parent.close_ns) else int(FORWARD_END.timestamp() * 1_000_000_000)
    end = min(int(np.searchsorted(prices.open_ns, deadline, side="left")), len(prices.open_ns))
    decision_close = int(parent.close_e8[confirmation_index])
    pivot = int(case["pivot_price_e8"])
    level = int(round((decision_close + pivot) / 2))
    sign = 1 if case["direction"] == "UP" else -1
    hit = None
    for index in range(anchor, end):
        if (int(prices.low_e8[index]) <= level) if sign > 0 else (int(prices.high_e8[index]) >= level):
            hit = index
            break
    confirmation_high = int(parent.high_e8[confirmation_index])
    confirmation_low = int(parent.low_e8[confirmation_index])
    if hit is None:
        reason = "HALF_RETRACE_NOT_REACHED_WITHIN_4_PARENT_BARS"
        return {
            "pullback_id": case["pullback_id"], "timeframe": "H4", "direction": case["direction"], "known_at_utc": case["known_at_utc"],
            "trigger": "RESPONSE_HALF_RETRACE_LIMIT", "status": "NO_TRIGGER", "reason": reason, "entry_index": None, "entry_at_utc": None,
            "entry_e8": None, "entry_delay_minutes": None, "entry_spread_usd_oz": None, "confirmation_high_e8": confirmation_high,
            "confirmation_low_e8": confirmation_low, "decision_close_e8": decision_close, "pivot_price_e8": pivot,
            "reference_level_e8": int(case["reference_level_e8"]), "atr14_e8": float(case["atr14_e8"]),
            "trigger_lineage_hash": canonical_hash([case["feature_lineage_hash"], "RESPONSE_HALF_RETRACE_LIMIT", reason]),
        }
    spread = float(prices.spread[hit])
    spread_value = None if not math.isfinite(spread) or spread < 0 else spread
    return {
        "pullback_id": case["pullback_id"], "timeframe": "H4", "direction": case["direction"], "known_at_utc": case["known_at_utc"],
        "trigger": "RESPONSE_HALF_RETRACE_LIMIT", "status": "FORMED", "reason": "", "entry_index": hit,
        "entry_at_utc": ns_iso(int(prices.open_ns[hit])), "entry_e8": level,
        "entry_delay_minutes": rounded((int(prices.open_ns[hit]) - known_ns) / MINUTE_NS), "entry_spread_usd_oz": spread_value,
        "confirmation_high_e8": confirmation_high, "confirmation_low_e8": confirmation_low, "decision_close_e8": decision_close,
        "pivot_price_e8": pivot, "reference_level_e8": int(case["reference_level_e8"]), "atr14_e8": float(case["atr14_e8"]),
        "trigger_lineage_hash": canonical_hash([case["feature_lineage_hash"], "RESPONSE_HALF_RETRACE_LIMIT", hit, level, level]),
    }


def apply_policy(
    cases: Sequence[Mapping[str, Any]], predictors: Sequence[Mapping[str, Any]], prices: anatomy_impl.PriceData, model: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    X = model_impl.transform(predictors, model["transform"])
    predictions_primary = model_impl.predict_tree(model["tree"], X, "primary")
    predictions_reference = model_impl.predict_tree(model["tree"], X, "reference")
    if not np.array_equal(predictions_primary, predictions_reference):
        raise ValueError("Forward tree prediction reproduction failed")
    selected = predictions_primary >= float(model["hyperparameters"]["prediction_trade_threshold_r"])
    parent = prices.parents["H4"]
    decisions = []
    trades = []
    reasons = Counter()
    anatomy_impl.END_NS = int(FORWARD_END.timestamp() * 1_000_000_000)
    for index, (case, predictor) in enumerate(zip(cases, predictors)):
        execution_case = {
            **case,
            "atr14_e8": predictor["atr14_e8"],
            "feature_lineage_hash": predictor["feature_lineage_hash"],
        }
        decision = {
            "candidate_id": CANDIDATE,
            "pullback_id": case["pullback_id"],
            "known_at_utc": case["known_at_utc"],
            "calendar_segment": str(case["known_at_utc"])[:4],
            "cluster_date": discovery_impl.trading_date(str(case["known_at_utc"])),
            "direction": case["direction"],
            "predicted_net_r": rounded(float(predictions_primary[index])),
            "model_selected": bool(selected[index]),
            "tree_input_hash": canonical_hash({name: predictor.get(name) for name in model["split_features"]}),
            "cot_available": predictor["cot_available"],
        }
        if not selected[index]:
            decision.update({"execution_status": "NOT_SELECTED", "execution_reason": "PREDICTION_BELOW_0P05R"})
            decision["row_hash"] = canonical_hash(decision)
            decisions.append(decision)
            continue
        known_ns = int(parse_dt(str(case["known_at_utc"])).timestamp() * 1_000_000_000)
        confirmation_index = int(np.searchsorted(parent.close_ns, known_ns, side="left"))
        anchor = int(np.searchsorted(prices.open_ns, known_ns, side="left"))
        if confirmation_index >= len(parent.close_ns) or int(parent.close_ns[confirmation_index]) != known_ns or anchor >= len(prices.open_ns) or int(prices.open_ns[anchor]) - known_ns > 5 * MINUTE_NS:
            reason = "MISSING_CONFIRMATION_OR_M1_ANCHOR"
            decision.update({"execution_status": "NO_TRADE", "execution_reason": reason})
            reasons[reason] += 1
            decision["row_hash"] = canonical_hash(decision)
            decisions.append(decision)
            continue
        primary_trigger = next(
            item for item in anatomy_impl.trigger_rows(execution_case, prices, confirmation_index, anchor)
            if item["trigger"] == "RESPONSE_HALF_RETRACE_LIMIT"
        )
        reference_trigger = reference_half_retrace_trigger(execution_case, prices)
        if canonical_json(primary_trigger) != canonical_json(reference_trigger):
            raise ValueError(f"Independent trigger mismatch: {case['pullback_id']}")
        primary_result = discovery_impl.simulate_core(
            execution_case, primary_trigger, "PIVOT_BUFFER_0P05_ATR", "FIXED_2P0_R", prices, {}, {}, "primary"
        )[8]
        reference_result = discovery_impl.simulate_core(
            execution_case, reference_trigger, "PIVOT_BUFFER_0P05_ATR", "FIXED_2P0_R", prices, {}, {}, "reference"
        )[8]
        if canonical_json(primary_result) != canonical_json(reference_result):
            raise ValueError(f"Independent forward execution mismatch: {case['pullback_id']}")
        decision.update({"execution_status": primary_result["status"], "execution_reason": primary_result["no_trade_reason"]})
        decision["row_hash"] = canonical_hash(decision)
        decisions.append(decision)
        if primary_result["status"] == "EXECUTED":
            trade = {"candidate_id": CANDIDATE, "calendar_segment": str(case["known_at_utc"])[:4], "predicted_net_r": rounded(float(predictions_primary[index])), **primary_result}
            trade["row_hash"] = canonical_hash(trade)
            trades.append(trade)
        else:
            reasons[str(primary_result["no_trade_reason"])] += 1
    decisions.sort(key=lambda row: (row["known_at_utc"], row["pullback_id"]))
    trades.sort(key=lambda row: (row["entry_at_utc"], row["pullback_id"]))
    return decisions, trades, {
        "eligible_cases": len(cases),
        "model_selected_cases": int(selected.sum()),
        "executed_trades": len(trades),
        "selected_no_trade_reasons": dict(sorted(reasons.items())),
        "prediction_checksum": hashlib.sha256(predictions_primary.astype("<f8").tobytes()).hexdigest(),
        "primary_reference_prediction_trigger_execution_exact": True,
    }


def profit_factor(rows: Sequence[Mapping[str, Any]], field: str) -> float | str | None:
    values = [float(item[field]) for item in rows]
    gains = sum(item for item in values if item > 0)
    losses = abs(sum(item for item in values if item < 0))
    return rounded(gains / losses) if losses else ("INF" if gains else None)


def summarize(rows: Sequence[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["entry_at_utc"], row["pullback_id"]))
    baseline = model_impl.metrics(ordered)
    bootstrap = model_impl.cluster_bootstrap(ordered, "net_r", seed)
    stress_values = [float(item["net_r_cost_1p5x"]) for item in ordered]
    return {
        **baseline,
        "bootstrap_ci90_r": bootstrap["ci90"],
        "bootstrap_ci95_r": bootstrap["ci95"],
        "bootstrap_p_one_sided": bootstrap["p_one_sided"],
        "cost_1p5x_expectancy_r": rounded(statistics.fmean(stress_values)) if stress_values else None,
        "cost_1p5x_profit_factor": profit_factor(ordered, "net_r_cost_1p5x"),
        "cost_1p5x_net_r": rounded(sum(stress_values)),
    }


def evaluate_verdict(trades: Sequence[Mapping[str, Any]], model: Mapping[str, Any]) -> dict[str, Any]:
    by_segment = {
        "2025": [item for item in trades if item["calendar_segment"] == "2025"],
        "2026": [item for item in trades if item["calendar_segment"] == "2026"],
    }
    summaries = {name: summarize(rows, 731911) for name, rows in by_segment.items()}
    combined = summarize(trades, 731911)
    support_failures = []
    for segment, floors in model["forward_protocol"]["support"].items():
        if summaries[segment]["trades"] < floors["trades"]:
            support_failures.append(f"{segment}_TRADES_LT_{floors['trades']}")
        if summaries[segment]["dates"] < floors["dates"]:
            support_failures.append(f"{segment}_DATES_LT_{floors['dates']}")
    gate_failures = []
    if not support_failures:
        for segment in ("2025", "2026"):
            if summaries[segment]["expectancy_r"] is None or summaries[segment]["expectancy_r"] <= 0:
                gate_failures.append(f"{segment}_EXPECTANCY_NOT_POSITIVE")
        if combined["expectancy_r"] is None or combined["expectancy_r"] <= 0:
            gate_failures.append("COMBINED_EXPECTANCY_NOT_POSITIVE")
        if combined["bootstrap_ci90_r"][0] is None or combined["bootstrap_ci90_r"][0] <= 0:
            gate_failures.append("COMBINED_CI90_LOWER_NOT_POSITIVE")
        if combined["profit_factor"] != "INF" and (combined["profit_factor"] is None or float(combined["profit_factor"]) < 1.15):
            gate_failures.append("COMBINED_PROFIT_FACTOR_LT_1P15")
        if combined["cost_1p5x_expectancy_r"] is None or combined["cost_1p5x_expectancy_r"] <= 0:
            gate_failures.append("COMBINED_COST_1P5X_EXPECTANCY_NOT_POSITIVE")
        if combined["max_drawdown_pct"] > 15:
            gate_failures.append("COMBINED_MAX_DRAWDOWN_GT_15PCT")
    if support_failures:
        verdict = "INCONCLUSIVE_FORWARD_SUPPORT"
    elif gate_failures:
        verdict = "REJECT_EXPOSED_FORWARD_ROBUSTNESS"
    else:
        verdict = "PASS_EXPOSED_FORWARD_ROBUSTNESS"
    return {
        "verdict": verdict,
        "support_failures": support_failures,
        "gate_failures": gate_failures,
        "segments": summaries,
        "combined": combined,
    }


def report_text(results: Mapping[str, Any]) -> str:
    lines = [
        "# Gold H4 Half-Retrace Final Falsification V1", "",
        f"Verdict: **{results['verdict']}**", "",
        "This was the single authorized post-hoc test. All 2021-2024 evidence remains hypothesis-generation only; no retuning, alternate execution, second candidate, or validation credit was introduced.", "",
        "| Segment | Trades | Dates | Win rate | Expectancy | 90% CI | Profit factor | Max DD | 1.5x-cost expectancy | 1.5x PF | Net PnL |", "|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("2025", "2026", "combined"):
        item = results["combined"] if name == "combined" else results["segments"][name]
        lines.append(
            f"| {name} | {item['trades']} | {item['dates']} | {item['win_rate_pct']}% | {item['expectancy_r']}R | {item['bootstrap_ci90_r']} | {item['profit_factor']} | {item['max_drawdown_pct']}% | {item['cost_1p5x_expectancy_r']}R | {item['cost_1p5x_profit_factor']} | ${item['net_pnl_usd']} |"
        )
    lines.extend([
        "", f"Support failures: `{results['support_failures']}`", f"Robustness-gate failures: `{results['gate_failures']}`", "",
        "The complete sealed tree, decisions, trades, source lineage and independent-reproduction checks are preserved in the research artifact directory.", "",
        "No live trading is authorized.", "",
    ])
    return "\n".join(lines)


def main() -> None:
    outputs = (CASES_PRIMARY, CASES_REFERENCE, TRADES_PRIMARY, TRADES_REFERENCE, RESULTS_PRIMARY, RESULTS_REFERENCE, SOURCE_CERT, REPORT, FINAL_SEAL, FINAL_STATE)
    if any(path.exists() for path in outputs):
        raise FileExistsError("Final falsification output already exists")
    model, model_seal = verify_controls()
    development_reproduction, overlap = verify_development_execution()
    sources = canonical_xau_sources()

    # This is the single forward-value opening and application. Both independent
    # computations below reuse the same immutable in-memory source snapshot.
    prices, raw_h4, price_diagnostics = read_forward_minutes(sources, overlap)
    del overlap
    dev_bars_by_tf, dev_coverage = census_impl.load_bars()
    h4, overlap_diagnostics = append_forward_h4(dev_bars_by_tf["H4"], raw_h4)
    del dev_bars_by_tf, raw_h4
    cases, _events, structure_diagnostics = build_forward_cases(h4)
    cot, cot_times, cot_diagnostics = load_cot()
    predictors_primary, predictors_reference, predictor_diagnostics = predictor_rows(cases, h4, cot, cot_times, model)
    if canonical_hash(predictors_primary) != canonical_hash(predictors_reference):
        raise ValueError("Predictor replay mismatch")
    decisions_primary, trades_primary, application_diagnostics = apply_policy(cases, predictors_primary, prices, model)
    decisions_reference, trades_reference, reference_application = apply_policy(cases, predictors_reference, prices, model)
    if canonical_hash(decisions_primary) != canonical_hash(decisions_reference) or canonical_hash(trades_primary) != canonical_hash(trades_reference):
        raise ValueError("Complete independent forward replay mismatch")
    if application_diagnostics != reference_application:
        raise ValueError("Independent application diagnostics differ")

    disposition = evaluate_verdict(trades_primary, model)
    results = {
        "version": "GOLD_H4_HALF_RETRACE_FINAL_FALSIFICATION_RESULTS_1_0",
        "candidate_id": CANDIDATE,
        "execution": EXECUTION,
        "verdict": disposition["verdict"],
        "support_failures": disposition["support_failures"],
        "gate_failures": disposition["gate_failures"],
        "segments": disposition["segments"],
        "combined": disposition["combined"],
        "application": application_diagnostics,
        "development_evidence_classification": "HYPOTHESIS_GENERATION_ONLY",
        "forward_evidence_classification": "EXPOSED_HISTORICAL_FALSIFICATION_NO_INDEPENDENT_VALIDATION_CREDIT",
        "previous_rejections_preserved": True,
        "retuned": False,
        "second_candidate_tested": False,
        "forward_values_accessed": True,
        "primary_reference_exact": True,
    }
    source_certification = {
        "version": "GOLD_H4_HALF_RETRACE_FORWARD_SOURCE_CERTIFICATION_1_0",
        "status": "PASS_FORWARD_SOURCE_AND_REPRODUCTION_INTEGRITY",
        "certified_at_utc": utc_now(),
        "model_seal": record(MODEL_SEAL),
        "cot_source_seal": record(COT_SEAL),
        "xau_source_snapshot": record(SOURCE_SNAPSHOT),
        "xau_source_files": [record(path) for path, _ in sources],
        "development_execution_reproduction": development_reproduction,
        "development_price_coverage": dev_coverage,
        "price_diagnostics": price_diagnostics,
        "h4_overlap_diagnostics": overlap_diagnostics,
        "structure_diagnostics": structure_diagnostics,
        "cot_diagnostics": cot_diagnostics,
        "predictor_diagnostics": predictor_diagnostics,
        "application_diagnostics": application_diagnostics,
        "paid_acquisition_usd": 0.0,
        "primary_reference_exact": True,
    }

    write_parquet_exclusive(CASES_PRIMARY, decisions_primary)
    write_parquet_exclusive(CASES_REFERENCE, decisions_reference)
    write_parquet_exclusive(TRADES_PRIMARY, trades_primary)
    write_parquet_exclusive(TRADES_REFERENCE, trades_reference)
    if sha256_file(CASES_PRIMARY) != sha256_file(CASES_REFERENCE) or sha256_file(TRADES_PRIMARY) != sha256_file(TRADES_REFERENCE):
        raise ValueError("Byte-identical Parquet reproduction failed")
    write_json_exclusive(RESULTS_PRIMARY, results)
    write_json_exclusive(RESULTS_REFERENCE, results)
    write_json_exclusive(SOURCE_CERT, source_certification)
    write_text_exclusive(REPORT, report_text(results))
    artifacts = (CASES_PRIMARY, CASES_REFERENCE, TRADES_PRIMARY, TRADES_REFERENCE, RESULTS_PRIMARY, RESULTS_REFERENCE, SOURCE_CERT, REPORT, MODEL, MODEL_SEAL, COT_RAW, COT_SEAL, ATTEMPT_FAILURE, CORRECTION, CORRECTION_SEAL, ATTEMPT_FAILURE_2, CORRECTION_2, CORRECTION_SEAL_2)
    seal = {
        "version": "GOLD_H4_HALF_RETRACE_FINAL_FALSIFICATION_SEAL_1_0",
        "status": results["verdict"],
        "sealed_at_utc": utc_now(),
        "artifacts": {path.name: record(path) for path in artifacts},
        "artifact_set_hash": canonical_hash({path.name: sha256_file(path) for path in artifacts}),
        "tree_hash": model["tree_hash"],
        "previous_rejections_preserved": True,
        "development_hypothesis_generation_only": True,
        "forward_values_accessed": True,
        "retuned": False,
        "alternative_execution_tested": False,
        "second_candidate_tested": False,
        "primary_reference_exact": True,
        "live_trading_authorized": False,
    }
    write_json_exclusive(FINAL_SEAL, seal)
    write_json_exclusive(FINAL_STATE, {
        "version": "GOLD_H4_HALF_RETRACE_FINAL_FALSIFICATION_STATE_FINAL_1_0",
        "status": results["verdict"],
        "final_seal": record(FINAL_SEAL),
        "next_step": "STOP_FINAL_FALSIFICATION_COMPLETE",
        "live_trading_authorized": False,
    })
    print(json.dumps({
        "status": results["verdict"],
        "segments": results["segments"],
        "combined": results["combined"],
        "support_failures": results["support_failures"],
        "gate_failures": results["gate_failures"],
        "application": results["application"],
        "final_seal": record(FINAL_SEAL),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
