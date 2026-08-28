#!/usr/bin/env python3
"""One-shot unchanged-translator run on the sealed 50-case unseen block."""

from __future__ import annotations

import gc
import gzip
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from gold_coherent_auction_end_to_end_v1_common import (  # noqa: E402
    load_certified_streams,
    materialize_case,
    predict_class,
    predict_class_probability,
    predict_regression,
    prepare_features,
    require,
    sha256_file,
    transform_rows,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    iso,
)
from gold_intel.analytics.coherent_auction_human_policy_v2 import (  # noqa: E402
    simulate_track,
)
from run_gold_coherent_auction_end_to_end_v1_inference import (  # noqa: E402
    classify_autonomous,
    first_m1_after,
    latest_m1_at,
    spread,
    summarize,
)


CONTRACT = ROOT / "GOLD_COHERENT_AUCTION_FROZEN_TRANSLATOR_UNSEEN_BLOCK_V1.md"
TRANSLATOR = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_end_to_end_same_month_v1"
    / "translator.json"
)
EXPOSED_CERTIFICATION = (
    ROOT
    / "research_artifacts"
    / "gold_matched_human_replay_v1"
    / "stream_materialization_certification.json"
)
EXPOSED_RESULT = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_end_to_end_same_month_v1"
    / "autonomous_result.json"
)
VALIDATION_ROOT = (
    ROOT / "research_artifacts" / "gold_coherent_auction_blind_validation_v1"
)
VALIDATION_CERTIFICATION = VALIDATION_ROOT / "stream_materialization_certification.json"
VALIDATION_REGISTRY = VALIDATION_ROOT / "population_registry.private.json"
PRIMARY_STREAM = VALIDATION_ROOT / "validation_streams.primary.jsonl.gz"
REFERENCE_STREAM = VALIDATION_ROOT / "validation_streams.reference.jsonl.gz"
OUT = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_frozen_translator_unseen_block_v1"
)
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY_RESULT = OUT / "unseen_primary.json"
REFERENCE_RESULT = OUT / "unseen_reference.json"
RESULT = OUT / "unseen_result.json"
REPORT = ROOT / "GOLD_COHERENT_AUCTION_FROZEN_TRANSLATOR_UNSEEN_BLOCK_V1_REPORT.md"
FINAL_SEAL = OUT / "final_seal.json"

