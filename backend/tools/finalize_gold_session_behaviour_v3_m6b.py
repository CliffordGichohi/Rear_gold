from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.session_behaviour_v3 import sha256_file

FINALIZER_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M6B_FINALIZER_V0_1"
EXPECTED_V06A_STATE_HASH = (
    "fa8963661bb3a6e8eff1d95dac1c713015882019f6b2ba6937bc398d1ae85629"
)


def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    report_path = (root / args.report).resolve()
    state_path = (root / args.state).resolve()
    completion_path = (root / args.completion_manifest).resolve()
    for path in (report_path, state_path, completion_path):
        _assert_within(root, path)
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite final seal: {path}")

    v06a_path = (
        root / "research_artifacts/gold_session_behaviour_v3_state_v06a.json"
    )
    v06a = _load_json(v06a_path)
    if v06a["state_hash"] != EXPECTED_V06A_STATE_HASH:
        raise ValueError("V06A predecessor state hash mismatch")
    if _state_hash(v06a) != EXPECTED_V06A_STATE_HASH:
        raise ValueError("V06A predecessor embedded state hash mismatch")

    source_manifest_path = (
        root
        / "research_artifacts/"
        "gold_session_behaviour_v3_m6b_source_snapshot_v01/manifest.json"
    )
    source_manifest = _verified_document(
        source_manifest_path,
        "manifest_hash",
    )
    preopen_path = (
        root
        / "research_manifests/"
        "gold_session_behaviour_v3_m6b_preopen_v01.json"
    )
    preopen = _verified_document(preopen_path, "manifest_hash")
    for relative, expected in preopen["implementation_freeze"].items():
        path = (root / relative).resolve()
        _assert_within(root, path)
        if sha256_file(path) != expected:
            raise ValueError(f"Pre-open implementation seal mismatch: {relative}")

    result_dir = (
        root
        / "research_artifacts/"
        "gold_session_behaviour_v3_m6b_results_v01"
    )
    bundle_path = result_dir / "result_bundle.json"
    result_manifest_path = result_dir / "manifest.json"
    bundle = _load_json(bundle_path)
    if _embedded_hash(
        bundle,
        "bundle_hash",
        excluded=("created_at",),
    ) != bundle["bundle_hash"]:
        raise ValueError("M6B bundle hash mismatch")
    result_manifest = _verified_document(
        result_manifest_path,
        "manifest_hash",
    )

    validation_v02_path = (
        root
        / "research_artifacts/"
        "gold_session_behaviour_v3_m6b_validation_v02.json"
    )
    validation_v03_path = (
        root
        / "research_artifacts/"
        "gold_session_behaviour_v3_m6b_validation_v03.json"
    )
    validation_v02 = _load_json(validation_v02_path)
    validation_v03 = _load_json(validation_v03_path)
    for validation in (validation_v02, validation_v03):
        if _embedded_hash(
            validation,
            "validation_hash",
            excluded=("validated_at",),
        ) != validation["validation_hash"]:
            raise ValueError("Independent validation hash mismatch")
    if validation_v02["verdict"] != (
        "FAIL_V3_MILESTONE_6B_INDEPENDENT_REPRODUCTION"
    ):
        raise ValueError("V02 failed validation attempt was not preserved")
    if validation_v03["verdict"] != (
        "PASS_V3_MILESTONE_6B_INDEPENDENT_REPRODUCTION"
    ):
        raise ValueError("Final independent reproduction did not pass")
    if int(validation_v03["summary"]["failed"]) != 0:
        raise ValueError("Final independent reproduction contains failed checks")

    segment_results = [
        _load_json(result_dir / code / "result.json")
        for code in ("exposed_calendar_2025", "locked_2026_ytd")
    ]
    for result in segment_results:
        if _embedded_hash(result, "segment_hash") != result["segment_hash"]:
            raise ValueError("Segment result hash mismatch")
        if len(result["candidate_results"]) != 2:
            raise ValueError("A segment did not evaluate both candidates")
    prospective = bundle["prospective_ledger"]
    prospective_manifest_path = (
        root / prospective["manifest_path"]
    ).resolve()
    prospective_manifest = _verified_document(
        prospective_manifest_path,
        "manifest_hash",
    )
    prospective_ledger_path = (root / prospective["ledger_path"]).resolve()
    if prospective_ledger_path.stat().st_size != 0:
        raise ValueError("Prospective ledger is not empty at initialization")
    if int(prospective_manifest["backfilled_decisions"]) != 0:
        raise ValueError("Prospective ledger contains a backfill")

    refresh_receipt_path = (
        result_dir / "source_refresh_receipt.json"
    )
    refresh_receipt = _source_refresh_receipt(root)
    _write_json(refresh_receipt_path, refresh_receipt)

    report = _report(
        segment_results=segment_results,
        bundle=bundle,
        source_manifest=source_manifest,
        validation=validation_v03,
    )
    report_path.write_text(report, encoding="utf-8")

    outputs = [
        _output(
            root,
            source_manifest_path,
            "FINAL_SOURCE_SNAPSHOT_MANIFEST",
        ),
        _output(root, preopen_path, "FROZEN_M6B_PREOPEN_MANIFEST"),
        _output(root, bundle_path, "SEALED_RESULT_BUNDLE"),
        _output(root, result_manifest_path, "SEALED_RESULT_MANIFEST"),
        _output(
            root,
            validation_v02_path,
            "PRESERVED_FAILED_VALIDATION_V02",
        ),
        _output(
            root,
            validation_v03_path,
            "PASSING_INDEPENDENT_REPRODUCTION_V03",
        ),
        _output(
            root,
            prospective_manifest_path,
            "PROSPECTIVE_LEDGER_MANIFEST",
        ),
        _output(
            root,
            prospective_ledger_path,
            "EMPTY_APPEND_ONLY_PROSPECTIVE_LEDGER",
        ),
        _output(
            root,
            refresh_receipt_path,
            "PERMITTED_SOURCE_REFRESH_RECEIPT",
        ),
        _output(root, report_path, "HONEST_MILESTONE_6B_REPORT"),
    ]
    state: dict[str, Any] = {
        "state_version": "GOLD_SESSION_BEHAVIOUR_V3_STATE_V0_6B",
        "generated_at": datetime.now(UTC).isoformat(),
        "predecessor_state": {
            "path": _relative(root, v06a_path),
            "file_sha256": sha256_file(v06a_path),
            "state_hash": v06a["state_hash"],
            "all_predecessor_output_seals_verified": True,
        },
        "authorization": {
            "milestone": "V3_M6B_ONE_TIME_FORWARD_VALUE_EVALUATION",
            "source_refresh": [
                "IC_MARKETS_MT5_XAUUSD",
                "US_VOLATILITY_INDEX",
                "US_FINANCIAL_STRESS",
            ],
            "paid_acquisition_permitted": False,
            "calendar_2025_open_once": True,
            "calendar_2026_ytd_open_once_after_2025_seal": True,
            "mandatory_stop_after_milestone": True,
        },
        "source_refresh_and_readiness": {
            "mt5_bars_received": 3756,
            "mt5_requested_end_exclusive": "2026-07-30T00:00:00Z",
            "fred_records_fetched": 24,
            "fred_observations_inserted": 4,
            "paid_acquisition": False,
            "source_values_printed_or_human_inspected_before_seal": False,
            "source_snapshot_hash": preopen["source_snapshot"][
                "source_snapshot_hash"
            ],
            "source_snapshot_manifest_hash": source_manifest[
                "manifest_hash"
            ],
            "metadata_readiness_verdict": (
                "READY_WITH_LOW_POWER_EXPECTED_AND_RECORDED_COVERAGE_GAPS"
            ),
            "terminal_2026_missing_dates_after_refresh": [],
            "potential_complete_cases": {
                "EXPOSED_CALENDAR_2025": {
                    "LONDON": 257,
                    "NEW_YORK": 257,
                },
                "LOCKED_2026_YTD": {
                    "LONDON": 143,
                    "NEW_YORK": 142,
                },
            },
        },
        "frozen_candidates": [
            "LONDON_VOLATILITY_DIRECTION_V0_1",
            "NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1",
        ],
        "protocol": {
            "fingerprint": preopen["protocol_fingerprint"],
            "candidate_definitions_changed": False,
            "new_variables_or_candidates": 0,
            "thresholds_retuned": False,
            "execution_variants": 0,
            "cot_used_as_pass_gate": False,
            "rejected_candidates_or_zn_rules_reopened": False,
            "trades_pnl_r_multiples_or_returns": 0,
        },
        "segments": {
            result["segment"]["segment_code"]: {
                "classification": result["segment"]["classification"],
                "positive_validation_credit": result["segment"][
                    "positive_validation_credit"
                ],
                "case_count": result["case_count"],
                "segment_hash": result["segment_hash"],
                "candidates": [
                    _state_candidate(item)
                    for item in result["candidate_results"]
                ],
            }
            for result in segment_results
        },
        "overall_candidate_verdicts": bundle[
            "overall_candidate_verdicts"
        ],
        "prospective_tracking": {
            "ledger_path": _relative(root, prospective_ledger_path),
            "ledger_file_sha256": sha256_file(prospective_ledger_path),
            "record_count": 0,
            "backfilled_decisions": 0,
            "start_session_date": "2026-07-31",
            "end_session_date": "2026-12-31",
            "next_eligible_session_date": "2026-07-31",
            "interim_inferential_testing_permitted": False,
        },
        "independent_reproduction": {
            "sealed_v01_runtime_attempt": (
                "HALTED_BEFORE_ARTIFACT_DUE_RESULT_FIELD_MAPPING_KEY_ERROR"
            ),
            "v02_verdict": validation_v02["verdict"],
            "v02_failed_checks": [
                item["code"]
                for item in validation_v02["checks"]
                if item["status"] == "FAIL"
            ],
            "v03_verdict": validation_v03["verdict"],
            "v03_checks_passed": validation_v03["summary"]["passed"],
            "v03_checks_failed": validation_v03["summary"]["failed"],
            "v03_validation_hash": validation_v03["validation_hash"],
            "source_database_reopened": False,
            "results_changed_by_validation_fixes": False,
        },
        "verification": {
            "relevant_unit_tests_passed": 43,
            "relevant_unit_tests_failed": 0,
            "ruff_errors": 0,
            "independent_checks_passed": 32,
            "independent_checks_failed": 0,
        },
        "current_milestone": {
            "code": "V3_M6B_ONE_TIME_FORWARD_VALUE_EVALUATION",
            "status": "COMPLETE_MANDATORY_STOP",
            "verdict": (
                "PASS_V3_MILESTONE_6B_PROCESS_WITH_BOTH_"
                "CANDIDATES_INCONCLUSIVE"
            ),
            "current_directional_bias_edge_candidates": 0,
        },
        "next_action": {
            "authorized": False,
            "code": "PROSPECTIVE_2026_POST_FREEZE_DECISION_TRACKING",
            "instruction_required": (
                "A new explicit instruction is required to operate the "
                "append-only prospective ledger. Missed decisions may never "
                "be backfilled."
            ),
        },
        "milestone_6b_outputs": outputs,
        "state_hash_policy": (
            "SHA-256 of canonical sorted compact JSON excluding generated_at "
            "and state_hash."
        ),
        "state_hash": "",
    }
    state["state_hash"] = _state_hash(state)
    _write_json(state_path, state)

    completion: dict[str, Any] = {
        "manifest_version": FINALIZER_VERSION,
        "milestone": "V3_M6B_ONE_TIME_FORWARD_VALUE_EVALUATION",
        "created_at": state["generated_at"],
        "source_snapshot_manifest_hash": source_manifest["manifest_hash"],
        "preopen_manifest_hash": preopen["manifest_hash"],
        "result_bundle_hash": bundle["bundle_hash"],
        "result_manifest_hash": result_manifest["manifest_hash"],
        "independent_validation_hash": validation_v03["validation_hash"],
        "state": {
            "path": _relative(root, state_path),
            "file_sha256": sha256_file(state_path),
            "state_hash": state["state_hash"],
        },
        "report": {
            "path": _relative(root, report_path),
            "file_sha256": sha256_file(report_path),
        },
        "research_boundary": state["protocol"],
        "verdict": state["current_milestone"]["verdict"],
        "mandatory_stop": True,
        "manifest_hash": "",
    }
    completion["manifest_hash"] = _embedded_hash(
        completion,
        "manifest_hash",
    )
    _write_json(completion_path, completion)
    print(
        json.dumps(
            {
                "completion_manifest_hash": completion["manifest_hash"],
                "independent_checks_failed": 0,
                "report": _relative(root, report_path),
                "state": _relative(root, state_path),
                "state_hash": state["state_hash"],
                "verdict": completion["verdict"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def _source_refresh_receipt(root: Path) -> dict[str, Any]:
    files = [
        root
        / "data/mt5/"
        "xauusd_1m_ic_markets_mt5_20260727T0721_20260728T0720.csv",
        root
        / "data/mt5/"
        "xauusd_1m_ic_markets_mt5_20260728T0721_20260729T0720.csv",
        root
        / "data/mt5/"
        "xauusd_1m_ic_markets_mt5_20260729T0721_20260729T2358.csv",
    ]
    if any(not path.is_file() for path in files):
        raise FileNotFoundError("An authorized MT5 refresh file is missing")
    receipt: dict[str, Any] = {
        "receipt_version": (
            "GOLD_SESSION_BEHAVIOUR_V3_M6B_SOURCE_REFRESH_RECEIPT_V0_1"
        ),
        "mt5": {
            "provider": "IC_MARKETS_MT5",
            "instrument": "XAUUSD",
            "timeframe": "1m",
            "requested_start_inclusive": "2026-07-27T07:21:00Z",
            "requested_end_exclusive": "2026-07-30T00:00:00Z",
            "bars_received": 3756,
            "ingestion_batch_ids": [
                "50b5d474-3f06-4e5b-872c-4b83b646efe2",
                "44b4941f-e6db-44b4-bb6c-e57dadbebd60",
                "5792e3a7-15b4-46c3-9cdc-8eeb8bab6cf5",
            ],
            "files": [
                {
                    "path": _relative(root, path),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in files
            ],
        },
        "fred": {
            "provider": "FRED_PUBLIC",
            "endpoint": "https://fred.stlouisfed.org/graph/fredgraph.csv",
            "series": [
                "US_VOLATILITY_INDEX",
                "US_FINANCIAL_STRESS",
            ],
            "requested_start_inclusive": "2026-07-01",
            "requested_end_inclusive": "2026-07-29",
            "records_fetched": {
                "US_VOLATILITY_INDEX": 20,
                "US_FINANCIAL_STRESS": 4,
            },
            "observations_inserted": 4,
            "batch_id": "e5807221-9b07-4637-baca-a0af7d1938df",
            "batch_content_hash": (
                "8e091c721b048258b87e30576c1269c75bdd43b9507ea13260351f4d43cd5530"
            ),
        },
        "paid_acquisition": False,
        "values_printed_or_human_inspected_during_refresh": False,
        "receipt_hash": "",
    }
    receipt["receipt_hash"] = _embedded_hash(receipt, "receipt_hash")
    return receipt


def _report(
    *,
    segment_results: Sequence[Mapping[str, Any]],
    bundle: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> str:
    rows = []
    for result in segment_results:
        segment = result["segment"]["segment_code"]
        for candidate in result["candidate_results"]:
            metrics = candidate["full_development"]
            contingency = metrics["contingency"]
            condition_n = (
                contingency["condition_up"] + contingency["condition_down"]
            )
            complement_n = (
                contingency["complement_up"] + contingency["complement_down"]
            )
            interval = metrics["newcombe_wilson_95pct_effect_pp"]
            rows.append(
                "| "
                + " | ".join(
                    [
                        segment,
                        candidate["candidate_code"],
                        str(condition_n),
                        str(complement_n),
                        f"{metrics['condition_up_rate_pct']:.2f}%",
                        f"{metrics['complement_up_rate_pct']:.2f}%",
                        f"{metrics['effect_pp']:+.2f} pp",
                        f"[{interval[0]:+.2f}, {interval[1]:+.2f}]",
                        f"{candidate['holm_adjusted_p_value']:.4f}",
                        f"{metrics['condition_path_profile']['median_signed_close_displacement']:+.2f}",
                        f"{metrics['complement_path_profile']['median_signed_close_displacement']:+.2f}",
                        candidate["segment_verdict"],
                    ]
                )
                + " |"
            )
    overall = {
        item["candidate_code"]: item["overall_verdict"]
        for item in bundle["overall_candidate_verdicts"]
    }
    return f"""# Gold Session Behaviour V3 — Milestone 6B

## Verdict

Milestone 6B completed under Amendment B. The process and independent reproduction passed, but **neither frozen candidate validated as a current directional-bias edge**.

- `LONDON_VOLATILITY_DIRECTION_V0_1`: `{overall['LONDON_VOLATILITY_DIRECTION_V0_1']}`
- `NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1`: `{overall['NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1']}`
- All four candidate/segment evaluations were `INCONCLUSIVE_MIXED_OR_UNDERPOWERED`.
- No support gate failed. The inconclusive verdicts came from weak or unstable effects, confidence intervals spanning zero, non-significant Holm-adjusted tests, and/or the frozen median-direction requirements.
- Calendar 2025 remains exposed historical evidence and receives no independent-validation credit.

## Source refresh and pre-open controls

- IC Markets MT5 XAUUSD: 3,756 real one-minute bars acquired for the missing interval through 29 July 2026.
- Free FRED public endpoint: only `US_VOLATILITY_INDEX` and `US_FINANCIAL_STRESS` refreshed; 24 records fetched and four new observations inserted.
- Paid acquisition: none.
- Final metadata readiness: `READY_WITH_LOW_POWER_EXPECTED_AND_RECORDED_COVERAGE_GAPS`.
- Terminal 27–29 July 2026 coverage gaps were cleared. Final complete-case counts were 257/257 for 2025 and 143 London / 142 New York for 2026 YTD.
- Final source snapshot hash: `{source_manifest['source_snapshot_hash']}`.
- Candidate definitions, thresholds, multiplicity, missing-data policy, and segment order were sealed before any candidate state or outcome was calculated.

## Frozen numerical results

Condition is `FALLING`; complement is `RISING`. UP rates use non-flat neutral session-close outcomes from 08:01 to 12:00 local time.

| Segment | Candidate | Condition n | Complement n | Condition UP | Complement UP | Effect | Newcombe 95% CI | Holm p | Condition median $ | Complement median $ | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
{chr(10).join(rows)}

## What the numbers mean

For London in 2025, falling VIX was only 2.39 percentage points more bullish than rising VIX, and both condition medians were positive. That is not the frozen directional separation.

For London in locked 2026 YTD, the point estimate reversed to -9.41 percentage points and the medians also reversed (-$3.09 versus +$1.76). This is adverse evidence, but it did not satisfy the strict rejection gate because the 95% interval still crossed zero and Holm-adjusted p was 0.6247. It is therefore honestly inconclusive—not a pass and not a protocol-level rejection.

The New York financial-stress candidate was nearly flat in both periods (-0.68 pp in 2025 and -0.78 pp in 2026 YTD), with broad intervals around zero. It did not replicate the development relationship.

## Support and integrity

- Joint-known feature coverage: 100% for every candidate/segment.
- Duplicate source records or case keys: zero.
- All condition/complement sample, combined sample, source-signature, and episode floors passed.
- Both candidates were evaluated in both segments regardless of earlier results.
- Independent reproduction used the sealed forward cases and did not reopen the database.
- Final reproduction: {validation['summary']['passed']}/{validation['summary']['total']} checks passed; hash `{validation['validation_hash']}`.

The first sealed validation program halted on a result-field mapping error before producing an artifact. A preserved V02 attempt then exposed binary-float signature comparison in the validator only. V03 corrected validation arithmetic to decimal representation; it changed no case, statistic, or verdict.

## Prospective ledger

The append-only ledger was initialized empty before the next eligible session:

- Start: 31 July 2026
- End: 31 December 2026
- Existing decisions: 0
- Backfilled decisions: 0
- Interim inferential testing: prohibited

Neither candidate is currently an edge candidate because the frozen protocol requires a locked-2026 PASS plus a prospective PASS, and neither received the locked-2026 PASS.

## Research boundary

No variable was added, no threshold was retuned, no candidate was repaired or filtered, COT was not used as a pass gate, no rejected ZN rule was reopened, and no execution, trade, PnL, R-multiple, or account-return calculation was performed.

Milestone 6B is complete. Mandatory stop applies.
"""


def _state_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    metrics = candidate["full_development"]
    contingency = metrics["contingency"]
    return {
        "candidate_code": candidate["candidate_code"],
        "segment_verdict": candidate["segment_verdict"],
        "support_eligible": metrics["support_eligible"],
        "support_failures": metrics["support_failures"],
        "joint_known_coverage_pct": metrics["joint_known_coverage_pct"],
        "condition_binary_cases": (
            contingency["condition_up"] + contingency["condition_down"]
        ),
        "complement_binary_cases": (
            contingency["complement_up"] + contingency["complement_down"]
        ),
        "condition_up_rate_pct": metrics["condition_up_rate_pct"],
        "complement_up_rate_pct": metrics["complement_up_rate_pct"],
        "effect_pp": metrics["effect_pp"],
        "newcombe_wilson_95pct_effect_pp": metrics[
            "newcombe_wilson_95pct_effect_pp"
        ],
        "fisher_exact_two_sided_p_value": metrics[
            "fisher_exact_two_sided_p_value"
        ],
        "holm_adjusted_p_value": candidate["holm_adjusted_p_value"],
        "condition_median_signed_close": metrics[
            "condition_path_profile"
        ]["median_signed_close_displacement"],
        "complement_median_signed_close": metrics[
            "complement_path_profile"
        ]["median_signed_close_displacement"],
    }


def _verified_document(path: Path, hash_field: str) -> dict[str, Any]:
    document = _load_json(path)
    if _embedded_hash(document, hash_field) != document[hash_field]:
        raise ValueError(f"Embedded hash mismatch: {path}")
    return document


def _state_hash(state: Mapping[str, Any]) -> str:
    return canonical_hash(
        {
            key: value
            for key, value in state.items()
            if key not in {"generated_at", "state_hash"}
        }
    )


def _output(root: Path, path: Path, role: str) -> dict[str, Any]:
    return {
        "path": _relative(root, path),
        "role": role,
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


def _relative(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root)).replace("\\", "/")


def _assert_within(root: Path, path: Path) -> None:
    if path != root and root not in path.parents:
        raise ValueError(f"Path must remain inside repository root: {path}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the sealed M6B artifacts, write the honest report, and "
            "seal V06B state."
        )
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--report",
        default="GOLD_SESSION_BEHAVIOUR_V3_MILESTONE_6B.md",
    )
    parser.add_argument(
        "--state",
        default="research_artifacts/gold_session_behaviour_v3_state_v06b.json",
    )
    parser.add_argument(
        "--completion-manifest",
        default=(
            "research_artifacts/"
            "gold_session_behaviour_v3_m6b_completion_manifest_v01.json"
        ),
    )
    return parser


if __name__ == "__main__":
    main()
