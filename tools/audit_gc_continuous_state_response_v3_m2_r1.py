#!/usr/bin/env python3
"""Outcome-blind support-feasibility and source-coverage audit for CSR V3 M2-R1.

The implementation never opens an outcome artifact.  It reads the sealed M2
predictor payloads only after the R1 protocol and implementation are frozen.
Price-source access is restricted to timestamp and quality metadata extracted
without deserializing OHLC fields.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import itertools
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "research_manifests" / "gc_continuous_state_response_v3_m2_r1_protocol_v01.json"
FREEZE = ROOT / "research_manifests" / "gc_continuous_state_response_v3_m2_r1_freeze_v01.json"
DOCUMENT = ROOT / "GC_CONTINUOUS_STATE_RESPONSE_EDGE_DISCOVERY_V3_MILESTONE_2_R1.md"
IMPLEMENTATION = Path(__file__).resolve()
TEST_FILE = ROOT / "tests" / "test_gc_continuous_state_response_v3_m2_r1.py"
MODEL_REGISTRY = ROOT / "research_manifests" / "gc_continuous_state_response_v3_model_registry_v01.json"
FEATURE_REGISTRY = ROOT / "research_manifests" / "gc_continuous_state_response_v3_feature_registry_v01.json"
M2_PROTOCOL = ROOT / "research_manifests" / "gc_continuous_state_response_v3_m2_protocol_v01.json"
M2_FREEZE = ROOT / "research_manifests" / "gc_continuous_state_response_v3_m2_freeze_v01.json"

DEFAULT_OUTPUT_NAME = "gc_continuous_state_response_v3_m2_r1_v01"
M2_OUTPUT_NAME = "gc_continuous_state_response_v3_m2_v01"
EXPECTED_M2_STATUS = "PASS_V3_M2_OUTCOME_BLIND_PREDICTOR_MATERIALIZATION"
EXPECTED_M2_FINAL_SEAL = "cd90cda29077067a84613559abec866bab17d88665384ab81a836efadd663a62"
EXPECTED_ANCHORS_PER_SESSION = 2_992
EXPECTED_ANCHORS_TOTAL = 5_984
EXPECTED_DATES_PER_SESSION = 187
EXPECTED_ANCHORS_PER_DATE = 16
EXPECTED_BLOCKS = set(range(1, 39))
SESSIONS = ("LONDON", "NEW_YORK")
OOF_YEARS = (2022, 2023, 2024)
OOF_COVERAGE_FRACTION = 0.80
FOLDS = ((1, 10, 11, 19), (2, 19, 20, 28), (3, 28, 29, 38))

FEATURE_IDS = (
    "CSR_FLOW_QUOTE_OFI_W60",
    "CSR_FLOW_TRADE_IMBALANCE_W60",
    "CSR_FLOW_DISPLAYED_IMBALANCE_W60",
    "CSR_BOOK_DEPTH_IMBALANCE_L5_W60",
    "CSR_BOOK_MICROPRICE_DISLOCATION_T0",
    "CSR_STRUCTURE_MOMENTUM_15M",
    "CSR_MACRO_ENGINE_SCORE",
    "CSR_MACRO_REAL_YIELD_SUPPORT",
    "CSR_MACRO_USD_SUPPORT",
    "CSR_MACRO_2Y_SUPPORT",
    "CSR_LIQ_SPREAD_FRAGILITY_60_900",
    "CSR_SESSION_LEVEL_TENSION",
)
STAGE1_IDS = FEATURE_IDS[:10]
TARGET_FEATURES = ("CSR_STRUCTURE_MOMENTUM_15M", "CSR_SESSION_LEVEL_TENSION")
TARGET_INTERACTIONS = ("CSR_INT_OFI_SESSION_LEVEL_TENSION",)

AV_AVAILABLE = "AVAILABLE"
AV_TECH_XAU = "UNAVAILABLE_TECHNICAL_XAU_GAP"
AV_ATR = "UNKNOWN_INSUFFICIENT_ATR_HISTORY"
AV_CONTEXT = "UNKNOWN_POINT_IN_TIME_CONTEXT"
AV_LEVEL = "UNKNOWN_NO_KNOWN_LEVEL"
AV_NONPOSITIVE = "UNKNOWN_NONPOSITIVE_INPUT"

DISPOSITIONS = (
    "RECOVERABLE_EXISTING_SEALED_SOURCE",
    "REQUIRES_ADDITIONAL_SOURCE",
    "DEFINITION_INDUCED_UNAVAILABLE",
    "GENUINE_SOURCE_GAP",
    "UNRESOLVED",
)

ONE_MINUTE_NS = 60_000_000_000
FIFTEEN_MINUTES_NS = 15 * ONE_MINUTE_NS
ONE_HOUR_NS = 60 * ONE_MINUTE_NS

META_COLUMNS = (
    "anchor_id",
    "session_row_id",
    "session_date",
    "session_code",
    "selected_month_week_id",
    "chronological_block",
    "anchor_offset_minutes",
    "session_open_ns",
    "decision_at_ns",
)
FEATURE_COLUMNS = tuple(
    f"{feature_id}__{suffix}"
    for feature_id in FEATURE_IDS
    for suffix in ("value", "availability", "available_at_ns", "lineage_hash")
)
SELECTED_COLUMNS = META_COLUMNS + FEATURE_COLUMNS


class AuditFailure(RuntimeError):
    """Formal R1 gate failure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditFailure(message)


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def timestamp_set_hash(values: Iterable[int]) -> str:
    digest = hashlib.sha256()
    for value in sorted(values):
        digest.update(str(int(value)).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def write_json_once(path: Path, value: Mapping[str, Any]) -> None:
    require(not path.exists(), f"Refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text_once(path: Path, text: str) -> None:
    require(not path.exists(), f"Refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def seal_receipt(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    output = dict(value)
    output[field] = None
    output[field] = canonical_hash(output)
    return output


def receipt_valid(value: Mapping[str, Any], field: str) -> bool:
    expected = value.get(field)
    if not isinstance(expected, str):
        return False
    check = dict(value)
    check[field] = None
    return canonical_hash(check) == expected


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, f"Naive timestamp: {value}")
    return parsed.astimezone(UTC)


def dt_ns(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def ns_date(value: int) -> str:
    return datetime.fromtimestamp(value // 1_000_000_000, tz=UTC).date().isoformat()


@dataclass(frozen=True, slots=True)
class Paths:
    data_root: Path
    m2_output: Path
    output: Path
    xau_source: Path

    @classmethod
    def build(
        cls,
        data_root: Path,
        output: Path | None = None,
        m2_output: Path | None = None,
    ) -> "Paths":
        inferred_m2 = data_root / "artifacts" / M2_OUTPUT_NAME
        if not inferred_m2.is_dir():
            inferred_m2 = ROOT / "research_artifacts" / M2_OUTPUT_NAME
        inferred_output = data_root / "artifacts" / DEFAULT_OUTPUT_NAME
        if data_root.resolve() == ROOT.resolve():
            inferred_output = ROOT / "research_artifacts" / DEFAULT_OUTPUT_NAME
        return cls(
            data_root=data_root,
            m2_output=m2_output or inferred_m2,
            output=output or inferred_output,
            xau_source=data_root / "data" / "gold_casebook_v01" / "price_bars.jsonl.gz",
        )


def verify_m2_boundary(paths: Paths, *, require_xau_source: bool) -> dict[str, Any]:
    manifest_path = paths.m2_output / "manifest.json"
    final_path = paths.m2_output / "final_seal.json"
    verdict_path = paths.m2_output / "verdict.json"
    require(manifest_path.is_file() and final_path.is_file() and verdict_path.is_file(), "M2 boundary files missing")
    manifest = load_json(manifest_path)
    final = load_json(final_path)
    verdict = load_json(verdict_path)
    require(receipt_valid(manifest, "manifest_receipt"), "M2 manifest receipt invalid")
    require(receipt_valid(final, "final_seal_receipt"), "M2 final seal receipt invalid")
    require(receipt_valid(verdict, "verdict_receipt"), "M2 verdict receipt invalid")
    require(final["final_seal_receipt"] == EXPECTED_M2_FINAL_SEAL, "M2 final seal changed")
    require(verdict["status"] == EXPECTED_M2_STATUS, "M2 verdict changed")
    require(final["manifest_sha256"] == sha256_file(manifest_path), "M2 manifest hash changed")
    require(final["verdict_sha256"] == sha256_file(verdict_path), "M2 verdict hash changed")
    require(not final["outcomes_accessed"] and not final["year_2025_or_2026_values_accessed"], "M2 locks changed")
    for name, expected in manifest["artifacts"].items():
        local = paths.m2_output / name
        require(local.is_file(), f"M2 artifact missing: {name}")
        require(local.stat().st_size == int(expected["bytes"]), f"M2 artifact size changed: {name}")
        require(sha256_file(local) == expected["sha256"], f"M2 artifact hash changed: {name}")
    m2_freeze = load_json(M2_FREEZE)
    require(receipt_valid(m2_freeze, "freeze_receipt"), "M2 freeze receipt invalid")
    require(m2_freeze["outcomes_accessed"] is False, "M2 freeze outcome lock changed")
    source_expected = m2_freeze["source_records"]["xauusd_price_bars"]
    if require_xau_source:
        require(paths.xau_source.is_file(), "Sealed XAUUSD source missing")
        require(paths.xau_source.stat().st_size == int(source_expected["bytes"]), "XAUUSD source size changed")
        require(sha256_file(paths.xau_source) == source_expected["sha256"], "XAUUSD source hash changed")
    return {
        "m2_status": verdict["status"],
        "m2_final_seal_receipt": final["final_seal_receipt"],
        "m2_manifest_receipt": manifest["manifest_receipt"],
        "m2_verdict_receipt": verdict["verdict_receipt"],
        "m2_manifest_sha256": sha256_file(manifest_path),
        "m2_final_seal_sha256": sha256_file(final_path),
        "m2_verdict_sha256": sha256_file(verdict_path),
        "m2_primary_london_sha256": manifest["artifacts"]["primary_london_anchors.parquet"]["sha256"],
        "m2_primary_new_york_sha256": manifest["artifacts"]["primary_new_york_anchors.parquet"]["sha256"],
        "m2_reference_london_sha256": manifest["artifacts"]["reference_london_anchors.parquet"]["sha256"],
        "m2_reference_new_york_sha256": manifest["artifacts"]["reference_new_york_anchors.parquet"]["sha256"],
        "xauusd_source_sha256": source_expected["sha256"],
        "xauusd_source_bytes": int(source_expected["bytes"]),
    }


def annual_gate(numerators: Mapping[str, int], denominators: Mapping[str, int]) -> tuple[dict[str, Any], bool]:
    report: dict[str, Any] = {}
    all_pass = True
    for year in OOF_YEARS:
        key = str(year)
        denominator = int(denominators[key])
        numerator = int(numerators[key])
        minimum = math.ceil(OOF_COVERAGE_FRACTION * denominator)
        passed = denominator > 0 and numerator >= minimum
        all_pass = all_pass and passed
        report[key] = {
            "numerator_available_dates": numerator,
            "denominator_frozen_oof_dates": denominator,
            "minimum_required_dates": minimum,
            "coverage_fraction": round(numerator / denominator, 8) if denominator else None,
            "status": "PASS" if passed else "SUPPORT_FAIL",
        }
    return report, all_pass


def synthetic_proof() -> dict[str, Any]:
    denominators = {"2022": 20, "2023": 60, "2024": 58}
    pass_report, pass_gate = annual_gate({"2022": 16, "2023": 48, "2024": 47}, denominators)
    fail_report, fail_gate = annual_gate({"2022": 15, "2023": 48, "2024": 47}, denominators)
    require(pass_gate and not fail_gate, "Synthetic annual-gate proof failed")
    require(pass_report["2024"]["minimum_required_dates"] == 47, "Ceiling rule differs")
    require(fail_report["2022"]["status"] == "SUPPORT_FAIL", "Failure disposition differs")
    envelopes = {"1970-01-01": (0, 10 * ONE_MINUTE_NS)}
    require(classify_missing([5 * ONE_MINUTE_NS], envelopes, AV_TECH_XAU) == "GENUINE_SOURCE_GAP", "Gap taxonomy differs")
    require(classify_missing([11 * ONE_MINUTE_NS], envelopes, AV_TECH_XAU) == "REQUIRES_ADDITIONAL_SOURCE", "Envelope taxonomy differs")
    require(classify_missing([], envelopes, AV_TECH_XAU) == "RECOVERABLE_EXISTING_SEALED_SOURCE", "Recovery taxonomy differs")
    require(classify_missing([], envelopes, AV_CONTEXT) == "DEFINITION_INDUCED_UNAVAILABLE", "Definition taxonomy differs")
    return {
        "status": "PASS_SYNTHETIC_PRE_ACCESS_PROOF",
        "annual_gate_pass_checksum": canonical_hash(pass_report),
        "annual_gate_fail_checksum": canonical_hash(fail_report),
        "taxonomy_checksum": canonical_hash(DISPOSITIONS),
    }


def freeze(paths: Paths) -> None:
    require(not FREEZE.exists(), f"Freeze already exists: {FREEZE}")
    protocol = load_json(PROTOCOL)
    require(protocol["status"] == "READY_TO_FREEZE_PRE_R1_ROW_ACCESS", "R1 protocol not ready")
    require(protocol["sole_support_gate_replacement"]["coverage_fraction"] == 0.8, "R1 fraction changed")
    boundary = verify_m2_boundary(paths, require_xau_source=False)
    feature_registry = load_json(FEATURE_REGISTRY)
    model_registry = load_json(MODEL_REGISTRY)
    require(feature_registry["feature_count"] == 12, "Feature registry changed")
    require(model_registry["stage1"]["tests_per_session"] == 10, "Stage-1 registry changed")
    require(model_registry["stage2"]["tests_per_session"] == 6, "Stage-2 registry changed")
    proof = synthetic_proof()
    payload = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_R1_FREEZE_V1_0",
            "status": "PASS_V3_M2_R1_PRE_ROW_ACCESS_FREEZE",
            "frozen_at_utc": utc_now(),
            "r1_predictor_rows_accessed_before_freeze": False,
            "r1_availability_classifications_accessed_before_freeze": False,
            "outcomes_accessed": False,
            "year_2025_or_2026_values_accessed": False,
            "boundary": boundary,
            "sole_gate_replacement": protocol["sole_support_gate_replacement"],
            "unchanged_support_gates": protocol["unchanged_support_gates"],
            "diagnostic_taxonomy": protocol["metadata_diagnostic"],
            "synthetic_proof": proof,
            "protocol_sha256": sha256_file(PROTOCOL),
            "implementation_sha256": sha256_file(IMPLEMENTATION),
            "test_sha256": sha256_file(TEST_FILE),
            "document_sha256": sha256_file(DOCUMENT),
            "feature_registry_sha256": sha256_file(FEATURE_REGISTRY),
            "model_registry_sha256": sha256_file(MODEL_REGISTRY),
            "m2_protocol_sha256": sha256_file(M2_PROTOCOL),
            "m2_freeze_sha256": sha256_file(M2_FREEZE),
            "freeze_receipt": None,
        },
        "freeze_receipt",
    )
    write_json_once(FREEZE, payload)
    print(canonical_json({"status": payload["status"], "freeze_receipt": payload["freeze_receipt"]}))


def verify_freeze(paths: Paths, *, require_xau_source: bool) -> dict[str, Any]:
    require(FREEZE.is_file(), "R1 freeze missing")
    frozen = load_json(FREEZE)
    require(receipt_valid(frozen, "freeze_receipt"), "R1 freeze receipt invalid")
    require(frozen["status"] == "PASS_V3_M2_R1_PRE_ROW_ACCESS_FREEZE", "R1 freeze status changed")
    expected_hashes = {
        "protocol_sha256": PROTOCOL,
        "implementation_sha256": IMPLEMENTATION,
        "test_sha256": TEST_FILE,
        "document_sha256": DOCUMENT,
        "feature_registry_sha256": FEATURE_REGISTRY,
        "model_registry_sha256": MODEL_REGISTRY,
        "m2_protocol_sha256": M2_PROTOCOL,
        "m2_freeze_sha256": M2_FREEZE,
    }
    for key, path in expected_hashes.items():
        require(sha256_file(path) == frozen[key], f"Frozen file changed: {path}")
    boundary = verify_m2_boundary(paths, require_xau_source=require_xau_source)
    require(boundary == frozen["boundary"], "M2 boundary differs from R1 freeze")
    require(not frozen["outcomes_accessed"] and not frozen["year_2025_or_2026_values_accessed"], "R1 locks changed")
    return frozen


def read_records(path: Path, *, reference: bool) -> list[dict[str, Any]]:
    parquet = pq.ParquetFile(path)
    require(set(SELECTED_COLUMNS).issubset(parquet.schema_arrow.names), f"M2 schema missing columns: {path}")
    if not reference:
        return [dict(row) for row in pq.read_table(path, columns=list(SELECTED_COLUMNS), use_threads=False).to_pylist()]
    records: list[dict[str, Any]] = []
    for group_index in range(parquet.num_row_groups):
        table = parquet.read_row_group(group_index, columns=list(SELECTED_COLUMNS), use_threads=False)
        for batch in table.to_batches(max_chunksize=7):
            records.extend(dict(row) for row in pa.Table.from_batches([batch]).to_pylist())
    return records


def validate_population(records: Sequence[Mapping[str, Any]], session: str) -> dict[str, Any]:
    require(len(records) == EXPECTED_ANCHORS_PER_SESSION, f"Anchor count differs: {session}")
    identities: list[str] = []
    dates = Counter()
    blocks: set[int] = set()
    null_classification_failures = 0
    future_available_at = 0
    lineage_failures = 0
    dst_failures = 0
    for record in records:
        require(record["session_code"] == session, f"Cross-session row: {session}")
        anchor_id = str(record["anchor_id"])
        expected_id = f"CSR_V3:{record['session_date']}:{session}:{int(record['anchor_offset_minutes']):03d}"
        require(anchor_id == expected_id, f"Anchor identity changed: {anchor_id}")
        identities.append(anchor_id)
        dates[str(record["session_date"])] += 1
        blocks.add(int(record["chronological_block"]))
        zone = ZoneInfo("Europe/London" if session == "LONDON" else "America/New_York")
        opened = datetime.fromtimestamp(int(record["session_open_ns"]) / 1_000_000_000, tz=UTC)
        local_open = opened.astimezone(zone)
        decision = int(record["decision_at_ns"])
        expected_decision = int(record["session_open_ns"]) + int(record["anchor_offset_minutes"]) * ONE_MINUTE_NS
        if local_open.date().isoformat() != str(record["session_date"]) or (local_open.hour, local_open.minute) != (8, 0) or decision != expected_decision:
            dst_failures += 1
        for feature_id in FEATURE_IDS:
            value = record[f"{feature_id}__value"]
            availability = str(record[f"{feature_id}__availability"])
            available_at = record[f"{feature_id}__available_at_ns"]
            lineage = str(record[f"{feature_id}__lineage_hash"])
            if (availability == AV_AVAILABLE) != (value is not None):
                null_classification_failures += 1
            if available_at is not None and int(available_at) > decision:
                future_available_at += 1
            if not re.fullmatch(r"[0-9a-f]{64}", lineage):
                lineage_failures += 1
    require(len(set(identities)) == len(identities), f"Duplicate anchors: {session}")
    require(len(dates) == EXPECTED_DATES_PER_SESSION, f"Date count differs: {session}")
    require(all(value == EXPECTED_ANCHORS_PER_DATE for value in dates.values()), f"Per-date anchors differ: {session}")
    require(blocks == EXPECTED_BLOCKS, f"Blocks differ: {session}")
    require(null_classification_failures == 0, f"Null classification failures: {session}")
    require(future_available_at == 0, f"Future available-at timestamps: {session}")
    require(lineage_failures == 0, f"Lineage failures: {session}")
    require(dst_failures == 0, f"DST failures: {session}")
    return {
        "anchors": len(records),
        "unique_anchors": len(set(identities)),
        "session_dates": len(dates),
        "chronological_blocks": len(blocks),
        "identity_checksum": canonical_hash(identities),
        "null_classification_failures": null_classification_failures,
        "future_available_at_failures": future_available_at,
        "lineage_failures": lineage_failures,
        "dst_failures": dst_failures,
    }


def known(record: Mapping[str, Any], feature_id: str) -> bool:
    return record[f"{feature_id}__availability"] == AV_AVAILABLE and record[f"{feature_id}__value"] is not None


def oof_universe(records: Sequence[Mapping[str, Any]]) -> dict[str, set[str]]:
    return {
        str(year): {
            str(record["session_date"])
            for record in records
            if int(record["chronological_block"]) >= 11 and str(record["session_date"]).startswith(str(year))
        }
        for year in OOF_YEARS
    }


def support_common(
    records: Sequence[Mapping[str, Any]], mask: Sequence[bool], universe: Mapping[str, set[str]]
) -> dict[str, Any]:
    selected = [record for record, eligible in zip(records, mask) if eligible]
    dates = {str(record["session_date"]) for record in selected}
    blocks = {int(record["chronological_block"]) for record in selected}
    folds: dict[str, Any] = {}
    for fold, _, start, end in FOLDS:
        subset = [record for record in selected if start <= int(record["chronological_block"]) <= end]
        folds[str(fold)] = {
            "block_range": [start, end],
            "dates": len({str(record["session_date"]) for record in subset}),
            "anchors": len(subset),
        }
    numerators = {
        year: len(
            {
                str(record["session_date"])
                for record in selected
                if str(record["session_date"]) in universe[year]
            }
        )
        for year in universe
    }
    denominators = {year: len(value) for year, value in universe.items()}
    annual, annual_pass = annual_gate(numerators, denominators)
    return {
        "known_anchors": len(selected),
        "completeness": round(len(selected) / len(records), 8),
        "distinct_dates": len(dates),
        "distinct_blocks": len(blocks),
        "validation_folds": folds,
        "annual_oof_coverage": annual,
        "annual_oof_coverage_gate": annual_pass,
    }


def ordered_gates(common: Mapping[str, Any], completeness_floor: float, positive_dates: int, negative_dates: int) -> dict[str, bool]:
    return {
        "distinct_dates_gte_150": int(common["distinct_dates"]) >= 150,
        "distinct_blocks_gte_30": int(common["distinct_blocks"]) >= 30,
        "completeness_floor": float(common["completeness"]) >= completeness_floor,
        "each_validation_fold_dates_gte_35": all(int(item["dates"]) >= 35 for item in common["validation_folds"].values()),
        "each_validation_fold_anchors_gte_480": all(int(item["anchors"]) >= 480 for item in common["validation_folds"].values()),
        "each_required_year_oof_coverage_gte_80pct": bool(common["annual_oof_coverage_gate"]),
        "positive_value_dates_gte_40": positive_dates >= 40,
        "negative_value_dates_gte_40": negative_dates >= 40,
    }


def feature_support(
    records: Sequence[Mapping[str, Any]], feature_id: str, universe: Mapping[str, set[str]]
) -> dict[str, Any]:
    mask = [known(record, feature_id) for record in records]
    common = support_common(records, mask, universe)
    positive = {
        str(record["session_date"])
        for record, eligible in zip(records, mask)
        if eligible and float(record[f"{feature_id}__value"]) > 0
    }
    negative = {
        str(record["session_date"])
        for record, eligible in zip(records, mask)
        if eligible and float(record[f"{feature_id}__value"]) < 0
    }
    gates = ordered_gates(common, 0.80, len(positive), len(negative))
    failures = [gate for gate, passed in gates.items() if not passed]
    return {
        "feature_id": feature_id,
        **common,
        "positive_value_dates": len(positive),
        "negative_value_dates": len(negative),
        "gates": gates,
        "failed_gates": failures,
        "support_status": "SUPPORT_ELIGIBLE" if not failures else "SUPPORT_FAIL",
    }


def center_scale(records: Sequence[Mapping[str, Any]], feature_id: str, train_end: int) -> tuple[float, float] | None:
    values = [
        float(record[f"{feature_id}__value"])
        for record in records
        if int(record["chronological_block"]) <= train_end and known(record, feature_id)
    ]
    if not values:
        return None
    center = float(statistics.median(values))
    scale = float(statistics.median(abs(value - center) for value in values))
    if scale == 0:
        scale = float(statistics.pstdev(values)) if len(values) > 1 else 0.0
    if scale == 0 or not math.isfinite(scale):
        return None
    return center, scale


def interaction_sign_support(
    records: Sequence[Mapping[str, Any]], interaction: Mapping[str, Any]
) -> tuple[set[str], set[str], int]:
    interaction_id = str(interaction["interaction_id"])
    left = str(interaction["left"])
    right = str(interaction["right"])
    positive: set[str] = set()
    negative: set[str] = set()
    scored = 0
    for _, train_end, start, end in FOLDS:
        left_transform = center_scale(records, left, train_end)
        right_transform = center_scale(records, right, train_end)
        if left_transform is None or right_transform is None:
            continue
        left_center, left_scale = left_transform
        right_center, right_scale = right_transform
        for record in records:
            block = int(record["chronological_block"])
            if not start <= block <= end or not known(record, left) or not known(record, right):
                continue
            left_value = float(record[f"{left}__value"])
            right_value = float(record[f"{right}__value"])
            z_left = (left_value - left_center) / left_scale
            z_right = (right_value - right_center) / right_scale
            score = 0.0
            if interaction_id in {
                "CSR_INT_OFI_MACRO_CONCORDANCE",
                "CSR_INT_TRADE_MACRO_CONCORDANCE",
                "CSR_INT_DEPTH_REAL_YIELD_CONCORDANCE",
                "CSR_INT_MICROPRICE_USD_CONCORDANCE",
            }:
                if left_value != 0 and right_value != 0 and math.copysign(1.0, left_value) == math.copysign(1.0, right_value):
                    score = math.copysign(min(abs(z_left), abs(z_right)), left_value)
            elif interaction_id == "CSR_INT_OFI_SPREAD_FRAGILITY":
                score = z_left * max(z_right, 0.0)
            elif interaction_id == "CSR_INT_OFI_SESSION_LEVEL_TENSION":
                score = z_left * right_value
            else:
                raise AuditFailure(f"Unregistered interaction: {interaction_id}")
            if score > 0:
                positive.add(str(record["session_date"]))
                scored += 1
            elif score < 0:
                negative.add(str(record["session_date"]))
                scored += 1
    return positive, negative, scored


def interaction_support(
    records: Sequence[Mapping[str, Any]], interaction: Mapping[str, Any], universe: Mapping[str, set[str]]
) -> dict[str, Any]:
    left = str(interaction["left"])
    right = str(interaction["right"])
    mask = [known(record, left) and known(record, right) for record in records]
    common = support_common(records, mask, universe)
    positive, negative, scored = interaction_sign_support(records, interaction)
    gates = ordered_gates(common, 0.70, len(positive), len(negative))
    failures = [gate for gate, passed in gates.items() if not passed]
    return {
        "interaction_id": interaction["interaction_id"],
        "left": left,
        "right": right,
        **common,
        "oof_nonzero_interaction_anchors": scored,
        "positive_value_dates": len(positive),
        "negative_value_dates": len(negative),
        "sign_support_method": "UNCHANGED_FROZEN_TRAIN_FOLD_ROBUST_CENTER_SCALE_AND_REGISTERED_FORMULA",
        "gates": gates,
        "failed_gates": failures,
        "support_status": "SUPPORT_ELIGIBLE" if not failures else "SUPPORT_FAIL",
    }


def legacy_consistency(
    m2_audit: Mapping[str, Any], session: str, stage1: Sequence[Mapping[str, Any]], stage2: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    old_stage1 = {item["feature_id"]: item for item in m2_audit["sessions"][session]["stage1"]}
    old_stage2 = {item["interaction_id"]: item for item in m2_audit["sessions"][session]["stage2"]}
    failures: list[str] = []
    common_fields = (
        "known_anchors",
        "completeness",
        "distinct_dates",
        "distinct_blocks",
        "validation_folds",
        "positive_value_dates",
        "negative_value_dates",
    )
    for item in stage1:
        old = old_stage1[item["feature_id"]]
        for field in common_fields:
            if item[field] != old[field]:
                failures.append(f"STAGE1:{item['feature_id']}:{field}")
        old_years = old["required_year_oof_dates"]
        new_years = {year: data["numerator_available_dates"] for year, data in item["annual_oof_coverage"].items()}
        if new_years != old_years:
            failures.append(f"STAGE1:{item['feature_id']}:year_numerators")
    for item in stage2:
        old = old_stage2[item["interaction_id"]]
        for field in (*common_fields, "oof_nonzero_interaction_anchors"):
            if item[field] != old[field]:
                failures.append(f"STAGE2:{item['interaction_id']}:{field}")
        old_years = old["required_year_oof_dates"]
        new_years = {year: data["numerator_available_dates"] for year, data in item["annual_oof_coverage"].items()}
        if new_years != old_years:
            failures.append(f"STAGE2:{item['interaction_id']}:year_numerators")
    return {"status": "PASS" if not failures else "FAIL", "failures": failures}


def support_audit(paths: Paths, implementation: str, *, reference: bool) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    models = load_json(MODEL_REGISTRY)
    m2_audit = load_json(paths.m2_output / f"{implementation}_support_audit.json")
    sessions: dict[str, Any] = {}
    records_by_session: dict[str, list[dict[str, Any]]] = {}
    for session in SESSIONS:
        path = paths.m2_output / f"{implementation}_{session.lower()}_anchors.parquet"
        records = read_records(path, reference=reference)
        records_by_session[session] = records
        population = validate_population(records, session)
        universe = oof_universe(records)
        denominators = {year: len(value) for year, value in universe.items()}
        stage1 = [feature_support(records, feature_id, universe) for feature_id in STAGE1_IDS]
        stage2 = [interaction_support(records, item, universe) for item in models["stage2"]["interactions"]]
        legacy = legacy_consistency(m2_audit, session, stage1, stage2)
        require(legacy["status"] == "PASS", f"Frozen support statistic changed: {implementation}/{session}/{legacy['failures']}")
        sessions[session] = {
            "population": population,
            "annual_oof_universe": {
                year: {
                    "denominator_frozen_oof_dates": len(values),
                    "session_date_identity_checksum": canonical_hash(sorted(values)),
                }
                for year, values in universe.items()
            },
            "stage1": stage1,
            "stage2": stage2,
            "stage1_support_eligible": sum(item["support_status"] == "SUPPORT_ELIGIBLE" for item in stage1),
            "stage1_support_fail": sum(item["support_status"] == "SUPPORT_FAIL" for item in stage1),
            "stage2_support_eligible": sum(item["support_status"] == "SUPPORT_ELIGIBLE" for item in stage2),
            "stage2_support_fail": sum(item["support_status"] == "SUPPORT_FAIL" for item in stage2),
            "legacy_nonamended_statistics": legacy,
        }
    payload = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_R1_SUPPORT_AUDIT_V1_0",
        "implementation": implementation,
        "reader": "ROW_GROUP_BATCH_REFERENCE" if reference else "WHOLE_TABLE_PRIMARY",
        "status": "PASS_OUTCOME_BLIND_AMENDED_SUPPORT_AUDIT",
        "sole_removed_gate": "each_required_year_oof_dates_gte_35",
        "sole_added_gate": "each_required_year_oof_coverage_gte_80pct",
        "sessions": sessions,
        "outcomes_opened_or_joined": False,
        "relationships_or_effects_calculated": False,
        "predictor_values_reported": False,
        "year_2025_or_2026_values_accessed": False,
    }
    comparable = dict(payload)
    comparable.pop("implementation")
    comparable.pop("reader")
    payload["audit_checksum"] = canonical_hash(comparable)
    return payload, records_by_session


STRING_PATTERNS_TEXT = {
    key: re.compile(rf'"{key}"\s*:\s*"([^"\\]*)"')
    for key in ("open_time", "close_time", "available_at", "timeframe", "instrument_code")
}
STRING_PATTERNS_BYTES = {
    key: re.compile(rb'"' + key.encode("ascii") + rb'"\s*:\s*"([^"\\]*)"')
    for key in ("open_time", "close_time", "available_at", "timeframe", "instrument_code")
}
COMPLETE_TEXT = re.compile(r'"complete"\s*:\s*(true|false)')
COMPLETE_BYTES = re.compile(rb'"complete"\s*:\s*(true|false)')


def text_value(line: str, key: str) -> str | None:
    match = STRING_PATTERNS_TEXT[key].search(line)
    return match.group(1) if match else None


def bytes_value(line: bytes, key: str) -> str | None:
    match = STRING_PATTERNS_BYTES[key].search(line)
    return match.group(1).decode("utf-8") if match else None


def scan_xau_metadata_primary(path: Path) -> tuple[dict[str, Any], set[int], dict[str, tuple[int, int]]]:
    valid: set[int] = set()
    envelope: dict[str, list[int]] = {}
    rows_seen = malformed = duplicate_valid = 0
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            opened_raw = text_value(line, "open_time")
            if opened_raw is None:
                continue
            if opened_raw.startswith(("2025-", "2026-")):
                break
            if text_value(line, "timeframe") != "1m" or text_value(line, "instrument_code") != "XAUUSD":
                continue
            rows_seen += 1
            closed_raw = text_value(line, "close_time")
            available_raw = text_value(line, "available_at")
            complete_match = COMPLETE_TEXT.search(line)
            if closed_raw is None or available_raw is None or complete_match is None or complete_match.group(1) != "true":
                malformed += 1
                continue
            opened = parse_dt(opened_raw)
            closed = parse_dt(closed_raw)
            available = parse_dt(available_raw)
            if closed - opened != timedelta(minutes=1) or available > closed:
                malformed += 1
                continue
            opened_ns = dt_ns(opened)
            if opened_ns in valid:
                duplicate_valid += 1
            valid.add(opened_ns)
            day = opened.date().isoformat()
            if day not in envelope:
                envelope[day] = [opened_ns, opened_ns]
            else:
                envelope[day][0] = min(envelope[day][0], opened_ns)
                envelope[day][1] = max(envelope[day][1], opened_ns)
    frozen_envelope = {key: (value[0], value[1]) for key, value in sorted(envelope.items())}
    report = {
        "scanner": "TEXT_REGEX_PRIMARY",
        "rows_seen_before_2025_lock": rows_seen,
        "valid_unique_minute_timestamps": len(valid),
        "malformed_or_late_metadata_rows": malformed,
        "duplicate_valid_timestamps": duplicate_valid,
        "valid_timestamp_checksum": timestamp_set_hash(valid),
        "utc_date_envelope_checksum": canonical_hash({key: list(value) for key, value in frozen_envelope.items()}),
        "utc_dates": len(frozen_envelope),
        "first_2025_or_2026_record_deserialized": False,
        "ohlc_fields_deserialized": False,
    }
    return report, valid, frozen_envelope


def scan_xau_metadata_reference(path: Path) -> tuple[dict[str, Any], set[int], dict[str, tuple[int, int]]]:
    valid: set[int] = set()
    envelope: dict[str, tuple[int, int]] = {}
    rows_seen = malformed = duplicate_valid = 0
    with gzip.open(path, "rb") as handle:
        for line in handle:
            opened_raw = bytes_value(line, "open_time")
            if opened_raw is None:
                continue
            if opened_raw.startswith(("2025-", "2026-")):
                break
            if bytes_value(line, "timeframe") != "1m" or bytes_value(line, "instrument_code") != "XAUUSD":
                continue
            rows_seen += 1
            closed_raw = bytes_value(line, "close_time")
            available_raw = bytes_value(line, "available_at")
            complete_match = COMPLETE_BYTES.search(line)
            if closed_raw is None or available_raw is None or complete_match is None or complete_match.group(1) != b"true":
                malformed += 1
                continue
            opened = parse_dt(opened_raw)
            closed = parse_dt(closed_raw)
            available = parse_dt(available_raw)
            if closed - opened != timedelta(seconds=60) or available > closed:
                malformed += 1
                continue
            opened_ns = dt_ns(opened)
            if opened_ns in valid:
                duplicate_valid += 1
            valid.add(opened_ns)
            day = opened.date().isoformat()
            prior = envelope.get(day)
            envelope[day] = (opened_ns, opened_ns) if prior is None else (min(prior[0], opened_ns), max(prior[1], opened_ns))
    envelope = dict(sorted(envelope.items()))
    report = {
        "scanner": "BINARY_REGEX_REFERENCE",
        "rows_seen_before_2025_lock": rows_seen,
        "valid_unique_minute_timestamps": len(valid),
        "malformed_or_late_metadata_rows": malformed,
        "duplicate_valid_timestamps": duplicate_valid,
        "valid_timestamp_checksum": timestamp_set_hash(valid),
        "utc_date_envelope_checksum": canonical_hash({key: list(value) for key, value in envelope.items()}),
        "utc_dates": len(envelope),
        "first_2025_or_2026_record_deserialized": False,
        "ohlc_fields_deserialized": False,
    }
    return report, valid, envelope


def required_minutes(feature_id: str, decision_ns: int) -> set[int]:
    hour_end = decision_ns - decision_ns % ONE_HOUR_NS
    atr_start = hour_end - 15 * ONE_HOUR_NS
    required = set(range(atr_start, hour_end, ONE_MINUTE_NS))
    if feature_id == "CSR_STRUCTURE_MOMENTUM_15M":
        latest_start = ((decision_ns - 1) // FIFTEEN_MINUTES_NS) * FIFTEEN_MINUTES_NS
        momentum_start = latest_start - 4 * FIFTEEN_MINUTES_NS
        required.update(range(momentum_start, latest_start + FIFTEEN_MINUTES_NS, ONE_MINUTE_NS))
    elif feature_id == "CSR_SESSION_LEVEL_TENSION":
        required.add(decision_ns - ONE_MINUTE_NS)
    else:
        raise AuditFailure(f"No frozen price-window rule: {feature_id}")
    return required


def classify_missing(
    missing: Sequence[int], envelope: Mapping[str, tuple[int, int]], availability: str
) -> str:
    if missing:
        outside = False
        for timestamp in missing:
            limits = envelope.get(ns_date(timestamp))
            if limits is None or timestamp < limits[0] or timestamp > limits[1]:
                outside = True
                break
        return "REQUIRES_ADDITIONAL_SOURCE" if outside else "GENUINE_SOURCE_GAP"
    if availability in {AV_CONTEXT, AV_LEVEL, AV_NONPOSITIVE}:
        return "DEFINITION_INDUCED_UNAVAILABLE"
    if availability in {AV_TECH_XAU, AV_ATR}:
        return "RECOVERABLE_EXISTING_SEALED_SOURCE"
    return "UNRESOLVED"


def diagnostic_rows(
    records_by_session: Mapping[str, Sequence[Mapping[str, Any]]],
    valid_minutes: set[int],
    envelope: Mapping[str, tuple[int, int]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    feature_lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    models = load_json(MODEL_REGISTRY)
    interactions = {item["interaction_id"]: item for item in models["stage2"]["interactions"]}
    require(set(TARGET_INTERACTIONS).issubset(interactions), "Target interaction registry changed")
    for session in SESSIONS:
        for record in records_by_session[session]:
            decision = int(record["decision_at_ns"])
            for feature_id in TARGET_FEATURES:
                availability = str(record[f"{feature_id}__availability"])
                if availability == AV_AVAILABLE:
                    continue
                required = required_minutes(feature_id, decision)
                missing = sorted(required.difference(valid_minutes))
                classification = classify_missing(missing, envelope, availability)
                require(classification in DISPOSITIONS, "Unregistered diagnostic disposition")
                output = {
                    "record_type": "FEATURE",
                    "test_id": feature_id,
                    "session_code": session,
                    "anchor_id": str(record["anchor_id"]),
                    "session_date": str(record["session_date"]),
                    "chronological_block": int(record["chronological_block"]),
                    "decision_at_ns": decision,
                    "anchor_offset_minutes": int(record["anchor_offset_minutes"]),
                    "availability": availability,
                    "available_at_ns": record[f"{feature_id}__available_at_ns"],
                    "lineage_hash": str(record[f"{feature_id}__lineage_hash"]),
                    "required_minute_count": len(required),
                    "available_required_minute_count": len(required) - len(missing),
                    "missing_required_minute_count": len(missing),
                    "missing_timestamp_checksum": timestamp_set_hash(missing),
                    "source_coverage_start_ns": min(required),
                    "source_coverage_end_exclusive_ns": max(required) + ONE_MINUTE_NS,
                    "classification": classification,
                }
                rows.append(output)
                feature_lookup[(session, output["anchor_id"], feature_id)] = output
    for session in SESSIONS:
        for record in records_by_session[session]:
            for interaction_id in TARGET_INTERACTIONS:
                interaction = interactions[interaction_id]
                left = str(interaction["left"])
                right = str(interaction["right"])
                left_availability = str(record[f"{left}__availability"])
                right_availability = str(record[f"{right}__availability"])
                if left_availability == AV_AVAILABLE and right_availability == AV_AVAILABLE:
                    continue
                target = feature_lookup.get((session, str(record["anchor_id"]), right))
                classification = target["classification"] if target is not None else "UNRESOLVED"
                rows.append(
                    {
                        "record_type": "INTERACTION",
                        "test_id": interaction_id,
                        "session_code": session,
                        "anchor_id": str(record["anchor_id"]),
                        "session_date": str(record["session_date"]),
                        "chronological_block": int(record["chronological_block"]),
                        "decision_at_ns": int(record["decision_at_ns"]),
                        "anchor_offset_minutes": int(record["anchor_offset_minutes"]),
                        "left_feature_id": left,
                        "left_availability": left_availability,
                        "left_available_at_ns": record[f"{left}__available_at_ns"],
                        "left_lineage_hash": str(record[f"{left}__lineage_hash"]),
                        "right_feature_id": right,
                        "right_availability": right_availability,
                        "right_available_at_ns": record[f"{right}__available_at_ns"],
                        "right_lineage_hash": str(record[f"{right}__lineage_hash"]),
                        "classification": classification,
                        "underlying_feature_disposition_checksum": canonical_hash(target) if target is not None else None,
                    }
                )
    rows.sort(key=lambda item: (item["session_code"], item["anchor_id"], item["record_type"], item["test_id"]))
    counts: dict[str, Any] = {}
    for session in SESSIONS:
        counts[session] = {}
        for test_id in (*TARGET_FEATURES, *TARGET_INTERACTIONS):
            selected = [item for item in rows if item["session_code"] == session and item["test_id"] == test_id]
            disposition_counts = Counter(str(item["classification"]) for item in selected)
            counts[session][test_id] = {
                "unavailable_anchors": len(selected),
                "dispositions": {key: disposition_counts.get(key, 0) for key in DISPOSITIONS},
                "row_identity_checksum": canonical_hash(
                    [(item["anchor_id"], item["classification"]) for item in selected]
                ),
            }
    require(all(item["classification"] in DISPOSITIONS for item in rows), "Unclassified diagnostic row")
    summary = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_R1_SOURCE_COVERAGE_DIAGNOSTIC_V1_0",
        "status": "PASS_METADATA_ONLY_SOURCE_COVERAGE_DISPOSITION",
        "target_features": list(TARGET_FEATURES),
        "registered_target_interactions": list(TARGET_INTERACTIONS),
        "rows": len(rows),
        "counts": counts,
        "row_checksum": canonical_hash(rows),
        "all_unavailable_anchors_classified": True,
        "outcomes_opened": False,
        "ohlc_values_accessed_or_reported": False,
        "year_2025_or_2026_values_accessed": False,
    }
    return rows, summary


def jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join((canonical_json(row) + "\n").encode("utf-8") for row in rows)


def support_comparable(audit: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(audit)
    output.pop("implementation", None)
    output.pop("reader", None)
    output.pop("audit_checksum", None)
    return output


def source_comparable(report: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(report)
    output.pop("scanner", None)
    return output


def eligible_registry(support: Mapping[str, Any]) -> dict[str, Any]:
    sessions: dict[str, Any] = {}
    for session in SESSIONS:
        stage1 = support["sessions"][session]["stage1"]
        stage2 = support["sessions"][session]["stage2"]
        sessions[session] = {
            "stage1_support_eligible": [item["feature_id"] for item in stage1 if item["support_status"] == "SUPPORT_ELIGIBLE"],
            "stage1_support_fail": [item["feature_id"] for item in stage1 if item["support_status"] == "SUPPORT_FAIL"],
            "stage2_support_eligible": [item["interaction_id"] for item in stage2 if item["support_status"] == "SUPPORT_ELIGIBLE"],
            "stage2_support_fail": [item["interaction_id"] for item in stage2 if item["support_status"] == "SUPPORT_FAIL"],
        }
        sessions[session]["m3_has_eligible_preregistered_test"] = bool(
            sessions[session]["stage1_support_eligible"] or sessions[session]["stage2_support_eligible"]
        )
    payload = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_R1_ELIGIBLE_TEST_REGISTRY_V1_0",
        "status": "FROZEN_POST_SUPPORT_RECERTIFICATION",
        "sessions": sessions,
        "outcomes_opened": False,
        "candidate_count": 0,
    }
    return seal_receipt({**payload, "registry_receipt": None}, "registry_receipt")


def report_text(
    verdict: Mapping[str, Any], support: Mapping[str, Any], diagnostic: Mapping[str, Any], registry: Mapping[str, Any]
) -> str:
    lines = [
        "# GC Continuous State-Response V3 — Milestone 2-R1 Report",
        "",
        f"Formal verdict: `{verdict['status']}`",
        "",
        "## Preserved boundary",
        "",
        f"- Milestone 2 remains `{EXPECTED_M2_STATUS}`.",
        f"- Milestone 2 final seal remains `{EXPECTED_M2_FINAL_SEAL}`.",
        "- No development outcome was opened or joined. Calendars 2025 and 2026 remained locked.",
        "- No data was acquired and no charge was incurred.",
        "",
        "## Sole support amendment",
        "",
        "The impossible fixed 35-date annual OOF rule was replaced by availability on at least 80% of each year's frozen OOF-date universe, rounded upward. Every other gate remained unchanged.",
        "",
    ]
    for session in SESSIONS:
        session_data = support["sessions"][session]
        lines.extend(
            [
                f"### {session.replace('_', ' ').title()}",
                "",
                "Frozen OOF universes: "
                + ", ".join(
                    f"{year}={data['denominator_frozen_oof_dates']}"
                    for year, data in session_data["annual_oof_universe"].items()
                )
                + ".",
                f"Stage 1: {session_data['stage1_support_eligible']} eligible, {session_data['stage1_support_fail']} support failures.",
                f"Stage 2: {session_data['stage2_support_eligible']} eligible, {session_data['stage2_support_fail']} support failures.",
                "",
                "Eligible Stage 1: " + (", ".join(registry["sessions"][session]["stage1_support_eligible"]) or "none") + ".",
                "Eligible Stage 2: " + (", ".join(registry["sessions"][session]["stage2_support_eligible"]) or "none") + ".",
                "",
            ]
        )
    lines.extend(["## Metadata-only source-coverage disposition", ""])
    for session in SESSIONS:
        for test_id, data in diagnostic["counts"][session].items():
            nonzero = ", ".join(f"{key}={value}" for key, value in data["dispositions"].items() if value)
            lines.append(f"- `{session}` / `{test_id}`: {data['unavailable_anchors']} unavailable; {nonzero or 'no dispositions' }.")
    lines.extend(
        [
            "",
            "## Milestone 3 readiness",
            "",
            f"At least one preregistered test is support-eligible in every session: `{str(verdict['m3_has_eligible_preregistered_test_per_session']).lower()}`.",
            "This is research readiness, not evidence of an edge. Relationship discovery still requires a separately authorized Milestone 3 outcome opening.",
            "",
            "## Bounded recommendation",
            "",
            verdict["bounded_recovery_recommendation"],
            "",
        ]
    )
    return "\n".join(lines)


def artifact_record(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def run(paths: Paths) -> None:
    frozen = verify_freeze(paths, require_xau_source=True)
    require(not paths.output.exists(), f"Refusing to overwrite R1 output: {paths.output}")
    paths.output.mkdir(parents=True)
    write_json_once(
        paths.output / "attempt_started.json",
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_R1_ATTEMPT_V1_0",
            "status": "STARTED_AFTER_PRE_ACCESS_FREEZE",
            "started_at_utc": utc_now(),
            "freeze_receipt": frozen["freeze_receipt"],
            "outcomes_accessed": False,
        },
    )

    primary_support, primary_records = support_audit(paths, "primary", reference=False)
    reference_support, reference_records = support_audit(paths, "reference", reference=True)
    require(support_comparable(primary_support) == support_comparable(reference_support), "Primary/reference support audits differ")
    write_json_once(paths.output / "primary_support_audit.json", primary_support)
    write_json_once(paths.output / "reference_support_audit.json", reference_support)

    primary_source, primary_minutes, primary_envelope = scan_xau_metadata_primary(paths.xau_source)
    reference_source, reference_minutes, reference_envelope = scan_xau_metadata_reference(paths.xau_source)
    require(source_comparable(primary_source) == source_comparable(reference_source), "Primary/reference source metadata differ")
    require(primary_minutes == reference_minutes and primary_envelope == reference_envelope, "Source timestamp sets differ")
    write_json_once(paths.output / "primary_source_coverage.json", primary_source)
    write_json_once(paths.output / "reference_source_coverage.json", reference_source)

    primary_rows, primary_diagnostic = diagnostic_rows(primary_records, primary_minutes, primary_envelope)
    reference_rows, reference_diagnostic = diagnostic_rows(reference_records, reference_minutes, reference_envelope)
    primary_payload = jsonl_bytes(primary_rows)
    reference_payload = jsonl_bytes(reference_rows)
    require(primary_payload == reference_payload, "Primary/reference disposition rows differ")
    require(primary_diagnostic == reference_diagnostic, "Primary/reference diagnostic summaries differ")
    primary_dispositions = paths.output / "primary_unavailability_dispositions.jsonl"
    reference_dispositions = paths.output / "reference_unavailability_dispositions.jsonl"
    require(not primary_dispositions.exists() and not reference_dispositions.exists(), "Disposition output exists")
    primary_dispositions.write_bytes(primary_payload)
    reference_dispositions.write_bytes(reference_payload)
    write_json_once(paths.output / "primary_source_coverage_diagnostic.json", primary_diagnostic)
    write_json_once(paths.output / "reference_source_coverage_diagnostic.json", reference_diagnostic)

    registry = eligible_registry(primary_support)
    write_json_once(paths.output / "eligible_test_registry.json", registry)
    m3_ready = all(registry["sessions"][session]["m3_has_eligible_preregistered_test"] for session in SESSIONS)
    dispositions = Counter(str(row["classification"]) for row in primary_rows if row["record_type"] == "FEATURE")
    if dispositions["REQUIRES_ADDITIONAL_SOURCE"] or dispositions["GENUINE_SOURCE_GAP"]:
        recommendation = (
            "If the price-structure fields are required in a future branch, authorize one separate outcome-blind source-recovery milestone "
            "covering only the frozen missing pre-anchor XAUUSD one-minute timestamps; retain the present predictors as SUPPORT_FAIL until then."
        )
    elif dispositions["RECOVERABLE_EXISTING_SEALED_SOURCE"]:
        recommendation = (
            "Authorize at most one separate outcome-blind reconstruction audit for the target price-structure fields using only the existing sealed source; "
            "retain the present predictors as SUPPORT_FAIL until independently reproduced."
        )
    else:
        recommendation = "No recovery is recommended from the available metadata."

    certification = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_R1_CERTIFICATION_V1_0",
        "status": "PASS_M2_R1_INDEPENDENT_REPRODUCTION",
        "gates": {
            "m2_boundary_and_seals_intact": True,
            "r1_amendment_frozen_before_row_access": True,
            "sole_support_gate_replacement_applied": True,
            "all_other_support_statistics_match_m2": True,
            "primary_reference_annual_universes_exact": True,
            "primary_reference_support_audits_exact": True,
            "primary_reference_source_timestamp_metadata_exact": True,
            "primary_reference_disposition_rows_byte_identical": True,
            "all_target_unavailable_anchors_classified": True,
            "outcomes_not_opened_or_joined": True,
            "year_2025_and_2026_values_not_accessed": True,
            "no_data_acquisition_or_charge": True,
            "no_relationships_effects_candidates_execution_trades_or_pnl": True,
        },
        "primary_support_checksum": primary_support["audit_checksum"],
        "reference_support_checksum": reference_support["audit_checksum"],
        "source_metadata_checksum": canonical_hash(source_comparable(primary_source)),
        "disposition_rows_sha256": hashlib.sha256(primary_payload).hexdigest(),
        "diagnostic_checksum": primary_diagnostic["row_checksum"],
        "eligible_registry_receipt": registry["registry_receipt"],
    }
    write_json_once(paths.output / "technical_certification.json", certification)

    verdict = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_R1_VERDICT_V1_0",
            "status": "PASS_V3_M2_R1_SUPPORT_FEASIBILITY_AND_SOURCE_COVERAGE_DISPOSITION",
            "completed_at_utc": utc_now(),
            "m2_status_preserved": EXPECTED_M2_STATUS,
            "m2_final_seal_preserved": EXPECTED_M2_FINAL_SEAL,
            "freeze_receipt": frozen["freeze_receipt"],
            "m3_has_eligible_preregistered_test_per_session": m3_ready,
            "support_summary": {
                session: {
                    key: int(primary_support["sessions"][session][key])
                    for key in (
                        "stage1_support_eligible",
                        "stage1_support_fail",
                        "stage2_support_eligible",
                        "stage2_support_fail",
                    )
                }
                for session in SESSIONS
            },
            "bounded_recovery_recommendation": recommendation,
            "outcomes_accessed_or_joined": False,
            "relationships_or_effects_calculated": False,
            "candidate_count": 0,
            "year_2025_or_2026_values_accessed": False,
            "data_acquired": False,
            "charge_incurred_usd": 0.0,
            "verdict_receipt": None,
        },
        "verdict_receipt",
    )
    write_json_once(paths.output / "verdict.json", verdict)

    state = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_STATE_V2_R1_0",
            "status": verdict["status"],
            "active_branch": "GC_CONTINUOUS_STATE_RESPONSE_EDGE_DISCOVERY_V3",
            "completed_milestone": "M2_R1_PRE_OUTCOME_SUPPORT_FEASIBILITY_AND_SOURCE_COVERAGE_DISPOSITION",
            "m2_final_seal_receipt": EXPECTED_M2_FINAL_SEAL,
            "m2_r1_freeze_receipt": frozen["freeze_receipt"],
            "m2_r1_verdict_receipt": verdict["verdict_receipt"],
            "eligible_test_registry_receipt": registry["registry_receipt"],
            "candidate_count": 0,
            "development_outcomes": "LOCKED_UNTIL_SEPARATELY_AUTHORIZED_M3",
            "calendar_2025": "LOCKED",
            "calendar_2026": "LOCKED",
            "next_milestone": "M3_RELATIONSHIP_DISCOVERY" if m3_ready else "NO_GO_SUPPORT_REMEDIATION",
            "next_milestone_authorized": False,
            "state_receipt": None,
        },
        "state_receipt",
    )
    write_json_once(paths.output / "state_v02_r1.json", state)
    write_text_once(paths.output / "GC_CONTINUOUS_STATE_RESPONSE_V3_MILESTONE_2_R1_REPORT.md", report_text(verdict, primary_support, primary_diagnostic, registry))

    artifact_names = (
        "attempt_started.json",
        "primary_support_audit.json",
        "reference_support_audit.json",
        "primary_source_coverage.json",
        "reference_source_coverage.json",
        "primary_unavailability_dispositions.jsonl",
        "reference_unavailability_dispositions.jsonl",
        "primary_source_coverage_diagnostic.json",
        "reference_source_coverage_diagnostic.json",
        "eligible_test_registry.json",
        "technical_certification.json",
        "verdict.json",
        "state_v02_r1.json",
        "GC_CONTINUOUS_STATE_RESPONSE_V3_MILESTONE_2_R1_REPORT.md",
    )
    manifest = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_R1_MANIFEST_V1_0",
            "status": verdict["status"],
            "sealed_at_utc": utc_now(),
            "freeze_receipt": frozen["freeze_receipt"],
            "verdict_receipt": verdict["verdict_receipt"],
            "state_receipt": state["state_receipt"],
            "artifacts": {name: artifact_record(paths.output / name) for name in artifact_names},
            "outcomes_accessed": False,
            "year_2025_or_2026_values_accessed": False,
            "data_acquired": False,
            "charge_incurred_usd": 0.0,
            "manifest_receipt": None,
        },
        "manifest_receipt",
    )
    write_json_once(paths.output / "manifest.json", manifest)
    final = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_R1_FINAL_SEAL_V1_0",
            "status": verdict["status"],
            "sealed_at_utc": utc_now(),
            "m2_final_seal_receipt": EXPECTED_M2_FINAL_SEAL,
            "freeze_receipt": frozen["freeze_receipt"],
            "manifest_receipt": manifest["manifest_receipt"],
            "manifest_sha256": sha256_file(paths.output / "manifest.json"),
            "verdict_sha256": sha256_file(paths.output / "verdict.json"),
            "state_sha256": sha256_file(paths.output / "state_v02_r1.json"),
            "outcomes_accessed": False,
            "year_2025_or_2026_values_accessed": False,
            "final_seal_receipt": None,
        },
        "final_seal_receipt",
    )
    write_json_once(paths.output / "final_seal.json", final)
    print(
        canonical_json(
            {
                "status": verdict["status"],
                "support_summary": verdict["support_summary"],
                "m3_ready": m3_ready,
                "final_seal_receipt": final["final_seal_receipt"],
            }
        )
    )


