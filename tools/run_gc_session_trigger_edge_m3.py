#!/usr/bin/env python3
"""Run GC Session Trigger Edge Discovery V2 Milestone 3.

The ``prepare`` action is outcome blind.  It seals the exact technical
population, test assignments, statistical protocol, implementation, and
source identities.  Only ``open-outcomes`` may read forward market values.
Stage 1 is sealed before Stage 2, and primary/reference implementations must
reproduce exactly.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
CONTRACT_PATH = ROOT / "GC_SESSION_TRIGGER_EDGE_DISCOVERY_V2_MILESTONE_3.md"
M1_CONTRACT_PATH = MANIFESTS / "gc_session_trigger_edge_contract_v01.json"
TAXONOMY_PATH = MANIFESTS / "gc_session_trigger_edge_taxonomy_v01.json"
OUTCOMES_PATH = MANIFESTS / "gc_session_trigger_edge_outcomes_v01.json"
FEATURES_PATH = MANIFESTS / "gc_session_trigger_edge_feature_traceability_v01.json"
STATISTICS_PATH = MANIFESTS / "gc_session_trigger_edge_statistics_v01.json"
ROW_REGISTRY_PATH = MANIFESTS / "gc_session_trigger_edge_m2_row_registry_v01.json"
PROTOCOL_PATH = MANIFESTS / "gc_session_trigger_edge_m3_protocol_v01.json"
POPULATION_PATH = MANIFESTS / "gc_session_trigger_edge_m3_population_v01.json"
TEST_REGISTRY_PATH = MANIFESTS / "gc_session_trigger_edge_m3_test_registry_v01.json"
FREEZE_PATH = MANIFESTS / "gc_session_trigger_edge_m3_freeze_v01.json"
M1_ARTIFACT_DIR = ROOT / "research_artifacts" / "gc_session_trigger_edge_m1_v01"
M1_MANIFEST_PATH = M1_ARTIFACT_DIR / "manifest.json"
M1_VERDICT_PATH = M1_ARTIFACT_DIR / "verdict.json"
M1_FINAL_SEAL_PATH = M1_ARTIFACT_DIR / "final_seal.json"
TEST_PATH = ROOT / "tests" / "test_gc_session_trigger_edge_m3.py"

DEFAULT_REMOTE_ROOT = Path("/home/wapi/rear_gold_step5b_v01")
DEFAULT_V2R1 = DEFAULT_REMOTE_ROOT / "artifacts/gc_session_trigger_edge_v2r1_v01"
DEFAULT_XAU = DEFAULT_REMOTE_ROOT / "data/gold_casebook_v01/price_bars.jsonl.gz"
DEFAULT_OUTPUT = DEFAULT_REMOTE_ROOT / "artifacts/gc_session_trigger_edge_m3_v01"

CONTRACT_VERSION = "GC_SESSION_TRIGGER_EDGE_DISCOVERY_CONTRACT_V1_0"
M3_VERSION = "GC_SESSION_TRIGGER_EDGE_V2_MILESTONE_3_V1_0"
SESSIONS = ("LONDON", "NEW_YORK")
EVENT_FAMILIES = (
    "LEVEL_SWEEP_RECLAIM",
    "LEVEL_BREAK_ACCEPT",
    "LEVEL_FAILED_ACCEPTANCE",
    "FLOW_DEPTH_ALIGNMENT_ONSET",
    "ABSORPTION_ONSET",
    "FRAGILITY_FLOW_ONSET",
)
LEVEL_EVENT_FAMILIES = EVENT_FAMILIES[:3]
ALL_CONTEXTS = (
    "MACRO_ENGINE_ALIGNMENT",
    "REAL_YIELD_USD_ALIGNMENT",
    "RECENT_RELEASE_ALIGNMENT",
    "STRUCTURE_15M_1H_ALIGNMENT",
)
LEVEL_CONTEXTS = (
    "FLOW_DEPTH_CONFIRMATION_FOR_LEVEL_EVENTS_ONLY",
    "LIQUIDITY_FRAGILITY_FOR_LEVEL_EVENTS_ONLY",
)
HORIZONS = (5, 15, 30, 60)
SECONDARY_HORIZONS = (5, 30, 60)
PRIMARY_HORIZON = 15
XAU_SCALE = 100_000_000
FLAT_THRESHOLD_SCALED = 1_000_000
GC_TICK_FIXED_1E9 = 100_000_000
BOOTSTRAP_REPETITIONS = 20_000
RANDOMIZATION_REPETITIONS = 100_000
QUANTILE_METHOD = "linear"
BH_Q = 0.05

OPEN_RE = re.compile(rb'"open_time"\s*:\s*"([^"]+)"')
TIMEFRAME_RE = re.compile(rb'"timeframe"\s*:\s*"([^"]+)"')
INSTRUMENT_RE = re.compile(rb'"instrument_code"\s*:\s*"([^"]+)"')
HOLDOUT_RE = re.compile(rb'"open_time"\s*:\s*"202[56]-')


OUTCOME_SCHEMA = pa.schema(
    [
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("session_date", pa.string(), nullable=False),
        pa.field("session_code", pa.string(), nullable=False),
        pa.field("selected_month_week_id", pa.string(), nullable=False),
        pa.field("event_family", pa.string(), nullable=False),
        pa.field("directional_prior", pa.string(), nullable=False),
        pa.field("decision_at_utc", pa.string(), nullable=False),
        pa.field("event_lineage_hash", pa.string(), nullable=False),
        pa.field("context_states_json", pa.string(), nullable=False),
        *[
            field
            for horizon in HORIZONS
            for field in (
                pa.field(f"xau_quality_{horizon}m", pa.string(), nullable=False),
                pa.field(f"xau_displacement_scaled_1e8_{horizon}m", pa.int64(), nullable=True),
                pa.field(f"xau_signed_displacement_scaled_1e8_{horizon}m", pa.int64(), nullable=True),
                pa.field(f"xau_state_{horizon}m", pa.string(), nullable=False),
                pa.field(f"xau_max_up_scaled_1e8_{horizon}m", pa.int64(), nullable=True),
                pa.field(f"xau_max_down_scaled_1e8_{horizon}m", pa.int64(), nullable=True),
                pa.field(f"xau_elapsed_to_max_up_minutes_{horizon}m", pa.int64(), nullable=True),
                pa.field(f"xau_elapsed_to_max_down_minutes_{horizon}m", pa.int64(), nullable=True),
                pa.field(f"xau_first_move_reversed_{horizon}m", pa.string(), nullable=False),
            )
        ],
        pa.field("xau_first_completed_minute_state", pa.string(), nullable=False),
        pa.field("gc_quality_15m", pa.string(), nullable=False),
        pa.field("gc_signed_displacement_fixed_1e9_15m", pa.int64(), nullable=True),
        pa.field("gc_signed_ticks_15m", pa.string(), nullable=False),
        pa.field("outcome_lineage_hash", pa.string(), nullable=False),
    ]
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed.astimezone(UTC)


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def write_text_exclusive(path: Path, value: str) -> None:
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def receipt_valid(record: Mapping[str, Any], field: str) -> bool:
    expected = record.get(field)
    if not isinstance(expected, str):
        return False
    without = dict(record)
    without.pop(field, None)
    return expected in {canonical_hash(without), canonical_hash({**record, field: None})}


def rounded(value: float | None, digits: int = 12) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    output = round(float(value), digits)
    return 0.0 if output == -0.0 else output


def seed_for(session: str, stage: int, test_id: str, method: str) -> int:
    payload = f"{CONTRACT_VERSION}|{session}|{stage}|{test_id}|{method}"
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16], 16)


def contexts_for_family(family: str) -> tuple[str, ...]:
    return (*ALL_CONTEXTS, *(LEVEL_CONTEXTS if family in LEVEL_EVENT_FAMILIES else ()))


def alignment_state(event: Mapping[str, Any], context: str) -> str:
    states = json.loads(str(event["context_states_json"]))
    direction = str(event["directional_prior"])
    if context == "MACRO_ENGINE_ALIGNMENT":
        value = states["MACRO_ENGINE_BIAS_STATE"]
        if value == "UNKNOWN":
            return "UNKNOWN"
        return "CONDITION" if value == ("BULLISH" if direction == "UP" else "BEARISH") else "COMPARISON"
    if context == "REAL_YIELD_USD_ALIGNMENT":
        value = states["REAL_YIELD_USD_CONFIRMATION"]
        if value == "UNKNOWN":
            return "UNKNOWN"
        return "CONDITION" if value == ("GOLD_BULLISH" if direction == "UP" else "GOLD_BEARISH") else "COMPARISON"
    if context == "RECENT_RELEASE_ALIGNMENT":
        value = states["RECENT_RELEASE_SURPRISE_DIRECTION"]
        if value == "UNKNOWN":
            return "UNKNOWN"
        return "CONDITION" if value == ("BULLISH" if direction == "UP" else "BEARISH") else "COMPARISON"
    if context == "STRUCTURE_15M_1H_ALIGNMENT":
        value = states["STRUCTURE_15M_1H_ALIGNMENT"]
        if value == "UNKNOWN":
            return "UNKNOWN"
        return "CONDITION" if value == ("BULLISH" if direction == "UP" else "BEARISH") else "COMPARISON"
    if context == "FLOW_DEPTH_CONFIRMATION_FOR_LEVEL_EVENTS_ONLY":
        value = states["FLOW_DEPTH_ALIGNMENT"]
        if value in {"UNKNOWN", "NEUTRAL_OR_UNKNOWN"}:
            return "UNKNOWN"
        return "CONDITION" if value == ("BULLISH" if direction == "UP" else "BEARISH") else "COMPARISON"
    if context == "LIQUIDITY_FRAGILITY_FOR_LEVEL_EVENTS_ONLY":
        value = states["LIQUIDITY_FRAGILITY"]
        if value == "UNKNOWN":
            return "UNKNOWN"
        return "CONDITION" if value == "FRAGILE" else "COMPARISON"
    raise KeyError(context)


def normalized_support(report: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key not in {"implementation", "support_receipt"}}


def protocol_payload() -> dict[str, Any]:
    return {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_PROTOCOL_V1_0",
        "status": "FROZEN_BEFORE_DEVELOPMENT_OUTCOME_VALUE_ACCESS",
        "primary_endpoint": "XAUUSD_FWD_15M_SIGNED_DISPLACEMENT",
        "secondary_horizons_minutes": list(SECONDARY_HORIZONS),
        "development_boundary": ["2021-11-08", "2024-12-13"],
        "sessions_separate": list(SESSIONS),
        "outcome": {
            "anchor": "close of complete XAUUSD one-minute bar ending at decision_at",
            "endpoint": "close of complete XAUUSD one-minute bar ending at decision_at+horizon",
            "complete_path_required": True,
            "horizons_minutes": list(HORIZONS),
            "scale": "integer 1e-8 USD per troy ounce",
            "states": {"UP": ">+0.01", "DOWN": "<-0.01", "FLAT": "inclusive [-0.01,+0.01]", "UNKNOWN": "any gate failure"},
            "flat_binary_policy": "exclude from binary hit rates; retain in continuous displacement",
            "unknown_policy": "retain identity; exclude only from the affected endpoint; never impute or drop a test from multiplicity",
            "availability": "complete unique IC Markets MT5 XAUUSD 1m records with available_at <= close_time",
            "source_opening": "one sequential source stream opening; matching rows parsed twice in memory for independent arithmetic",
            "gc_consistency": "authoritative continuous-matching uncrossed two-sided bucket states at decision_at and +15m; 0.1 USD GC tick",
        },
        "stage_1": {
            "tests_per_session": 6,
            "null": 0.50,
            "effect": "sign-normalized favorable hit rate minus 0.50",
            "minimum_hit_rate": 0.56,
            "bootstrap_lower_hit_rate": ">0.50",
            "bootstrap_lower_median_signed_displacement": ">0",
        },
        "stage_2": {
            "registered_per_session": 30,
            "evaluate": "only frozen SUPPORT_ELIGIBLE tests; SUPPORT_FAIL tests retain null p-values",
            "effect": "condition favorable hit rate minus comparison favorable hit rate",
            "minimum_condition_hit_rate": 0.56,
            "minimum_lift_percentage_points": 10.0,
            "bootstrap_lower_lift": ">0",
            "bootstrap_lower_median_difference": ">0",
        },
        "uncertainty": {
            "bootstrap": {"unit": "selected_month_week_id", "blocks": 38, "resamples": BOOTSTRAP_REPETITIONS, "quantiles": [0.025, 0.975], "method": QUANTILE_METHOD, "minimum_finite": 19_000},
            "randomization": {"unit": "session_date", "repetitions": RANDOMIZATION_REPETITIONS, "two_sided": True, "rule": "all binary event outcomes on a date flip together"},
            "seed": "uint64 from first 16 hex SHA256(contract_version|session|stage|test_id|method)",
        },
        "multiplicity": {
            "primary": "Benjamini-Hochberg separately by session and stage across all outcome-blind support-eligible tests",
            "q_threshold": BH_Q,
            "secondary": "Holm across 5m, 30m, 60m within each test; descriptive only",
        },
        "directional_symmetry": "both UP-prior and DOWN-prior subgroup effects must be favorable; one-sided pooled effects cannot advance",
        "annual_stability": {
            "required_years": [2022, 2023, 2024],
            "stage1_year_support": "at least 8 assigned events",
            "stage2_year_support": "at least 5 distinct condition dates",
            "gate": "favorable effect in every supported required year and all three required years supported",
            "year_2021": "descriptive only",
        },
        "block_stability": {
            "segments": [[1, 10], [11, 20], [21, 29], [30, 38]],
            "stage1_segment_support": {"events": 20, "distinct_dates": 13, "up_events": 8, "down_events": 8},
            "stage2_segment_support": {"condition_events": 13, "comparison_events": 18, "condition_dates": 8, "comparison_dates": 10, "condition_up_dates": 3, "condition_down_dates": 3, "comparison_up_dates": 4, "comparison_down_dates": 4},
            "gate": "at least three supported segments, favorable effect in at least three, and no supported segment effect below -5 percentage points",
        },
        "first_event_sensitivity": "earliest event per session_date and event_family; effect must be favorable and at least 50% of the complete canonical-event effect",
        "cross_venue": "not failed unless >=20 known GC observations and the 95% block-bootstrap upper confidence bound for median sign-normalized GC displacement is below zero",
        "candidate_cap_per_session": 2,
        "ranking": ["lowest BH q-value", "highest lower confidence bound on favorable hit-rate lift", "highest minimum bullish/bearish distinct-date support", "largest favorable effect", "largest distinct-date support", "lexicographically smallest test_id"],
        "prohibited": ["retuning", "inversion", "repair", "selective filtering", "2025 or 2026 access", "execution optimization", "trades", "PnL", "R multiples", "account returns"],
        "outcome_values_accessed": False,
        "year_2025_or_2026_values_accessed": False,
    }


def _verify_outer_v2r1(v2r1: Path) -> dict[str, Any]:
    verdict = load_json(v2r1 / "v2r1_verdict.json")
    manifest = load_json(v2r1 / "v2r1_manifest.json")
    final = load_json(v2r1 / "v2r1_final_seal.json")
    status = "PASS_GC_SESSION_TRIGGER_EDGE_V2R1_TECHNICAL_CERTIFICATION"
    if verdict.get("status") != status or manifest.get("status") != status or final.get("status") != status:
        raise ValueError("V2-R1 status chain failed")
    if not receipt_valid(verdict, "verdict_receipt") or not receipt_valid(manifest, "manifest_receipt") or not receipt_valid(final, "final_seal_receipt"):
        raise ValueError("V2-R1 receipt chain failed")
    if final["verdict_sha256"] != sha256_file(v2r1 / "v2r1_verdict.json") or final["manifest_sha256"] != sha256_file(v2r1 / "v2r1_manifest.json"):
        raise ValueError("V2-R1 final hashes failed")
    if int(verdict.get("total_session_commits", 0)) != 374 or not bool(verdict.get("formal_pass")):
        raise ValueError("V2-R1 population gate failed")
    return {"verdict": verdict, "manifest": manifest, "final": final}


def _event_identity(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_id": str(event["event_id"]),
        "session_date": str(event["session_date"]),
        "session_code": str(event["session_code"]),
        "selected_month_week_id": str(event["selected_month_week_id"]),
        "event_family": str(event["event_family"]),
        "directional_prior": str(event["directional_prior"]),
        "decision_at_utc": str(event["decision_at_utc"]),
        "decision_id": str(event["decision_id"]),
        "quality_state": str(event["quality_state"]),
        "lineage_hash": str(event["lineage_hash"]),
        "context_states_hash": canonical_hash(json.loads(str(event["context_states_json"]))),
        "context_signatures_hash": canonical_hash(json.loads(str(event["context_signatures_json"]))),
    }


def prepare(v2r1: Path, xau: Path, output: Path) -> None:
    for path in (PROTOCOL_PATH, POPULATION_PATH, TEST_REGISTRY_PATH, FREEZE_PATH):
        if path.exists():
            raise FileExistsError(path)
    if output.exists():
        raise FileExistsError(output)
    if not CONTRACT_PATH.exists() or not xau.exists():
        raise FileNotFoundError((CONTRACT_PATH, xau))
    m1_manifest = load_json(M1_MANIFEST_PATH)
    m1_verdict = load_json(M1_VERDICT_PATH)
    m1_final = load_json(M1_FINAL_SEAL_PATH)
    m1_status = "PASS_MILESTONE_1_CONTRACT_FROZEN_CONDITIONAL_M2_READINESS"
    if any(record.get("status") != m1_status for record in (m1_manifest, m1_verdict, m1_final)):
        raise ValueError("Milestone-1 predecessor status failed")
    if not receipt_valid(m1_manifest, "manifest_receipt") or not receipt_valid(m1_verdict, "verdict_receipt") or not receipt_valid(m1_final, "final_seal_receipt"):
        raise ValueError("Milestone-1 predecessor receipts failed")
    if m1_final["manifest_sha256"] != sha256_file(M1_MANIFEST_PATH) or m1_final["verdict_sha256"] != sha256_file(M1_VERDICT_PATH):
        raise ValueError("Milestone-1 final hashes failed")
    m1_artifacts = {Path(str(item["path"])).name: item for item in m1_manifest["artifacts"]}
    for path in (M1_CONTRACT_PATH, TAXONOMY_PATH, OUTCOMES_PATH, FEATURES_PATH, STATISTICS_PATH):
        if sha256_file(path) != str(m1_artifacts[path.name]["sha256"]):
            raise ValueError(f"Milestone-1 registry changed: {path}")
    chain = _verify_outer_v2r1(v2r1)
    inner_manifest = load_json(v2r1 / "manifest.json")
    inner_verdict = load_json(v2r1 / "verdict.json")
    inner_seal = load_json(v2r1 / "final_seal.json")
    if inner_verdict.get("status") != "PASS_GC_SESSION_TRIGGER_EDGE_V2_TECHNICAL_CERTIFICATION":
        raise ValueError("Inner V2-R1 technical verdict failed")
    if inner_seal.get("manifest_sha256") != sha256_file(v2r1 / "manifest.json") or inner_seal.get("verdict_sha256") != sha256_file(v2r1 / "verdict.json"):
        raise ValueError("Inner V2-R1 seal hashes failed")

    artifacts = {Path(str(item["path"])).name: item for item in inner_manifest["artifacts"]}
    required_names = (
        "primary_events.parquet", "reference_events.parquet", "primary_support_counts.json", "reference_support_counts.json",
        "primary_london_one_second_features.parquet", "reference_london_one_second_features.parquet",
        "primary_new_york_one_second_features.parquet", "reference_new_york_one_second_features.parquet",
    )
    source_bindings: dict[str, Any] = {}
    for name in required_names:
        path = v2r1 / name
        expected = str(artifacts[name]["sha256"])
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"V2-R1 source changed: {name}")
        source_bindings[name] = {"path": str(path), "bytes": path.stat().st_size, "sha256": actual}
    if source_bindings["primary_events.parquet"]["sha256"] != source_bindings["reference_events.parquet"]["sha256"]:
        raise ValueError("Independent event payloads differ")

    primary_support = load_json(v2r1 / "primary_support_counts.json")
    reference_support = load_json(v2r1 / "reference_support_counts.json")
    if normalized_support(primary_support) != normalized_support(reference_support):
        raise ValueError("Independent support reports differ")
    if primary_support.get("stage1_tests") != 12 or primary_support.get("stage1_support_eligible") != 12:
        raise ValueError("Stage-1 support gate changed")
    if primary_support.get("stage2_tests") != 60 or primary_support.get("stage2_support_eligible") != 26:
        raise ValueError("Stage-2 support gate changed")

    event_table = pq.read_table(v2r1 / "primary_events.parquet")
    events = event_table.to_pylist()
    if len(events) != 4_950 or len({str(item["event_id"]) for item in events}) != 4_950:
        raise ValueError("Event identity population changed")
    row_registry = load_json(ROW_REGISTRY_PATH)
    available_rows = [item for item in row_registry["rows"] if item["availability_disposition"] == "EXPECTED_AVAILABLE"]
    unavailable_rows = [item for item in row_registry["rows"] if item["availability_disposition"] == "UNAVAILABLE_DOCUMENTED"]
    if len(available_rows) != 374 or len(unavailable_rows) != 2:
        raise ValueError("Session population changed")
    available_keys = {(str(item["session_date"]), str(item["session_code"])) for item in available_rows}
    if any((str(item["session_date"]), str(item["session_code"])) not in available_keys for item in events):
        raise ValueError("Event outside available session population")
    if any(not ("2021-11-08" <= str(item["session_date"]) <= "2024-12-13") for item in events):
        raise ValueError("Event outside development boundary")
    identities = [_event_identity(item) for item in events]
    identities.sort(key=lambda item: item["event_id"])
    eligible = [item for item in events if item["quality_state"] == "ELIGIBLE"]
    unavailable = [item for item in events if item["quality_state"] != "ELIGIBLE"]
    if len(eligible) != 4_930 or len(unavailable) != 20:
        raise ValueError("Technical event disposition changed")

    stage1_support = {str(item["test_id"]): item for item in primary_support["stage1"]}
    stage2_support = {str(item["test_id"]): item for item in primary_support["stage2"]}
    tests: list[dict[str, Any]] = []
    for session in SESSIONS:
        for family in EVENT_FAMILIES:
            test_id = f"S1:{session}:{family}"
            assigned = sorted(str(item["event_id"]) for item in eligible if item["session_code"] == session and item["event_family"] == family)
            support = stage1_support[test_id]
            if len(assigned) != int(support["counts"]["event_instances"]):
                raise ValueError(f"Stage-1 support assignment mismatch: {test_id}")
            tests.append({
                "test_id": test_id, "stage": 1, "session": session, "event_family": family, "context": None,
                "support_status": str(support["support_status"]), "support_counts": support["counts"],
                "assigned_event_count": len(assigned), "assigned_event_ids_hash": canonical_hash(assigned),
                "bootstrap_seed_uint64": seed_for(session, 1, test_id, "SELECTED_MONTH_WEEK_BLOCK_BOOTSTRAP_15M"),
                "randomization_seed_uint64": seed_for(session, 1, test_id, "DATE_CLUSTER_SIGN_FLIP_15M"),
                "secondary_randomization_seeds": {str(h): seed_for(session, 1, test_id, f"DATE_CLUSTER_SIGN_FLIP_{h}M") for h in SECONDARY_HORIZONS},
                "gc_bootstrap_seed_uint64": seed_for(session, 1, test_id, "GC_MEDIAN_BLOCK_BOOTSTRAP_15M"),
            })
        for family in EVENT_FAMILIES:
            base_events = [item for item in eligible if item["session_code"] == session and item["event_family"] == family]
            for context in contexts_for_family(family):
                test_id = f"S2:{session}:{family}:{context}"
                groups: dict[str, list[str]] = {"CONDITION": [], "COMPARISON": [], "UNKNOWN": []}
                for item in base_events:
                    groups[alignment_state(item, context)].append(str(item["event_id"]))
                groups = {key: sorted(value) for key, value in groups.items()}
                support = stage2_support[test_id]
                if (
                    len(groups["CONDITION"]) != int(support["condition_counts"]["event_instances"])
                    or len(groups["COMPARISON"]) != int(support["comparison_counts"]["event_instances"])
                    or len(groups["UNKNOWN"]) != int(support["unknown_context_events"])
                ):
                    raise ValueError(f"Stage-2 support assignment mismatch: {test_id}")
                tests.append({
                    "test_id": test_id, "stage": 2, "session": session, "event_family": family, "context": context,
                    "support_status": str(support["support_status"]),
                    "condition_counts": support["condition_counts"], "comparison_counts": support["comparison_counts"],
                    "unknown_context_events": int(support["unknown_context_events"]),
                    "condition_event_count": len(groups["CONDITION"]), "comparison_event_count": len(groups["COMPARISON"]), "unknown_event_count": len(groups["UNKNOWN"]),
                    "condition_event_ids_hash": canonical_hash(groups["CONDITION"]), "comparison_event_ids_hash": canonical_hash(groups["COMPARISON"]), "unknown_event_ids_hash": canonical_hash(groups["UNKNOWN"]),
                    "bootstrap_seed_uint64": seed_for(session, 2, test_id, "SELECTED_MONTH_WEEK_BLOCK_BOOTSTRAP_15M"),
                    "randomization_seed_uint64": seed_for(session, 2, test_id, "DATE_CLUSTER_SIGN_FLIP_15M"),
                    "secondary_randomization_seeds": {str(h): seed_for(session, 2, test_id, f"DATE_CLUSTER_SIGN_FLIP_{h}M") for h in SECONDARY_HORIZONS},
                    "gc_bootstrap_seed_uint64": seed_for(session, 2, test_id, "GC_MEDIAN_BLOCK_BOOTSTRAP_15M"),
                })
    tests.sort(key=lambda item: (int(item["stage"]), str(item["session"]), str(item["test_id"])))
    if len(tests) != 72 or sum(item["support_status"] == "SUPPORT_ELIGIBLE" for item in tests if item["stage"] == 1) != 12 or sum(item["support_status"] == "SUPPORT_ELIGIBLE" for item in tests if item["stage"] == 2) != 26:
        raise ValueError("Exact test registry gate failed")

    decision_targets: dict[str, dict[str, Any]] = {}
    for event in eligible:
        decision = parse_time(str(event["decision_at_utc"]))
        key = f"{event['session_date']}|{event['session_code']}|{iso_z(decision)}"
        decision_targets.setdefault(key, {
            "session_date": str(event["session_date"]), "session_code": str(event["session_code"]), "decision_at_utc": iso_z(decision),
            "anchor_open_utc": iso_z(decision - timedelta(minutes=1)),
            "forward_open_start_utc": iso_z(decision), "forward_open_end_exclusive_utc": iso_z(decision + timedelta(minutes=60)),
        })

    protocol = protocol_payload()
    protocol["frozen_at_utc"] = utc_now()
    protocol["protocol_receipt"] = None
    protocol["protocol_receipt"] = canonical_hash({**protocol, "protocol_receipt": None})
    write_json_exclusive(PROTOCOL_PATH, protocol)

    population = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_POPULATION_V1_0",
        "status": "SEALED_EXACT_DEVELOPMENT_POPULATION_BEFORE_OUTCOME_ACCESS",
        "sealed_at_utc": utc_now(),
        "sessions": [{key: item[key] for key in ("row_id", "session_date", "session_code", "selected_month_week_id", "availability_disposition", "session_open_utc", "trigger_scan_start_inclusive_utc", "trigger_scan_end_exclusive_utc", "coverage_end_exclusive_utc")} for item in row_registry["rows"]],
        "available_session_count": 374,
        "documented_unavailable_session_count": 2,
        "event_identities": identities,
        "event_rows": len(events), "eligible_event_rows": len(eligible), "technical_unavailable_event_rows": len(unavailable),
        "eligible_event_ids_hash": canonical_hash(sorted(str(item["event_id"]) for item in eligible)),
        "technical_unavailable_event_ids_hash": canonical_hash(sorted(str(item["event_id"]) for item in unavailable)),
        "unique_decision_targets": [decision_targets[key] for key in sorted(decision_targets)],
        "unique_decision_target_count": len(decision_targets),
        "outcome_values_accessed": False, "year_2025_or_2026_values_accessed": False,
        "population_receipt": None,
    }
    population["population_receipt"] = canonical_hash({**population, "population_receipt": None})
    write_json_exclusive(POPULATION_PATH, population)

    test_registry = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_TEST_REGISTRY_V1_0",
        "status": "SEALED_COMPLETE_SUPPORT_CLASSIFIED_TEST_REGISTRY_BEFORE_OUTCOME_ACCESS",
        "sealed_at_utc": utc_now(), "tests": tests,
        "counts": {"total": 72, "stage1_total": 12, "stage1_support_eligible": 12, "stage2_total": 60, "stage2_support_eligible": 26, "stage2_support_fail": 34},
        "normalized_support_payload_hash": canonical_hash(normalized_support(primary_support)),
        "outcome_values_accessed": False, "year_2025_or_2026_values_accessed": False,
        "registry_receipt": None,
    }
    test_registry["registry_receipt"] = canonical_hash({**test_registry, "registry_receipt": None})
    write_json_exclusive(TEST_REGISTRY_PATH, test_registry)

    xau_sha = sha256_file(xau)
    expected_xau_sha = "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e"
    if xau_sha != expected_xau_sha:
        raise ValueError("Sealed XAUUSD source hash changed")
    predecessor_files = (M1_CONTRACT_PATH, TAXONOMY_PATH, OUTCOMES_PATH, FEATURES_PATH, STATISTICS_PATH, ROW_REGISTRY_PATH, M1_MANIFEST_PATH, M1_VERDICT_PATH, M1_FINAL_SEAL_PATH)
    freeze = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_FREEZE_V1_0",
        "status": "SEALED_BEFORE_DEVELOPMENT_OUTCOME_VALUE_ACCESS",
        "sealed_at_utc": utc_now(),
        "contract": {"path": str(CONTRACT_PATH), "sha256": sha256_file(CONTRACT_PATH), "bytes": CONTRACT_PATH.stat().st_size},
        "implementation": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(Path(__file__).resolve()), "bytes": Path(__file__).stat().st_size},
        "tests": {"path": str(TEST_PATH), "sha256": sha256_file(TEST_PATH), "bytes": TEST_PATH.stat().st_size},
        "protocol": {"path": str(PROTOCOL_PATH), "sha256": sha256_file(PROTOCOL_PATH)},
        "population": {"path": str(POPULATION_PATH), "sha256": sha256_file(POPULATION_PATH)},
        "test_registry": {"path": str(TEST_REGISTRY_PATH), "sha256": sha256_file(TEST_REGISTRY_PATH)},
        "predecessor_files": {path.name: {"path": str(path), "sha256": sha256_file(path)} for path in predecessor_files},
        "v2r1": {"path": str(v2r1), "outer_final_seal_receipt": chain["final"]["final_seal_receipt"], "outer_manifest_sha256": sha256_file(v2r1 / "v2r1_manifest.json"), "outer_final_seal_sha256": sha256_file(v2r1 / "v2r1_final_seal.json")},
        "technical_sources": source_bindings,
        "xau_source": {"path": str(xau), "sha256": xau_sha, "bytes": xau.stat().st_size},
        "outcome_values_accessed_before_freeze": False, "year_2025_or_2026_values_accessed": False,
        "freeze_receipt": None,
    }
    freeze["freeze_receipt"] = canonical_hash({**freeze, "freeze_receipt": None})
    write_json_exclusive(FREEZE_PATH, freeze)

    output.mkdir(parents=True)
    preflight = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_PREFLIGHT_V1_0",
        "status": "PASS_M3_PRE_OUTCOME_FREEZE_AND_READINESS",
        "completed_at_utc": utc_now(),
        "counts": test_registry["counts"] | {"available_sessions": 374, "event_rows": 4_950, "eligible_event_rows": 4_930, "unique_decision_targets": len(decision_targets)},
        "bindings": {"freeze_sha256": sha256_file(FREEZE_PATH), "population_sha256": sha256_file(POPULATION_PATH), "test_registry_sha256": sha256_file(TEST_REGISTRY_PATH), "protocol_sha256": sha256_file(PROTOCOL_PATH)},
        "outcome_values_accessed": False, "year_2025_or_2026_values_accessed": False,
        "preflight_receipt": None,
    }
    preflight["preflight_receipt"] = canonical_hash({**preflight, "preflight_receipt": None})
    write_json_exclusive(output / "preflight.json", preflight)
    print(json.dumps({"status": preflight["status"], "counts": preflight["counts"], "outcomes": False}, sort_keys=True))


def verify_control(v2r1: Path, xau: Path, output: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    freeze = load_json(FREEZE_PATH)
    protocol = load_json(PROTOCOL_PATH)
    population = load_json(POPULATION_PATH)
    registry = load_json(TEST_REGISTRY_PATH)
    if freeze.get("status") != "SEALED_BEFORE_DEVELOPMENT_OUTCOME_VALUE_ACCESS":
        raise ValueError("M3 freeze missing")
    for record, field in ((freeze, "freeze_receipt"), (protocol, "protocol_receipt"), (population, "population_receipt"), (registry, "registry_receipt")):
        if not receipt_valid(record, field):
            raise ValueError(f"Invalid M3 receipt: {field}")
    bindings = {
        CONTRACT_PATH: freeze["contract"]["sha256"],
        Path(__file__).resolve(): freeze["implementation"]["sha256"],
        TEST_PATH: freeze["tests"]["sha256"],
        PROTOCOL_PATH: freeze["protocol"]["sha256"],
        POPULATION_PATH: freeze["population"]["sha256"],
        TEST_REGISTRY_PATH: freeze["test_registry"]["sha256"],
    }
    for name, item in freeze["predecessor_files"].items():
        del name
        bindings[Path(item["path"])] = item["sha256"]
    for name, item in freeze["technical_sources"].items():
        del name
        bindings[Path(item["path"])] = item["sha256"]
    bindings[xau] = freeze["xau_source"]["sha256"]
    bindings[v2r1 / "v2r1_manifest.json"] = freeze["v2r1"]["outer_manifest_sha256"]
    bindings[v2r1 / "v2r1_final_seal.json"] = freeze["v2r1"]["outer_final_seal_sha256"]
    for path, expected in bindings.items():
        if not path.exists() or sha256_file(path) != expected:
            raise ValueError(f"Frozen binding changed: {path}")
    if len(population["sessions"]) != 376 or population["available_session_count"] != 374 or population["eligible_event_rows"] != 4_930:
        raise ValueError("M3 population counts changed")
    counts = registry["counts"]
    if counts != {"total": 72, "stage1_total": 12, "stage1_support_eligible": 12, "stage2_total": 60, "stage2_support_eligible": 26, "stage2_support_fail": 34}:
        raise ValueError("M3 test counts changed")
    preflight = load_json(output / "preflight.json")
    if preflight.get("status") != "PASS_M3_PRE_OUTCOME_FREEZE_AND_READINESS" or not receipt_valid(preflight, "preflight_receipt"):
        raise ValueError("M3 preflight changed")
    return freeze, population, registry


def verify_record_hash(record: Mapping[str, Any]) -> bool:
    expected = record.get("record_hash")
    if not isinstance(expected, str):
        return False
    unhashed = deepcopy(record)
    unhashed.pop("record_hash", None)
    return canonical_hash(unhashed) == expected


def decimal_to_scaled(value: Any) -> int:
    decimal = Decimal(str(value))
    scaled = decimal * Decimal(XAU_SCALE)
    integral = scaled.to_integral_value(rounding=ROUND_HALF_UP)
    if scaled != integral:
        raise ValueError(f"XAUUSD value exceeds frozen 1e-8 scale: {value}")
    return int(integral)


def displacement_state(value: int | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value > FLAT_THRESHOLD_SCALED:
        return "UP"
    if value < -FLAT_THRESHOLD_SCALED:
        return "DOWN"
    return "FLAT"


def _selected_price_bars(
    xau: Path,
    target_opens: set[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    primary: dict[str, dict[str, Any]] = {}
    reference: dict[str, dict[str, Any]] = {}
    invalid: dict[str, list[str]] = defaultdict(list)
    metadata_rows = selected_rows = 0
    selected_line_numbers: list[int] = []
    holdout_metadata_seen = False
    with gzip.open(xau, "rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            metadata_rows += 1
            if HOLDOUT_RE.search(raw):
                holdout_metadata_seen = True
                raise ValueError("2025/2026 timestamp found in sealed development source")
            timeframe = TIMEFRAME_RE.search(raw)
            instrument = INSTRUMENT_RE.search(raw)
            opened_match = OPEN_RE.search(raw)
            if timeframe is None or instrument is None or opened_match is None:
                continue
            if timeframe.group(1) != b"1m" or instrument.group(1) != b"XAUUSD":
                continue
            opened = iso_z(parse_time(opened_match.group(1).decode("ascii")))
            if opened not in target_opens:
                continue
            selected_rows += 1
            selected_line_numbers.append(line_number)
            if opened in primary or invalid.get(opened):
                primary.pop(opened, None)
                reference.pop(opened, None)
                invalid[opened].append("DUPLICATE_TIMESTAMP")
                continue
            try:
                p_record = json.loads(raw)
                r_record = json.loads(raw, parse_float=Decimal)
                if not isinstance(p_record, dict) or not isinstance(r_record, dict) or not verify_record_hash(p_record):
                    raise ValueError("RECORD_HASH_OR_TYPE")
                if p_record.get("record_type") != "PRICE_BAR" or p_record.get("provider_code") != "IC_MARKETS_MT5":
                    raise ValueError("PROVIDER_OR_RECORD_TYPE")
                if p_record.get("instrument_code") != "XAUUSD" or p_record.get("timeframe") != "1m":
                    raise ValueError("INSTRUMENT_OR_TIMEFRAME")
                open_dt = parse_time(str(p_record["open_time"]))
                close_dt = parse_time(str(p_record["close_time"]))
                available_dt = parse_time(str(p_record["available_at"]))
                if iso_z(open_dt) != opened or close_dt != open_dt + timedelta(minutes=1) or available_dt > close_dt:
                    raise ValueError("TIMESTAMP_OR_AVAILABILITY")
                if p_record.get("complete") is not True or int(p_record.get("missing_source_minutes", -1)) != 0:
                    raise ValueError("INCOMPLETE")
                p_close = decimal_to_scaled(p_record["ohlc"]["close"])
                r_close = decimal_to_scaled(r_record["ohlc"]["close"])
                if p_close != r_close:
                    raise ValueError("INDEPENDENT_ARITHMETIC_INPUT_MISMATCH")
                lineage = {
                    "record_id": str(p_record["record_id"]),
                    "record_hash": str(p_record["record_hash"]),
                    "source_hash": str(p_record["source"]["source_hash"]),
                    "open_time": iso_z(open_dt),
                    "close_time": iso_z(close_dt),
                    "source_line_sha256": hashlib.sha256(raw).hexdigest(),
                }
                primary[opened] = {"close_scaled": p_close, "lineage": lineage}
                reference[opened] = {"close_scaled": r_close, "lineage": deepcopy(lineage)}
            except Exception as exc:  # a frozen missing-data disposition, never a repair
                primary.pop(opened, None)
                reference.pop(opened, None)
                invalid[opened].append(type(exc).__name__ + ":" + str(exc))
    if primary != reference:
        raise ValueError("Independent selected XAUUSD bar payloads differ")
    diagnostics = {
        "source_stream_open_count": 1,
        "metadata_rows_seen": metadata_rows,
        "target_timestamp_count": len(target_opens),
        "selected_source_rows": selected_rows,
        "valid_unique_target_timestamps": len(primary),
        "missing_target_timestamps": len(target_opens.difference(primary).difference(invalid)),
        "invalid_target_timestamps": len(invalid),
        "invalid_reason_counts": dict(sorted(Counter(reason for reasons in invalid.values() for reason in reasons).items())),
        "selected_line_numbers_hash": canonical_hash(selected_line_numbers),
        "holdout_metadata_seen": holdout_metadata_seen,
    }
    return primary, reference, diagnostics


def _gc_target_states(feature_path: Path, target_end_ns: set[int]) -> tuple[dict[int, int | None], dict[str, Any]]:
    output: dict[int, int | None] = {}
    matched = valid = 0
    columns = ("bucket_end_ns", "market_state", "state_available", "book_two_sided", "book_locked", "book_crossed", "midpoint_fixed_1e9")
    parquet = pq.ParquetFile(feature_path)
    for group_index in range(parquet.metadata.num_row_groups):
        values = parquet.read_row_group(group_index, columns=list(columns)).to_pydict()
        for index, end_ns in enumerate(values["bucket_end_ns"]):
            stamp = int(end_ns)
            if stamp not in target_end_ns:
                continue
            if stamp in output:
                raise ValueError(f"Duplicate GC bucket end in {feature_path}: {stamp}")
            matched += 1
            eligible = (
                values["market_state"][index] == "CONTINUOUS_MATCHING"
                and bool(values["state_available"][index])
                and bool(values["book_two_sided"][index])
                and not bool(values["book_locked"][index])
                and not bool(values["book_crossed"][index])
                and values["midpoint_fixed_1e9"][index] is not None
            )
            midpoint = int(values["midpoint_fixed_1e9"][index]) if eligible else None
            output[stamp] = midpoint
            valid += int(midpoint is not None)
    return output, {"target_bucket_ends": len(target_end_ns), "matched_bucket_ends": matched, "valid_bucket_states": valid, "unknown_bucket_states": matched - valid}


def _calculate_event_outcome(
    event: Mapping[str, Any],
    bars: Mapping[str, Mapping[str, Any]],
    gc_states: Mapping[int, int | None],
    xau_source_sha: str,
) -> dict[str, Any]:
    decision = parse_time(str(event["decision_at_utc"]))
    sign = 1 if event["directional_prior"] == "UP" else -1
    anchor_key = iso_z(decision - timedelta(minutes=1))
    forward_keys = [iso_z(decision + timedelta(minutes=minute)) for minute in range(60)]
    anchor = bars.get(anchor_key)
    forward = [bars.get(key) for key in forward_keys]
    row: dict[str, Any] = {
        "event_id": str(event["event_id"]),
        "session_date": str(event["session_date"]),
        "session_code": str(event["session_code"]),
        "selected_month_week_id": str(event["selected_month_week_id"]),
        "event_family": str(event["event_family"]),
        "directional_prior": str(event["directional_prior"]),
        "decision_at_utc": iso_z(decision),
        "event_lineage_hash": str(event["lineage_hash"]),
        "context_states_json": str(event["context_states_json"]),
    }
    first_state = "UNKNOWN"
    lineage_by_horizon: dict[str, Any] = {}
    for horizon in HORIZONS:
        selected = forward[:horizon]
        complete = anchor is not None and all(item is not None for item in selected)
        if not complete:
            quality = "UNKNOWN_MISSING_INVALID_OR_NONUNIQUE_PATH"
            displacement = signed = None
            state = "UNKNOWN"
            maximum = minimum = elapsed_max = elapsed_min = None
            reversal = "UNKNOWN"
            lineage_by_horizon[str(horizon)] = "UNKNOWN"
        else:
            assert anchor is not None
            path = [item for item in selected if item is not None]
            displacements = [int(item["close_scaled"]) - int(anchor["close_scaled"]) for item in path]
            displacement = displacements[-1]
            signed = sign * displacement
            state = displacement_state(displacement)
            quality = "VALID_COMPLETE_PATH"
            maximum, minimum = max(displacements), min(displacements)
            elapsed_max, elapsed_min = displacements.index(maximum) + 1, displacements.index(minimum) + 1
            first = displacement_state(displacements[0])
            if horizon == 5:
                first_state = first
            reversal = (
                "UNKNOWN" if first not in {"UP", "DOWN"} or state == "UNKNOWN"
                else "TRUE" if (first == "UP" and state == "DOWN") or (first == "DOWN" and state == "UP")
                else "FALSE"
            )
            lineage_by_horizon[str(horizon)] = canonical_hash([anchor["lineage"], *[item["lineage"] for item in path]])
        row[f"xau_quality_{horizon}m"] = quality
        row[f"xau_displacement_scaled_1e8_{horizon}m"] = displacement
        row[f"xau_signed_displacement_scaled_1e8_{horizon}m"] = signed
        row[f"xau_state_{horizon}m"] = state
        row[f"xau_max_up_scaled_1e8_{horizon}m"] = maximum
        row[f"xau_max_down_scaled_1e8_{horizon}m"] = minimum
        row[f"xau_elapsed_to_max_up_minutes_{horizon}m"] = elapsed_max
        row[f"xau_elapsed_to_max_down_minutes_{horizon}m"] = elapsed_min
        row[f"xau_first_move_reversed_{horizon}m"] = reversal
    if first_state == "UNKNOWN" and anchor is not None and forward[0] is not None:
        first_state = displacement_state(int(forward[0]["close_scaled"]) - int(anchor["close_scaled"]))
    row["xau_first_completed_minute_state"] = first_state

    anchor_ns = int(decision.timestamp() * 1_000_000_000)
    end_ns = int((decision + timedelta(minutes=15)).timestamp() * 1_000_000_000)
    gc_anchor, gc_end = gc_states.get(anchor_ns), gc_states.get(end_ns)
    if gc_anchor is None or gc_end is None:
        row["gc_quality_15m"] = "UNKNOWN_TECHNICAL_STATE"
        row["gc_signed_displacement_fixed_1e9_15m"] = None
        row["gc_signed_ticks_15m"] = "UNKNOWN"
    else:
        gc_signed = sign * (int(gc_end) - int(gc_anchor))
        row["gc_quality_15m"] = "VALID"
        row["gc_signed_displacement_fixed_1e9_15m"] = gc_signed
        ticks = (Decimal(gc_signed) / Decimal(GC_TICK_FIXED_1E9)).normalize()
        row["gc_signed_ticks_15m"] = format(ticks, "f")
    row["outcome_lineage_hash"] = canonical_hash({
        "event_id": row["event_id"], "event_lineage_hash": row["event_lineage_hash"],
        "xau_source_sha256": xau_source_sha, "xau_horizon_lineage": lineage_by_horizon,
        "gc_anchor_bucket_end_ns": anchor_ns, "gc_endpoint_bucket_end_ns": end_ns,
    })
    return row


def write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(path)
    table = pa.Table.from_pylist(list(rows), schema=OUTCOME_SCHEMA)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(temporary, table, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6", row_group_size=65_536)
    temporary.replace(path)


def open_outcomes(v2r1: Path, xau: Path, output: Path) -> None:
    freeze, population, _ = verify_control(v2r1, xau, output)
    if (output / "outcome_opening.json").exists():
        raise FileExistsError("Development outcomes were already opened")
    events = pq.read_table(v2r1 / "primary_events.parquet").to_pylist()
    eligible = [item for item in events if item["quality_state"] == "ELIGIBLE"]
    eligible_ids = sorted(str(item["event_id"]) for item in eligible)
    if canonical_hash(eligible_ids) != population["eligible_event_ids_hash"] or len(eligible) != 4_930:
        raise ValueError("Eligible event rows changed before outcome opening")
    target_opens: set[str] = set()
    for target in population["unique_decision_targets"]:
        anchor = parse_time(str(target["anchor_open_utc"]))
        forward = parse_time(str(target["forward_open_start_utc"]))
        target_opens.add(iso_z(anchor))
        target_opens.update(iso_z(forward + timedelta(minutes=minute)) for minute in range(60))
    primary_bars, reference_bars, xau_diagnostics = _selected_price_bars(xau, target_opens)

    gc_primary_by_session: dict[str, dict[int, int | None]] = {}
    gc_reference_by_session: dict[str, dict[int, int | None]] = {}
    gc_diagnostics: dict[str, Any] = {}
    for session in SESSIONS:
        targets: set[int] = set()
        for event in eligible:
            if event["session_code"] != session:
                continue
            decision = parse_time(str(event["decision_at_utc"]))
            targets.add(int(decision.timestamp() * 1_000_000_000))
            targets.add(int((decision + timedelta(minutes=15)).timestamp() * 1_000_000_000))
        primary_path = Path(freeze["technical_sources"][f"primary_{session.lower()}_one_second_features.parquet"]["path"])
        reference_path = Path(freeze["technical_sources"][f"reference_{session.lower()}_one_second_features.parquet"]["path"])
        p_values, p_diag = _gc_target_states(primary_path, targets)
        r_values, r_diag = _gc_target_states(reference_path, targets)
        if p_values != r_values or p_diag != r_diag:
            raise ValueError(f"Independent GC consistency extraction differs: {session}")
        gc_primary_by_session[session] = p_values
        gc_reference_by_session[session] = r_values
        gc_diagnostics[session] = p_diag

    primary_rows = [_calculate_event_outcome(item, primary_bars, gc_primary_by_session[str(item["session_code"])], freeze["xau_source"]["sha256"]) for item in eligible]
    reference_rows = [_calculate_event_outcome(item, reference_bars, gc_reference_by_session[str(item["session_code"])], freeze["xau_source"]["sha256"]) for item in eligible]
    primary_rows.sort(key=lambda item: item["event_id"])
    reference_rows.sort(key=lambda item: item["event_id"])
    if canonical_hash(primary_rows) != canonical_hash(reference_rows):
        raise ValueError("Independent outcome arithmetic or join differs")
    paths = {
        "primary": output / "primary_joined_event_outcomes.parquet",
        "reference": output / "reference_joined_event_outcomes.parquet",
    }
    write_parquet_exclusive(paths["primary"], primary_rows)
    write_parquet_exclusive(paths["reference"], reference_rows)
    if paths["primary"].read_bytes() != paths["reference"].read_bytes():
        raise ValueError("Independent outcome Parquet payloads differ")
    quality_counts = {
        str(horizon): dict(sorted(Counter(str(row[f"xau_quality_{horizon}m"]) for row in primary_rows).items()))
        for horizon in HORIZONS
    }
    state_counts = {
        str(horizon): dict(sorted(Counter(str(row[f"xau_state_{horizon}m"]) for row in primary_rows).items()))
        for horizon in HORIZONS
    }
    opening = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_OUTCOME_OPENING_V1_0",
        "status": "PASS_SINGLE_CONTROLLED_DEVELOPMENT_OUTCOME_OPEN_AND_JOIN",
        "completed_at_utc": utc_now(),
        "source_open_count": 1,
        "eligible_event_rows_joined": len(primary_rows),
        "technical_unavailable_event_rows_not_joined": 20,
        "primary_reference_exact": True,
        "joined_payload_hash": canonical_hash(primary_rows),
        "quality_counts": quality_counts,
        "state_counts": state_counts,
        "xau_source_diagnostics": xau_diagnostics,
        "gc_source_diagnostics": gc_diagnostics,
        "files": {name: {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size} for name, path in paths.items()},
        "development_outcomes_opened_once": True,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "opening_receipt": None,
    }
    opening["opening_receipt"] = canonical_hash({**opening, "opening_receipt": None})
    write_json_exclusive(output / "outcome_opening.json", opening)
    print(json.dumps({"status": opening["status"], "event_rows": len(primary_rows), "quality_15m": quality_counts["15"], "outcomes_opened": True}, sort_keys=True))


def _signed_value(row: Mapping[str, Any], horizon: int) -> int | None:
    value = row.get(f"xau_signed_displacement_scaled_1e8_{horizon}m")
    return None if value is None else int(value)


def _binary_summary(rows: Sequence[Mapping[str, Any]], horizon: int) -> dict[str, Any]:
    values = [_signed_value(row, horizon) for row in rows]
    known = [value for value in values if value is not None]
    successes = sum(value > FLAT_THRESHOLD_SCALED for value in known)
    failures = sum(value < -FLAT_THRESHOLD_SCALED for value in known)
    flats = len(known) - successes - failures
    binary = successes + failures
    return {
        "assigned_events": len(rows), "known_continuous": len(known), "unknown": len(rows) - len(known),
        "favorable": successes, "unfavorable": failures, "flat": flats, "binary": binary,
        "hit_rate": None if binary == 0 else successes / binary,
        "median_signed_scaled_1e8": None if not known else float(np.median(np.asarray(known, dtype=np.int64))),
    }


def _effect_fraction(condition: Sequence[Mapping[str, Any]], comparison: Sequence[Mapping[str, Any]] | None, horizon: int) -> float | None:
    condition_summary = _binary_summary(condition, horizon)
    if condition_summary["hit_rate"] is None:
        return None
    if comparison is None:
        return float(condition_summary["hit_rate"]) - 0.5
    comparison_summary = _binary_summary(comparison, horizon)
    if comparison_summary["hit_rate"] is None:
        return None
    return float(condition_summary["hit_rate"]) - float(comparison_summary["hit_rate"])


def _median_difference_scaled(condition: Sequence[Mapping[str, Any]], comparison: Sequence[Mapping[str, Any]] | None, horizon: int) -> float | None:
    first = _binary_summary(condition, horizon)["median_signed_scaled_1e8"]
    if first is None:
        return None
    if comparison is None:
        return float(first)
    second = _binary_summary(comparison, horizon)["median_signed_scaled_1e8"]
    return None if second is None else float(first) - float(second)


def _ordered_blocks(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    first_dates: dict[str, str] = {}
    for row in rows:
        block = str(row["selected_month_week_id"])
        session_date = str(row["session_date"])
        first_dates[block] = min(first_dates.get(block, session_date), session_date)
    blocks = sorted(first_dates, key=lambda block: (first_dates[block], block))
    if len(blocks) != 38:
        raise ValueError(f"Expected 38 development month-week blocks, got {len(blocks)}")
    return blocks


def _bootstrap_metrics(
    condition: Sequence[Mapping[str, Any]],
    comparison: Sequence[Mapping[str, Any]] | None,
    blocks: Sequence[str],
    seed: int,
    implementation: str,
    horizon: int = 15,
    repetitions: int = BOOTSTRAP_REPETITIONS,
) -> dict[str, Any]:
    condition_by_block: list[np.ndarray] = []
    comparison_by_block: list[np.ndarray] = []
    for block in blocks:
        condition_by_block.append(np.asarray([value for row in condition if str(row["selected_month_week_id"]) == block for value in [_signed_value(row, horizon)] if value is not None], dtype=np.int64))
        if comparison is not None:
            comparison_by_block.append(np.asarray([value for row in comparison if str(row["selected_month_week_id"]) == block for value in [_signed_value(row, horizon)] if value is not None], dtype=np.int64))
    c_n = np.asarray([int((np.abs(values) > FLAT_THRESHOLD_SCALED).sum()) for values in condition_by_block], dtype=np.int64)
    c_s = np.asarray([int((values > FLAT_THRESHOLD_SCALED).sum()) for values in condition_by_block], dtype=np.int64)
    if comparison is not None:
        p_n = np.asarray([int((np.abs(values) > FLAT_THRESHOLD_SCALED).sum()) for values in comparison_by_block], dtype=np.int64)
        p_s = np.asarray([int((values > FLAT_THRESHOLD_SCALED).sum()) for values in comparison_by_block], dtype=np.int64)
    else:
        p_n = p_s = np.zeros(len(blocks), dtype=np.int64)
    rng = np.random.Generator(np.random.PCG64(seed))
    effects = np.full(repetitions, np.nan, dtype=np.float64)
    medians = np.full(repetitions, np.nan, dtype=np.float64)
    for start in range(0, repetitions, 500):
        size = min(500, repetitions - start)
        draws = rng.integers(0, len(blocks), size=(size, len(blocks)), endpoint=False)
        c_total_n = c_n[draws].sum(axis=1)
        c_total_s = c_s[draws].sum(axis=1)
        if comparison is not None:
            p_total_n = p_n[draws].sum(axis=1)
            p_total_s = p_s[draws].sum(axis=1)
            valid = (c_total_n > 0) & (p_total_n > 0)
            effects[start : start + size][valid] = c_total_s[valid] / c_total_n[valid] - p_total_s[valid] / p_total_n[valid]
        else:
            valid = c_total_n > 0
            effects[start : start + size][valid] = c_total_s[valid] / c_total_n[valid]
        for local_index, selected in enumerate(draws):
            if implementation == "primary":
                c_parts = [condition_by_block[int(index)] for index in selected if len(condition_by_block[int(index)])]
                p_parts = [comparison_by_block[int(index)] for index in selected if comparison is not None and len(comparison_by_block[int(index)])]
            else:
                multiplicities = Counter(int(index) for index in selected)
                c_parts = [np.repeat(condition_by_block[index], count) for index, count in sorted(multiplicities.items()) if len(condition_by_block[index])]
                p_parts = [np.repeat(comparison_by_block[index], count) for index, count in sorted(multiplicities.items()) if comparison is not None and len(comparison_by_block[index])]
            if not c_parts:
                continue
            c_median = float(np.median(np.concatenate(c_parts)))
            if comparison is None:
                medians[start + local_index] = c_median
            elif p_parts:
                medians[start + local_index] = c_median - float(np.median(np.concatenate(p_parts)))
    finite_effect = effects[np.isfinite(effects)]
    finite_median = medians[np.isfinite(medians)]
    effect_ci = [None, None]
    median_ci = [None, None]
    if len(finite_effect):
        effect_ci = [rounded(float(value)) for value in np.quantile(finite_effect, (0.025, 0.975), method=QUANTILE_METHOD)]
    if len(finite_median):
        median_ci = [rounded(float(value) / XAU_SCALE) for value in np.quantile(finite_median, (0.025, 0.975), method=QUANTILE_METHOD)]
    return {
        "finite_effect_replicates": len(finite_effect), "finite_median_replicates": len(finite_median),
        "effect_ci_fraction": effect_ci, "median_difference_ci_usd": median_ci,
        "effect_replicates_hash": canonical_hash([rounded(float(value)) for value in finite_effect]),
        "median_replicates_hash": canonical_hash([rounded(float(value)) for value in finite_median]),
    }


def _randomization_p_value(
    condition: Sequence[Mapping[str, Any]],
    comparison: Sequence[Mapping[str, Any]] | None,
    session_dates: Sequence[str],
    observed: float,
    seed: int,
    implementation: str,
    horizon: int = 15,
    repetitions: int = RANDOMIZATION_REPETITIONS,
) -> dict[str, Any]:
    condition_by_date = {date: _binary_summary([row for row in condition if row["session_date"] == date], horizon) for date in session_dates}
    comparison_by_date = {date: _binary_summary([row for row in comparison if row["session_date"] == date], horizon) for date in session_dates} if comparison is not None else {}
    c_n = np.asarray([condition_by_date[date]["binary"] for date in session_dates], dtype=np.int64)
    c_s = np.asarray([condition_by_date[date]["favorable"] for date in session_dates], dtype=np.int64)
    if comparison is not None:
        p_n = np.asarray([comparison_by_date[date]["binary"] for date in session_dates], dtype=np.int64)
        p_s = np.asarray([comparison_by_date[date]["favorable"] for date in session_dates], dtype=np.int64)
    else:
        p_n = p_s = np.zeros(len(session_dates), dtype=np.int64)
    rng = np.random.Generator(np.random.PCG64(seed))
    extreme = nonfinite = 0
    threshold = abs(observed) - 1e-15
    for start in range(0, repetitions, 1_000):
        size = min(1_000, repetitions - start)
        flips = rng.integers(0, 2, size=(size, len(session_dates)), endpoint=False, dtype=np.int8)
        if implementation == "primary":
            c_success = (c_s[None, :] + flips * (c_n - 2 * c_s)[None, :]).sum(axis=1)
            if comparison is not None:
                p_success = (p_s[None, :] + flips * (p_n - 2 * p_s)[None, :]).sum(axis=1)
        else:
            c_success = np.zeros(size, dtype=np.int64)
            p_success = np.zeros(size, dtype=np.int64)
            for index in range(len(session_dates)):
                c_success += np.where(flips[:, index] == 1, c_n[index] - c_s[index], c_s[index])
                if comparison is not None:
                    p_success += np.where(flips[:, index] == 1, p_n[index] - p_s[index], p_s[index])
        c_total = int(c_n.sum())
        if comparison is None:
            valid = np.full(size, c_total > 0, dtype=bool)
            effects = c_success / c_total - 0.5 if c_total else np.full(size, np.nan)
        else:
            p_total = int(p_n.sum())
            valid = np.full(size, c_total > 0 and p_total > 0, dtype=bool)
            effects = c_success / c_total - p_success / p_total if c_total and p_total else np.full(size, np.nan)
        extreme += int((valid & (np.abs(effects) >= threshold)).sum())
        nonfinite += int((~valid).sum())
    return {"extreme_count": extreme, "nonfinite_count": nonfinite, "p_value": rounded((1 + extreme) / (1 + repetitions), 12)}


def _bh_adjust(results: list[dict[str, Any]]) -> None:
    eligible = [item for item in results if item.get("p_value") is not None]
    eligible.sort(key=lambda item: (float(item["p_value"]), str(item["test_id"])))
    running = 1.0
    count = len(eligible)
    for index in range(count - 1, -1, -1):
        rank = index + 1
        running = min(running, min(1.0, float(eligible[index]["p_value"]) * count / rank))
        eligible[index]["bh_q_value"] = rounded(running, 12)


def _holm_adjust(items: list[dict[str, Any]]) -> None:
    ordered = sorted(items, key=lambda item: (float(item["p_value"]), int(item["horizon_minutes"])))
    running = 0.0
    total = len(ordered)
    for index, item in enumerate(ordered):
        running = max(running, min(1.0, (total - index) * float(item["p_value"])))
        item["holm_adjusted_p_value"] = rounded(running, 12)


def _first_family_events(base_rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    first: dict[str, Mapping[str, Any]] = {}
    for row in base_rows:
        key = str(row["session_date"])
        candidate = (str(row["decision_at_utc"]), str(row["event_id"]))
        current = first.get(key)
        if current is None or candidate < (str(current["decision_at_utc"]), str(current["event_id"])):
            first[key] = row
    return [first[key] for key in sorted(first)]


def _split_test_rows(base_rows: Sequence[Mapping[str, Any]], test: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]] | None, int]:
    if int(test["stage"]) == 1:
        return list(base_rows), None, 0
    condition: list[Mapping[str, Any]] = []
    comparison: list[Mapping[str, Any]] = []
    unknown = 0
    for row in base_rows:
        state = alignment_state(row, str(test["context"]))
        if state == "CONDITION":
            condition.append(row)
        elif state == "COMPARISON":
            comparison.append(row)
        else:
            unknown += 1
    return condition, comparison, unknown


def _symmetry(condition: Sequence[Mapping[str, Any]], comparison: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    passed = True
    for prior in ("UP", "DOWN"):
        cond = [row for row in condition if row["directional_prior"] == prior]
        comp = None if comparison is None else [row for row in comparison if row["directional_prior"] == prior]
        effect = _effect_fraction(cond, comp, 15)
        prior_pass = effect is not None and effect > 0
        passed &= prior_pass
        result[prior] = {"effect_pp": None if effect is None else rounded(100 * effect), "pass": prior_pass, "condition": _binary_summary(cond, 15), "comparison": None if comp is None else _binary_summary(comp, 15)}
    return {"subgroups": result, "both_directional_priors_favorable": passed}


def _annual_stability(condition: Sequence[Mapping[str, Any]], comparison: Sequence[Mapping[str, Any]] | None, stage: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    required_pass = True
    supported_required = 0
    for year in (2021, 2022, 2023, 2024):
        cond = [row for row in condition if str(row["session_date"]).startswith(str(year))]
        comp = None if comparison is None else [row for row in comparison if str(row["session_date"]).startswith(str(year))]
        support = len(cond) >= 8 if stage == 1 else len({str(row["session_date"]) for row in cond}) >= 5
        effect = _effect_fraction(cond, comp, 15) if support else None
        favorable = effect is not None and effect > 0
        if year in (2022, 2023, 2024):
            supported_required += int(support)
            required_pass &= support and favorable
        rows.append({"year": year, "support": support, "condition_events": len(cond), "condition_dates": len({str(row['session_date']) for row in cond}), "comparison_events": None if comp is None else len(comp), "effect_pp": None if effect is None else rounded(100 * effect), "favorable": favorable, "required": year in (2022, 2023, 2024)})
    return {"years": rows, "supported_required_years": supported_required, "gate_pass": required_pass and supported_required == 3}


def _block_stability(condition: Sequence[Mapping[str, Any]], comparison: Sequence[Mapping[str, Any]] | None, stage: int, blocks: Sequence[str]) -> dict[str, Any]:
    segments = ((0, 10), (10, 20), (20, 29), (29, 38))
    rows: list[dict[str, Any]] = []
    for start, end in segments:
        selected = set(blocks[start:end])
        cond = [row for row in condition if row["selected_month_week_id"] in selected]
        comp = None if comparison is None else [row for row in comparison if row["selected_month_week_id"] in selected]
        if stage == 1:
            support = (
                len(cond) >= 20
                and len({str(row["session_date"]) for row in cond}) >= 13
                and sum(row["directional_prior"] == "UP" for row in cond) >= 8
                and sum(row["directional_prior"] == "DOWN" for row in cond) >= 8
            )
        else:
            assert comp is not None
            support = (
                len(cond) >= 13 and len(comp) >= 18
                and len({str(row["session_date"]) for row in cond}) >= 8
                and len({str(row["session_date"]) for row in comp}) >= 10
                and len({str(row["session_date"]) for row in cond if row["directional_prior"] == "UP"}) >= 3
                and len({str(row["session_date"]) for row in cond if row["directional_prior"] == "DOWN"}) >= 3
                and len({str(row["session_date"]) for row in comp if row["directional_prior"] == "UP"}) >= 4
                and len({str(row["session_date"]) for row in comp if row["directional_prior"] == "DOWN"}) >= 4
            )
        effect = _effect_fraction(cond, comp, 15) if support else None
        rows.append({"blocks": [start + 1, end], "support": support, "condition_events": len(cond), "comparison_events": None if comp is None else len(comp), "effect_pp": None if effect is None else rounded(100 * effect), "favorable": effect is not None and effect > 0, "not_below_minus_5pp": effect is not None and 100 * effect >= -5.0})
    supported = [item for item in rows if item["support"]]
    favorable_count = sum(item["favorable"] for item in supported)
    gate = len(supported) >= 3 and favorable_count >= 3 and all(item["not_below_minus_5pp"] for item in supported)
    return {"segments": rows, "supported_segments": len(supported), "favorable_supported_segments": favorable_count, "gate_pass": gate}


def _first_event_sensitivity(base_rows: Sequence[Mapping[str, Any]], test: Mapping[str, Any], full_effect: float) -> dict[str, Any]:
    first = _first_family_events(base_rows)
    condition, comparison, unknown = _split_test_rows(first, test)
    effect = _effect_fraction(condition, comparison, 15)
    passed = effect is not None and effect > 0 and full_effect > 0 and effect >= 0.5 * full_effect
    return {"first_family_events": len(first), "condition_events": len(condition), "comparison_events": None if comparison is None else len(comparison), "unknown_context_events": unknown, "effect_pp": None if effect is None else rounded(100 * effect), "minimum_required_pp": rounded(50 * full_effect), "gate_pass": passed}


def _gc_bootstrap(
    condition: Sequence[Mapping[str, Any]],
    blocks: Sequence[str],
    seed: int,
    implementation: str,
    repetitions: int = BOOTSTRAP_REPETITIONS,
) -> dict[str, Any]:
    by_block = [np.asarray([int(row["gc_signed_displacement_fixed_1e9_15m"]) for row in condition if row["selected_month_week_id"] == block and row["gc_signed_displacement_fixed_1e9_15m"] is not None], dtype=np.int64) for block in blocks]
    known = sum(len(values) for values in by_block)
    if known < 20:
        return {"known_observations": known, "status": "UNKNOWN_INSUFFICIENT_KNOWN_GC", "bootstrap_finite": 0, "median_ticks_ci": [None, None], "supported_opposite": False, "gate_pass": True}
    rng = np.random.Generator(np.random.PCG64(seed))
    medians = np.full(repetitions, np.nan, dtype=np.float64)
    for index in range(repetitions):
        selected = rng.integers(0, len(blocks), size=len(blocks), endpoint=False)
        if implementation == "primary":
            parts = [by_block[int(item)] for item in selected if len(by_block[int(item)])]
        else:
            counts = Counter(int(item) for item in selected)
            parts = [np.repeat(by_block[item], count) for item, count in sorted(counts.items()) if len(by_block[item])]
        if parts:
            medians[index] = float(np.median(np.concatenate(parts)))
    finite = medians[np.isfinite(medians)]
    lower, upper = np.quantile(finite, (0.025, 0.975), method=QUANTILE_METHOD)
    supported_opposite = float(upper) < 0
    return {"known_observations": known, "status": "EVALUATED", "bootstrap_finite": len(finite), "median_ticks_ci": [rounded(float(lower) / GC_TICK_FIXED_1E9), rounded(float(upper) / GC_TICK_FIXED_1E9)], "replicates_hash": canonical_hash([rounded(float(value)) for value in finite]), "supported_opposite": supported_opposite, "gate_pass": not supported_opposite}


def _support_fail_result(test: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "test_id": test["test_id"], "stage": int(test["stage"]), "session": test["session"], "event_family": test["event_family"], "context": test.get("context"),
        "support_status": "SUPPORT_FAIL", "verdict": "SUPPORT_FAIL", "p_value": None, "bh_q_value": None,
        "outcome_conditioned_calculation_performed": False,
    }


def _evaluate_test(
    session_rows: Sequence[Mapping[str, Any]],
    test: Mapping[str, Any],
    implementation: str,
    blocks: Sequence[str],
    session_dates: Sequence[str],
) -> dict[str, Any]:
    if test["support_status"] != "SUPPORT_ELIGIBLE":
        return _support_fail_result(test)
    base_rows = [row for row in session_rows if row["event_family"] == test["event_family"]]
    condition, comparison, unknown_context = _split_test_rows(base_rows, test)
    if int(test["stage"]) == 1:
        if canonical_hash(sorted(str(row["event_id"]) for row in condition)) != test["assigned_event_ids_hash"]:
            raise ValueError(f"Stage-1 assignment changed: {test['test_id']}")
    else:
        if canonical_hash(sorted(str(row["event_id"]) for row in condition)) != test["condition_event_ids_hash"] or canonical_hash(sorted(str(row["event_id"]) for row in comparison or [])) != test["comparison_event_ids_hash"]:
            raise ValueError(f"Stage-2 assignment changed: {test['test_id']}")
    effect = _effect_fraction(condition, comparison, 15)
    if effect is None:
        raise ValueError(f"Support-eligible test has no binary effect: {test['test_id']}")
    median_difference = _median_difference_scaled(condition, comparison, 15)
    bootstrap = _bootstrap_metrics(condition, comparison, blocks, int(test["bootstrap_seed_uint64"]), implementation)
    randomization = _randomization_p_value(condition, comparison, session_dates, effect, int(test["randomization_seed_uint64"]), implementation)
    secondary: list[dict[str, Any]] = []
    for horizon in SECONDARY_HORIZONS:
        horizon_effect = _effect_fraction(condition, comparison, horizon)
        if horizon_effect is None:
            secondary.append({"horizon_minutes": horizon, "effect_pp": None, "p_value": None, "holm_adjusted_p_value": None, "condition": _binary_summary(condition, horizon), "comparison": None if comparison is None else _binary_summary(comparison, horizon)})
            continue
        p_value = _randomization_p_value(condition, comparison, session_dates, horizon_effect, int(test["secondary_randomization_seeds"][str(horizon)]), implementation, horizon=horizon)
        secondary.append({"horizon_minutes": horizon, "effect_pp": rounded(100 * horizon_effect), "p_value": p_value["p_value"], "holm_adjusted_p_value": None, "condition": _binary_summary(condition, horizon), "comparison": None if comparison is None else _binary_summary(comparison, horizon)})
    _holm_adjust([item for item in secondary if item["p_value"] is not None])
    symmetry = _symmetry(condition, comparison)
    annual = _annual_stability(condition, comparison, int(test["stage"]))
    block = _block_stability(condition, comparison, int(test["stage"]), blocks)
    first = _first_event_sensitivity(base_rows, test, effect)
    gc = _gc_bootstrap(condition, blocks, int(test["gc_bootstrap_seed_uint64"]), implementation)
    condition_summary = _binary_summary(condition, 15)
    comparison_summary = None if comparison is None else _binary_summary(comparison, 15)
    minimum_direction_dates = min(
        len({str(row["session_date"]) for row in condition if row["directional_prior"] == "UP"}),
        len({str(row["session_date"]) for row in condition if row["directional_prior"] == "DOWN"}),
    )
    result = {
        "test_id": test["test_id"], "stage": int(test["stage"]), "session": test["session"], "event_family": test["event_family"], "context": test.get("context"),
        "support_status": "SUPPORT_ELIGIBLE", "support_counts": test.get("support_counts"), "condition_support_counts": test.get("condition_counts"), "comparison_support_counts": test.get("comparison_counts"),
        "unknown_context_events": unknown_context,
        "condition": condition_summary, "comparison": comparison_summary,
        "effect_pp": rounded(100 * effect),
        "median_difference_usd": None if median_difference is None else rounded(median_difference / XAU_SCALE),
        "bootstrap": bootstrap,
        "randomization": randomization,
        "p_value": randomization["p_value"], "bh_q_value": None,
        "secondary_consistency": secondary,
        "directional_symmetry": symmetry, "annual_stability": annual, "block_stability": block, "first_event_sensitivity": first, "gc_consistency": gc,
        "minimum_bullish_bearish_condition_distinct_dates": minimum_direction_dates,
        "condition_distinct_dates": len({str(row["session_date"]) for row in condition}),
        "outcome_conditioned_calculation_performed": True,
        "advancement_checks": None, "verdict": "PENDING_MULTIPLICITY",
    }
    return result


def _finalize_results(results: list[dict[str, Any]], stage: int) -> None:
    for session in SESSIONS:
        _bh_adjust([item for item in results if item["session"] == session and item["support_status"] == "SUPPORT_ELIGIBLE"])
    for result in results:
        if result["support_status"] != "SUPPORT_ELIGIBLE":
            continue
        bootstrap = result["bootstrap"]
        lower_effect = bootstrap["effect_ci_fraction"][0]
        lower_median = bootstrap["median_difference_ci_usd"][0]
        condition_hit = result["condition"]["hit_rate"]
        if stage == 1:
            effect_gate = condition_hit is not None and float(condition_hit) >= 0.56
            lower_gate = lower_effect is not None and float(lower_effect) > 0.50
        else:
            effect_gate = condition_hit is not None and float(condition_hit) >= 0.56 and result["effect_pp"] is not None and float(result["effect_pp"]) >= 10.0
            lower_gate = lower_effect is not None and float(lower_effect) > 0
        checks = {
            "frozen_effect_threshold": effect_gate,
            "bootstrap_effect_lower_bound": lower_gate,
            "bootstrap_median_lower_bound_gt_zero": lower_median is not None and float(lower_median) > 0,
            "bootstrap_finite_effect_gte_19000": int(bootstrap["finite_effect_replicates"]) >= 19_000,
            "bootstrap_finite_median_gte_19000": int(bootstrap["finite_median_replicates"]) >= 19_000,
            "bh_q_lte_0_05": result["bh_q_value"] is not None and float(result["bh_q_value"]) <= BH_Q,
            "directional_symmetry": bool(result["directional_symmetry"]["both_directional_priors_favorable"]),
            "annual_stability": bool(result["annual_stability"]["gate_pass"]),
            "block_stability": bool(result["block_stability"]["gate_pass"]),
            "first_event_sensitivity": bool(result["first_event_sensitivity"]["gate_pass"]),
            "gc_not_statistically_opposite": bool(result["gc_consistency"]["gate_pass"]),
        }
        result["advancement_checks"] = checks
        result["verdict"] = "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED" if all(checks.values()) else "REJECT"


def evaluate_stage(v2r1: Path, xau: Path, output: Path, implementation: str, stage: int) -> None:
    _, population, registry = verify_control(v2r1, xau, output)
    opening = load_json(output / "outcome_opening.json")
    if opening.get("status") != "PASS_SINGLE_CONTROLLED_DEVELOPMENT_OUTCOME_OPEN_AND_JOIN" or not receipt_valid(opening, "opening_receipt"):
        raise ValueError("M3 outcome opening is not sealed")
    if stage == 2:
        stage1 = load_json(output / "stage1_seal.json")
        if stage1.get("status") != "PASS_M3_STAGE_1_INDEPENDENT_REPRODUCTION_SEALED" or not receipt_valid(stage1, "seal_receipt"):
            raise ValueError("Stage 1 must be sealed before Stage 2")
    joined_path = output / f"{implementation}_joined_event_outcomes.parquet"
    if sha256_file(joined_path) != opening["files"][implementation]["sha256"]:
        raise ValueError("Joined event outcome payload changed")
    rows = pq.read_table(joined_path).to_pylist()
    if len(rows) != 4_930 or canonical_hash(sorted(str(row["event_id"]) for row in rows)) != population["eligible_event_ids_hash"]:
        raise ValueError("Joined event population changed")
    blocks = _ordered_blocks(rows)
    tests = [item for item in registry["tests"] if int(item["stage"]) == stage]
    results: list[dict[str, Any]] = []
    for session in SESSIONS:
        session_rows = [row for row in rows if row["session_code"] == session]
        dates = sorted({str(item["session_date"]) for item in population["sessions"] if item["session_code"] == session and item["availability_disposition"] == "EXPECTED_AVAILABLE"})
        if len(dates) != 187:
            raise ValueError(f"Expected 187 available {session} dates")
        for test in [item for item in tests if item["session"] == session]:
            results.append(_evaluate_test(session_rows, test, implementation, blocks, dates))
    results.sort(key=lambda item: (str(item["session"]), str(item["test_id"])))
    _finalize_results(results, stage)
    expected = 12 if stage == 1 else 60
    if len(results) != expected:
        raise ValueError("Complete stage registry was not recorded")
    summary = {
        session: {
            "registered": sum(item["session"] == session for item in results),
            "support_fail": sum(item["session"] == session and item["verdict"] == "SUPPORT_FAIL" for item in results),
            "rejected": sum(item["session"] == session and item["verdict"] == "REJECT" for item in results),
            "provisional_pass": sum(item["session"] == session and item["verdict"] == "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED" for item in results),
        }
        for session in SESSIONS
    }
    payload = {
        "stage": stage, "test_results": results, "summary": summary,
        "eligible_event_rows": 4_930, "outcome_joined_payload_hash": opening["joined_payload_hash"],
        "test_registry_sha256": sha256_file(TEST_REGISTRY_PATH), "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "year_2025_or_2026_values_accessed": False, "execution_trade_pnl_r_or_return_calculated": False,
    }
    record = {"version": f"GC_SESSION_TRIGGER_EDGE_V2_M3_STAGE_{stage}_RUN_V1_0", "implementation": implementation, "completed_at_utc": utc_now(), "payload": payload, "payload_hash": canonical_hash(payload)}
    write_json_exclusive(output / f"{implementation}_stage{stage}_results.json", record)
    print(json.dumps({"implementation": implementation, "stage": stage, "summary": summary, "payload_hash": record["payload_hash"]}, sort_keys=True))


def seal_stage1(v2r1: Path, xau: Path, output: Path) -> None:
    verify_control(v2r1, xau, output)
    records = {name: load_json(output / f"{name}_stage1_results.json") for name in ("primary", "reference")}
    if records["primary"]["payload_hash"] != records["reference"]["payload_hash"]:
        raise ValueError("Stage-1 independent reproduction failed")
    seal = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_STAGE_1_SEAL_V1_0", "status": "PASS_M3_STAGE_1_INDEPENDENT_REPRODUCTION_SEALED", "sealed_at_utc": utc_now(),
        "payload_hash": records["primary"]["payload_hash"], "summary": records["primary"]["payload"]["summary"],
        "files": {name: {"path": str(output / f"{name}_stage1_results.json"), "sha256": sha256_file(output / f"{name}_stage1_results.json")} for name in ("primary", "reference")},
        "stage_1_completed_before_stage_2": True, "independent_reproduction_exact": True, "year_2025_or_2026_values_accessed": False,
        "seal_receipt": None,
    }
    seal["seal_receipt"] = canonical_hash({**seal, "seal_receipt": None})
    write_json_exclusive(output / "stage1_seal.json", seal)
    print(json.dumps({"status": seal["status"], "summary": seal["summary"], "payload_hash": seal["payload_hash"]}, sort_keys=True))


def _ranking_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    lower = float(item["bootstrap"]["effect_ci_fraction"][0])
    lower_lift = lower - 0.50 if int(item["stage"]) == 1 else lower
    return (
        float(item["bh_q_value"]),
        -lower_lift,
        -int(item["minimum_bullish_bearish_condition_distinct_dates"]),
        -float(item["effect_pp"]),
        -int(item["condition_distinct_dates"]),
        str(item["test_id"]),
    )


def _verify_stage_files(output: Path, stage: int, expected_payload_hash: str) -> None:
    for implementation in ("primary", "reference"):
        path = output / f"{implementation}_stage{stage}_results.json"
        record = load_json(path)
        if record.get("payload_hash") != expected_payload_hash:
            raise ValueError(f"Stage {stage} payload changed: {implementation}")


def seal_final(v2r1: Path, xau: Path, output: Path) -> None:
    freeze, _, registry = verify_control(v2r1, xau, output)
    opening = load_json(output / "outcome_opening.json")
    stage1 = load_json(output / "stage1_seal.json")
    if stage1.get("status") != "PASS_M3_STAGE_1_INDEPENDENT_REPRODUCTION_SEALED" or not receipt_valid(stage1, "seal_receipt"):
        raise ValueError("Stage-1 seal failed")
    _verify_stage_files(output, 1, str(stage1["payload_hash"]))
    stage2_records = {name: load_json(output / f"{name}_stage2_results.json") for name in ("primary", "reference")}
    if stage2_records["primary"]["payload_hash"] != stage2_records["reference"]["payload_hash"]:
        raise ValueError("Stage-2 independent reproduction failed")
    stage1_results = load_json(output / "primary_stage1_results.json")["payload"]["test_results"]
    stage2_results = stage2_records["primary"]["payload"]["test_results"]
    all_results = [*stage1_results, *stage2_results]
    if len(all_results) != 72 or sum(item["verdict"] == "SUPPORT_FAIL" for item in all_results) != 34:
        raise ValueError("Complete 72-test result registry failed")
    if {str(item["test_id"]) for item in all_results} != {str(item["test_id"]) for item in registry["tests"]}:
        raise ValueError("Result and frozen test registries differ")

    shortlist: dict[str, list[dict[str, Any]]] = {}
    pass_not_shortlisted: dict[str, list[str]] = {}
    for session in SESSIONS:
        passing = [item for item in all_results if item["session"] == session and item["verdict"] == "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED"]
        passing.sort(key=_ranking_key)
        shortlist[session] = [
            {
                "rank": rank, "test_id": item["test_id"], "stage": item["stage"], "event_family": item["event_family"], "context": item.get("context"),
                "effect_pp": item["effect_pp"], "condition_hit_rate": rounded(item["condition"]["hit_rate"]),
                "bootstrap_effect_ci_fraction": item["bootstrap"]["effect_ci_fraction"], "bootstrap_median_difference_ci_usd": item["bootstrap"]["median_difference_ci_usd"],
                "p_value": item["p_value"], "bh_q_value": item["bh_q_value"], "condition_events": item["condition"]["assigned_events"], "condition_distinct_dates": item["condition_distinct_dates"],
                "label": "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED",
            }
            for rank, item in enumerate(passing[:2], start=1)
        ]
        pass_not_shortlisted[session] = [str(item["test_id"]) for item in passing[2:]]
    candidate_count = sum(len(items) for items in shortlist.values())
    status = "PASS_M3_DISCOVERY_WITH_PROVISIONAL_CANDIDATES" if candidate_count else "PASS_M3_DISCOVERY_ZERO_CANDIDATES"
    summary = {
        "registered_tests": 72,
        "support_fail": sum(item["verdict"] == "SUPPORT_FAIL" for item in all_results),
        "support_eligible_rejected": sum(item["verdict"] == "REJECT" for item in all_results),
        "development_pass_before_cap": sum(item["verdict"] == "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED" for item in all_results),
        "shortlisted_provisional_candidates": candidate_count,
        "passing_not_shortlisted_due_cap": sum(len(items) for items in pass_not_shortlisted.values()),
        "by_session_stage": {
            f"{session}_STAGE_{stage}": {
                "registered": sum(item["session"] == session and int(item["stage"]) == stage for item in all_results),
                "support_fail": sum(item["session"] == session and int(item["stage"]) == stage and item["verdict"] == "SUPPORT_FAIL" for item in all_results),
                "rejected": sum(item["session"] == session and int(item["stage"]) == stage and item["verdict"] == "REJECT" for item in all_results),
                "pass": sum(item["session"] == session and int(item["stage"]) == stage and item["verdict"] == "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED" for item in all_results),
            }
            for session in SESSIONS for stage in (1, 2)
        },
    }
    complete = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_COMPLETE_RESULTS_V1_0",
        "status": status, "summary": summary, "shortlist": shortlist, "pass_not_shortlisted_due_cap": pass_not_shortlisted,
        "results": all_results, "all_results_hash": canonical_hash(all_results),
        "stage1_payload_hash": stage1["payload_hash"], "stage2_payload_hash": stage2_records["primary"]["payload_hash"],
        "outcome_joined_payload_hash": opening["joined_payload_hash"],
        "year_2025_or_2026_values_accessed": False, "execution_trade_pnl_r_or_return_calculated": False,
    }
    complete_path = output / "complete_results.json"
    write_json_exclusive(complete_path, complete)
    verdict = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_VERDICT_V1_0", "status": status, "formal_milestone_pass": True, "completed_at_utc": utc_now(),
        "development_event_rows": 4_930, "registered_tests": 72, "summary": summary, "shortlist": shortlist, "pass_not_shortlisted_due_cap": pass_not_shortlisted,
        "research_interpretation": "Provisional development relationships were found; they are not validated trading edges." if candidate_count else "No frozen support-eligible relationship passed every development gate; no candidate advances.",
        "development_only": True, "out_of_sample_validation_credit": False,
        "year_2025_or_2026_values_accessed": False, "execution_trade_pnl_r_or_return_calculated": False, "data_acquired": False, "charge_incurred_usd": 0.0,
        "verdict_receipt": None,
    }
    verdict["verdict_receipt"] = canonical_hash({**verdict, "verdict_receipt": None})
    verdict_path = output / "verdict.json"
    write_json_exclusive(verdict_path, verdict)

    report_lines = [
        "# GC Session Trigger Edge Discovery V2 Milestone 3 Report", "", f"Formal status: `{status}`", "",
        "## Complete frozen search", "",
        "- Certified development sessions: `374`.", "- Eligible event rows: `4,930`.", "- Registered tests: `72` (12 Stage 1 and 60 Stage 2).",
        f"- Outcome-blind Stage-2 support failures retained: `{summary['support_fail']}`.", f"- Support-eligible rejections: `{summary['support_eligible_rejected']}`.",
        f"- Development passes before the two-per-session cap: `{summary['development_pass_before_cap']}`.", f"- Shortlisted provisional candidates: `{summary['shortlisted_provisional_candidates']}`.", "",
        "## Provisional shortlist", "",
    ]
    for session in SESSIONS:
        report_lines.extend([f"### {session.replace('_', ' ').title()}", ""])
        if not shortlist[session]:
            report_lines.append("No registered condition passed every frozen gate.")
        else:
            for item in shortlist[session]:
                report_lines.append(
                    f"- Rank {item['rank']}: `{item['test_id']}` — effect `{item['effect_pp']}` pp, "
                    f"hit rate `{item['condition_hit_rate']}`, BH q `{item['bh_q_value']}`, "
                    f"support `{item['condition_events']}` events across `{item['condition_distinct_dates']}` dates."
                )
        report_lines.append("")
    report_lines.extend([
        "## Scope boundary", "",
        "These are development-only conditional direction-frequency results. A provisional candidate is not a validated edge, trade, or expected-return claim.", "",
        "Calendar 2025 and 2026 remained locked. No execution, trade, PnL, R multiple, position size, or account return was calculated. Milestone 3 stops here.", "",
    ])
    report_path = output / "GC_SESSION_TRIGGER_EDGE_MILESTONE_3_REPORT.md"
    write_text_exclusive(report_path, "\n".join(report_lines))

    artifact_names = (
        "preflight.json", "outcome_opening.json", "primary_joined_event_outcomes.parquet", "reference_joined_event_outcomes.parquet",
        "primary_stage1_results.json", "reference_stage1_results.json", "stage1_seal.json",
        "primary_stage2_results.json", "reference_stage2_results.json", "complete_results.json", "verdict.json", "GC_SESSION_TRIGGER_EDGE_MILESTONE_3_REPORT.md",
    )
    artifacts = {name: {"path": str(output / name), "sha256": sha256_file(output / name), "bytes": (output / name).stat().st_size} for name in artifact_names}
    manifest = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_MANIFEST_V1_0", "status": status, "sealed_at_utc": utc_now(),
        "predecessors": {"v2r1_final_seal_receipt": freeze["v2r1"]["outer_final_seal_receipt"], "m3_freeze_receipt": freeze["freeze_receipt"], "outcome_opening_receipt": opening["opening_receipt"], "stage1_seal_receipt": stage1["seal_receipt"]},
        "artifacts": artifacts, "summary": summary, "shortlist": shortlist, "pass_not_shortlisted_due_cap": pass_not_shortlisted,
        "independent_reproduction": {"outcome_arithmetic_and_join": True, "stage1": True, "stage2": True, "stage2_payload_hash": stage2_records["primary"]["payload_hash"]},
        "complete_72_test_registry_recorded": True, "stage2_support_eligible_evaluated": 26, "stage2_support_fail_not_outcome_conditioned": 34,
        "candidate_repair_retune_inversion_or_filter": False, "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False, "data_acquired": False, "charge_incurred_usd": 0.0,
        "manifest_receipt": None,
    }
    manifest["manifest_receipt"] = canonical_hash({**manifest, "manifest_receipt": None})
    manifest_path = output / "manifest.json"
    write_json_exclusive(manifest_path, manifest)
    final = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_FINAL_SEAL_V1_0", "status": status, "sealed_at_utc": utc_now(),
        "manifest_sha256": sha256_file(manifest_path), "manifest_receipt": manifest["manifest_receipt"],
        "verdict_sha256": sha256_file(verdict_path), "verdict_receipt": verdict["verdict_receipt"],
        "complete_results_sha256": sha256_file(complete_path), "report_sha256": sha256_file(report_path),
        "final_seal_receipt": None,
    }
    final["final_seal_receipt"] = canonical_hash({**final, "final_seal_receipt": None})
    write_json_exclusive(output / "final_seal.json", final)
    print(json.dumps({"status": status, "summary": summary, "shortlist": shortlist, "final_seal_receipt": final["final_seal_receipt"]}, sort_keys=True))


def verify_final(v2r1: Path, xau: Path, output: Path) -> None:
    verify_control(v2r1, xau, output)
    opening = load_json(output / "outcome_opening.json")
    stage1 = load_json(output / "stage1_seal.json")
    manifest = load_json(output / "manifest.json")
    verdict = load_json(output / "verdict.json")
    final = load_json(output / "final_seal.json")
    for record, field in ((opening, "opening_receipt"), (stage1, "seal_receipt"), (manifest, "manifest_receipt"), (verdict, "verdict_receipt"), (final, "final_seal_receipt")):
        if not receipt_valid(record, field):
            raise ValueError(f"Final verification receipt failed: {field}")
    if final["manifest_sha256"] != sha256_file(output / "manifest.json") or final["verdict_sha256"] != sha256_file(output / "verdict.json") or final["complete_results_sha256"] != sha256_file(output / "complete_results.json") or final["report_sha256"] != sha256_file(output / "GC_SESSION_TRIGGER_EDGE_MILESTONE_3_REPORT.md"):
        raise ValueError("Final seal hashes failed")
    for name, item in manifest["artifacts"].items():
        if sha256_file(Path(item["path"])) != item["sha256"]:
            raise ValueError(f"Manifest artifact changed: {name}")
    if manifest["summary"] != verdict["summary"] or manifest["shortlist"] != verdict["shortlist"]:
        raise ValueError("Manifest/verdict result mismatch")
    if not manifest.get("complete_72_test_registry_recorded") or manifest.get("stage2_support_eligible_evaluated") != 26 or manifest.get("stage2_support_fail_not_outcome_conditioned") != 34:
        raise ValueError("Final test-completeness gate failed")
    print(json.dumps({"status": final["status"], "final_seal_receipt": final["final_seal_receipt"], "shortlisted_provisional_candidates": verdict["summary"]["shortlisted_provisional_candidates"], "year_2025_or_2026_values_accessed": False}, sort_keys=True))


def self_test() -> None:
    synthetic: list[dict[str, Any]] = []
    blocks = [f"B{index:02d}" for index in range(1, 5)]
    for index in range(24):
        signed = 2_000_000 if index % 3 else -2_000_000
        synthetic.append({
            "event_id": f"E{index:03d}", "session_date": f"2024-01-{1 + index // 2:02d}", "selected_month_week_id": blocks[index % 4],
            "directional_prior": "UP" if index % 2 else "DOWN", "xau_signed_displacement_scaled_1e8_15m": signed,
            "gc_signed_displacement_fixed_1e9_15m": 100_000_000, "decision_at_utc": f"2024-01-{1 + index // 2:02d}T08:{index % 2:02d}:00Z",
        })
    primary_boot = _bootstrap_metrics(synthetic[:12], synthetic[12:], blocks, 7, "primary", repetitions=200)
    reference_boot = _bootstrap_metrics(synthetic[:12], synthetic[12:], blocks, 7, "reference", repetitions=200)
    if primary_boot != reference_boot:
        raise AssertionError("Synthetic bootstrap reproduction failed")
    dates = sorted({str(row["session_date"]) for row in synthetic})
    effect = _effect_fraction(synthetic[:12], synthetic[12:], 15)
    if effect is None:
        raise AssertionError("Synthetic effect missing")
    primary_random = _randomization_p_value(synthetic[:12], synthetic[12:], dates, effect, 11, "primary", repetitions=1_000)
    reference_random = _randomization_p_value(synthetic[:12], synthetic[12:], dates, effect, 11, "reference", repetitions=1_000)
    if primary_random != reference_random:
        raise AssertionError("Synthetic randomization reproduction failed")
    if displacement_state(FLAT_THRESHOLD_SCALED) != "FLAT" or displacement_state(FLAT_THRESHOLD_SCALED + 1) != "UP" or displacement_state(-FLAT_THRESHOLD_SCALED - 1) != "DOWN":
        raise AssertionError("Frozen outcome threshold failed")
    bh = [{"test_id": "a", "p_value": 0.01}, {"test_id": "b", "p_value": 0.04}]
    _bh_adjust(bh)
    if bh[0]["bh_q_value"] != 0.02 or bh[1]["bh_q_value"] != 0.04:
        raise AssertionError("BH self-test failed")
    print(json.dumps({"status": "PASS_M3_SYNTHETIC_INDEPENDENT_REPRODUCTION", "outcome_values_accessed": False}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("self-test", "prepare", "open-outcomes", "primary-stage1", "reference-stage1", "seal-stage1", "primary-stage2", "reference-stage2", "seal-final", "verify"))
    parser.add_argument("--v2r1", type=Path, default=DEFAULT_V2R1)
    parser.add_argument("--xau", type=Path, default=DEFAULT_XAU)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.action == "self-test":
        self_test()
    elif args.action == "prepare":
        prepare(args.v2r1, args.xau, args.output)
    elif args.action == "open-outcomes":
        open_outcomes(args.v2r1, args.xau, args.output)
    elif args.action in {"primary-stage1", "reference-stage1", "primary-stage2", "reference-stage2"}:
        implementation = "primary" if args.action.startswith("primary") else "reference"
        stage = 1 if args.action.endswith("stage1") else 2
        evaluate_stage(args.v2r1, args.xau, args.output, implementation, stage)
    elif args.action == "seal-stage1":
        seal_stage1(args.v2r1, args.xau, args.output)
    elif args.action == "seal-final":
        seal_final(args.v2r1, args.xau, args.output)
    else:
        verify_final(args.v2r1, args.xau, args.output)


if __name__ == "__main__":
    main()
