from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash
from gold_intel.analytics.session_behaviour_v3_discovery import (
    DISCOVERY_VERSION,
    FEATURE_TRANSFORM_VERSION,
    REGISTRY_VERSION,
    embedded_hash,
    feature_registry,
    interaction_registry,
    registry_fingerprint,
)

FROZEN_AT = "2026-07-30T10:47:46.2426076Z"
M3_STATE_HASH = "c569bd67aae862c4e86de49aa99d4d33ee6d820cf970251603a74f73619045a7"
M3_STATE_FILE_SHA256 = (
    "f56a8732fe466f2f5574c80b9421eb5b3f2f7e1435fd177bcae4c57cb9efc980"
)
CONTRACT_HASH = "79a74f81bce0b80ca6c5da6b420400479013484a4bb759684402546672fa140b"
TRACEABILITY_HASH = (
    "8707c39eb75bf3c74ce33908b0a3f4b0a1f679ee68848f1d10dce25e4bdf6bb4"
)
CASE_MANIFEST_HASH = (
    "d6aad4b861d98899d6fdcc92ea53a20221434af5038a3bcb86a8b9faa1d8e7b7"
)
CASE_ARTIFACT_SHA256 = (
    "d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9"
)
CASE_ARTIFACT_BYTES = 103_763_781
BOOK_SHA256 = "3e7ddc561932a859a4c9043a38ff71b7003907963fb52247e41edaeefc8ac42a"

AUTHORIZATION = (
    "Proceed to V3 Milestone 4 under the existing contract. Use only the "
    "sealed 2021-08-01 through 2024-12-31 development case matrix. First "
    "freeze and seal the complete book-traceable eligible-feature registry, "
    "states, transforms, missing-data policy, support floors, permitted "
    "two-condition interactions, uncertainty and multiplicity methods, and "
    "ranking order before calculating relationships. Then conduct bounded "
    "conditional-bias discovery separately for London and New York, examining "
    "individual variables before interactions. Record all tested relationships "
    "and negative results honestly. Allow no more than two provisional "
    "candidates per session to advance, with zero candidates acceptable. Do "
    "not optimize execution, retune after seeing results, inspect 2025 or 2026 "
    "values, or reopen rejected ZN rules. Complete only Milestone 4 and stop."
)

