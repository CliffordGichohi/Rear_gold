#!/usr/bin/env python3
"""Freeze the Step 5D protocol before any development outcome is opened.

This preparatory program is deliberately metadata-only.  It verifies hashes and
JSON control metadata, enumerates the bounded tests implied by the sealed Step
5A registry, and writes immutable protocol/test-registry/freeze documents.  It
never opens the V3 case payload or either Step 5C Parquet value payload.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "research_manifests"
ARTIFACT_DIR = ROOT / "research_artifacts"

CONTRACT_PATH = MANIFEST_DIR / "gc_microstructure_conditional_edge_discovery_contract_v01.json"
FEATURE_REGISTRY_PATH = MANIFEST_DIR / "gc_microstructure_step_5a_feature_hypothesis_registry_v01.json"
STEP5C_MANIFEST_PATH = ARTIFACT_DIR / "gc_microstructure_step5c_v01" / "manifest.json"
STEP5C_VERDICT_PATH = ARTIFACT_DIR / "gc_microstructure_step5c_v01" / "verdict.json"
CASE_MANIFEST_PATH = ARTIFACT_DIR / "gold_session_behaviour_v3_case_matrix_v01" / "manifest.json"
CASE_PAYLOAD_PATH = ARTIFACT_DIR / "gold_session_behaviour_v3_case_matrix_v01" / "cases.jsonl.gz"

PROTOCOL_PATH = MANIFEST_DIR / "gc_microstructure_step_5d_protocol_v01.json"
TEST_REGISTRY_PATH = MANIFEST_DIR / "gc_microstructure_step_5d_test_registry_v01.json"
FREEZE_PATH = MANIFEST_DIR / "gc_microstructure_step_5d_freeze_v01.json"

EXPECTED = {
    "contract_file": "da9048f497c853ef3b1f2a4debe6c80f8c650217004bfe6df05e045751554fcb",
    "feature_registry_file": "4b207a1dec5aa78a904c86cf8c6a14bf0a517dd918f24c5270c254400c865f01",
    "step5c_manifest_file": "f7150f861f4883e3f7c100822af527ba497b8343225c24ebe16ffe11107e31fb",
    "step5c_verdict_file": "f98702e5260f60fa258a8f5ed43adc944724075bf442f958677fdf8fe3dee2ad",
    "step5c_manifest_hash": "37ba904c257499a5247696fbae24461c994b765dfbc44b3bbeaa59cb9d58fb75",
    "step5c_verdict_hash": "d4c632a9fb9b33bb1e4385e0116d082fffcbe14b15385677c0dc55978fb124f6",
    "step5c_decision_file": "277993e0cd2d5bff2e8f49c6aaf519ac024a1f7ac1ed8bbd0808f5d3213b5d98",
    "case_manifest_file": "dddbe125d11afef2094b7843f5521b7bbfcc95178e3fa376b60af8bdd2efc3b5",
    "case_manifest_hash": "d6aad4b861d98899d6fdcc92ea53a20221434af5038a3bcb86a8b9faa1d8e7b7",
    "case_payload_file": "d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9",
}

SESSIONS = ("LONDON", "NEW_YORK")
UNKNOWN_STATES = ("UNKNOWN", "NEUTRAL_OR_UNKNOWN", "UNKNOWN_WITHOUT_EVENT_AND_REGIME_CORE")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected object: {path}")
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    path.write_text(payload, encoding="utf-8", newline="\n")


def seed(session: str, test_id: str, namespace: str) -> int:
    material = f"GC_MICRO_STEP5_V1|{session}|{test_id}|{namespace}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=False)


def make_test(
    *,
    session: str,
    stage: int,
    hypothesis_ids: Iterable[str],
    conditions: Iterable[tuple[str, str]],
    favorable_direction: str,
) -> dict[str, Any]:
    condition_rows = [{"field": field, "state": state} for field, state in conditions]
    condition_token = "+".join(f"{item['field']}={item['state']}" for item in condition_rows)
    test_id = f"{session}:STAGE_{stage}:{condition_token}:{favorable_direction}"
    return {
        "test_id": test_id,
        "session": session,
        "stage": stage,
        "hypothesis_ids": list(hypothesis_ids),
        "conditions": condition_rows,
        "favorable_direction": favorable_direction,
        "condition_semantics": "ALL_EXACT_STATES_MUST_MATCH",
        "complement_semantics": "ALL_CONSTITUENTS_KNOWN_AND_EXACT_REGISTERED_CONDITION_FALSE",
        "bootstrap_seed_uint64": seed(session, test_id, "BOOTSTRAP"),
        "permutation_seed_uint64": seed(session, test_id, "PERMUTATION"),
    }


def directional_tests(
    *,
    session: str,
    stage: int,
    hypothesis_ids: Iterable[str],
    field: str,
    bullish_state: str = "BULLISH",
    bearish_state: str = "BEARISH",
) -> list[dict[str, Any]]:
    return [
        make_test(
            session=session,
            stage=stage,
            hypothesis_ids=hypothesis_ids,
            conditions=((field, bullish_state),),
            favorable_direction="UP",
        ),
        make_test(
            session=session,
            stage=stage,
            hypothesis_ids=hypothesis_ids,
            conditions=((field, bearish_state),),
            favorable_direction="DOWN",
        ),
    ]


def conditioned_tests(
    *,
    session: str,
    hypothesis_id: str,
    directional_field: str,
    directional_states: tuple[tuple[str, str], ...],
    conditioner_field: str,
    conditioner_states: Iterable[str],
) -> list[dict[str, Any]]:
    tests: list[dict[str, Any]] = []
    for direction_state, favorable in directional_states:
        for context_state in conditioner_states:
            tests.append(
                make_test(
                    session=session,
                    stage=2,
                    hypothesis_ids=(hypothesis_id,),
                    conditions=((directional_field, direction_state), (conditioner_field, context_state)),
                    favorable_direction=favorable,
                )
            )
    return tests


def confirming_tests(
    *,
    session: str,
    hypothesis_id: str,
    first_field: str,
    bullish_first: str,
    bearish_first: str,
    second_field: str,
    bullish_second: str,
    bearish_second: str,
) -> list[dict[str, Any]]:
    return [
        make_test(
            session=session,
            stage=2,
            hypothesis_ids=(hypothesis_id,),
            conditions=((first_field, bullish_first), (second_field, bullish_second)),
            favorable_direction="UP",
        ),
        make_test(
            session=session,
            stage=2,
            hypothesis_ids=(hypothesis_id,),
            conditions=((first_field, bearish_first), (second_field, bearish_second)),
            favorable_direction="DOWN",
        ),
    ]


def build_tests() -> list[dict[str, Any]]:
    tests: list[dict[str, Any]] = []
    for session in SESSIONS:
        for field, hypotheses, bullish, bearish in (
            ("FLOW_PRESSURE_W60", ("H1_MICRO_FLOW_CONTINUATION",), "BULLISH", "BEARISH"),
            ("FLOW_PRESSURE_W900", ("H1_MICRO_FLOW_CONTINUATION",), "BULLISH", "BEARISH"),
            ("DEPTH_PRESSURE_W60", ("H2_DEPTH_CONFIRMATION",), "BULLISH", "BEARISH"),
            ("DEPTH_PRESSURE_W900", ("H2_DEPTH_CONFIRMATION",), "BULLISH", "BEARISH"),
            (
                "ABSORPTION_STATE_W60",
                ("H3_ABSORPTION_REVERSAL",),
                "BULLISH_ABSORPTION",
                "BEARISH_ABSORPTION",
            ),
            (
                "FLOW_DEPTH_ALIGNMENT",
                ("H1_MICRO_FLOW_CONTINUATION", "H2_DEPTH_CONFIRMATION"),
                "BULLISH",
                "BEARISH",
            ),
        ):
            tests.extend(
                directional_tests(
                    session=session,
                    stage=1,
                    hypothesis_ids=hypotheses,
                    field=field,
                    bullish_state=bullish,
                    bearish_state=bearish,
                )
            )

        directional = (("BULLISH", "UP"), ("BEARISH", "DOWN"))
        absorption = (("BULLISH_ABSORPTION", "UP"), ("BEARISH_ABSORPTION", "DOWN"))

        tests.extend(
            conditioned_tests(
                session=session,
                hypothesis_id="H4_LIQUIDITY_CONDITIONING",
                directional_field="FLOW_PRESSURE_W60",
                directional_states=directional,
                conditioner_field="LIQUIDITY_ACTIVITY_SHIFT",
                conditioner_states=("HIGH", "LOW"),
            )
        )
        tests.extend(
            conditioned_tests(
                session=session,
                hypothesis_id="H4_LIQUIDITY_CONDITIONING",
                directional_field="FLOW_DEPTH_ALIGNMENT",
                directional_states=directional,
                conditioner_field="LIQUIDITY_FRAGILITY",
                conditioner_states=("FRAGILE", "RESILIENT"),
            )
        )

        for args in (
            (
                "MACRO_ENGINE_BIAS_STATE",
                "BULLISH",
                "BEARISH",
                "FLOW_DEPTH_ALIGNMENT",
                "BULLISH",
                "BEARISH",
            ),
            (
                "REAL_YIELD_USD_CONFIRMATION",
                "GOLD_BULLISH",
                "GOLD_BEARISH",
                "FLOW_DEPTH_ALIGNMENT",
                "BULLISH",
                "BEARISH",
            ),
            (
                "RECENT_RELEASE_SURPRISE_DIRECTION",
                "BULLISH",
                "BEARISH",
                "FLOW_PRESSURE_W60",
                "BULLISH",
                "BEARISH",
            ),
        ):
            tests.extend(
                confirming_tests(
                    session=session,
                    hypothesis_id="H5_MACRO_MICRO_CONFIRMATION",
                    first_field=args[0],
                    bullish_first=args[1],
                    bearish_first=args[2],
                    second_field=args[3],
                    bullish_second=args[4],
                    bearish_second=args[5],
                )
            )
        tests.extend(
            conditioned_tests(
                session=session,
                hypothesis_id="H5_MACRO_MICRO_CONFIRMATION",
                directional_field="FLOW_DEPTH_ALIGNMENT",
                directional_states=directional,
                conditioner_field="REGIME_REACTION_FUNCTION_STATE",
                conditioner_states=(
                    "INFLATION_FOCUS",
                    "GROWTH_LABOUR_FOCUS",
                    "FINANCIAL_STRESS_FOCUS",
                    "EVENT_SURPRISE_WITH_PARTIAL_MACRO",
                    "BALANCED_REACTION_FUNCTION",
                ),
            )
        )
        tests.extend(
            conditioned_tests(
                session=session,
                hypothesis_id="H5_MACRO_MICRO_CONFIRMATION",
                directional_field="FLOW_DEPTH_ALIGNMENT",
                directional_states=directional,
                conditioner_field="FINANCIAL_STRESS_STATE",
                conditioner_states=("STRESS", "NORMAL"),
            )
        )

        for first_field, bullish_first, bearish_first, second_field in (
            ("ASIA_RANGE_LOCATION", "ABOVE_ASIA_HIGH", "BELOW_ASIA_LOW", "FLOW_DEPTH_ALIGNMENT"),
            (
                "ASIA_PREDECISION_BREAK_STATE",
                "ACCEPTED_ABOVE",
                "ACCEPTED_BELOW",
                "FLOW_PRESSURE_W60",
            ),
            ("PRIOR_DAY_RANGE_LOCATION", "ABOVE_PRIOR_HIGH", "BELOW_PRIOR_LOW", "FLOW_DEPTH_ALIGNMENT"),
            ("STRUCTURE_15M_1H_ALIGNMENT", "BULLISH", "BEARISH", "FLOW_DEPTH_ALIGNMENT"),
        ):
            tests.extend(
                confirming_tests(
                    session=session,
                    hypothesis_id="H6_LEVEL_MICRO_ACCEPTANCE",
                    first_field=first_field,
                    bullish_first=bullish_first,
                    bearish_first=bearish_first,
                    second_field=second_field,
                    bullish_second="BULLISH",
                    bearish_second="BEARISH",
                )
            )
        tests.extend(
            conditioned_tests(
                session=session,
                hypothesis_id="H6_LEVEL_MICRO_ACCEPTANCE",
                directional_field="FLOW_PRESSURE_W60",
                directional_states=directional,
                conditioner_field="ASIA_RANGE_COMPRESSION",
                conditioner_states=("LOW", "NORMAL", "HIGH"),
            )
        )

        tests.extend(
            conditioned_tests(
                session=session,
                hypothesis_id="H7_POSITIONING_AMPLIFICATION",
                directional_field="FLOW_DEPTH_ALIGNMENT",
                directional_states=directional,
                conditioner_field="COT_MANAGED_MONEY_CROWDING",
                conditioner_states=("CROWDED_LONGS", "CROWDED_SHORTS", "BALANCED"),
            )
        )
        tests.extend(
            conditioned_tests(
                session=session,
                hypothesis_id="H7_POSITIONING_AMPLIFICATION",
                directional_field="ABSORPTION_STATE_W60",
                directional_states=absorption,
                conditioner_field="COT_MANAGED_MONEY_CROWDING",
                conditioner_states=("CROWDED_LONGS", "CROWDED_SHORTS", "BALANCED"),
            )
        )
        tests.extend(
            conditioned_tests(
                session=session,
                hypothesis_id="H7_POSITIONING_AMPLIFICATION",
                directional_field="FLOW_DEPTH_ALIGNMENT",
                directional_states=directional,
                conditioner_field="COT_WEEKLY_CHANGE_SIGN",
                conditioner_states=("UP", "DOWN", "FLAT"),
            )
        )

        if session == "NEW_YORK":
            tests.extend(
                confirming_tests(
                    session=session,
                    hypothesis_id="H8_NEW_YORK_HANDOVER",
                    first_field="LONDON_PRE_NEW_YORK_DIRECTION",
                    bullish_first="UP",
                    bearish_first="DOWN",
                    second_field="FLOW_DEPTH_ALIGNMENT",
                    bullish_second="BULLISH",
                    bearish_second="BEARISH",
                )
            )
            tests.extend(
                confirming_tests(
                    session=session,
                    hypothesis_id="H8_NEW_YORK_HANDOVER",
                    first_field="LONDON_ASIA_INTERACTION_PRE_NEW_YORK",
                    bullish_first="ACCEPTED_ABOVE",
                    bearish_first="ACCEPTED_BELOW",
                    second_field="FLOW_PRESSURE_W60",
                    bullish_second="BULLISH",
                    bearish_second="BEARISH",
                )
            )

    tests.sort(key=lambda item: (item["stage"], item["session"], item["test_id"]))
    ids = [item["test_id"] for item in tests]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate immutable test_id")
    expected_counts = {
        (1, "LONDON"): 12,
        (1, "NEW_YORK"): 12,
        (2, "LONDON"): 60,
        (2, "NEW_YORK"): 64,
    }
    actual = {
        key: sum(item["stage"] == key[0] and item["session"] == key[1] for item in tests)
        for key in expected_counts
    }
    if actual != expected_counts:
        raise ValueError(f"Frozen test count changed: {actual}")
    return tests


def verify_metadata() -> dict[str, Any]:
    bindings = {
        "contract_file": CONTRACT_PATH,
        "feature_registry_file": FEATURE_REGISTRY_PATH,
        "step5c_manifest_file": STEP5C_MANIFEST_PATH,
        "step5c_verdict_file": STEP5C_VERDICT_PATH,
        "case_manifest_file": CASE_MANIFEST_PATH,
        "case_payload_file": CASE_PAYLOAD_PATH,
    }
    for name, path in bindings.items():
        actual = sha256_file(path)
        if actual != EXPECTED[name]:
            raise ValueError(f"Predecessor seal failed: {name} {actual}")

    contract = load_json(CONTRACT_PATH)
    feature_registry = load_json(FEATURE_REGISTRY_PATH)
    step5c_manifest = load_json(STEP5C_MANIFEST_PATH)
    step5c_verdict = load_json(STEP5C_VERDICT_PATH)
    case_manifest = load_json(CASE_MANIFEST_PATH)
    if step5c_manifest.get("manifest_hash") != EXPECTED["step5c_manifest_hash"]:
        raise ValueError("Step 5C manifest hash changed")
    if step5c_verdict.get("verdict_hash") != EXPECTED["step5c_verdict_hash"]:
        raise ValueError("Step 5C verdict hash changed")
    if step5c_manifest.get("status") != "PASS_STEP_5C_FEATURE_MATERIALIZATION":
        raise ValueError("Step 5C PASS missing")
    if not step5c_verdict.get("formal_pass"):
        raise ValueError("Step 5C formal verdict is not PASS")
    if step5c_manifest.get("development_outcomes_opened_or_joined"):
        raise ValueError("Step 5C outcome-blind boundary changed")
    if step5c_manifest.get("year_2025_or_2026_values_accessed"):
        raise ValueError("Step 5C holdout lock changed")
    if case_manifest.get("manifest_hash") != EXPECTED["case_manifest_hash"]:
        raise ValueError("Development case manifest hash changed")
    partition = case_manifest.get("development_partition", {})
    if partition.get("session_date_start_inclusive") != "2021-08-01":
        raise ValueError("Case source development start changed")
    if partition.get("session_date_end_inclusive") != "2024-12-31":
        raise ValueError("Case source contains a non-development partition")
    if case_manifest.get("case_counts", {}).get("total") != 1659:
        raise ValueError("Case source count changed")

    if contract.get("hypothesis_search_space", {}).get("maximum_conditions_per_test") != 2:
        raise ValueError("Maximum condition count changed")
    if not contract.get("hypothesis_search_space", {}).get("zero_candidates_acceptable"):
        raise ValueError("Zero-candidate rule changed")
    if feature_registry.get("status") != "FROZEN_BEFORE_METADATA_ESTIMATE_OR_RESEARCH_VALUE_ACCESS":
        raise ValueError("Feature registry freeze status changed")

    decision_artifacts = [
        item
        for item in step5c_manifest.get("artifacts", [])
        if str(item.get("path", "")).endswith("decision_features.parquet")
    ]
    if len(decision_artifacts) != 2:
        raise ValueError("Step 5C decision artifact count changed")
    if {item.get("sha256") for item in decision_artifacts} != {EXPECTED["step5c_decision_file"]}:
        raise ValueError("Step 5C decision artifact hashes changed")
    return {
        name: {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": EXPECTED[name]}
        for name, path in bindings.items()
    }


def main() -> None:
    if any(path.exists() for path in (PROTOCOL_PATH, TEST_REGISTRY_PATH, FREEZE_PATH)):
        raise FileExistsError("A Step 5D freeze artifact already exists; refusing to replace it")
    bindings = verify_metadata()
    tests = build_tests()
    frozen_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    test_registry: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_TEST_REGISTRY_V0_1",
        "status": "FROZEN_BEFORE_DEVELOPMENT_OUTCOME_ACCESS",
        "frozen_at_utc": frozen_at,
        "construction": {
            "stage_1": "Every preregistered directional state of the six directional microstructure fields, once per session.",
            "stage_2": "Only Step 5A registered variable pairs. Signed contexts use same-direction confirming states only; non-directional conditioners use every explicitly known registered state crossed with each registered directional micro state.",
            "unknown_state_exclusions": list(UNKNOWN_STATES),
            "contradictions_rejections_and_unregistered_states": "Descriptive only; never inverted, repaired, or promoted.",
        },
        "counts": {
            "total": len(tests),
            "stage_1": sum(item["stage"] == 1 for item in tests),
            "stage_2": sum(item["stage"] == 2 for item in tests),
            "london_stage_1": 12,
            "new_york_stage_1": 12,
            "london_stage_2": 60,
            "new_york_stage_2": 64,
        },
        "tests": tests,
    }
    test_registry["registry_hash"] = canonical_hash(test_registry)
    write_json_exclusive(TEST_REGISTRY_PATH, test_registry)
    test_registry_file_hash = sha256_file(TEST_REGISTRY_PATH)

    protocol: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_PROTOCOL_V0_1",
        "status": "FROZEN_BEFORE_DEVELOPMENT_OUTCOME_ACCESS",
        "classification": "DEVELOPMENT_CONDITIONAL_EDGE_DISCOVERY_ONLY",
        "frozen_at_utc": frozen_at,
        "authority": {
            "authorized_step": "STEP_5D",
            "authorized_partition": "SEALED_DEVELOPMENT_2021-11-08_THROUGH_2024-12-13_ONLY",
            "year_2025": "LOCKED",
            "year_2026": "LOCKED",
            "mandatory_stop": "Stop after Step 5D development results and independent reproduction are sealed.",
        },
        "predecessor_bindings": {
            **bindings,
            "step5c_manifest_hash": EXPECTED["step5c_manifest_hash"],
            "step5c_verdict_hash": EXPECTED["step5c_verdict_hash"],
            "step5c_decision_parquet_sha256": EXPECTED["step5c_decision_file"],
            "case_manifest_hash": EXPECTED["case_manifest_hash"],
            "test_registry_path": str(TEST_REGISTRY_PATH.relative_to(ROOT)).replace("\\", "/"),
            "test_registry_file_sha256": test_registry_file_hash,
            "test_registry_hash": test_registry["registry_hash"],
        },
        "row_identity_and_join": {
            "feature_rows": 376,
            "session_rows": {"LONDON": 188, "NEW_YORK": 188},
            "unique_key": ["session_date", "session_code"],
            "secondary_identity_checks": ["decision_at_utc", "row_id"],
            "selected_month_week_id_source": "sealed Step 5C row registry",
            "development_date_min": "2021-11-08",
            "development_date_max": "2024-12-13",
            "engineering_dates_excluded_permanently": [
                "2024-01-05",
                "2024-01-09",
                "2024-01-11",
                "2024-01-30",
                "2024-01-31",
                "2024-03-20",
            ],
            "documented_unavailable_rows": ["2022-04-15|LONDON", "2022-04-15|NEW_YORK"],
            "join_cardinality": "ONE_TO_ONE_FOR_374_AVAILABLE_ROWS_PLUS_EXACTLY_TWO_DOCUMENTED_UNKNOWN_ROWS",
            "duplicate_or_unexpected_missing_key": "FORMAL_INTEGRITY_FAILURE_AND_NO_TESTING",
        },
        "outcome_source_and_opening": {
            "source": "sealed V3 development case payload only",
            "source_file_sha256": EXPECTED["case_payload_file"],
            "source_manifest_hash": EXPECTED["case_manifest_hash"],
            "source_partition_end": "2024-12-31",
            "single_open_rule": "Stream the sealed gzip once. Inspect only metadata on unselected rows; deserialize subsequent_behaviour only for the 374 selected available keys.",
            "independent_extraction": "For each selected row, primary reads neutral_excursions signed close plus sealed net state; reference reads SESSION_CLOSE horizon displacement and recomputes the state. They must match exactly during the one source stream.",
            "outcome_projection": "Write only key, signed displacement, UP/DOWN/FLAT/UNKNOWN, observation end, and hashed lineage; no secondary outcome is admitted to testing.",
            "join_reproduction": "Join the single sealed projection independently to primary and reference Step 5C decision files and require byte-identical joined payloads.",
        },
        "neutral_outcome": {
            "instrument": "IC_MARKETS_MT5_XAUUSD",
            "reference": "Open of first complete one-minute bar opening exactly 08:01 local.",
            "end": "Final complete one-minute bar closing no later than 12:00 local.",
            "signed_displacement": "final_close minus reference_open in USD per troy ounce",
            "states": {
                "UP": "signed_displacement > +0.01",
                "DOWN": "signed_displacement < -0.01",
                "FLAT": "absolute signed_displacement <= 0.01",
                "UNKNOWN": "missing, incomplete, timestamp-invalid, lineage-invalid, or documented unavailable",
            },
            "binary_inference": "UP and DOWN only",
            "flat_policy": "Retain and report; exclude from binary effects and support; include in known signed-displacement median gate.",
            "secondary_outcomes": "Not loaded into the joined analysis payload and never used for selection, ranking, rescue, or rejection.",
        },
        "known_and_missing_policy": {
            "constituent_known": "state is not an unknown-state exclusion, epistemic_status is not UNKNOWN, quality is neither MISSING nor INVALID, and source_signature is not UNKNOWN",
            "unknown_state_exclusions": list(UNKNOWN_STATES),
            "test_known": "Every constituent is known and the primary outcome is UP, DOWN, or FLAT.",
            "binary_known": "Every constituent is known and the primary outcome is UP or DOWN.",
            "unknown_is_never": ["zero", "flat", "normal", "no-event", "balanced", "confirmation", "complement support"],
            "pairwise_exclusion": True,
            "repair_backfill_or_relabel": False,
        },
        "stage_order": {
            "stage_1": "Run and independently reproduce the complete Stage-1 family, apply BH, write and seal the complete table.",
            "stage_2_gate": "Stage 2 may begin only after the Stage-1 manifest and verdict verify.",
            "stage_2": "Run only the 124 registered two-condition tests and independently reproduce the complete family.",
            "optional_stopping": False,
        },
        "support_gates": {
            "known_coverage_minimum_fraction": 0.70,
            "coverage_denominator": "All 188 frozen rows in the applicable session, including the documented unavailable row.",
            "test_known_coverage": "Joint constituent-known plus primary-outcome-known fraction must meet 0.70.",
            "interaction_constituent_coverage": "Each constituent field separately must meet 0.70.",
            "standalone": {
                "condition_binary_rows_min": 40,
                "complement_binary_rows_min": 80,
                "condition_distinct_weeks_min": 12,
                "complement_distinct_weeks_min": 20,
                "calendar_years_with_at_least_condition_rows": {"minimum_years": 3, "rows_per_year": 5},
            },
            "interaction": {
                "condition_binary_rows_min": 30,
                "complement_binary_rows_min": 100,
                "condition_distinct_weeks_min": 10,
                "complement_distinct_weeks_min": 24,
                "calendar_years_with_at_least_condition_rows": {"minimum_years": 3, "rows_per_year": 4},
            },
            "support_failure": "SUPPORT_FAIL; descriptive counts only; no p-value, q-value, candidate, or advancement credit.",
        },
        "effect_and_uncertainty": {
            "effect_percentage_points": "100 * (Pr(favorable direction|condition) - Pr(favorable direction|known complement))",
            "bootstrap": {
                "method": "calendar-year-stratified selected-week cluster bootstrap",
                "replicates": 20000,
                "sampling": "Within each year sample its distinct selected_month_week_id clusters with replacement, preserving every selected row in a sampled cluster.",
                "interval": "2.5th and 97.5th Type-7 linear percentiles of finite replicate effects",
                "minimum_finite_replicates": 19000,
                "seed": "Exact uint64 stored per test in frozen test registry",
            },
            "permutation": {
                "method": "two-sided calendar-year-stratified selected-week outcome-block permutation",
                "replicates": 100000,
                "block": "Within year, permute whole five-weekday outcome vectors among selected_month_week_id clusters; fixed condition rows receive the permuted outcome from the same weekday slot. Missing slots remain UNKNOWN.",
                "statistic": "Absolute favorable-direction percentage-point effect",
                "finite_rule": "A replicate without both condition and complement binary outcomes is non-extreme and separately counted; support eligibility makes this exceptional.",
                "p_value": "(1 + count(abs(permuted_effect) >= abs(observed_effect))) / (100000 + 1)",
                "seed": "Exact uint64 stored per test in frozen test registry",
            },
            "multiplicity": {
                "method": "Benjamini-Hochberg",
                "fdr_q": 0.05,
                "families": ["LONDON_STAGE_1", "NEW_YORK_STAGE_1", "LONDON_STAGE_2", "NEW_YORK_STAGE_2"],
                "members": "Every support-eligible preregistered test, including negative and contrary results.",
                "tie_break": "immutable test_id ascending",
            },
        },
        "stability": {
            "annual": {
                "blocks": [2021, 2022, 2023, 2024],
                "supported": "At least the stage-specific per-year condition floor (5 standalone; 4 interaction) and at least one complement binary row.",
                "gate": "At least three supported annual blocks have effect >0; no supported annual effect is <= -10 percentage points.",
            },
            "leave_one_year_out": "For each of four omitted years, require condition and complement binary support >0 and effect >0.",
            "rolling": {
                "window": "12 consecutive selected monthly weeks advanced one selected month at a time",
                "expected_windows": 27,
                "evaluable": "At least one condition and one complement binary row",
                "minimum_evaluable_windows": 10,
                "minimum_positive_fraction": 0.70,
            },
            "median_signed_displacement": "Median across every condition row with a known signed displacement, including FLAT; must be >0 for UP and <0 for DOWN.",
        },
        "decision_rules": {
            "SUPPORT_FAIL": "Any frozen support gate fails.",
            "REJECT": "Support passes but one or more advancement gates fail.",
            "PASS": "All support and advancement gates pass; label PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED.",
            "advancement": {
                "minimum_effect_pp": {"stage_1": 10.0, "stage_2": 15.0},
                "bootstrap_lower_95pct_gt_zero": True,
                "bh_q_lte": 0.05,
                "median_signed_displacement_matches_direction": True,
                "all_stability_gates": True,
            },
            "maximum_provisional_candidates_per_session": 2,
            "ranking_order": [
                "lowest BH q",
                "highest bootstrap lower 95 percent bound",
                "largest favorable effect",
                "largest condition distinct-week support",
                "lexicographically smallest immutable test_id",
            ],
            "overflow": "A passing test outside the top two is recorded PASS_NOT_SHORTLISTED_CAP; it is not a provisional candidate.",
            "zero_candidates_acceptable": True,
        },
        "independent_reproduction": {
            "primary": "NumPy mask/vectorized block-resampling implementation over the primary Step 5C joined file.",
            "reference": "Separately coded indexed/group-loop implementation over the reference Step 5C joined file using the same frozen random schedules.",
            "required_exact": [
                "joined row identities and values",
                "test IDs and condition/complement classifications",
                "support counts",
                "effect estimates",
                "bootstrap finite counts and percentile bounds",
                "permutation extreme counts and p-values",
                "BH q-values",
                "annual leave-one-year-out and rolling diagnostics",
                "verdicts rankings and complete-result checksums",
            ],
        },
        "prohibited": [
            "adding retuning repairing inverting or selectively filtering a test",
            "raw feature search or threshold search",
            "three-way interaction",
            "opening any 2025 or 2026 value",
            "using a secondary outcome as a gate",
            "execution entry exit stop target sizing slippage trade PnL R or return calculation",
            "acquisition or charge",
        ],
    }
    protocol["protocol_hash"] = canonical_hash(protocol)
    write_json_exclusive(PROTOCOL_PATH, protocol)
    protocol_file_hash = sha256_file(PROTOCOL_PATH)

    freeze: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_FREEZE_V0_1",
        "status": "SEALED_BEFORE_DEVELOPMENT_OUTCOME_ACCESS",
        "frozen_at_utc": frozen_at,
        "development_outcomes_accessed_before_freeze": False,
        "market_outcome_values_accessed_before_freeze": False,
        "year_2025_or_2026_values_accessed": False,
        "files": {
            "protocol": {
                "path": str(PROTOCOL_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": protocol_file_hash,
                "canonical_hash": protocol["protocol_hash"],
            },
            "test_registry": {
                "path": str(TEST_REGISTRY_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": test_registry_file_hash,
                "canonical_hash": test_registry["registry_hash"],
            },
        },
        "predecessor_file_hashes": {name: record["sha256"] for name, record in bindings.items()},
        "predecessor_semantic_hashes": {
            "step5c_manifest_hash": EXPECTED["step5c_manifest_hash"],
            "step5c_verdict_hash": EXPECTED["step5c_verdict_hash"],
            "case_manifest_hash": EXPECTED["case_manifest_hash"],
        },
        "frozen_test_counts": test_registry["counts"],
        "next_action": "Only the sealed Step 5D outcome opening, Stage 1, Stage 2, reproduction, and final seal are authorized.",
    }
    freeze["freeze_receipt"] = canonical_hash(freeze)
    write_json_exclusive(FREEZE_PATH, freeze)

    print(
        json.dumps(
            {
                "status": freeze["status"],
                "protocol_sha256": protocol_file_hash,
                "test_registry_sha256": test_registry_file_hash,
                "freeze_sha256": sha256_file(FREEZE_PATH),
                "freeze_receipt": freeze["freeze_receipt"],
                "test_counts": test_registry["counts"],
                "development_outcomes_accessed": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
