#!/usr/bin/env python3
"""Freeze GC Session Trigger Edge Discovery V1 Milestone 2.

This preparation step is metadata-only.  It binds the sealed Milestone 1
contract, builds the exact DST-aware research-window registry, and records
the value-blind materialization and support protocol before any development
market row is opened for Milestone 2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"

M1_CONTRACT = MANIFESTS / "gc_session_trigger_edge_contract_v01.json"
M1_TAXONOMY = MANIFESTS / "gc_session_trigger_edge_taxonomy_v01.json"
M1_OUTCOMES = MANIFESTS / "gc_session_trigger_edge_outcomes_v01.json"
M1_FEATURES = MANIFESTS / "gc_session_trigger_edge_feature_traceability_v01.json"
M1_STATISTICS = MANIFESTS / "gc_session_trigger_edge_statistics_v01.json"
M1_FREEZE = MANIFESTS / "gc_session_trigger_edge_m1_freeze_v01.json"
M1_MANIFEST = ARTIFACTS / "gc_session_trigger_edge_m1_v01" / "manifest.json"
M1_VERDICT = ARTIFACTS / "gc_session_trigger_edge_m1_v01" / "verdict.json"
M1_FINAL_SEAL = ARTIFACTS / "gc_session_trigger_edge_m1_v01" / "final_seal.json"

STEP5C_REGISTRY = MANIFESTS / "gc_microstructure_step_5c_row_registry_v01.json"
STEP5C_PROTOCOL = MANIFESTS / "gc_microstructure_step_5c_protocol_v01.json"
STEP5C_CONTEXT_MANIFEST = ARTIFACTS / "gc_microstructure_step5c_v01" / "manifest.json"
STEP5B2_MANIFEST = ARTIFACTS / "gc_microstructure_step_5b2_v01" / "step5b2_final" / "manifest.json"
CASEBOOK_MANIFEST = ARTIFACTS / "gold_casebook_v01" / "manifest.json"
CASEBOOK_PRICE = ARTIFACTS / "gold_casebook_v01" / "price_bars.jsonl.gz"
BASE_ENGINE = ROOT / "tools" / "build_gc_microstructure_features_step4a.py"
STEP5C_ENGINE = ROOT / "tools" / "materialize_gc_microstructure_step5c.py"
M2_ENGINE = ROOT / "tools" / "materialize_gc_session_trigger_edge_m2.py"

PROTOCOL_PATH = MANIFESTS / "gc_session_trigger_edge_m2_protocol_v01.json"
ROW_REGISTRY_PATH = MANIFESTS / "gc_session_trigger_edge_m2_row_registry_v01.json"
FREEZE_PATH = MANIFESTS / "gc_session_trigger_edge_m2_freeze_v01.json"
OUTPUT_DIR = ARTIFACTS / "gc_session_trigger_edge_m2_v01"
PREFLIGHT_PATH = OUTPUT_DIR / "protocol_preflight.json"

EXPECTED_M1_FINAL_SEAL_SHA256 = "d2df2418ca06ef3e28ecbbe531459df659840853579ef82a9a99e26785862957"
EXPECTED_M1_STATUS = "PASS_MILESTONE_1_CONTRACT_FROZEN_CONDITIONAL_M2_READINESS"
EXPECTED_STEP5C_REGISTRY_SHA256 = "a0c2b6dff0dd6c57e25b5f194342c69202e02f2e642f6fe8ae75ac2ea1bbe225"
EXPECTED_AVAILABLE_SESSION_ROWS = 374
EXPECTED_ALL_SESSION_ROWS = 376
FEATURE_BUCKETS = 18_900
DECISIONS_PER_SESSION = 240
XAU_COVERAGE_BARS_PER_SESSION = 300

AUTHORIZATION = (
    "Proceed to GC Session Trigger Edge Discovery V1 Milestone 2 under the sealed Milestone 1 contract. "
    "Preserve every prior verdict, artifact, registry, definition, threshold, support gate, multiplicity rule, "
    "and seal. Use only the existing sealed 2021-11-08 through 2024-12-13 development sources. Certify "
    "full-session plus sixty-minute MBO, MBP-10 and XAUUSD timestamp coverage; materialize the unchanged 85 "
    "one-second features, point-in-time contexts, and six frozen event families; and produce event-support "
    "counts separately for London and New York. Keep all forward outcomes completely hidden and unjoined. "
    "Do not calculate relationships, hit rates, effects, candidates, execution, trades, PnL, R multiples, or "
    "returns. Do not inspect 2025 or 2026, acquire data, or incur a charge. Independently reproduce, document, "
    "seal, and stop after Milestone 2."
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _receipt(value: Mapping[str, Any], field: str) -> str:
    copy = dict(value)
    copy.pop(field, None)
    return hashlib.sha256(_canonical(copy)).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _file(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _ns(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _verify_m1() -> dict[str, Any]:
    required = (
        M1_CONTRACT,
        M1_TAXONOMY,
        M1_OUTCOMES,
        M1_FEATURES,
        M1_STATISTICS,
        M1_FREEZE,
        M1_MANIFEST,
        M1_VERDICT,
        M1_FINAL_SEAL,
        STEP5C_REGISTRY,
        STEP5C_PROTOCOL,
        STEP5C_CONTEXT_MANIFEST,
        STEP5B2_MANIFEST,
        CASEBOOK_MANIFEST,
        CASEBOOK_PRICE,
        BASE_ENGINE,
        STEP5C_ENGINE,
        M2_ENGINE,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    if _sha256(M1_FINAL_SEAL) != EXPECTED_M1_FINAL_SEAL_SHA256:
        raise ValueError("Milestone 1 final seal changed")
    final = _read(M1_FINAL_SEAL)
    manifest = _read(M1_MANIFEST)
    verdict = _read(M1_VERDICT)
    freeze = _read(M1_FREEZE)
    if final.get("status") != EXPECTED_M1_STATUS or manifest.get("status") != EXPECTED_M1_STATUS:
        raise ValueError("Milestone 1 did not pass")
    if final.get("manifest_sha256") != _sha256(M1_MANIFEST):
        raise ValueError("Milestone 1 manifest binding failed")
    if final.get("verdict_sha256") != _sha256(M1_VERDICT):
        raise ValueError("Milestone 1 verdict binding failed")
    if final.get("freeze_sha256") != _sha256(M1_FREEZE):
        raise ValueError("Milestone 1 freeze binding failed")
    if _receipt(final, "final_seal_receipt") != final.get("final_seal_receipt"):
        raise ValueError("Milestone 1 final receipt failed")
    if _receipt(freeze, "freeze_receipt") != freeze.get("freeze_receipt"):
        raise ValueError("Milestone 1 freeze receipt failed")
    if _receipt(verdict, "verdict_receipt") != verdict.get("verdict_receipt"):
        raise ValueError("Milestone 1 verdict receipt failed")
    if _sha256(STEP5C_REGISTRY) != EXPECTED_STEP5C_REGISTRY_SHA256:
        raise ValueError("Step 5C row registry changed")
    return {
        "m1_status": final["status"],
        "m1_final_seal_receipt": final["final_seal_receipt"],
        "verified_paths": len(required),
    }


def _build_rows() -> list[dict[str, Any]]:
    source = _read(STEP5C_REGISTRY)
    rows = source.get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_ALL_SESSION_ROWS:
        raise ValueError("Unexpected Step 5C row population")
    output: list[dict[str, Any]] = []
    for old in rows:
        opened = _parse(str(old["decision_at_utc"]))
        available = str(old["availability_disposition"]) == "EXPECTED_AVAILABLE"
        start = opened - timedelta(minutes=15)
        scan_end = opened + timedelta(hours=4)
        end = opened + timedelta(hours=5)
        day = opened.replace(hour=0, minute=0, second=0, microsecond=0)
        output.append(
            {
                "row_id": f"TRIGGER_M2:{old['session_date']}:{old['session_code']}",
                "source_step5c_row_id": old["row_id"],
                "session_date": old["session_date"],
                "session_code": old["session_code"],
                "session_timezone": old["session_timezone"],
                "selected_month_week_id": old["selected_month_week_id"],
                "interval_id": old["interval_id"],
                "mbo_request_id": old["mbo_request_id"],
                "mbp10_request_id": old["mbp10_request_id"],
                "expected_instrument_id": old["expected_instrument_id"],
                "availability_disposition": old["availability_disposition"],
                "session_open_utc": opened.isoformat().replace("+00:00", "Z"),
                "feature_start_inclusive_utc": start.isoformat().replace("+00:00", "Z"),
                "trigger_scan_start_inclusive_utc": opened.isoformat().replace("+00:00", "Z"),
                "trigger_scan_end_exclusive_utc": scan_end.isoformat().replace("+00:00", "Z"),
                "coverage_end_exclusive_utc": end.isoformat().replace("+00:00", "Z"),
                "window_start_inclusive_ns": _ns(start),
                "window_end_exclusive_ns": _ns(end),
                "utc_day_start_ns": _ns(day),
                "bucket_index_start_inclusive": int((start - day).total_seconds()),
                "bucket_index_end_exclusive": int((end - day).total_seconds()),
                "expected_bucket_rows": FEATURE_BUCKETS if available else 0,
                "expected_decision_rows": DECISIONS_PER_SESSION if available else 0,
                "expected_xau_coverage_bars": XAU_COVERAGE_BARS_PER_SESSION if available else 0,
                "permanently_engineering_only": False,
            }
        )
    output.sort(key=lambda item: (item["session_date"], item["session_code"]))
    if sum(row["expected_bucket_rows"] > 0 for row in output) != EXPECTED_AVAILABLE_SESSION_ROWS:
        raise ValueError("Available-session count changed")
    return output


def _build_protocol(frozen_at: str, row_registry: Mapping[str, Any]) -> dict[str, Any]:
    taxonomy = _read(M1_TAXONOMY)
    features = _read(M1_FEATURES)
    statistics = _read(M1_STATISTICS)
    protocol: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_PROTOCOL_V1_0",
        "status": "FROZEN_BEFORE_M2_DEVELOPMENT_MARKET_VALUE_ACCESS",
        "frozen_at_utc": frozen_at,
        "authorization_sha256": hashlib.sha256(AUTHORIZATION.encode("utf-8")).hexdigest(),
        "classification": "OUTCOME_BLIND_TRIGGER_SUPPORT_AND_TECHNICAL_MATERIALIZATION",
        "development_boundary": {
            "selected_dates": 188,
            "available_session_dates_per_session": 187,
            "month_week_blocks": 38,
            "start": "2021-11-08",
            "end": "2024-12-13",
            "calendar_2025": "LOCKED_NO_FILE_OR_ROW_ACCESS",
            "calendar_2026": "LOCKED_NO_FILE_OR_ROW_ACCESS",
        },
        "time_grid": {
            "sessions": taxonomy["research_units"]["sessions"],
            "dst_authority": "IANA zoneinfo independently for Europe/London and America/New_York",
            "feature_warmup_seconds": 900,
            "trigger_scan_seconds": 14_400,
            "coverage_tail_seconds": 3_600,
            "one_second_buckets_per_available_session": FEATURE_BUCKETS,
            "minute_decisions_per_available_session": DECISIONS_PER_SESSION,
            "xau_coverage_bars_per_available_session": XAU_COVERAGE_BARS_PER_SESSION,
            "micro_onset_first_eligible_local_close": "08:02:00",
            "micro_antecedent_boundaries": "08:00 and 08:01 are calculated; 08:00 is antecedent-only",
        },
        "feature_materialization": {
            "columns": features["sealed_85_microstructure_columns"]["columns"],
            "count": 85,
            "formulas_binding": features["sealed_85_microstructure_columns"]["formulas_sha256"],
            "source_roles": {
                "MBO": "deterministic one-second event flow",
                "MBP10": "authoritative top-ten as-of state",
            },
            "timestamp_authority": "ts_recv",
            "bucket_boundary": "left-closed right-open source allocation; state as of bucket end",
            "overlap_policy": "London and New York are independent research units. A sealed source row in their UTC overlap is allocated exactly once inside each applicable session window and reported as intentional cross-session reuse.",
            "state_reset": "Clear all feature, rolling-state, event, and level-event state at every session-date/session boundary.",
            "market_state": "All frozen spans are daytime continuous matching; only two-sided uncrossed authoritative bucket-close states are eligible for GC state predicates.",
            "bad_timestamp_and_snapshot_semantics": "Unchanged sealed Step 5B.2 and Step 4A.3 dispositions.",
            "missing_updates": "A zero-update second is retained. MBP-10 state may carry only from the latest eligible prior authoritative row; MBO event flow is zero for that bucket.",
        },
        "derived_states": features["prior_derived_states"],
        "event_families": taxonomy["event_families"],
        "level_families": taxonomy["level_families"],
        "canonicalization": taxonomy["canonicalization"],
        "event_detection_clarifications": {
            "strict_level_comparisons": True,
            "adjacency": "Two-close acceptance and next-bar reclaim require exact adjacent complete one-minute timestamps; a gap resets adjacency and pending acceptance state.",
            "failed_acceptance_clock": "Bars 1 through 5 after the acceptance-confirming close are eligible; the first return is retained; a later return is not the frozen event.",
            "opening_range_availability": "SESSION_OPENING_RANGE_15 is usable at and after the 08:15 local close only when all first fifteen bars are unique, complete, and timely.",
            "micro_onset": "The same qualifying state/pair must exist at the current and immediately prior completed-minute boundary and be absent at the boundary before that.",
            "pooled_cap": "After per-level and per-direction canonicalization, retain at most the three earliest canonical events per family/date; exact simultaneous level confirmations merge into a sorted level-family list.",
        },
        "point_in_time_contexts": {
            "fundamental": features["fundamental_contexts"],
            "price_session_structure": features["price_session_and_structure"],
            "event_attachment": "Materialize at every eligible minute decision and attach the exact decision row to each event.",
            "latest_fact_policy": "Carry a session-open fact only while its available_at remains no later than the event decision and no later eligible vintage exists in the sealed inputs.",
            "structure_policy": "No new structure algorithm is introduced. Re-evaluate the frozen 15m/1h facts at event time and require detected_at/available_at no later than decision_at; otherwise UNKNOWN.",
            "recent_release_policy": "Use only a release already represented by the sealed point-in-time event state with a verified pre-release forecast; do not reconstruct or infer an absent intraday surprise.",
            "unknown_policy": features["unknown_policy"],
        },
        "xau_timestamp_coverage": {
            "required_interval": "Every one-minute bar open in [session open, session open+5h), exactly 300 timestamps.",
            "trigger_value_boundary": "OHLC may be used only for bars completing no later than the current event decision. Bars after a decision are never joined or transformed into outcomes in M2.",
            "allowed_known_gaps": [
                {"session_date": "2021-12-13", "session": "NEW_YORK", "utc_open_times": ["16:32", "16:33"]},
                {"session_date": "2023-03-15", "session": "NEW_YORK", "utc_open_ranges": ["13:19-13:27"]},
                {"session_date": "2023-08-15", "session": "LONDON", "utc_open_ranges": ["08:05-08:40", "09:37-09:39", "10:05-10:08"]},
                {"session_date": "2023-09-13", "session": "NEW_YORK", "utc_open_ranges": ["14:48-14:50"]},
            ],
            "documented_unavailable": [{"session_date": "2022-04-15", "sessions": ["LONDON", "NEW_YORK"], "reason": "CME_GOOD_FRIDAY"}],
            "event_gap_disposition": "Emit a detected trigger as UNKNOWN_FORWARD_COVERAGE and exclude it from support admission when its detection, anchor, or any registered path through +60 minutes intersects a missing timestamp. Never bridge or impute.",
        },
        "support_only_registry": {
            "stage1": statistics["stage_1"],
            "stage2": statistics["stage_2"],
            "permitted_stage2_contexts": features["permitted_stage2_contexts"],
            "stage2_test_count_per_session": 30,
            "stage2_mapping": {
                "all_six_event_families": ["MACRO_ENGINE_ALIGNMENT", "REAL_YIELD_USD_ALIGNMENT", "RECENT_RELEASE_ALIGNMENT", "STRUCTURE_15M_1H_ALIGNMENT"],
                "three_level_event_families_only": ["FLOW_DEPTH_CONFIRMATION_FOR_LEVEL_EVENTS_ONLY", "LIQUIDITY_FRAGILITY_FOR_LEVEL_EVENTS_ONLY"],
                "comparison": "Same event/session with a known nonaligned state; UNKNOWN excluded and reported.",
            },
            "counts_only": ["instances", "distinct_dates", "distinct_month_week_blocks", "directional instances and dates", "year counts", "UNKNOWN exclusions"],
            "prohibited": ["market direction", "hit rate", "effect", "p-value", "candidate", "ranking by outcome"],
        },
        "integrity_gates": {
            "predecessor_seals": "all pass",
            "sources": "all 80 existing sealed requests verified; no acquisition or substitution",
            "session_rows": EXPECTED_ALL_SESSION_ROWS,
            "available_session_rows": EXPECTED_AVAILABLE_SESSION_ROWS,
            "feature_rows": EXPECTED_AVAILABLE_SESSION_ROWS * FEATURE_BUCKETS,
            "minute_decision_rows": EXPECTED_AVAILABLE_SESSION_ROWS * DECISIONS_PER_SESSION,
            "xau_expected_timestamps": EXPECTED_AVAILABLE_SESSION_ROWS * XAU_COVERAGE_BARS_PER_SESSION,
            "xau_allowed_missing_timestamps": 57,
            "unexpected_xau_missing_or_duplicate_timestamps": 0,
            "feature_schema_columns": 85,
            "continuous_crossed_bucket_closes": 0,
            "primary_reference": "identical schemas, identities, null/UNKNOWN classifications, per-column checksums, complete-row checksums, event rows, support counts, diagnostics, and byte-identical Parquet outputs",
        },
        "verdict_order": [
            "FAIL_PREDECESSOR_OR_SOURCE_SEAL",
            "FAIL_FULL_SESSION_TIMESTAMP_COVERAGE",
            "FAIL_FEATURE_INTEGRITY",
            "FAIL_EVENT_OR_CONTEXT_INTEGRITY",
            "FAIL_REPRODUCTION",
            "PASS_MILESTONE_2_OUTCOME_BLIND_SUPPORT_MATERIALIZATION",
        ],
        "prohibited": [
            "development forward-outcome construction or join",
            "relationship, hit-rate, effect, p-value, candidate, or directional-edge calculation",
            "execution, trades, PnL, R multiples, account returns, or optimization",
            "2025 or 2026 file or row access",
            "data acquisition, provider request, paid API call, or charge",
            "feature, threshold, context, event, support, or multiplicity retuning",
            "raw feature values in the human report",
        ],
        "row_registry": {
            "path": ROW_REGISTRY_PATH.relative_to(ROOT).as_posix(),
            "registry_receipt": row_registry["registry_receipt"],
        },
        "outcomes_opened_or_joined": False,
        "year_2025_or_2026_values_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "protocol_receipt": None,
    }
    protocol["protocol_receipt"] = _receipt(protocol, "protocol_receipt")
    return protocol


def prepare() -> None:
    if any(path.exists() for path in (PROTOCOL_PATH, ROW_REGISTRY_PATH, FREEZE_PATH, PREFLIGHT_PATH)):
        raise FileExistsError("Refusing to overwrite an existing Milestone 2 freeze")
    verified = _verify_m1()
    frozen_at = _utc_now()
    rows = _build_rows()
    registry: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_ROW_REGISTRY_V1_0",
        "status": "FROZEN_BEFORE_M2_DEVELOPMENT_MARKET_VALUE_ACCESS",
        "frozen_at_utc": frozen_at,
        "source_registry": _file(STEP5C_REGISTRY),
        "rows": rows,
        "counts": {
            "all_session_rows": len(rows),
            "available_session_rows": sum(row["expected_bucket_rows"] > 0 for row in rows),
            "documented_unavailable_rows": sum(row["expected_bucket_rows"] == 0 for row in rows),
            "expected_feature_rows": sum(row["expected_bucket_rows"] for row in rows),
            "expected_minute_decision_rows": sum(row["expected_decision_rows"] for row in rows),
            "expected_xau_timestamps": sum(row["expected_xau_coverage_bars"] for row in rows),
        },
        "market_values_accessed": False,
        "outcomes_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "registry_receipt": None,
    }
    registry["registry_receipt"] = _receipt(registry, "registry_receipt")
    _write_exclusive(ROW_REGISTRY_PATH, registry)
    protocol = _build_protocol(frozen_at, registry)
    _write_exclusive(PROTOCOL_PATH, protocol)
    freeze: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_FREEZE_V1_0",
        "status": "SEALED_BEFORE_M2_DEVELOPMENT_MARKET_VALUE_ACCESS",
        "frozen_at_utc": frozen_at,
        "authorization_sha256": hashlib.sha256(AUTHORIZATION.encode("utf-8")).hexdigest(),
        "predecessors": {
            "m1_contract": _file(M1_CONTRACT),
            "m1_taxonomy": _file(M1_TAXONOMY),
            "m1_outcomes": _file(M1_OUTCOMES),
            "m1_features": _file(M1_FEATURES),
            "m1_statistics": _file(M1_STATISTICS),
            "m1_freeze": _file(M1_FREEZE),
            "m1_manifest": _file(M1_MANIFEST),
            "m1_verdict": _file(M1_VERDICT),
            "m1_final_seal": _file(M1_FINAL_SEAL),
            "step5c_protocol": _file(STEP5C_PROTOCOL),
            "step5c_context_manifest": _file(STEP5C_CONTEXT_MANIFEST),
            "step5b2_manifest": _file(STEP5B2_MANIFEST),
            "casebook_manifest": _file(CASEBOOK_MANIFEST),
            "casebook_price_bars": _file(CASEBOOK_PRICE),
            "base_feature_engine": _file(BASE_ENGINE),
            "step5c_materializer": _file(STEP5C_ENGINE),
        },
        "protocol": _file(PROTOCOL_PATH),
        "row_registry": _file(ROW_REGISTRY_PATH),
        "implementation": _file(M2_ENGINE),
        "verified_predecessor_paths": verified["verified_paths"],
        "development_market_rows_accessed_before_freeze": 0,
        "outcome_values_accessed_before_freeze": False,
        "year_2025_or_2026_values_accessed": False,
        "next_milestone_authorized": False,
        "freeze_receipt": None,
    }
    freeze["freeze_receipt"] = _receipt(freeze, "freeze_receipt")
    _write_exclusive(FREEZE_PATH, freeze)
    preflight = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_PROTOCOL_PREFLIGHT_V1_0",
        "status": "PASS_M2_PROTOCOL_FROZEN_BEFORE_VALUE_ACCESS",
        "completed_at_utc": _utc_now(),
        "m1_verification": verified,
        "protocol": _file(PROTOCOL_PATH),
        "row_registry": _file(ROW_REGISTRY_PATH),
        "freeze": _file(FREEZE_PATH),
        "counts": registry["counts"],
        "development_market_rows_accessed": 0,
        "outcome_values_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
    }
    _write_exclusive(PREFLIGHT_PATH, preflight)
    verify()
    print(json.dumps({"status": preflight["status"], "counts": registry["counts"]}, sort_keys=True))


def verify() -> None:
    _verify_m1()
    registry = _read(ROW_REGISTRY_PATH)
    protocol = _read(PROTOCOL_PATH)
    freeze = _read(FREEZE_PATH)
    preflight = _read(PREFLIGHT_PATH)
    if _receipt(registry, "registry_receipt") != registry.get("registry_receipt"):
        raise ValueError("M2 row-registry receipt failed")
    if _receipt(protocol, "protocol_receipt") != protocol.get("protocol_receipt"):
        raise ValueError("M2 protocol receipt failed")
    if _receipt(freeze, "freeze_receipt") != freeze.get("freeze_receipt"):
        raise ValueError("M2 freeze receipt failed")
    for key, path in (("protocol", PROTOCOL_PATH), ("row_registry", ROW_REGISTRY_PATH), ("implementation", M2_ENGINE)):
        if freeze[key]["sha256"] != _sha256(path):
            raise ValueError(f"M2 freeze binding failed: {key}")
    if preflight.get("status") != "PASS_M2_PROTOCOL_FROZEN_BEFORE_VALUE_ACCESS":
        raise ValueError("M2 protocol preflight did not pass")
    if registry["counts"] != preflight["counts"]:
        raise ValueError("M2 frozen counts changed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "verify"))
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    else:
        verify()
        print(json.dumps({"status": "PASS_M2_PROTOCOL_FREEZE_VERIFICATION"}, sort_keys=True))


if __name__ == "__main__":
    main()
