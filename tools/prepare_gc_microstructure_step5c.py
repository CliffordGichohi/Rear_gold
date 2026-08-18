#!/usr/bin/env python3
"""Freeze the Step 5C protocol before any research market-value access.

This preparation stage reads only sealed manifests, registries, schemas, file
metadata, and predecessor verdicts. It does not open Parquet rows, case rows,
price bars, development outcomes, or any 2025/2026 value.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"

CONTRACT = MANIFESTS / "gc_microstructure_conditional_edge_discovery_contract_v01.json"
FEATURE_REGISTRY = MANIFESTS / "gc_microstructure_step_5a_feature_hypothesis_registry_v01.json"
BUDGET_AMENDMENT = MANIFESTS / "gc_microstructure_step_5b_budget_amendment_c_v01.json"
BUDGET_REGISTRY = MANIFESTS / "gc_microstructure_step_5b_budget_c_request_registry_v01.json"
BUDGET_FREEZE = MANIFESTS / "gc_microstructure_step_5b_budget_c_freeze_v01.json"
ACQUISITION = ARTIFACTS / "gc_microstructure_step_5b_budget_c_v01" / "acquisition_manifest.json"
STEP5B2_MANIFEST = ARTIFACTS / "gc_microstructure_step_5b2_v01" / "step5b2_final" / "manifest.json"
STEP5B2_VERDICT = ARTIFACTS / "gc_microstructure_step_5b2_v01" / "step5b2_final" / "verdict.json"
STEP4B3_PROTOCOL = MANIFESTS / "gc_microstructure_step_4b3_protocol_v01.json"
STEP4B3_MANIFEST = ARTIFACTS / "gc_microstructure_step_4b3_v01" / "manifest.json"
STEP4B3_VERDICT = ARTIFACTS / "gc_microstructure_step_4b3_v01" / "verdict.json"
CASE_MATRIX_MANIFEST = ARTIFACTS / "gold_session_behaviour_v3_case_matrix_v01" / "manifest.json"
CASE_SCHEMA = ROOT / "research_schemas" / "gold_session_behaviour_v3_case_matrix.schema.json"
CASEBOOK_MANIFEST = ARTIFACTS / "gold_casebook_v01" / "manifest.json"
CASEBOOK_ENGINE = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "session_behaviour_v3.py"
DISCOVERY_ENGINE = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "session_behaviour_v3_discovery.py"
CASEBOOK_HELPERS = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "casebook.py"
BASE_FEATURE_ENGINE = ROOT / "tools" / "build_gc_microstructure_features_step4a.py"

ROW_REGISTRY_OUT = MANIFESTS / "gc_microstructure_step_5c_row_registry_v01.json"
PROTOCOL_OUT = MANIFESTS / "gc_microstructure_step_5c_protocol_v01.json"
FREEZE_OUT = MANIFESTS / "gc_microstructure_step_5c_freeze_v01.json"

EXPECTED_FILES = {
    CONTRACT: "da9048f497c853ef3b1f2a4debe6c80f8c650217004bfe6df05e045751554fcb",
    FEATURE_REGISTRY: "4b207a1dec5aa78a904c86cf8c6a14bf0a517dd918f24c5270c254400c865f01",
    BUDGET_AMENDMENT: "60ae7fa1bdca50461ab2f1089040996f8f99ad6e7def1dbb9dc7ab181c30f246",
    BUDGET_REGISTRY: "d8dfe8a04e0f824c98ec4e88b6c75b7e56214616e56124b76bdbfe0b20b0dd99",
    BUDGET_FREEZE: "ddfe58d2a366410f649de89bc7081b0081d16717a7245fec83f5d2bfa9efa916",
    ACQUISITION: "b4e64d508790364dbd400da1478b139bb643d2b7afc9c97ff6691958365c5ccc",
    STEP5B2_MANIFEST: "3fedb586ce4f9621721575b748b82043f47a4f6630488c29e0b2f8e73b4c86f1",
    STEP5B2_VERDICT: "5f3bd13cc2336a50c09ecfcc44c7d63b226a4d212f9d08666d6a50e93e09a6cb",
    STEP4B3_PROTOCOL: "8a67158b943add18bdeaea5b8b87a8c41fd1427ef6aa45248a38eb03293539cd",
    STEP4B3_MANIFEST: "54ba09d63c6c791bfdcd2047112b15a431c686a12f6e1f7a82beae9e5a3e6249",
    STEP4B3_VERDICT: "fc2d5e4040f15d8edfb72935ec0f491000c58d8116baf763c19fe59588260c48",
    CASE_MATRIX_MANIFEST: "dddbe125d11afef2094b7843f5521b7bbfcc95178e3fa376b60af8bdd2efc3b5",
    CASE_SCHEMA: "33d47e452695e624f5ae10dc29ebbd99d05bd0c6f8096540cce69f9b521e92a7",
    CASEBOOK_MANIFEST: "38e4aadc43917a5b91d04d47ab18542d7514fe257cc030f959d34080865314d6",
    CASEBOOK_ENGINE: "33d53780a2db17f5cb8940bf3251797ddf273531f8b64ed330b7cb892c5115be",
    DISCOVERY_ENGINE: "921a6d02c71514438e46a81d22f0ea788b2bdfca88172e564d10b510f14e96dc",
    CASEBOOK_HELPERS: "fa4370052d4ffdc9ec144009373d427c13477a4b4bbfc31bf72eaeb737f381e3",
    BASE_FEATURE_ENGINE: "c5589914a1acae6a3a1e9079c302821477866bba3741317392c567bb590c2369",
}

FEATURE_SCHEMA_SHA256 = "dfaf74cdc55b37469966857fc1ed2279b3d18c98f90454ced65859cb32494232"
STEP5B2_STATUS = "PASS_STEP_5B2_SOURCE_INTEGRITY_RECERTIFICATION"
STEP5B2_MANIFEST_HASH = "ccbf10b2e23612d3de2e2d880cfcde2a569fbb3b419de421e8887c17cf81cc4f"
STEP4B3_STATUS = "PASS_MULTIDAY_FEATURE_ROBUSTNESS"
STEP4B3_MANIFEST_HASH = "6252b239c4962fd8dcf3bce1a712b416e67af8303bbea7cd40de2ab6a3522bbe"
CASE_MATRIX_HASH = "d6aad4b861d98899d6fdcc92ea53a20221434af5038a3bcb86a8b9faa1d8e7b7"
CASEBOOK_HASH = "d1241633b073cd7307f1da00a13a2d76c132f3dccefc52a076be2c641f06b85f"

MICRO_STATES = (
    "FLOW_PRESSURE_W60",
    "FLOW_PRESSURE_W900",
    "DEPTH_PRESSURE_W60",
    "DEPTH_PRESSURE_W900",
    "LIQUIDITY_ACTIVITY_SHIFT",
    "LIQUIDITY_FRAGILITY",
    "ABSORPTION_STATE_W60",
    "FLOW_DEPTH_ALIGNMENT",
)
FUNDAMENTAL_CONTEXTS = (
    "MACRO_ENGINE_BIAS_STATE",
    "REAL_YIELD_USD_CONFIRMATION",
    "REGIME_REACTION_FUNCTION_STATE",
    "RECENT_RELEASE_SURPRISE_DIRECTION",
    "UPCOMING_CATALYST_RISK",
    "FINANCIAL_STRESS_STATE",
    "COT_MANAGED_MONEY_CROWDING",
    "COT_WEEKLY_CHANGE_SIGN",
)
LEVEL_CONTEXTS = (
    "ASIA_RANGE_LOCATION",
    "ASIA_PREDECISION_BREAK_STATE",
    "PRIOR_DAY_RANGE_LOCATION",
    "STRUCTURE_15M_1H_ALIGNMENT",
    "ASIA_RANGE_COMPRESSION",
    "LONDON_PRE_NEW_YORK_DIRECTION",
    "LONDON_ASIA_INTERACTION_PRE_NEW_YORK",
)


def main() -> None:
    for path in (ROW_REGISTRY_OUT, PROTOCOL_OUT, FREEZE_OUT):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}")
    for path, expected in EXPECTED_FILES.items():
        _verify_hash(path, expected)

    contract = _read_json(CONTRACT)
    feature_registry = _read_json(FEATURE_REGISTRY)
    budget_registry = _read_json(BUDGET_REGISTRY)
    acquisition = _read_json(ACQUISITION)
    step5b2_manifest = _read_json(STEP5B2_MANIFEST)
    step5b2_verdict = _read_json(STEP5B2_VERDICT)
    step4b3_manifest = _read_json(STEP4B3_MANIFEST)
    step4b3_verdict = _read_json(STEP4B3_VERDICT)
    case_manifest = _read_json(CASE_MATRIX_MANIFEST)
    casebook_manifest = _read_json(CASEBOOK_MANIFEST)

    _verify_predecessors(
        contract,
        feature_registry,
        budget_registry,
        acquisition,
        step5b2_manifest,
        step5b2_verdict,
        step4b3_manifest,
        step4b3_verdict,
        case_manifest,
        casebook_manifest,
    )
    row_registry = _build_row_registry(budget_registry, acquisition)
    _write_json(ROW_REGISTRY_OUT, row_registry)

    frozen_at = _now()
    protocol = _build_protocol(row_registry, frozen_at)
    _write_json(PROTOCOL_OUT, protocol)
    freeze = {
        "version": "GC_MICROSTRUCTURE_STEP_5C_FREEZE_V0_1",
        "status": "SEALED_BEFORE_RESEARCH_MARKET_VALUE_ACCESS",
        "sealed_at_utc": _now(),
        "classification": "DEVELOPMENT_FEATURE_MATERIALIZATION_ONLY",
        "protocol": _file_record(PROTOCOL_OUT),
        "row_registry": _file_record(ROW_REGISTRY_OUT),
        "preparation_tool": _file_record(Path(__file__)),
        "pre_value_checks": {
            "step5b2_pass_bound": True,
            "all_80_source_requests_bound": True,
            "all_188_dates_bound": True,
            "all_376_session_rows_bound": True,
            "all_85_feature_columns_bound": True,
            "all_8_microstructure_states_bound": True,
            "all_8_fundamental_contexts_bound": True,
            "all_7_level_session_contexts_bound": True,
            "outcome_fields_in_output_schema": 0,
            "development_outcomes_accessed": False,
            "market_values_accessed": False,
            "year_2025_or_2026_values_accessed": False,
        },
        "recertification_started": False,
        "charge_incurred_usd": 0.0,
    }
    _write_json(FREEZE_OUT, freeze)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5C_PROTOCOL_FROZEN",
                "protocol_sha256": _sha256(PROTOCOL_OUT),
                "row_registry_sha256": _sha256(ROW_REGISTRY_OUT),
                "freeze_sha256": _sha256(FREEZE_OUT),
                "dates": 188,
                "session_rows": 376,
                "available_bucket_rows": row_registry["expected_counts"]["available_bucket_rows"],
                "market_values_or_outcomes_accessed": False,
                "charge_incurred_usd": 0.0,
            },
            sort_keys=True,
        )
    )


def _verify_predecessors(
    contract: dict[str, Any],
    feature_registry: dict[str, Any],
    budget_registry: dict[str, Any],
    acquisition: dict[str, Any],
    step5b2_manifest: dict[str, Any],
    step5b2_verdict: dict[str, Any],
    step4b3_manifest: dict[str, Any],
    step4b3_verdict: dict[str, Any],
    case_manifest: dict[str, Any],
    casebook_manifest: dict[str, Any],
) -> None:
    if step5b2_verdict["status"] != STEP5B2_STATUS or not step5b2_verdict["formal_pass"]:
        raise ValueError("Step 5B.2 PASS is not intact")
    if step5b2_manifest["status"] != STEP5B2_STATUS or step5b2_manifest["manifest_hash"] != STEP5B2_MANIFEST_HASH:
        raise ValueError("Step 5B.2 manifest changed")
    if step4b3_verdict["status"] != STEP4B3_STATUS or not step4b3_verdict["formal_pass"]:
        raise ValueError("Step 4B.3 feature robustness PASS is not intact")
    if step4b3_manifest["status"] != STEP4B3_STATUS or step4b3_manifest["manifest_hash"] != STEP4B3_MANIFEST_HASH:
        raise ValueError("Step 4B.3 manifest changed")
    if case_manifest["manifest_hash"] != CASE_MATRIX_HASH:
        raise ValueError("V3 case-matrix manifest changed")
    if casebook_manifest["manifest_hash"] != CASEBOOK_HASH:
        raise ValueError("Casebook source-bundle manifest changed")
    if feature_registry["sealed_feature_columns"]["expected_count"] != 85:
        raise ValueError("Frozen feature count changed")
    if tuple(item["state_id"] for item in feature_registry["derived_microstructure_states"]) != MICRO_STATES:
        raise ValueError("Frozen derived-state registry changed")
    if tuple(item["context_id"] for item in feature_registry["eligible_fundamental_bias_contexts"]) != FUNDAMENTAL_CONTEXTS:
        raise ValueError("Frozen fundamental-context registry changed")
    if tuple(item["context_id"] for item in feature_registry["eligible_price_level_and_session_contexts"]) != LEVEL_CONTEXTS:
        raise ValueError("Frozen level/session-context registry changed")
    if budget_registry["sample_counts"]["selected_dates"] != 188:
        raise ValueError("Budget C date count changed")
    if budget_registry["provider_quote_request_count"] != 80 or len(budget_registry["provider_quote_requests"]) != 80:
        raise ValueError("Budget C request count changed")
    if len(acquisition["requests"]) != 80 or acquisition["batch_jobs_submitted"] != 80:
        raise ValueError("Acquisition request count changed")
    if acquisition["features_calculated"] or acquisition["execution_optimized"]:
        raise ValueError("Step 5B boundary changed")
    if contract["eligible_decision_state"]["microstructure_columns"][:7] != "Exactly":
        raise ValueError("Discovery contract feature binding changed")


def _build_row_registry(
    budget_registry: dict[str, Any], acquisition: dict[str, Any]
) -> dict[str, Any]:
    requests = {item["request_id"]: item for item in acquisition["requests"]}
    interval_requests: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for item in budget_registry["provider_quote_requests"]:
        interval_requests[item["interval_id"]][item["schema"]] = item
    if len(interval_requests) != 40 or any(set(pair) != {"mbo", "mbp-10"} for pair in interval_requests.values()):
        raise ValueError("Expected 40 exact MBO/MBP-10 request pairs")

    date_to_interval: dict[str, str] = {}
    for interval in budget_registry["request_intervals"]:
        for date in interval["selected_dates"]:
            if date in date_to_interval:
                raise ValueError(f"Duplicate interval allocation for {date}")
            date_to_interval[date] = interval["interval_id"]

    rows: list[dict[str, Any]] = []
    source_bindings: list[dict[str, Any]] = []
    seen_request_ids: set[str] = set()
    for interval_id in sorted(interval_requests):
        pair = interval_requests[interval_id]
        mbo_meta = pair["mbo"]
        mbp_meta = pair["mbp-10"]
        mbo = requests[mbo_meta["request_id"]]
        mbp = requests[mbp_meta["request_id"]]
        if mbo["selected_dates"] != mbp["selected_dates"]:
            raise ValueError(f"Paired selected dates differ: {interval_id}")
        if mbo["expected_instrument_id_by_date"] != mbp["expected_instrument_id_by_date"]:
            raise ValueError(f"Paired instrument mappings differ: {interval_id}")
        for request in (mbo, mbp):
            seen_request_ids.add(request["request_id"])
            normalized = request["normalization"]["normalized_payload"]
            source_bindings.append(
                {
                    "request_id": request["request_id"],
                    "interval_id": interval_id,
                    "schema": request["schema"],
                    "selected_dates": request["selected_dates"],
                    "expected_instrument_id_by_date": request["expected_instrument_id_by_date"],
                    "normalized_payload": normalized,
                    "data_quality": request["normalization"]["data_quality"],
                    "lineage": request["normalization"]["lineage"],
                    "source_seal": request["normalization"]["seal"],
                    "provider_record_count": request["job_details"]["record_count"],
                }
            )

    for selected in budget_registry["selected_dates"]:
        date = selected["trade_date"]
        interval_id = date_to_interval[date]
        pair = interval_requests[interval_id]
        mbo = requests[pair["mbo"]["request_id"]]
        mbp = requests[pair["mbp-10"]["request_id"]]
        instrument_id = int(mbo["expected_instrument_id_by_date"][date])
        for session, key, timezone in (
            ("LONDON", "london_decision_at_utc", "Europe/London"),
            ("NEW_YORK", "new_york_decision_at_utc", "America/New_York"),
        ):
            decision = _parse(selected[key])
            day_start = datetime(decision.year, decision.month, decision.day, tzinfo=UTC)
            decision_ns = int(decision.timestamp() * 1_000_000_000)
            day_start_ns = int(day_start.timestamp() * 1_000_000_000)
            start_ns = decision_ns - 900_000_000_000
            start_bucket = (start_ns - day_start_ns) // 1_000_000_000
            end_bucket = (decision_ns - day_start_ns) // 1_000_000_000
            if not (0 <= start_bucket < end_bucket <= 86_400 and end_bucket - start_bucket == 900):
                raise ValueError(f"Invalid frozen window: {date} {session}")
            availability = (
                "UNAVAILABLE_DOCUMENTED"
                if date == "2022-04-15"
                else "EXPECTED_AVAILABLE"
            )
            rows.append(
                {
                    "row_id": f"STEP5C:{date}:{session}",
                    "session_date": date,
                    "session_code": session,
                    "session_timezone": timezone,
                    "decision_at_utc": decision.isoformat().replace("+00:00", "Z"),
                    "window_start_inclusive_ns": start_ns,
                    "window_end_exclusive_ns": decision_ns,
                    "utc_day_start_ns": day_start_ns,
                    "bucket_index_start_inclusive": start_bucket,
                    "bucket_index_end_exclusive": end_bucket,
                    "expected_bucket_rows": 0 if availability == "UNAVAILABLE_DOCUMENTED" else 900,
                    "availability_disposition": availability,
                    "selected_month_week_id": selected["selected_month_week_id"],
                    "interval_id": interval_id,
                    "mbo_request_id": mbo["request_id"],
                    "mbp10_request_id": mbp["request_id"],
                    "expected_instrument_id": instrument_id,
                    "permanently_engineering_only": False,
                }
            )

    rows.sort(key=lambda item: (item["session_date"], item["session_code"]))
    if len(rows) != 376 or len({item["row_id"] for item in rows}) != 376:
        raise ValueError("Expected 376 unique Step 5C rows")
    if len(seen_request_ids) != 80 or len(source_bindings) != 80:
        raise ValueError("Expected 80 source bindings")
    counts = Counter(item["availability_disposition"] for item in rows)
    if counts != {"EXPECTED_AVAILABLE": 374, "UNAVAILABLE_DOCUMENTED": 2}:
        raise ValueError(f"Unexpected availability counts: {counts}")

    payload = {
        "version": "GC_MICROSTRUCTURE_STEP_5C_ROW_REGISTRY_V0_1",
        "status": "FROZEN_BEFORE_RESEARCH_MARKET_VALUE_ACCESS",
        "classification": "OUTCOME_BLIND_DEVELOPMENT_FEATURE_ROWS",
        "date_range": {"start": "2021-11-08", "end": "2024-12-13"},
        "source_bindings": sorted(source_bindings, key=lambda item: item["request_id"]),
        "rows": rows,
        "expected_counts": {
            "dates": 188,
            "session_rows": 376,
            "london_rows": 188,
            "new_york_rows": 188,
            "available_session_rows": 374,
            "unavailable_documented_rows": 2,
            "available_bucket_rows": 374 * 900,
            "london_bucket_rows": 187 * 900,
            "new_york_bucket_rows": 187 * 900,
            "source_requests": 80,
            "request_pairs": 40,
        },
        "engineering_dates_included": [],
        "year_2025_or_2026_rows": 0,
        "outcome_fields": [],
        "registry_hash": None,
    }
    payload["registry_hash"] = _canonical_hash({**payload, "registry_hash": None})
    return payload


def _build_protocol(row_registry: dict[str, Any], frozen_at: str) -> dict[str, Any]:
    input_records = {str(path.relative_to(ROOT)).replace("\\", "/"): _file_record(path) for path in EXPECTED_FILES}
    return {
        "version": "GC_MICROSTRUCTURE_STEP_5C_PROTOCOL_V0_1",
        "status": "FROZEN_BEFORE_RESEARCH_MARKET_VALUE_ACCESS",
        "frozen_at_utc": frozen_at,
        "classification": "OUTCOME_BLIND_DEVELOPMENT_FEATURE_MATERIALIZATION_ONLY",
        "purpose": "Materialize the preregistered GC microstructure decision state and eligible point-in-time contexts without opening or joining a development outcome.",
        "sealed_inputs": input_records,
        "required_predecessors": {
            "step5b2_status": STEP5B2_STATUS,
            "step5b2_manifest_hash": STEP5B2_MANIFEST_HASH,
            "step4b3_status": STEP4B3_STATUS,
            "step4b3_manifest_hash": STEP4B3_MANIFEST_HASH,
            "case_matrix_manifest_hash": CASE_MATRIX_HASH,
            "casebook_source_manifest_hash": CASEBOOK_HASH,
            "feature_schema_sha256": FEATURE_SCHEMA_SHA256,
            "all_prior_verdicts_and_artifacts_immutable": True,
        },
        "row_registry": {
            **_file_record(ROW_REGISTRY_OUT),
            "registry_hash": row_registry["registry_hash"],
            "dates": 188,
            "session_rows": 376,
        },
        "source_allocation": {
            "source_requests": 80,
            "request_pairs": 40,
            "normalized_payloads_only": True,
            "MBO_role": "Event-flow measurements only; no MBO-to-MBP row alignment.",
            "MBP10_role": "Authoritative top-ten book state and quote-OFI measurements.",
            "selected_row_rule": "Read only rows with ts_recv in a frozen 900-second decision window, plus exactly one value-blindly located prior MBP-10 row per available window as the state/OFI anchor.",
            "outside_window_rows": "Classify as OUTSIDE_FEATURE_WINDOWS using sealed Parquet row counts; do not open their market fields.",
            "allocation_identity": "Every selected source row is assigned to exactly one non-overlapping session window; anchors are marked ANCHOR_ONLY and never counted as a window update.",
            "source_order": ["ts_recv", "source_row_ordinal"],
            "duplicates": "Preserve every provider emission in original order; never deduplicate.",
            "filter_repair_relabel_substitute": False,
        },
        "temporal_contract": {
            "availability_timestamp": "ts_recv",
            "bucket_width_ns": 1_000_000_000,
            "bucket_interval": "[bucket_start_ns,bucket_end_ns)",
            "feature_window": "[decision_cutoff-900 seconds,decision_cutoff)",
            "W60": "Last 60 complete one-second buckets of the feature window.",
            "W900": "All 900 complete one-second buckets of the feature window.",
            "terminal_bucket": "[decision_cutoff-1 second,decision_cutoff)",
            "post_cutoff_rows_permitted": False,
            "date_boundary": "Clear book, quote-OFI, event, and anchor state at every UTC calendar-date boundary.",
            "segment_boundary": "Clear book and quote-OFI baselines at every CME market-segment boundary.",
            "target_state": "Every available target window must be CONTINUOUS_MATCHING under the DST-aware CME schedule.",
            "dst_source": "IANA Europe/London, America/New_York, and America/Chicago rules encoded in the frozen row registry and recomputed independently.",
        },
        "raw_feature_payload": {
            "columns": 85,
            "column_order_source": "gc_microstructure_step_5a_feature_hypothesis_registry_v01.json",
            "schema_sha256": FEATURE_SCHEMA_SHA256,
            "formulas": "Unchanged Step 4A formulas, integer rounding, missingness, authoritative MBP-10 state, MBO flow, and one-second bucket semantics.",
            "outputs": ["LONDON 85-column bucket Parquet", "NEW_YORK 85-column bucket Parquet"],
            "expected_available_rows": 336_600,
            "good_friday": "2022-04-15 emits no bucket rows and remains in the decision matrix as UNAVAILABLE_DOCUMENTED/UNKNOWN.",
        },
        "derived_microstructure_states": {
            "state_ids": list(MICRO_STATES),
            "rounding": "All ratios and even-count integer medians use half-away-from-zero rounding.",
            "median": "Sort non-null integer bucket-close values; odd uses center; even uses integer midpoint with half-away-from-zero rounding.",
            "FLOW_PRESSURE_W60_W900": "Recompute displayed-pressure and trade-imbalance ratios from window aggregate quantities. quote_ofi_raw is known only with at least one eligible transition. BULLISH requires at least two known positive components and no known negative component; BEARISH is the mirror; otherwise CONFLICTED; fewer than two known is UNKNOWN.",
            "DEPTH_PRESSURE_W60_W900": "Use deterministic medians of L1/L5/L10 depth imbalance and terminal microprice-minus-midpoint sign. At least three known inputs are required; three or more positive is BULLISH, three or more negative is BEARISH, otherwise CONFLICTED.",
            "LIQUIDITY_ACTIVITY_SHIFT": "Compare W60 and W900 per-second rates for mbo_live_records, mbp_update_count, and quote_ofi_transition_count by exact cross multiplication. At least two higher is HIGH, at least two lower is LOW, otherwise STABLE.",
            "LIQUIDITY_FRAGILITY": "Compare W60 median spread to W900 median, terminal book age to W900 median, and W60 median total L10 depth to W900 median. At least two fragile comparisons is FRAGILE, two exact reverse comparisons is RESILIENT, otherwise MIXED; fewer than two known comparisons is UNKNOWN.",
            "ABSORPTION_STATE_W60": "Require nonzero directional trade quantity, known midpoint progress, and at least one known quote-OFI or L5-depth confirmation. Buy>sell with non-positive progress and a negative confirmation is BEARISH_ABSORPTION; sell>buy with non-negative progress and a positive confirmation is BULLISH_ABSORPTION; otherwise NONE.",
            "FLOW_DEPTH_ALIGNMENT": "BULLISH when FLOW_PRESSURE_W60 and DEPTH_PRESSURE_W60 are both BULLISH; BEARISH when both BEARISH; CONFLICTED when they oppose; otherwise NEUTRAL_OR_UNKNOWN.",
            "threshold_search_or_retuning": False,
        },
        "outcome_blind_context_projection": {
            "source": "Sealed gold_casebook_v01 source bundle, rebuilt without calling subsequent-behaviour construction and without reading a post-cutoff price bar.",
            "selected_decision_rows": 376,
            "projection_fields": ["case/session identity", "decision_state only", "pre-New-York registered price-path inputs only", "lineage and quality"],
            "forbidden_fields": ["subsequent_behaviour", "neutral session direction", "fixed-horizon returns", "excursions", "session close", "path outcome", "MFE", "MAE", "trade fields"],
            "price_bar_rule": "For New York-only handover contexts, admit complete XAUUSD bars from the London 08:01 local reference through a close no later than the New York decision cutoff. Never expose those bars to the London row.",
            "asia_history_rule": "For ASIA_RANGE_COMPRESSION use the prior 20 eligible unique development session dates from the complete sealed 2021-2024 casebook chronology, excluding the current date; Type-7 25th/75th percentiles; fewer than 20 observations is UNKNOWN.",
            "point_in_time_gate": "Every fact and price bar must have available_at <= the receiving row's decision_at; equality is permitted only for a fully published/closed record.",
        },
        "fundamental_contexts": {
            "context_ids": list(FUNDAMENTAL_CONTEXTS),
            "MACRO_ENGINE_BIAS_STATE": "Directional score >=+20 BULLISH, <=-20 BEARISH, otherwise NEUTRAL; missing/ineligible UNKNOWN.",
            "REAL_YIELD_USD_CONFIRMATION": "Use eligible observation-to-observation absolute-change signs: both negative GOLD_BULLISH, both positive GOLD_BEARISH, otherwise CONFLICTED; either unknown/stale makes UNKNOWN.",
            "REGIME_REACTION_FUNCTION_STATE": "Retain eligible reaction-function category without relabeling.",
            "RECENT_RELEASE_SURPRISE_DIRECTION": "Use eligible pre-existing event-impact direction only when tied to the latest importance-5 release in the prior 24 hours with verified pre-release forecast availability; otherwise UNKNOWN.",
            "UPCOMING_CATALYST_RISK": "HIGH only for a verified scheduled importance-5 US macro/FOMC event strictly after decision_at and no later than observation_end; NONE only with verified calendar coverage; otherwise UNKNOWN.",
            "FINANCIAL_STRESS_STATE": "Eligible latest level >0 STRESS, <=0 NORMAL, otherwise UNKNOWN.",
            "COT_MANAGED_MONEY_CROWDING": "Retain eligible published crowding_state; age >10 calendar days or unverified available_at is UNKNOWN; epistemic class INFERRED.",
            "COT_WEEKLY_CHANGE_SIGN": "Use latest two reports both published/available by decision_at; compare managed-money net contracts: UP, DOWN, or FLAT; either stale/unavailable makes UNKNOWN.",
        },
        "price_level_session_contexts": {
            "context_ids": list(LEVEL_CONTEXTS),
            "ASIA_RANGE_LOCATION": "Eligible decision XAUUSD price above Asia high, below Asia low, or inside; missing coordinate is UNKNOWN.",
            "ASIA_PREDECISION_BREAK_STATE": "Apply the frozen two-consecutive-complete-5m-close acceptance rule after both Asia levels are known and through decision_at. Accepted/holding maps ACCEPTED_ABOVE/BELOW; rejected breach or returned-inside accepted break maps REJECTED_ABOVE/BELOW; none maps NO_BREAK. If both sides complete, select the latest completion timestamp; an exact opposing tie is UNKNOWN.",
            "PRIOR_DAY_RANGE_LOCATION": "Eligible decision XAUUSD price above prior-day high, below prior-day low, or inside; missing coordinate is UNKNOWN.",
            "STRUCTURE_15M_1H_ALIGNMENT": "Both eligible frozen trends bullish -> BULLISH; both bearish -> BEARISH; both known otherwise -> MIXED; any unknown -> UNKNOWN.",
            "ASIA_RANGE_COMPRESSION": "Current Asia range <= prior-20 Type-7 p25 LOW, >= p75 HIGH, otherwise NORMAL; missing or fewer than 20 prior eligible ranges UNKNOWN.",
            "LONDON_PRE_NEW_YORK_DIRECTION": "NEW_YORK only: first complete one-minute bar opening exactly 08:01 Europe/London to last complete bar closing <= New York cutoff. Displacement >+0.01 UP, <-0.01 DOWN, otherwise FLAT. LONDON rows are UNKNOWN by registered session eligibility.",
            "LONDON_ASIA_INTERACTION_PRE_NEW_YORK": "NEW_YORK only: same frozen 5m/two-close acceptance rule from London 08:00 local to the New York cutoff against Asia high/low. Holding acceptance maps ACCEPTED; rejected/failed accepted break maps REJECTED; none maps NO_COMPLETED_INTERACTION; latest completion wins and exact opposing tie is UNKNOWN. LONDON rows are UNKNOWN.",
        },
        "missing_data": {
            "UNKNOWN_is_not_zero_flat_normal_or_no_event": True,
            "documented_good_friday_rows": ["STEP5C:2022-04-15:LONDON", "STEP5C:2022-04-15:NEW_YORK"],
            "missing_bucket_window": "No raw rows; all eight states UNKNOWN; contexts remain independently point-in-time materialized where eligible.",
            "missing_context": "State UNKNOWN with epistemic_status UNKNOWN, quality MISSING, and source_signature UNKNOWN.",
            "repair_or_backfill": False,
        },
        "independent_reproduction": {
            "primary": "NumPy mask/bincount event allocation, forward latest-state selection, and direct context extractors.",
            "reference": "Independent NumPy add.at allocation, reverse unique latest-state selection, and separately implemented context extractors.",
            "required_identical": ["output schemas", "row identities", "null counts", "per-column checksums", "complete-row checksums", "technical diagnostics", "byte-identical Parquet outputs"],
            "book_equality_may_not_select_rows": True,
        },
        "integrity_gates": {
            "all_predecessor_and_80_source_seals_verify": True,
            "exactly_376_unique_decision_rows": True,
            "exactly_336600_available_bucket_rows": True,
            "exact_85_column_schema_and_order": True,
            "every_selected_row_allocated_once_and_anchors_excluded": True,
            "publisher_and_per_date_instrument_mapping_exact": True,
            "timestamps_and_source_ordinals_nondecreasing": True,
            "no_post_cutoff_or_cross_date_segment_state_carry": True,
            "continuous_matching_bucket_close_crossed_states_zero": True,
            "empty_levels_canonical_and_sizes_counts_nonnegative": True,
            "unknown_actions_and_maybe_bad_book_rows_zero": True,
            "all_BAD_TS_RECV_rows_must_remain_within_Step5B2_permitted_semantics": True,
            "context_available_at_not_after_decision": True,
            "outcome_columns_or_accesses_zero": True,
            "primary_reference_exact_reproduction": True,
        },
        "pass_rule": "PASS only if all source/predecessor gates, both feature implementations, the outcome-blind context projection, exact coverage/null/schema/checksum gates, and independent reproduction pass. Otherwise record an honest formal failure without repair.",
        "status_precedence": ["FAIL_PREDECESSOR_OR_SOURCE", "FAIL_CONTEXT_PROJECTION", "FAIL_FEATURE_INTEGRITY", "FAIL_REPRODUCTION", "PASS_STEP_5C_FEATURE_MATERIALIZATION"],
        "prohibited": ["acquisition or charge", "source repair/filter/relabel/deduplication", "development outcome access or join", "2025 or 2026 value access", "relationship/effect/p-value calculation", "candidate/signal creation", "execution/trade/PnL/R/return calculation", "feature/window/state/context/threshold retuning", "Step 5D"],
        "completion_policy": "Document, seal, independently verify, and stop after Step 5C before any outcome or relationship access.",
        "market_values_accessed_before_freeze": False,
        "development_outcomes_accessed": False,
        "charge_incurred_usd": 0.0,
    }


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_hash(path: Path, expected: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = _sha256(path)
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {path}: {actual} != {expected}")


def _file_record(path: Path) -> dict[str, Any]:
    relative = str(path.relative_to(ROOT)).replace("\\", "/")
    return {"path": relative, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