TRANSLATOR_SHA256 = "c95e200194bece77ed435741202d1bacd4f267ab0f1d1ed7803dd9d4ebd30841"
EXPOSED_RESULT_SHA256 = "c2ff398eaf3cb865191e85bace5542a79a9d23063fe51d164c4b31bc7979637d"
STREAM_SHA256 = "b3f1628e30f1549253478fb45d628bd09eab3abf95fed492c715e030a9b819ef"
CERTIFICATION_SHA256 = "7d079c11c3b55dce81d0972ac82102cf8c8963e5e6ae4644e48fb4291e57014a"
REGISTRY_SHA256 = "2faef0abde0bd677ec9712bb676c7114dcd39037d4d2da40b417d9ec4ff912ad"
POPULATION_SHA256 = "36a60ccfccedda19a39a48e6c38326b5f0d54f8bd7380cfd1595aa27d8c791f3"


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def write_new_json(path: Path, payload: dict[str, Any]) -> None:
    require(not path.exists(), f"Append-only output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def verify_freeze() -> dict[str, Any]:
    require(FREEZE.is_file(), "Prevalue freeze is absent")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    submitted = freeze.pop("freeze_sha256")
    require(canonical_hash(freeze) == submitted, "Prevalue freeze payload differs")
    freeze["freeze_sha256"] = submitted
    require(
        freeze["status"] == "SEALED_BEFORE_UNSEEN_STREAM_OPEN",
        "Prevalue freeze status differs",
    )
    for record in freeze["files"].values():
        path = ROOT / record["path"]
        require(path.is_file(), f"Frozen file is absent: {path}")
        require(sha256_file(path) == record["sha256"], f"Frozen file differs: {path}")
    require(sha256_file(TRANSLATOR) == TRANSLATOR_SHA256, "Translator differs")
    require(sha256_file(EXPOSED_RESULT) == EXPOSED_RESULT_SHA256, "Control differs")
    require(
        sha256_file(VALIDATION_CERTIFICATION) == CERTIFICATION_SHA256,
        "Validation certification differs",
    )
    require(sha256_file(VALIDATION_REGISTRY) == REGISTRY_SHA256, "Registry differs")
    require(sha256_file(PRIMARY_STREAM) == STREAM_SHA256, "Primary stream differs")
    require(sha256_file(REFERENCE_STREAM) == STREAM_SHA256, "Reference stream differs")
    return freeze


def load_bundle(path: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    require(sha256_file(path) == STREAM_SHA256, f"Certified bundle differs: {path}")
    streams: dict[str, dict[str, Any]] = {}
    lineage: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for source_row, line in enumerate(handle, start=1):
            payload = json.loads(line)
            submitted = payload.pop("stream_sha256")
            require(
                canonical_hash(payload) == submitted,
                f"Stream payload differs at source row {source_row}",
            )
            payload["stream_sha256"] = submitted
            alias = str(payload["case_alias"])
            require(alias not in streams, f"Duplicate validation alias: {alias}")
            streams[alias] = payload
            lineage.append(
                {
                    "source_row": source_row,
                    "case_alias": alias,
                    "stream_sha256": submitted,
                    "population_identity_sha256": payload["source_lineage"][
                        "population_sha256"
                    ],
                }
            )
    expected = [f"GAV-2022-{index:03d}" for index in range(1, 51)]
    require(list(streams) == expected, "Validation alias order differs")
    require(len(streams) == 50, "Expected exactly 50 validation streams")
    require(
        sum(row["session_code"] == "LONDON" for row in streams.values()) == 25,
        "London validation count differs",
    )
    require(
        sum(row["session_code"] == "NEW_YORK" for row in streams.values()) == 25,
        "New York validation count differs",
    )
    return streams, lineage


def infer_streams(
    *,
    streams: dict[str, dict[str, Any]],
    lineage: list[dict[str, Any]],
    translator: dict[str, Any],
    side: str,
    include_validation_metadata: bool,
) -> dict[str, Any]:
    prepared = prepare_features(streams.values())
    rows: list[dict[str, Any]] = []
    semantic = translator["semantic"]
    geometry = translator["geometry"]
    schema = translator["preprocessing"]
    for alias in sorted(streams):
        stream = streams[alias]
        checkpoints = materialize_case(
            alias=alias,
            stream=stream,
            prepared=prepared,
            end_at=None,
        )
        signal_row: dict[str, Any] | None = None
        signal_probability: float | None = None
        for checkpoint in checkpoints:
            matrix = transform_rows([checkpoint], schema)
            probability = float(
                predict_class_probability(
                    semantic["tree"], matrix, positive_class=1
                )[0]
            )
            if probability >= float(semantic["threshold"]):
                signal_row = checkpoint
                signal_probability = probability
                break
        prefix = (
            {
                "session_code": stream["session_code"],
                "start_inclusive": stream["start_inclusive"],
                "end_exclusive": stream["end_exclusive"],
            }
            if include_validation_metadata
            else {}
        )
        if signal_row is None:
            row = {
                "case_alias": alias,
                "trading_date_utc": stream["trading_date_utc"],
                **prefix,
                "signal_at": None,
                "signal_probability": None,
                "classification": None,
                "result": None,
            }
            row["row_sha256"] = canonical_hash(row)
            rows.append(row)
            continue

        matrix = transform_rows([signal_row], schema)
        stop_distance = float(
            predict_regression(geometry["stop_distance_tree"], matrix)[0]
        )
        target_distance = float(
            predict_regression(geometry["target_distance_tree"], matrix)[0]
        )
        family = str(predict_class(geometry["family_tree"], matrix)[0])
        reference_close = float(signal_row["m1_reference_close"])
        m15_atr = float(signal_row["m15_atr_scale"])
        stop = reference_close - stop_distance * m15_atr
        target = reference_close + target_distance * m15_atr
        signal_at = str(signal_row["checkpoint_at"])
        fill_bar = first_m1_after(stream, signal_at)
        decision_bar = latest_m1_at(stream, signal_at)
        require(fill_bar is not None, f"Execution bar unavailable: {alias}")
        require(decision_bar is not None, f"Decision bar unavailable: {alias}")
        fill = float(fill_bar["open"]) + spread(fill_bar) / 2.0 + 0.05
        cost_per_ounce = spread(decision_bar) + 2.0 * 0.05
        classification = classify_autonomous(
            stream=stream,
            signal_at=signal_at,
            family=family,
            fill=fill,
            stop=stop,
            target=target,
            cost_per_ounce=cost_per_ounce,
        )
        result = simulate_track(
            classification=classification,
            stream=stream,
            fill_at=iso(fill_bar["open_at"]),
            track="COMPLETE_V2_POLICY",
        )
        row = {
            "case_alias": alias,
            "trading_date_utc": stream["trading_date_utc"],
            **prefix,
            "signal_at": signal_at,
            "signal_probability": signal_probability,
            "geometry": {
                "reference_close": reference_close,
                "m15_atr": m15_atr,
                "stop_distance_atr": stop_distance,
                "target_distance_atr": target_distance,
                "family": family,
                "fill_at": iso(fill_bar["open_at"]),
                "fill": fill,
                "stop": stop,
                "target": target,
                "cost_per_ounce": cost_per_ounce,
            },
            "classification": classification,
            "result": result,
        }
        row["row_sha256"] = canonical_hash(row)
        rows.append(row)
    output = {
        "version": "GOLD_COHERENT_AUCTION_FROZEN_TRANSLATOR_INFERENCE_V1_0",
        "side": side,
        "translator_sha256": TRANSLATOR_SHA256,
        "source_lineage_sha256": canonical_hash(lineage),
        "rows": rows,
        "summary": summarize(rows),
        "fitting_performed": False,
        "human_ledger_opened": False,
        "human_classification_opened": False,
        "stored_signal_registry_opened": False,
        "outcome_ledger_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    output["payload_sha256"] = canonical_hash(output)
    return output


def prove_exposed_control(translator: dict[str, Any]) -> dict[str, Any]:
    expected = json.loads(EXPOSED_RESULT.read_text(encoding="utf-8"))
    control: dict[str, Any] = {}
    for side in ("primary", "reference"):
        streams, lineage = load_certified_streams(EXPOSED_CERTIFICATION, side)
        reproduced = infer_streams(
            streams=streams,
            lineage=lineage,
            translator=translator,
            side=side,
            include_validation_metadata=False,
        )
        require(reproduced["rows"] == expected["rows"], f"Exposed {side} rows differ")
        require(
            reproduced["summary"] == expected["summary"],
            f"Exposed {side} summary differs",
        )
        control[side] = {
            "rows_sha256": canonical_hash(reproduced["rows"]),
            "summary_sha256": canonical_hash(reproduced["summary"]),
        }
        del streams, lineage, reproduced
        gc.collect()
    require(control["primary"] == control["reference"], "Control sides differ")
    return control


def net_values(rows: list[dict[str, Any]]) -> list[float]:
    return [
        float(row["result"]["net_r50"])
        for row in rows
        if row["result"] is not None and row["result"]["executed"]
    ]


def evaluation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    executed = [
        row
        for row in rows
        if row["result"] is not None and row["result"]["executed"]
    ]
    net = net_values(rows)
    wins = [value for value in net if value > 1e-12]
    losses = [value for value in net if value < -1e-12]
    profit_factor = (
        sum(wins) / abs(sum(losses))
        if losses
        else math.inf if wins else None
    )
    ordered = sorted(
        rows,
        key=lambda row: (
            row["trading_date_utc"],
            row["start_inclusive"],
            row["case_alias"],
        ),
    )
    halves = [ordered[:25], ordered[25:]]
    half_net = [sum(net_values(group)) for group in halves]
    stressed = sum(
        float(row["result"]["stressed_1_5x_cost_r50"])
        for row in executed
    )
    positive_gross_by_session: dict[str, float] = {}
    for session in ("LONDON", "NEW_YORK"):
        positive_gross_by_session[session] = sum(
            max(float(row["result"]["gross_usd"]) / 50.0, 0.0)
            for row in executed
            if row["session_code"] == session
        )
    positive_gross_total = sum(positive_gross_by_session.values())
    maximum_session_share = (
        max(positive_gross_by_session.values()) / positive_gross_total
        if positive_gross_total > 0
        else 1.0
    )
    summary = summarize(rows)
    expectancy = sum(net) / len(net) if net else 0.0
    integrity = True
    pass_gates = {
        "executed_trades_gte_20": len(executed) >= 20,
        "net_expectancy_positive": expectancy > 0.0,
        "profit_factor_gte_1p10": profit_factor is not None and profit_factor >= 1.10,
        "both_chronological_halves_positive": all(value > 0.0 for value in half_net),
        "maximum_session_positive_gross_share_lte_0p80": maximum_session_share <= 0.80,
        "stressed_1p5x_cost_net_positive": stressed > 0.0,
        "integrity_exact_reproduction_pass": integrity,
    }
    reject_gate = (
        expectancy <= 0.0
        or (profit_factor is not None and profit_factor < 1.0)
        or not integrity
    )
    verdict = (
        "PROVISIONAL_PASS"
        if all(pass_gates.values())
        else "REJECT" if reject_gate else "INCONCLUSIVE"
    )
    session_metrics: dict[str, Any] = {}
    for session in ("LONDON", "NEW_YORK"):
        subset = [row for row in rows if row["session_code"] == session]
        session_metrics[session] = {
            **summarize(subset),
            "expectancy_r50": (
                sum(net_values(subset)) / len(net_values(subset))
                if net_values(subset)
                else 0.0
            ),
            "stressed_1p5x_cost_net_r50": sum(
                float(row["result"]["stressed_1_5x_cost_r50"])
                for row in subset
                if row["result"] is not None and row["result"]["executed"]
            ),
        }
    return {
        "verdict": verdict,
        "pass_gates": pass_gates,
        "combined": {
            **summary,
            "executed_trades": len(executed),
            "expectancy_r50": expectancy,
            "profit_factor": profit_factor,
            "stressed_1p5x_cost_net_r50": stressed,
            "chronological_half_net_r50": half_net,
            "positive_gross_r50_by_session": positive_gross_by_session,
            "maximum_session_positive_gross_share": maximum_session_share,
        },
        "by_session": session_metrics,
    }


def markdown(result: dict[str, Any]) -> str:
    metrics = result["evaluation"]["combined"]
    lines = [
        "# Gold Coherent-Auction Frozen-Translator Unseen-Block V1 Report",
        "",
        f"Verdict: `{result['evaluation']['verdict']}`",
        "",
        "## Combined result",
        "",
        f"- Cases: `{metrics['cases']}`",
        f"- Signals / no-signals: `{metrics['signal_days']}` / `{metrics['no_signal_days']}`",
        f"- Admitted / rejected: `{metrics['admitted']}` / `{metrics['rejected']}`",
        f"- Wins / losses / scratches: `{metrics['wins']}` / `{metrics['losses']}` / `{metrics['scratches']}`",
        f"- Win rate: `{(metrics['win_rate'] or 0.0) * 100:.2f}%`",
        f"- Net: `{metrics['net_r50']:+.6f}R` / `${metrics['net_usd']:+.2f}`",
        f"- Expectancy: `{metrics['expectancy_r50']:+.6f}R/trade`",
        f"- Profit factor: `{metrics['profit_factor']}`",
        f"- Maximum drawdown: `{metrics['maximum_drawdown_r50']:.6f}R`",
        f"- 1.5x-cost net: `{metrics['stressed_1p5x_cost_net_r50']:+.6f}R`",
        f"- Chronological halves: `{metrics['chronological_half_net_r50'][0]:+.6f}R`, `{metrics['chronological_half_net_r50'][1]:+.6f}R`",
        "",
        "## Session results",
        "",
        "| Session | Signals | Admitted | Wins | Losses | Net R | Expectancy | PF |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for session, row in result["evaluation"]["by_session"].items():
        lines.append(
            f"| {session} | {row['signal_days']} | {row['admitted']} | {row['wins']} | "
            f"{row['losses']} | {row['net_r50']:+.4f} | {row['expectancy_r50']:+.4f} | "
            f"{row['profit_factor']} |"
        )
    lines.extend(
        [
            "",
            "## Every case",
            "",
            "| Case | Date | Session | Signal | Disposition | Family | Net R |",
            "|---|---|---|---|---|---|---:|",
        ]
    )
    for row in result["rows"]:
        classification = row["classification"]
        disposition = (
            "NO_SIGNAL"
            if classification is None
            else classification["primary_disposition"]
        )
        family = "NONE" if classification is None else classification["family"]
        net_r = 0.0 if row["result"] is None else float(row["result"]["net_r50"])
        lines.append(
            f"| {row['case_alias']} | {row['trading_date_utc']} | {row['session_code']} | "
            f"{row['signal_at'] or 'NONE'} | {disposition} | {family} | {net_r:+.4f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The translator and execution policy were not fitted or changed for this block. "
            "The result is an unseen-translator historical robustness test, not independent "
            "market validation or authorization for live trading. Calendar 2025 and 2026 "
            "remained unopened.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    freeze = verify_freeze()
    for path in (PRIMARY_RESULT, REFERENCE_RESULT, RESULT, REPORT, FINAL_SEAL):
        require(not path.exists(), f"One-shot output already exists: {path}")
    translator = json.loads(TRANSLATOR.read_text(encoding="utf-8"))
    require(
        translator["status"] == "PASS_PREPATH_TRANSLATOR_FREEZE",
        "Translator status differs",
    )
    control = prove_exposed_control(translator)

    primary_streams, primary_lineage = load_bundle(PRIMARY_STREAM)
    primary = infer_streams(
        streams=primary_streams,
        lineage=primary_lineage,
        translator=translator,
        side="primary",
        include_validation_metadata=True,
    )
    del primary_streams, primary_lineage
    gc.collect()

    reference_streams, reference_lineage = load_bundle(REFERENCE_STREAM)
    reference = infer_streams(
        streams=reference_streams,
        lineage=reference_lineage,
        translator=translator,
        side="reference",
        include_validation_metadata=True,
    )
    del reference_streams, reference_lineage
    gc.collect()

    require(primary["rows"] == reference["rows"], "Unseen primary/reference rows differ")
    require(
        primary["summary"] == reference["summary"],
        "Unseen primary/reference summary differs",
    )
    evaluation_result = evaluation(primary["rows"])
    write_new_json(PRIMARY_RESULT, primary)
    write_new_json(REFERENCE_RESULT, reference)
    combined = {
        "version": "GOLD_COHERENT_AUCTION_FROZEN_TRANSLATOR_UNSEEN_BLOCK_V1_RESULT_1_0",
        "completed_at": now(),
        "contract_sha256": sha256_file(CONTRACT),
        "prevalue_freeze_sha256": freeze["freeze_sha256"],
        "translator_sha256": TRANSLATOR_SHA256,
        "population_sha256": POPULATION_SHA256,
        "source_stream_sha256": STREAM_SHA256,
        "exposed_control_reproduction": control,
        "primary_reference_exact": True,
        "primary_sha256": sha256_file(PRIMARY_RESULT),
        "reference_sha256": sha256_file(REFERENCE_RESULT),
        "rows": primary["rows"],
        "evaluation": evaluation_result,
        "fitting_performed": False,
        "retuning_performed": False,
        "human_fresh_decisions_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    combined["result_sha256"] = canonical_hash(combined)
    write_new_json(RESULT, combined)
    require(not REPORT.exists(), f"Append-only report already exists: {REPORT}")
    REPORT.write_text(markdown(combined), encoding="utf-8", newline="\n")
    final_seal = {
        "version": "GOLD_COHERENT_AUCTION_FROZEN_TRANSLATOR_UNSEEN_BLOCK_V1_FINAL_SEAL_1_0",
        "sealed_at": now(),
        "verdict": evaluation_result["verdict"],
        "files": {
            "contract": {
                "path": CONTRACT.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(CONTRACT),
            },
            "prevalue_freeze": {
                "path": FREEZE.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(FREEZE),
            },
            "primary": {
                "path": PRIMARY_RESULT.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(PRIMARY_RESULT),
            },
            "reference": {
                "path": REFERENCE_RESULT.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(REFERENCE_RESULT),
            },
            "result": {
                "path": RESULT.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(RESULT),
            },
            "report": {
                "path": REPORT.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(REPORT),
            },
        },
        "translator_unchanged": True,
        "primary_reference_exact": True,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    final_seal["seal_sha256"] = canonical_hash(final_seal)
    write_new_json(FINAL_SEAL, final_seal)
    print(json.dumps({"verdict": evaluation_result["verdict"], **evaluation_result["combined"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