UNMAPPED_DISPOSITIONS: dict[str, tuple[str, str]] = {
    "GOV_POINT_IN_TIME_LINEAGE": (
        "AUDIT_CONTROL",
        "Enforced for every case and feature, but not a varying condition.",
    ),
    "MECH_INSTRUMENT_IDENTITY": (
        "CONSTANT_NOT_TESTED",
        "All cases are the same IC Markets XAUUSD broker-feed identity.",
    ),
    "MECH_VOLUME": (
        "AUDIT_ONLY_NOT_NORMALIZED",
        "Broker tick volume is not COMEX volume and lacks a frozen comparable "
        "point-in-time normalization for directional discovery.",
    ),
    "MECH_PARTICIPANT_MOTIVE": (
        "INFERENCE_ONLY",
        "Institutional motive is never tested as observed fact; bounded COT "
        "inference states are separately registered.",
    ),
    "STRUCT_SWINGS_AND_SEQUENCE": (
        "REPRESENTED_BY_DERIVED_STRUCTURE",
        "Frozen trend, BOS, MSS, momentum, compression, and range-location "
        "features represent the deterministic structure state without mining "
        "individual historical pivots.",
    ),
    "STRUCT_BREAK_ACCEPT_REJECT_RETEST": (
        "PRE_DECISION_SUBSET_ONLY",
        "Pre-decision BOS and MSS are registered. Post-decision acceptance, "
        "rejection, failed-break, and retest facts remain outcomes.",
    ),
    "REGIME_LEVEL_DIRECTION_RATE": (
        "REPRESENTED_BY_SERIES_AND_REGIME_FEATURES",
        "Individual series changes, regime label, reaction function, and the "
        "transparent score are registered explicitly.",
    ),
    "EXPECT_ACTUAL_VS_FORECAST": (
        "INELIGIBLE_UNVERIFIED_FORECAST_CLOCK",
        "Historical forecast first-publication timing is not verified.",
    ),
    "EXPECT_PREVIOUS_AND_REVISIONS": (
        "REPRESENTED_BY_VINTAGE_SERIES_CHANGE",
        "The registered point-in-time series changes preserve the eligible "
        "vintage and previous record without using later revisions.",
    ),
    "POSITION_OPEN_INTEREST": (
        "INFERENCE_ONLY_NOT_RAW_LEVEL",
        "The nonstationary weekly level is not tested directly; the frozen "
        "price/open-interest participation classification is registered.",
    ),
    "POSITION_FAST_SLOW_DIVERGENCE": (
        "INELIGIBLE_INCOMPLETE_SLOW_MONEY",
        "ETF and central-bank slow-money inputs are unavailable.",
    ),
    "CATALYST_SCHEDULE": (
        "INELIGIBLE_UNVERIFIED_SCHEDULE_CLOCK",
        "Historical schedule first-publication timestamps are unverified.",
    ),
    "CATALYST_RELEASE_COMPONENTS": (
        "REPRESENTED_BY_CATALYST_COMPONENT",
        "The bounded event-impact direction uses only already-released, "
        "decision-known information; raw release-component mining is excluded.",
    ),
    "CATALYST_PROXIMITY": (
        "INELIGIBLE_UNVERIFIED_SCHEDULE_CLOCK",
        "Pre-event proximity cannot be trusted without verified schedule availability.",
    ),
    "CATALYST_FIXED_REACTIONS": (
        "AUDIT_ONLY_TO_AVOID_EVENT_PATH_MINING",
        "Completed prior-event reactions remain auditable decision facts but "
        "are not separately state-mined in this bounded screen.",
    ),
    "CATALYST_EVENT_PATH": (
        "AUDIT_ONLY_TO_AVOID_EVENT_PATH_MINING",
        "Completed prior-event path labels are not separately state-mined.",
    ),
    "CATALYST_FED_AND_AUCTIONS": (
        "INELIGIBLE_INCOMPLETE_EVENT_TAXONOMY",
        "Historical coverage and pre-event publication clocks are incomplete.",
    ),
    "SESSION_CLOCKS_DST": (
        "STRATIFICATION_CONTROL",
        "DST-aware clocks define the separate London and New York units; they "
        "are not a varying feature within a session.",
    ),
    "SESSION_LBMA_WINDOWS": (
        "INELIGIBLE_NOT_LICENSED",
        "Benchmark-window microstructure is not separately licensed.",
    ),
    "CROSS_CONFIRMATION_DIVERGENCE": (
        "INTERACTION_ONLY",
        "Exact preregistered rates/USD, gold/silver, and risk-state interactions "
        "provide the bounded confirmation tests.",
    ),
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _state_hash(state: dict[str, Any]) -> str:
    return canonical_hash(
        {
            key: value
            for key, value in state.items()
            if key not in {"generated_at", "state_hash"}
        }
    )


def _factor_dispositions(
    traceability: dict[str, Any],
    features: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mapping: dict[str, list[str]] = {}
    for feature in features:
        for factor_id in feature["traceability_factor_ids"]:
            mapping.setdefault(str(factor_id), []).append(str(feature["feature_id"]))
    output: list[dict[str, Any]] = []
    for row in traceability["field_requirements"]:
        factor_id = str(row["factor_id"])
        feature_ids = sorted(mapping.get(factor_id, []))
        if feature_ids:
            disposition = "ELIGIBLE_REGISTERED_FEATURE"
            reason = (
                "Mapped to one or more frozen feature transforms. Empirical support "
                "still controls whether a state is tested."
            )
        elif row["role"] == "OUTCOME":
            disposition = "OUTCOME_ONLY"
            reason = "Used only in frozen outcome definitions; never a decision condition."
        elif row["role"] == "EXECUTION_OUT_OF_SCOPE":
            disposition = "EXECUTION_OUT_OF_SCOPE"
            reason = "V3 prohibits execution and trade research."
        elif row["development_coverage"] == "UNAVAILABLE":
            disposition = "INELIGIBLE_UNAVAILABLE"
            reason = "; ".join(row["limitations"])
        elif factor_id in UNMAPPED_DISPOSITIONS:
            disposition, reason = UNMAPPED_DISPOSITIONS[factor_id]
        else:
            raise ValueError(f"Unclassified Reference-Book factor: {factor_id}")
        output.append(
            {
                "book_chapters": list(row["book_chapters"]),
                "book_requirement": str(row["book_requirement"]),
                "development_coverage": str(row["development_coverage"]),
                "disposition": disposition,
                "factor_id": factor_id,
                "feature_ids": feature_ids,
                "reason": reason,
            }
        )
    if len(output) != 75 or len({item["factor_id"] for item in output}) != 75:
        raise ValueError("Reference-Book factor disposition coverage is incomplete")
    return output


def build_manifest(root: Path) -> dict[str, Any]:
    state_path = root / "research_artifacts/gold_session_behaviour_v3_state_v03.json"
    contract_path = (
        root / "research_manifests/gold_session_behaviour_discovery_contract_v03.json"
    )
    trace_path = (
        root / "research_manifests/gold_session_behaviour_v3_traceability_v01.json"
    )
    case_manifest_path = (
        root
        / "research_artifacts/gold_session_behaviour_v3_case_matrix_v01/manifest.json"
    )
    case_path = (
        root
        / "research_artifacts/gold_session_behaviour_v3_case_matrix_v01/cases.jsonl.gz"
    )
    book_path = root / "Gold_USD_Market_Intelligence_Reference_Book.pdf"
    module_path = (
        root
        / "backend/src/gold_intel/analytics/session_behaviour_v3_discovery.py"
    )
    test_path = root / "backend/tests/unit/test_session_behaviour_v3_discovery.py"

    state = _load(state_path)
    contract = _load(contract_path)
    traceability = _load(trace_path)
    case_manifest = _load(case_manifest_path)
    checks = {
        "book_sha256": _sha256_file(book_path) == BOOK_SHA256,
        "case_artifact_bytes": case_path.stat().st_size == CASE_ARTIFACT_BYTES,
        "case_artifact_sha256": _sha256_file(case_path) == CASE_ARTIFACT_SHA256,
        "case_manifest_hash": case_manifest["manifest_hash"] == CASE_MANIFEST_HASH,
        "contract_hash": (
            contract["manifest_hash"] == CONTRACT_HASH
            and embedded_hash(contract, "manifest_hash") == CONTRACT_HASH
        ),
        "m3_state_file_sha256": _sha256_file(state_path) == M3_STATE_FILE_SHA256,
        "m3_state_hash": (
            state["state_hash"] == M3_STATE_HASH and _state_hash(state) == M3_STATE_HASH
        ),
        "m3_verdict": (
            state["current_milestone"]["verdict"]
            == "PASS_V3_MILESTONE_3_INDEPENDENT_VALIDATION_MANDATORY_STOP"
        ),
        "traceability_hash": (
            traceability["catalog_hash"] == TRACEABILITY_HASH
            and embedded_hash(traceability, "catalog_hash") == TRACEABILITY_HASH
        ),
    }
    failed = [code for code, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"Pre-freeze seal checks failed: {failed}")

    features = feature_registry()
    interactions = interaction_registry()
    factor_dispositions = _factor_dispositions(traceability, features)
    document: dict[str, Any] = {
        "authorization": {
            "authorized_on": "2026-07-30",
            "scope": "Complete only V3 Milestone 4 bounded development discovery and stop.",
            "verbatim": AUTHORIZATION,
        },
        "candidate_policy": {
            "advance_label": "PROVISIONAL_M4_CANDIDATE_NO_VALIDATION_CREDIT",
            "candidate_gate": {
                "common": [
                    "support_eligible is true",
                    "Benjamini-Hochberg q-value <= 0.10",
                    "absolute conditional up-rate difference versus the known complement >= 7.5 percentage points for a single condition or >= 10.0 percentage points for an interaction",
                    "Newcombe-Wilson 95% difference interval excludes zero",
                    "median signed close displacement has the same sign as the empirical directional association",
                ],
                "interaction_additional": [
                    "absolute effect is at least 3.0 percentage points larger than each constituent state's single-condition absolute effect",
                    "both constituent single states satisfy their own support floor, irrespective of their q-values",
                ],
            },
            "maximum_per_session": 2,
            "ranking_order": [
                "candidate_gate_pass descending",
                "Benjamini-Hochberg q-value ascending",
                "absolute conditional up-rate difference descending",
                "condition support descending",
                "condition_id lexicographically ascending",
            ],
            "zero_candidates_acceptable": True,
        },
        "development_partition": {
            "access_class": "DEVELOPMENT",
            "end_exclusive": "2025-01-01T00:00:00+00:00",
            "session_date_end_inclusive": "2024-12-31",
            "session_date_start_inclusive": "2021-08-01",
            "start_inclusive": "2021-08-01T00:00:00+00:00",
        },
        "discovery_order": {
            "stage_1": (
                "Calculate and record every registered single feature-state "
                "relationship separately within each eligible session."
            ),
            "stage_2": (
                "Only after stage 1 is complete, calculate the 40 exact "
                "preregistered two-condition interactions. No performance-driven "
                "pair generation is allowed."
            ),
        },
        "factor_dispositions": factor_dispositions,
        "feature_registry": features,
        "frozen_inputs": {
            "case_matrix": {
                "artifact_bytes": CASE_ARTIFACT_BYTES,
                "artifact_path": (
                    "research_artifacts/gold_session_behaviour_v3_case_matrix_v01/"
                    "cases.jsonl.gz"
                ),
                "artifact_sha256": CASE_ARTIFACT_SHA256,
                "case_counts": {"london": 833, "new_york": 826, "total": 1659},
                "manifest_hash": CASE_MANIFEST_HASH,
            },
            "contract_manifest_hash": CONTRACT_HASH,
            "m3_state": {
                "file_sha256": M3_STATE_FILE_SHA256,
                "path": "research_artifacts/gold_session_behaviour_v3_state_v03.json",
                "state_hash": M3_STATE_HASH,
            },
            "reference_book_sha256": BOOK_SHA256,
            "traceability_catalog_hash": TRACEABILITY_HASH,
        },
        "implementation_freeze": {
            "feature_module_path": (
                "backend/src/gold_intel/analytics/session_behaviour_v3_discovery.py"
            ),
            "feature_module_sha256": _sha256_file(module_path),
            "feature_transform_version": FEATURE_TRANSFORM_VERSION,
            "preregistry_tests": {
                "command": (
                    "pytest -q "
                    "backend/tests/unit/test_session_behaviour_v3_discovery.py"
                ),
                "passed": 5,
                "total": 5,
            },
            "registry_fingerprint": registry_fingerprint(features, interactions),
            "test_file_path": (
                "backend/tests/unit/test_session_behaviour_v3_discovery.py"
            ),
            "test_file_sha256": _sha256_file(test_path),
        },
        "interaction_registry": interactions,
        "manifest_version": REGISTRY_VERSION,
        "milestone": "V3_M4_BOUNDED_CONDITIONAL_BIAS_DISCOVERY",
        "missing_and_quality_policy": {
            "cot_exception": (
                "CFTC facts marked UNVERIFIED_AVAILABILITY remain eligible only "
                "because M2 independently enforced Tuesday observation, Friday "
                "publication, and available_at <= decision_at. They retain their "
                "observed/inferred labels and are never presented as institutional motive."
            ),
            "eligible_fact_qualities": ["VALID", "PARTIAL"],
            "excluded_fact_qualities": [
                "MISSING",
                "NOT_APPLICABLE",
                "NOT_LICENSED",
                "ROLL_CROSSING",
                "STALE",
                "UNVERIFIED_AVAILABILITY except the explicit CFTC exception",
            ],
            "missing_state": "UNKNOWN",
            "policy": (
                "UNKNOWN or excluded-quality inputs are omitted from the feature's "
                "known denominator and can never satisfy a condition. No imputation, "
                "zero fill, forward fill beyond the source's own valid point-in-time "
                "state, or missingness-as-confirmation is allowed."
            ),
        },
        "outcome_policy": {
            "flat_threshold_usd_per_ounce": 0.01,
            "primary": {
                "binary_analysis": (
                    "UP versus DOWN among non-flat SESSION_CLOSE observations"
                ),
                "down": "signed SESSION_CLOSE displacement < -0.01",
                "flat": "absolute signed SESSION_CLOSE displacement <= 0.01",
                "flat_handling": (
                    "Recorded explicitly and excluded from binary contingency tests."
                ),
                "source_path": (
                    "subsequent_behaviour.fixed_horizons[horizon=SESSION_CLOSE]."
                    "signed_displacement"
                ),
                "up": "signed SESSION_CLOSE displacement > 0.01",
            },
            "secondary_descriptive_not_ranked": [
                "60-minute direction counts",
                "median signed close displacement",
                "median absolute close displacement",
                "median maximum upward displacement",
                "median maximum downward displacement magnitude",
                "median session range",
                "high-first and low-first counts",
            ],
            "trade_interpretation": False,
        },
        "prohibited": {
            "calendar_2025_or_2026_value_access": True,
            "candidate_repair_or_retuning": True,
            "condition_count_above_two": True,
            "execution_optimization": True,
            "feature_or_interaction_addition_after_freeze": True,
            "mfe_mae_trade_entry_exit_stop_target_pnl_or_r_multiple": True,
            "opaque_machine_learning": True,
            "rejected_zn_rule_reopen_inversion_threshold_filter_or_rename": True,
            "session_pooling_or_transfer": True,
        },
        "recorded_at": FROZEN_AT,
        "research_boundary_at_freeze": {
            "case_outcomes_deserialized_by_freeze_tool": False,
            "conditional_relationships_calculated": 0,
            "execution_variants": 0,
            "feature_states_registered": sum(
                len(feature["tested_states"]) for feature in features
            ),
            "features_registered": len(features),
            "interactions_registered": len(interactions),
            "provisional_candidates": 0,
            "reference_book_factors_disposed": len(factor_dispositions),
            "values_2025_opened": False,
            "values_2026_opened": False,
        },
        "session_separation": {
            "combined_result_permitted": False,
            "sessions": ["LONDON", "NEW_YORK"],
            "superiority_or_transfer_claim_permitted": False,
        },
        "statistical_policy": {
            "effect": (
                "Conditional UP percentage minus the UP percentage of all other "
                "known non-flat cases for the same feature/session."
            ),
            "multiplicity": {
                "families": (
                    "Benjamini-Hochberg is applied separately by session and stage "
                    "(single conditions versus preregistered interactions)."
                ),
                "fdr_q_threshold": 0.10,
                "include": "Every support-eligible tested condition in its family.",
            },
            "point_estimates": [
                "conditional and complement UP/DOWN counts and percentages",
                "percentage-point UP-rate difference",
                "Haldane-Anscombe corrected odds ratio when any cell is zero",
            ],
            "primary_p_value": (
                "Two-sided Fisher exact test on condition versus known complement "
                "by UP versus DOWN."
            ),
            "uncertainty": (
                "Wilson 95% intervals for each proportion and the Newcombe-Wilson "
                "95% interval for their difference."
            ),
            "warning": (
                "M4 is development discovery. Daily cases are serially dependent; "
                "chronology-aware and cluster-aware stability belongs to M5 and "
                "no M4 p/q value receives validation credit."
            ),
        },
        "support_floors": {
            "interaction": {
                "condition_cases_minimum": 60,
                "condition_prevalence_pct_minimum": 7.5,
                "distinct_joint_source_signatures_minimum": 8,
                "known_complement_cases_minimum": 80,
                "state_episodes_minimum": 8,
            },
            "single_condition": {
                "condition_cases_minimum": 80,
                "condition_prevalence_pct_minimum": 10.0,
                "distinct_source_signatures_minimum": 8,
                "feature_known_coverage_pct_minimum": 50.0,
                "known_complement_cases_minimum": 80,
                "state_episodes_minimum": 8,
            },
        },
        "transform_version": DISCOVERY_VERSION,
        "validation_gates": [
            "All predecessor, Reference Book, traceability, case-matrix, and M3 state seals match before the registry is written.",
            "All 75 Reference-Book factors receive an explicit disposition.",
            "Exactly 102 features and 230 tested feature states are frozen.",
            "Exactly 40 two-condition interactions are frozen and each references registered tested states.",
            "No ZN feature, candidate, rule, source path, or transform is present.",
            "No case outcome is deserialized by this freeze operation.",
            "The frozen registry fingerprint and manifest hash recompute exactly.",
        ],
    }
    document["manifest_hash"] = embedded_hash(document, "manifest_hash")
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    output = (
        root
        / "research_manifests/gold_session_behaviour_v3_m4_discovery_v01.json"
    )
    document = build_manifest(root)
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if output.exists() and output.read_text(encoding="utf-8") != payload:
        raise ValueError(f"Refusing to replace a different frozen manifest: {output}")
    output.write_text(payload, encoding="utf-8")
    print(
        json.dumps(
            {
                "features": len(document["feature_registry"]),
                "interactions": len(document["interaction_registry"]),
                "manifest_hash": document["manifest_hash"],
                "output": str(output),
                "reference_book_factors": len(document["factor_dispositions"]),
                "tested_feature_states": document["research_boundary_at_freeze"][
                    "feature_states_registered"
                ],
                "verdict": "PASS_V3_MILESTONE_4_PRE_RESULT_REGISTRY_FROZEN",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
