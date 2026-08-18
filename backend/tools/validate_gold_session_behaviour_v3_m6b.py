from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.session_behaviour_v3 import sha256_file
from gold_intel.analytics.session_behaviour_v3_m6a import (
    M5_SHORTLIST_CODES,
    protocol_fingerprint,
)
from gold_intel.analytics.session_behaviour_v3_m6b import (
    forward_case_hash,
)

VALIDATION_VERSION = (
    "GOLD_SESSION_BEHAVIOUR_V3_M6B_INDEPENDENT_REPRODUCTION_V0_1"
)
Z_95 = 1.959963984540054

CANDIDATES = (
    {
        "candidate_code": "LONDON_VOLATILITY_DIRECTION_V0_1",
        "session_code": "LONDON",
        "feature_id": "MACRO_VOLATILITY_CHANGE",
        "source_series_code": "US_VOLATILITY_INDEX",
    },
    {
        "candidate_code": "NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1",
        "session_code": "NEW_YORK",
        "feature_id": "MACRO_FINANCIAL_STRESS_CHANGE",
        "source_series_code": "US_FINANCIAL_STRESS",
    },
)


def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    bundle_path = (root / args.bundle).resolve()
    manifest_path = (root / args.manifest).resolve()
    output_path = (root / args.output).resolve()
    for path in (bundle_path, manifest_path, output_path):
        _assert_within(root, path)
    if output_path.exists():
        raise FileExistsError("M6B independent validation seal already exists")

    bundle = _load_json(bundle_path)
    manifest = _load_json(manifest_path)
    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "RESULT_BUNDLE_HASH_VALID",
            _embedded_hash(
                bundle,
                "bundle_hash",
                excluded=("created_at",),
            )
            == bundle["bundle_hash"],
        )
    )
    checks.append(
        _check(
            "RESULT_MANIFEST_HASH_VALID",
            _embedded_hash(manifest, "manifest_hash")
            == manifest["manifest_hash"],
        )
    )
    checks.append(
        _check(
            "PROTOCOL_AND_CANDIDATE_INVENTORY_FROZEN",
            bundle["preopen_manifest"]
            and [item["candidate_code"] for item in CANDIDATES]
            == list(M5_SHORTLIST_CODES)
            and protocol_fingerprint()
            == "308ff594d85b478b755f85397d19ed7e76faad50fa447af29f7ee8692dcd54de",
        )
    )

    reproduced_segments: list[dict[str, Any]] = []
    expected_order = [
        "EXPOSED_CALENDAR_2025",
        "LOCKED_2026_YTD",
    ]
    for index, segment_ref in enumerate(bundle["segment_manifests"]):
        segment_manifest_path = (root / segment_ref["path"]).resolve()
        segment_manifest = _load_json(segment_manifest_path)
        segment_code = str(segment_manifest["segment"]["segment_code"])
        checks.append(
            _check(
                f"{segment_code}::REPORTING_ORDER",
                segment_code == expected_order[index],
            )
        )
        checks.append(
            _check(
                f"{segment_code}::MANIFEST_FILE_AND_EMBEDDED_HASH_VALID",
                sha256_file(segment_manifest_path)
                == segment_ref["file_sha256"]
                and _embedded_hash(segment_manifest, "manifest_hash")
                == segment_manifest["manifest_hash"]
                == segment_ref["manifest_hash"],
            )
        )
        cases_path = (
            root / segment_manifest["case_artifact"]["path"]
        ).resolve()
        result_path = (
            root / segment_manifest["result_artifact"]["path"]
        ).resolve()
        cases = _load_jsonl(cases_path)
        result = _load_json(result_path)
        checks.append(
            _check(
                f"{segment_code}::SEALED_CASE_AND_RESULT_FILES_VALID",
                sha256_file(cases_path)
                == segment_manifest["case_artifact"]["file_sha256"]
                and sha256_file(result_path)
                == segment_manifest["result_artifact"]["file_sha256"]
                and len(cases)
                == int(segment_manifest["case_artifact"]["case_count"]),
            )
        )
        case_checks = _validate_cases(cases, segment_code=segment_code)
        checks.extend(case_checks)
        reproduced = _independent_segment(cases, segment_code=segment_code)
        reproduced_segments.append(reproduced)
        checks.extend(
            _compare_segment(
                recorded=result,
                reproduced=reproduced,
                segment_code=segment_code,
            )
        )

    prospective = bundle["prospective_ledger"]
    prospective_manifest_path = (root / prospective["manifest_path"]).resolve()
    prospective_manifest = _load_json(prospective_manifest_path)
    ledger_path = (root / prospective["ledger_path"]).resolve()
    checks.append(
        _check(
            "PROSPECTIVE_LEDGER_INITIALIZED_EMPTY_APPEND_ONLY_NO_BACKFILL",
            sha256_file(prospective_manifest_path)
            == prospective["manifest_file_sha256"]
            and _embedded_hash(prospective_manifest, "manifest_hash")
            == prospective_manifest["manifest_hash"]
            and sha256_file(ledger_path)
            == hashlib.sha256(b"").hexdigest()
            == prospective["ledger_file_sha256"]
            and int(prospective["record_count"]) == 0
            and int(prospective["backfilled_decisions"]) == 0
            and prospective_manifest["policy"][
                "missed_decision_backfill_permitted"
            ]
            is False,
        )
    )
    independent_overall = _overall(reproduced_segments)
    checks.append(
        _check(
            "OVERALL_CANDIDATE_VERDICTS_REPRODUCED",
            independent_overall == bundle["overall_candidate_verdicts"],
        )
    )
    boundary = bundle["research_boundary"]
    checks.append(
        _check(
            "NO_RETUNING_EXECUTION_COT_ZN_OR_RETURNS",
            boundary["candidate_definitions_changed"] is False
            and int(boundary["new_variables_or_candidates"]) == 0
            and boundary["thresholds_retuned"] is False
            and int(boundary["execution_variants"]) == 0
            and int(boundary["trades_or_returns"]) == 0
            and boundary["cot_used_as_pass_gate"] is False
            and boundary["rejected_candidates_or_zn_rules_reopened"] is False,
        )
    )

    failed = [item for item in checks if item["status"] != "PASS"]
    validation: dict[str, Any] = {
        "validation_version": VALIDATION_VERSION,
        "milestone": "V3_M6B_ONE_TIME_FORWARD_VALUE_EVALUATION",
        "validated_at": datetime.now().astimezone().isoformat(),
        "result_bundle": {
            "path": _portable(bundle_path),
            "file_sha256": sha256_file(bundle_path),
            "bundle_hash": bundle["bundle_hash"],
        },
        "result_manifest": {
            "path": _portable(manifest_path),
            "file_sha256": sha256_file(manifest_path),
            "manifest_hash": manifest["manifest_hash"],
        },
        "method": {
            "source_database_reopened": False,
            "sealed_forward_cases_used": True,
            "feature_states_recomputed_from_two_source_values": True,
            "neutral_outcomes_recomputed_from_case_observations": True,
            "contingencies_effects_fisher_newcombe_holm_and_verdicts_reimplemented": True,
            "production_evaluator_called_for_statistics": False,
        },
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
        },
        "independent_overall_candidate_verdicts": independent_overall,
        "verdict": (
            "PASS_V3_MILESTONE_6B_INDEPENDENT_REPRODUCTION"
            if not failed
            else "FAIL_V3_MILESTONE_6B_INDEPENDENT_REPRODUCTION"
        ),
        "validation_hash": "",
    }
    validation["validation_hash"] = _embedded_hash(
        validation,
        "validation_hash",
        excluded=("validated_at",),
    )
    _write_json(output_path, validation)
    print(
        json.dumps(
            {
                "checks_passed": validation["summary"]["passed"],
                "checks_failed": validation["summary"]["failed"],
                "validation_hash": validation["validation_hash"],
                "verdict": validation["verdict"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    if failed:
        raise SystemExit(1)


def _validate_cases(
    cases: Sequence[Mapping[str, Any]],
    *,
    segment_code: str,
) -> list[dict[str, Any]]:
    hash_valid = True
    feature_valid = True
    outcome_valid = True
    boundary_valid = True
    for case in cases:
        hash_valid &= (
            case["segment_code"] == segment_code
            and forward_case_hash(case) == case["case_hash"]
        )
        decision = case["decision_state"]
        sources = decision["source_records"]
        state = str(decision["feature_state"])
        if state == "UNKNOWN":
            feature_valid &= sources == []
        else:
            feature_valid &= len(sources) == 2
            if len(sources) == 2:
                change = float(sources[1]["value"]) - float(sources[0]["value"])
                expected_state = (
                    "RISING"
                    if change > 0
                    else "FALLING"
                    if change < 0
                    else "UNCHANGED"
                )
                expected_signature = canonical_hash(
                    {
                        "absolute_change": change,
                        "previous_record_id": sources[0]["record_id"],
                        "record_id": sources[1]["record_id"],
                    }
                )
                feature_valid &= (
                    state == expected_state
                    and decision["source_signature"] == expected_signature
                )
        outcome = case["subsequent_behaviour"]
        signed = float(outcome["session_close"]) - float(
            outcome["neutral_reference_open"]
        )
        sixty = float(outcome["sixty_minute_close"]) - float(
            outcome["neutral_reference_open"]
        )
        expected_direction = _direction(signed)
        expected_sixty = _direction(sixty)
        outcome_valid &= (
            _same_number(signed, outcome["signed_close_displacement"])
            and _same_number(abs(signed), outcome["absolute_close_displacement"])
            and outcome["close_direction"] == expected_direction
            and outcome["sixty_minute_direction"] == expected_sixty
            and int(case["lineage"]["measurement_bar_count"]) == 239
        )
        boundary = case["research_boundary"]
        boundary_valid &= (
            boundary["trade_direction_assigned"] is False
            and boundary[
                "entry_exit_stop_target_or_size_assigned"
            ]
            is False
            and boundary["pnl_r_multiple_or_return_calculated"] is False
        )
    return [
        _check(f"{segment_code}::ALL_CASE_HASHES_VALID", hash_valid),
        _check(
            f"{segment_code}::FEATURE_STATES_AND_SIGNATURES_REPRODUCED",
            feature_valid,
        ),
        _check(
            f"{segment_code}::NEUTRAL_OUTCOMES_REPRODUCED",
            outcome_valid,
        ),
        _check(
            f"{segment_code}::NO_TRADE_OR_RETURN_FIELDS",
            boundary_valid,
        ),
    ]


def _independent_segment(
    cases: Sequence[Mapping[str, Any]],
    *,
    segment_code: str,
) -> dict[str, Any]:
    records = []
    for candidate in CANDIDATES:
        selected = sorted(
            [
                case
                for case in cases
                if case["session_code"] == candidate["session_code"]
            ],
            key=lambda item: (item["session_date"], item["case_id"]),
        )
        states = [
            str(case["decision_state"]["feature_state"]) for case in selected
        ]
        joint_known = [state != "UNKNOWN" for state in states]
        condition_all = [
            case
            for case, state in zip(selected, states, strict=True)
            if state == "FALLING"
        ]
        complement_all = [
            case
            for case, state in zip(selected, states, strict=True)
            if state == "RISING"
        ]
        condition = [
            case
            for case in condition_all
            if case["subsequent_behaviour"]["close_direction"] != "FLAT"
        ]
        complement = [
            case
            for case in complement_all
            if case["subsequent_behaviour"]["close_direction"] != "FLAT"
        ]
        condition_up = sum(
            case["subsequent_behaviour"]["close_direction"] == "UP"
            for case in condition
        )
        complement_up = sum(
            case["subsequent_behaviour"]["close_direction"] == "UP"
            for case in complement
        )
        condition_down = len(condition) - condition_up
        complement_down = len(complement) - complement_up
        condition_rate = (
            condition_up / len(condition) if condition else None
        )
        complement_rate = (
            complement_up / len(complement) if complement else None
        )
        effect = (
            100 * (condition_rate - complement_rate)
            if condition_rate is not None and complement_rate is not None
            else None
        )
        condition_signatures = {
            case["decision_state"]["source_signature"]
            for case in condition_all
        }
        complement_signatures = {
            case["decision_state"]["source_signature"]
            for case in complement_all
        }
        failures = []
        coverage = 100 * sum(joint_known) / len(selected) if selected else 0.0
        if coverage < 50.0:
            failures.append("JOINT_KNOWN_COVERAGE_BELOW_MINIMUM")
        if len(condition) < 25:
            failures.append("CONDITION_BINARY_CASES_BELOW_MINIMUM")
        if len(complement) < 25:
            failures.append("COMPLEMENT_BINARY_CASES_BELOW_MINIMUM")
        if len(condition) + len(complement) < 80:
            failures.append("COMBINED_BINARY_CASES_BELOW_MINIMUM")
        if len(condition_signatures) < 4:
            failures.append("CONDITION_SOURCE_SIGNATURES_BELOW_MINIMUM")
        if len(complement_signatures) < 4:
            failures.append("COMPLEMENT_SOURCE_SIGNATURES_BELOW_MINIMUM")
        condition_episodes = _episodes(states, "FALLING")
        complement_episodes = _episodes(states, "RISING")
        if condition_episodes < 4:
            failures.append("CONDITION_EPISODES_BELOW_MINIMUM")
        if complement_episodes < 4:
            failures.append("COMPLEMENT_EPISODES_BELOW_MINIMUM")
        support = not failures
        interval = (
            _newcombe(
                condition_up,
                len(condition),
                complement_up,
                len(complement),
            )
            if condition and complement
            else [None, None]
        )
        p_value = (
            _fisher(
                condition_up,
                condition_down,
                complement_up,
                complement_down,
            )
            if support
            else None
        )
        records.append(
            {
                "candidate_code": candidate["candidate_code"],
                "session_code": candidate["session_code"],
                "case_count": len(selected),
                "joint_known_cases": sum(joint_known),
                "joint_known_coverage_pct": _rounded(coverage),
                "excluded_known_cases": sum(
                    state == "UNCHANGED" for state in states
                ),
                "condition_all_cases": len(condition_all),
                "complement_all_cases": len(complement_all),
                "condition_distinct_source_signatures": len(
                    condition_signatures
                ),
                "complement_distinct_source_signatures": len(
                    complement_signatures
                ),
                "condition_state_episodes": condition_episodes,
                "complement_state_episodes": complement_episodes,
                "condition_median": _median_displacement(condition_all),
                "complement_median": _median_displacement(complement_all),
                "contingency": {
                    "condition_up": condition_up,
                    "condition_down": condition_down,
                    "complement_up": complement_up,
                    "complement_down": complement_down,
                },
                "condition_up_rate_pct": _rounded(
                    100 * condition_rate
                    if condition_rate is not None
                    else None
                ),
                "complement_up_rate_pct": _rounded(
                    100 * complement_rate
                    if complement_rate is not None
                    else None
                ),
                "effect_pp": _rounded(effect),
                "interval": [
                    _rounded(100 * value) if value is not None else None
                    for value in interval
                ],
                "p_value": _rounded(p_value),
                "support_eligible": support,
                "support_failures": sorted(set(failures)),
                "holm_adjusted_p_value": None,
                "segment_verdict": None,
            }
        )
    _holm(records)
    for record in records:
        record["segment_verdict"] = _verdict(record)
    return {
        "segment_code": segment_code,
        "candidate_results": records,
    }


def _compare_segment(
    *,
    recorded: Mapping[str, Any],
    reproduced: Mapping[str, Any],
    segment_code: str,
) -> list[dict[str, Any]]:
    recorded_by_code = {
        item["candidate_code"]: item for item in recorded["candidate_results"]
    }
    output = []
    for item in reproduced["candidate_results"]:
        code = item["candidate_code"]
        actual = recorded_by_code[code]
        metrics = actual["full_development"]
        exact_fields = (
            "case_count",
            "joint_known_cases",
            "excluded_known_cases",
            "condition_all_cases",
            "complement_all_cases",
            "condition_distinct_source_signatures",
            "complement_distinct_source_signatures",
            "condition_state_episodes",
            "complement_state_episodes",
            "contingency",
            "support_eligible",
            "support_failures",
        )
        exact = all(metrics[field] == item[field] for field in exact_fields)
        numeric = all(
            _same_number(metrics[field], item[field])
            for field in (
                "joint_known_coverage_pct",
                "condition_up_rate_pct",
                "complement_up_rate_pct",
                "effect_pp",
                "fisher_exact_two_sided_p_value",
            )
        )
        numeric &= all(
            _same_number(left, right)
            for left, right in zip(
                metrics["newcombe_wilson_95pct_effect_pp"],
                item["interval"],
                strict=True,
            )
        )
        numeric &= _same_number(
            metrics["condition_path_profile"][
                "median_signed_close_displacement"
            ],
            item["condition_median"],
        )
        numeric &= _same_number(
            metrics["complement_path_profile"][
                "median_signed_close_displacement"
            ],
            item["complement_median"],
        )
        verdict = (
            _same_number(
                actual["holm_adjusted_p_value"],
                item["holm_adjusted_p_value"],
            )
            and actual["segment_verdict"] == item["segment_verdict"]
        )
        output.extend(
            [
                _check(
                    f"{segment_code}::{code}::SUPPORT_AND_CONTINGENCY_REPRODUCED",
                    exact,
                ),
                _check(
                    f"{segment_code}::{code}::EFFECT_UNCERTAINTY_AND_MEDIANS_REPRODUCED",
                    numeric,
                ),
                _check(
                    f"{segment_code}::{code}::HOLM_AND_VERDICT_REPRODUCED",
                    verdict,
                ),
            ]
        )
    return output


def _overall(segments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_segment = {
        segment["segment_code"]: {
            item["candidate_code"]: item
            for item in segment["candidate_results"]
        }
        for segment in segments
    }
    output = []
    for code in M5_SHORTLIST_CODES:
        exposed = by_segment["EXPOSED_CALENDAR_2025"][code][
            "segment_verdict"
        ]
        locked = by_segment["LOCKED_2026_YTD"][code]["segment_verdict"]
        if "REJECT_MATERIAL_REVERSE_REPLICATION" in {exposed, locked}:
            overall = "REJECTED_MATERIAL_REVERSE_IN_HISTORICAL_FORWARD_SEGMENT"
        elif locked == "PASS_MATERIAL_POSITIVE_REPLICATION":
            overall = "INCONCLUSIVE_PENDING_PROSPECTIVE_REPLICATION"
        else:
            overall = "INCONCLUSIVE_NO_LOCKED_2026_PASS"
        output.append(
            {
                "candidate_code": code,
                "exposed_2025_verdict": exposed,
                "exposed_2025_positive_validation_credit": False,
                "locked_2026_ytd_verdict": locked,
                "locked_2026_ytd_positive_validation_credit": True,
                "prospective_2026_verdict": "PENDING_NO_DECISIONS_YET",
                "overall_verdict": overall,
                "current_directional_bias_edge_candidate": False,
            }
        )
    return output


def _verdict(record: Mapping[str, Any]) -> str:
    if not record["support_eligible"]:
        return "INCONCLUSIVE_INSUFFICIENT_SUPPORT"
    effect = record["effect_pp"]
    lower, upper = record["interval"]
    p_value = record["holm_adjusted_p_value"]
    condition_median = record["condition_median"]
    complement_median = record["complement_median"]
    if (
        effect is not None
        and effect >= 7.5
        and lower is not None
        and lower > 0
        and p_value is not None
        and p_value <= 0.10
        and condition_median is not None
        and condition_median > 0
        and complement_median is not None
        and complement_median < 0
    ):
        return "PASS_MATERIAL_POSITIVE_REPLICATION"
    if (
        effect is not None
        and effect <= -7.5
        and upper is not None
        and upper < 0
        and p_value is not None
        and p_value <= 0.10
        and condition_median is not None
        and condition_median < 0
        and complement_median is not None
        and complement_median > 0
    ):
        return "REJECT_MATERIAL_REVERSE_REPLICATION"
    return "INCONCLUSIVE_MIXED_OR_UNDERPOWERED"


def _holm(records: Sequence[dict[str, Any]]) -> None:
    ordered = sorted(
        records,
        key=lambda item: (
            item["p_value"] if item["p_value"] is not None else 1.0,
            item["candidate_code"],
        ),
    )
    running = 0.0
    for index, record in enumerate(ordered):
        raw = record["p_value"] if record["p_value"] is not None else 1.0
        adjusted = min(1.0, raw * (2 - index))
        running = max(running, adjusted)
        record["holm_adjusted_p_value"] = _rounded(running)


def _episodes(states: Sequence[str], target: str) -> int:
    episodes = 0
    previous = False
    for state in states:
        current = state == target
        if current and not previous:
            episodes += 1
        previous = current
    return episodes


def _median_displacement(cases: Sequence[Mapping[str, Any]]) -> float | None:
    if not cases:
        return None
    return _rounded(
        statistics.median(
            float(case["subsequent_behaviour"]["signed_close_displacement"])
            for case in cases
        )
    )


def _fisher(a: int, b: int, c: int, d: int) -> float:
    row_one = a + b
    row_two = c + d
    column_one = a + c
    total = row_one + row_two
    if total == 0:
        return 1.0
    lower = max(0, column_one - row_two)
    upper = min(row_one, column_one)

    def probability(x: int) -> float:
        return (
            math.comb(column_one, x)
            * math.comb(total - column_one, row_one - x)
            / math.comb(total, row_one)
        )

    observed = probability(a)
    return min(
        1.0,
        math.fsum(
            probability(x)
            for x in range(lower, upper + 1)
            if probability(x) <= observed + 1e-15
        ),
    )


def _wilson(successes: int, total: int) -> list[float]:
    proportion = successes / total
    denominator = 1 + Z_95**2 / total
    center = (proportion + Z_95**2 / (2 * total)) / denominator
    half = (
        Z_95
        * math.sqrt(
            proportion * (1 - proportion) / total
            + Z_95**2 / (4 * total**2)
        )
        / denominator
    )
    return [max(0.0, center - half), min(1.0, center + half)]


def _newcombe(
    successes_one: int,
    total_one: int,
    successes_two: int,
    total_two: int,
) -> list[float]:
    p_one = successes_one / total_one
    p_two = successes_two / total_two
    lower_one, upper_one = _wilson(successes_one, total_one)
    lower_two, upper_two = _wilson(successes_two, total_two)
    difference = p_one - p_two
    lower = difference - math.sqrt(
        (p_one - lower_one) ** 2 + (upper_two - p_two) ** 2
    )
    upper = difference + math.sqrt(
        (upper_one - p_one) ** 2 + (p_two - lower_two) ** 2
    )
    return [max(-1.0, lower), min(1.0, upper)]


def _direction(value: float) -> str:
    if value > 0.01:
        return "UP"
    if value < -0.01:
        return "DOWN"
    return "FLAT"


def _same_number(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    return abs(float(left) - float(right)) <= 1e-8


def _rounded(value: float | None) -> float | None:
    return round(value, 8) if value is not None else None


def _check(code: str, passed: bool) -> dict[str, Any]:
    return {"code": code, "status": "PASS" if passed else "FAIL"}


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


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    output = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Expected JSON object line: {path}")
            output.append(value)
    return output


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
            "Independently reproduce V3 M6B from the sealed forward cases "
            "without reopening the source database."
        )
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--bundle",
        default=(
            "research_artifacts/"
            "gold_session_behaviour_v3_m6b_results_v01/result_bundle.json"
        ),
    )
    parser.add_argument(
        "--manifest",
        default=(
            "research_artifacts/"
            "gold_session_behaviour_v3_m6b_results_v01/manifest.json"
        ),
    )
    parser.add_argument(
        "--output",
        default=(
            "research_artifacts/"
            "gold_session_behaviour_v3_m6b_validation_v01.json"
        ),
    )
    return parser


if __name__ == "__main__":
    main()