def verify(paths: Paths) -> None:
    frozen = verify_freeze(paths, require_xau_source=False)
    manifest = load_json(paths.output / "manifest.json")
    final = load_json(paths.output / "final_seal.json")
    verdict = load_json(paths.output / "verdict.json")
    state = load_json(paths.output / "state_v02_r1.json")
    require(receipt_valid(manifest, "manifest_receipt"), "R1 manifest receipt invalid")
    require(receipt_valid(final, "final_seal_receipt"), "R1 final receipt invalid")
    require(receipt_valid(verdict, "verdict_receipt"), "R1 verdict receipt invalid")
    require(receipt_valid(state, "state_receipt"), "R1 state receipt invalid")
    require(final["freeze_receipt"] == frozen["freeze_receipt"], "R1 freeze linkage changed")
    require(final["manifest_sha256"] == sha256_file(paths.output / "manifest.json"), "R1 manifest hash changed")
    require(final["verdict_sha256"] == sha256_file(paths.output / "verdict.json"), "R1 verdict hash changed")
    require(final["state_sha256"] == sha256_file(paths.output / "state_v02_r1.json"), "R1 state hash changed")
    for name, expected in manifest["artifacts"].items():
        path = paths.output / name
        require(path.is_file(), f"R1 artifact missing: {name}")
        require(path.stat().st_size == int(expected["bytes"]), f"R1 artifact size changed: {name}")
        require(sha256_file(path) == expected["sha256"], f"R1 artifact hash changed: {name}")
    primary_support = load_json(paths.output / "primary_support_audit.json")
    reference_support = load_json(paths.output / "reference_support_audit.json")
    require(support_comparable(primary_support) == support_comparable(reference_support), "Sealed support audits differ")
    primary_source = load_json(paths.output / "primary_source_coverage.json")
    reference_source = load_json(paths.output / "reference_source_coverage.json")
    require(source_comparable(primary_source) == source_comparable(reference_source), "Sealed source audits differ")
    require(
        (paths.output / "primary_unavailability_dispositions.jsonl").read_bytes()
        == (paths.output / "reference_unavailability_dispositions.jsonl").read_bytes(),
        "Sealed disposition rows differ",
    )
    require(not verdict["outcomes_accessed_or_joined"] and not verdict["year_2025_or_2026_values_accessed"], "R1 locks changed")
    print(canonical_json({"status": "PASS_V3_M2_R1_INDEPENDENT_VERIFICATION", "verdict": verdict["status"], "final_seal_receipt": final["final_seal_receipt"]}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "run", "verify", "self-test"))
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument("--m2-output", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    paths = Paths.build(args.data_root.resolve(), args.output, args.m2_output)
    if args.action == "freeze":
        freeze(paths)
    elif args.action == "run":
        run(paths)
    elif args.action == "verify":
        verify(paths)
    else:
        print(canonical_json(synthetic_proof()))


if __name__ == "__main__":
    try:
        main()
    except AuditFailure as exc:
        print(canonical_json({"status": "FAIL", "reason": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
