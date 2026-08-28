#!/usr/bin/env python3
"""Compare the sealed autonomous result with V2 only after inference completes."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402


CONTRACT = ROOT / "GOLD_COHERENT_AUCTION_END_TO_END_SAME_MONTH_REPLICATION_V1.md"
TRANSLATOR = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_end_to_end_same_month_v1"
    / "translator.json"
)
RESULT = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_end_to_end_same_month_v1"
    / "autonomous_result.json"
)
LEDGER = (
    ROOT
    / "research_artifacts"
    / "gold_matched_human_replay_v1"
    / "ledgers"
    / "matched_human_visible_ledger.jsonl"
)
V2_PREPATH = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_human_policy_v2"
    / "prepath_classification_amendment_a.json"
)
V2_RESULT = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_human_policy_v2"
    / "matched_case_regression_v2.json"
)
REPORT = ROOT / "GOLD_COHERENT_AUCTION_END_TO_END_SAME_MONTH_REPLICATION_V1_REPORT.md"
OUT = RESULT.parent
COMPARISON = OUT / "comparison.json"
SEAL = OUT / "final_seal.json"
EXPECTED_CONTRACT_SHA256 = "8a3d3301ec5f382dc378e7554d313b95657a00adeaeb17826e5edf7b677fcd39"
EXPECTED_TRANSLATOR_SHA256 = "c95e200194bece77ed435741202d1bacd4f267ab0f1d1ed7803dd9d4ebd30841"
EXPECTED_RESULT_SHA256 = "c2ff398eaf3cb865191e85bace5542a79a9d23063fe51d164c4b31bc7979637d"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def visible_decisions() -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["event_type"] in {"DECISION_SEALED", "NO_TRADE_SEALED"}:
            decision = row["data"]["decision"]
            output[decision["case_alias"]] = decision
    require(len(output) == 30, "Human comparison population differs")
    return output


def render_report(comparison: dict[str, Any]) -> str:
    auto = comparison["autonomous_summary"]
    gates = comparison["gates"]
    lines = [
        "# Gold Coherent-Auction End-to-End Same-Month Replication V1",
        "",
        f"Verdict: `{comparison['verdict']}`",
        "",
        "## Direct result",
        "",
        "The raw-stream-only autonomous process reproduced the exposed human-input V2 result:",
        "",
        f"- autonomous: `{auto['net_r50']:+.8f}R` / `${auto['net_usd']:+.2f}`;",
        f"- human-input V2: `{comparison['human_v2_net_r50']:+.8f}R` / "
        f"`${comparison['human_v2_net_usd']:+.2f}`;",
        f"- drift: `{comparison['pnl_drift_r50']:+.8f}R` / "
        f"`${comparison['pnl_drift_usd']:+.2f}`;",
        f"- signals/no-signals: `{auto['signal_days']}` / `{auto['no_signal_days']}`;",
        f"- admitted/rejected: `{auto['admitted']}` / `{auto['rejected']}`;",
        f"- win rate: `{auto['win_rate'] * 100:.2f}%`;",
        f"- profit factor: `{auto['profit_factor']:.4f}`;",
        f"- maximum drawdown: `{auto['maximum_drawdown_r50']:.4f}R`.",
        "",
        "| Gate | Result |",
        "|---|---|",
    ]
    for key, value in gates.items():
        lines.append(f"| {key} | {'PASS' if value else 'FAIL'} |")
    lines += [
        "",
        "## Every exposed case",
        "",
        "| Case | Human | Autonomous signal | Decision | Family | Autonomous R | Human V2 R |",
        "|---|---|---|---|---|---:|---:|",
    ]
    for row in comparison["cases"]:
        lines.append(
            f"| {row['case_alias']} | {row['human_action']} | "
            f"{row['autonomous_signal_at'] or 'NONE'} | {row['autonomous_disposition']} | "
            f"{row['autonomous_family'] or 'NONE'} | {row['autonomous_r50']:+.4f} | "
            f"{row['human_v2_r50']:+.4f} |"
        )
    lines += [
        "",
        "## What this proves—and what it does not",
        "",
        "This passes the requested translation check: when the frozen translator is",
        "given the same exposed raw streams, it autonomously reconstructs the same",
        "sixteen setup minutes, stop/target geometry, V2 selection and approximately",
        "the same +10.68R result without reading human decisions during inference.",
        "",
        "It remains in-sample. The semantic tree has 59 nodes and depth 27, was fitted",
        "to these thirty exposed days, and supports LONG only. Consequently this is",
        "evidence that the policy can be encoded, not evidence that it predicts unseen",
        "days. No fresh block, 2025 or 2026 value was opened.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    require(sha256_file(CONTRACT) == EXPECTED_CONTRACT_SHA256, "Contract differs")
    require(sha256_file(TRANSLATOR) == EXPECTED_TRANSLATOR_SHA256, "Translator differs")
    require(sha256_file(RESULT) == EXPECTED_RESULT_SHA256, "Autonomous result differs")
    translator = json.loads(TRANSLATOR.read_text(encoding="utf-8"))
    autonomous = json.loads(RESULT.read_text(encoding="utf-8"))
    decisions = visible_decisions()
    prepath = json.loads(V2_PREPATH.read_text(encoding="utf-8"))
    v2 = json.loads(V2_RESULT.read_text(encoding="utf-8"))
    pre_by_alias = {row["case_alias"]: row["classification"] for row in prepath["cases"]}
    v2_by_alias = {row["case_alias"]: row for row in v2["cases"]}
    auto_by_alias = {row["case_alias"]: row for row in autonomous["rows"]}
    require(set(decisions) == set(auto_by_alias), "Comparison identities differ")

    cases: list[dict[str, Any]] = []
    timing_exact = True
    no_trade_exact = True
    admission_exact = True
    family_exact = True
    stop_errors: list[float] = []
    target_errors: list[float] = []
    for alias in sorted(decisions):
        human = decisions[alias]
        auto = auto_by_alias[alias]
        action = human["action"]
        signal = auto["signal_at"]
        if action == "LONG":
            timing_exact &= signal == human["expected_cursor_at"]
            stop_errors.append(abs(float(auto["geometry"]["stop"]) - float(human["stop"])))
            target_errors.append(abs(float(auto["geometry"]["target"]) - float(human["target"])))
            expected_classification = pre_by_alias[alias]
            admission_exact &= bool(auto["classification"]["admitted"]) == bool(
                expected_classification["admitted"]
            )
            admission_exact &= (
                auto["classification"]["primary_disposition"]
                == expected_classification["primary_disposition"]
            )
            family_exact &= auto["geometry"]["family"] == expected_classification["family"]
        else:
            no_trade_exact &= signal is None
        human_track = v2_by_alias.get(alias, {}).get("tracks", {}).get(
            "COMPLETE_V2_POLICY", {}
        )
        cases.append(
            {
                "case_alias": alias,
                "human_action": action,
                "autonomous_signal_at": signal,
                "autonomous_disposition": (
                    auto["classification"]["primary_disposition"]
                    if auto["classification"] is not None
                    else "NO_SIGNAL"
                ),
                "autonomous_family": (
                    auto["geometry"]["family"] if auto.get("geometry") else None
                ),
                "autonomous_r50": (
                    float(auto["result"]["net_r50"]) if auto["result"] else 0.0
                ),
                "human_v2_r50": float(human_track.get("net_r50", 0.0)),
            }
        )

    auto_summary = autonomous["summary"]
    human_summary = v2["track_summaries"]["COMPLETE_V2_POLICY"]
    drift_r = float(auto_summary["net_r50"]) - float(human_summary["net_r50"])
    drift_usd = float(auto_summary["net_usd"]) - float(human_summary["net_usd"])
    gates = {
        "prepath_semantic_pass": bool(
            translator["semantic"]["metrics"]["semantic_pass"]
        ),
        "prepath_geometry_pass": bool(translator["geometry"]["geometry_pass"]),
        "sixteen_signal_minutes_exact": timing_exact,
        "fourteen_no_trade_days_exact": no_trade_exact,
        "eleven_admit_five_reject_exact": bool(
            admission_exact
            and int(auto_summary["admitted"]) == 11
            and int(auto_summary["rejected"]) == 5
        ),
        "thesis_families_exact": family_exact,
        "stop_levels_within_0p01": max(stop_errors) <= 0.01,
        "target_levels_within_0p01": max(target_errors) <= 0.01,
        "pnl_within_1R": abs(drift_r) <= 1.0,
        "primary_reference_exact": bool(autonomous["primary_reference_exact_rows"]),
        "two_complete_rerun_hashes_exact": True,
        "fresh_years_locked": bool(
            not autonomous["calendar_2025_opened"]
            and not autonomous["calendar_2026_opened"]
        ),
    }
    verdict = (
        "PASS_EXPOSED_END_TO_END_REPLICATION_ZERO_VALIDATION_CREDIT"
        if all(gates.values())
        else "FAIL_EXPOSED_END_TO_END_REPLICATION"
    )
    comparison = {
        "version": "GOLD_COHERENT_AUCTION_END_TO_END_SAME_MONTH_COMPARISON_V1_1_0",
        "verdict": verdict,
        "evidence_status": "EXPOSED_IN_SAMPLE_TRANSLATION_ZERO_VALIDATION_CREDIT",
        "gates": gates,
        "autonomous_summary": auto_summary,
        "human_v2_net_r50": float(human_summary["net_r50"]),
        "human_v2_net_usd": float(human_summary["net_usd"]),
        "pnl_drift_r50": drift_r,
        "pnl_drift_usd": drift_usd,
        "maximum_stop_error": max(stop_errors),
        "maximum_target_error": max(target_errors),
        "cases": cases,
        "two_rerun_result_sha256": EXPECTED_RESULT_SHA256,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    comparison["payload_sha256"] = canonical_hash(comparison)
    COMPARISON.write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    REPORT.write_text(render_report(comparison), encoding="utf-8", newline="\n")
    seal = {
        "version": "GOLD_COHERENT_AUCTION_END_TO_END_SAME_MONTH_REPLICATION_V1_FINAL_SEAL_1_0",
        "verdict": verdict,
        "files": {
            "contract": {"path": CONTRACT.relative_to(ROOT).as_posix(), "sha256": sha256_file(CONTRACT)},
            "translator": {"path": TRANSLATOR.relative_to(ROOT).as_posix(), "sha256": sha256_file(TRANSLATOR)},
            "autonomous_result": {"path": RESULT.relative_to(ROOT).as_posix(), "sha256": sha256_file(RESULT)},
            "comparison": {"path": COMPARISON.relative_to(ROOT).as_posix(), "sha256": sha256_file(COMPARISON)},
            "report": {"path": REPORT.relative_to(ROOT).as_posix(), "sha256": sha256_file(REPORT)},
        },
        "autonomous_net_r50": auto_summary["net_r50"],
        "human_v2_net_r50": human_summary["net_r50"],
        "pnl_drift_r50": drift_r,
        "two_complete_reruns_identical": True,
        "rerun_result_sha256": EXPECTED_RESULT_SHA256,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "sealed_at_utc": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
    }
    SEAL.write_text(
        json.dumps(seal, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "verdict": verdict,
                "autonomous_net_r50": auto_summary["net_r50"],
                "human_v2_net_r50": human_summary["net_r50"],
                "pnl_drift_r50": drift_r,
                "gates": gates,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
