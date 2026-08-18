from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import (
    canonical_hash,
    finalize_record,
    json_ready,
)
from gold_intel.backtesting.casebook_baseline import BaselineTrade
from gold_intel.backtesting.casebook_outcome_atlas import (
    ATLAS_SCHEMA_VERSION,
    ATLAS_VERSION,
    OutcomePair,
    SourceTrade,
    build_atlas,
    outcome_case_to_dict,
)

VALIDATION_VERSION = "GOLD_CASEBOOK_DISCOVERY_V2_OUTCOME_ATLAS_VALIDATION_V0_1"


def main() -> None:
    args = _parser().parse_args()
    root = Path(args.atlas_root)
    measurement = _load_json(Path(args.measurement_manifest))
    measurement_hash = _verify_hashed_document(
        measurement,
        hash_field="manifest_hash",
        excluded_fields=(),
        label="measurement manifest",
    )
    baseline_root = Path(args.baseline_root)
    baseline_manifest = _load_json(baseline_root / "manifest.json")
    baseline_hash = _verify_hashed_document(
        baseline_manifest,
        hash_field="manifest_hash",
        excluded_fields=(),
        label="baseline manifest",
    )
    baseline_trades_artifact = _artifact(baseline_manifest, "trades.jsonl.gz")
    baseline_trades_path = baseline_root / "trades.jsonl.gz"
    _verify_file_hash(
        baseline_trades_path,
        str(baseline_trades_artifact["sha256"]),
    )

    bundle = _load_json(root / "manifest.json")
    bundle_hash = _verify_hashed_document(
        bundle,
        hash_field="manifest_hash",
        excluded_fields=(),
        label="atlas bundle manifest",
    )
    if bundle["measurement_manifest_hash"] != measurement_hash:
        raise ValueError("Bundle measurement-manifest lineage differs")
    if bundle["source"]["baseline_bundle_manifest_hash"] != baseline_hash:
        raise ValueError("Bundle baseline lineage differs")
    _verify_bundle_artifacts(root, bundle)

    atlas = _load_json(root / "atlas.json")
    atlas_document_hash = _verify_hashed_document(
        atlas,
        hash_field="document_hash",
        excluded_fields=(),
        label="atlas document",
    )
    atlas_artifact = _artifact(bundle, "atlas.json")
    if atlas_artifact["document_hash"] != atlas_document_hash:
        raise ValueError("Bundle atlas-document hash differs")

    pairs, source_trade_count = _load_source_pairs(
        baseline_trades_path,
        execution_manifest_hash=str(measurement["execution"]["execution_manifest_hash"]),
    )
    expected_outcomes, expected_sessions = build_atlas(
        pairs,
        measurement_manifest_hash=measurement_hash,
    )
    actual_outcomes = _load_and_verify_outcomes(
        root / "outcomes.jsonl.gz",
        expected_outcomes=expected_outcomes,
    )
    if atlas["sessions"] != expected_sessions:
        raise ValueError("Atlas session summaries do not reconstruct")
    if atlas["record_counts"] != {
        "source_baseline_trades_read": source_trade_count,
        "outcome_cases": len(expected_outcomes),
        "london_cases": sum(outcome.session_code == "LONDON" for outcome in expected_outcomes),
        "new_york_cases": sum(outcome.session_code == "NEW_YORK" for outcome in expected_outcomes),
    }:
        raise ValueError("Atlas record counts do not reconstruct")
    _verify_guardrails(atlas)

    validation: dict[str, Any] = {
        "validation_version": VALIDATION_VERSION,
        "atlas_version": ATLAS_VERSION,
        "schema_version": ATLAS_SCHEMA_VERSION,
        "milestone": "V2_M2_DESCRIPTIVE_OUTCOME_ATLAS",
        "source": {
            "measurement_manifest_hash": measurement_hash,
            "baseline_bundle_manifest_hash": baseline_hash,
            "baseline_trades_sha256": baseline_trades_artifact["sha256"],
            "bundle_manifest_hash": bundle_hash,
            "atlas_document_hash": atlas_document_hash,
            "outcomes_sha256": _artifact(bundle, "outcomes.jsonl.gz")["sha256"],
        },
        "checks": {
            "source_artifact_hashes_verified": True,
            "source_record_hashes_verified": source_trade_count,
            "both_directions_reconstructed_per_case": len(expected_outcomes),
            "outcome_record_hashes_verified": actual_outcomes,
            "outcome_records_reconstructed_exactly": actual_outcomes,
            "session_summaries_reconstructed_exactly": 2,
            "year_quarter_month_summaries_reconstructed_exactly": True,
            "constant_execution_lineage_verified": True,
            "sessions_remained_separate": True,
            "relationship_discovery_performed": False,
            "explanatory_features_loaded": False,
            "calendar_2025_loaded": False,
            "calendar_2026_loaded": False,
        },
        "result": "PASS_SEMANTIC_VALIDATION",
    }
    validation["validation_hash"] = canonical_hash(validation)
    validation_path = root / "semantic_validation.json"
    _write_json(validation_path, validation)
    Path(args.markdown_output).write_text(
        _render_markdown(
            atlas=atlas,
            bundle=bundle,
            validation=validation,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "atlas_document_hash": atlas_document_hash,
                "bundle_manifest_hash": bundle_hash,
                "calendar_2025_loaded": False,
                "outcome_cases_validated": actual_outcomes,
                "relationship_discovery_performed": False,
                "result": validation["result"],
                "validation_hash": validation["validation_hash"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def _load_and_verify_outcomes(
    path: Path,
    *,
    expected_outcomes: Sequence[Any],
) -> int:
    expected = {
        outcome.case_id: finalize_record(
            {
                "record_type": "V2_OUTCOME_CASE",
                "record_id": f"V2-OUTCOME-{outcome.case_id}",
                "atlas_version": ATLAS_VERSION,
                "schema_version": ATLAS_SCHEMA_VERSION,
                "epistemic_status": "CALCULATED",
                "holdout_loaded": False,
                **outcome_case_to_dict(outcome),
            }
        )
        for outcome in expected_outcomes
    }
    actual: dict[str, Mapping[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2025-' in line or '"session_date":"2026-' in line:
                raise ValueError("Outcome ledger enters a locked calendar")
            record = json.loads(line)
            _verify_record_hash(record)
            case_id = str(record["case_id"])
            if case_id in actual:
                raise ValueError(f"Duplicate outcome record: {case_id}")
            if record != json_ready(expected[case_id]):
                raise ValueError(f"Outcome record does not reconstruct: {case_id}")
            actual[case_id] = record
    if set(actual) != set(expected):
        raise ValueError("Outcome ledger case set differs from source")
    return len(actual)


def _load_source_pairs(
    path: Path,
    *,
    execution_manifest_hash: str,
) -> tuple[list[OutcomePair], int]:
    grouped: dict[str, dict[str, SourceTrade]] = defaultdict(dict)
    count = 0
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2025-' in line or '"session_date":"2026-' in line:
                raise ValueError("Baseline source enters a locked calendar")
            if (
                '"control_code":"ALWAYS_LONG"' not in line
                and '"control_code":"ALWAYS_SHORT"' not in line
            ):
                continue
            record = json.loads(line)
            _verify_record_hash(record)
            trade = _trade_from_record(record)
            if trade.execution_manifest_hash != execution_manifest_hash:
                raise ValueError("Source execution hash changed")
            if trade.session_date.year >= 2025:
                raise ValueError("Source trade enters the holdout")
            if trade.side in grouped[trade.case_id]:
                raise ValueError(f"Duplicate source side: {trade.case_id}")
            grouped[trade.case_id][trade.side] = SourceTrade(
                record_id=str(record["record_id"]),
                record_hash=str(record["record_hash"]),
                trade=trade,
            )
            count += 1
    if any(set(value) != {"LONG", "SHORT"} for value in grouped.values()):
        raise ValueError("Source case lacks one fixed direction")
    return (
        [
            OutcomePair(long=value["LONG"], short=value["SHORT"])
            for _, value in sorted(
                grouped.items(),
                key=lambda item: (
                    item[1]["LONG"].trade.decision_at,
                    item[0],
                ),
            )
        ],
        count,
    )


def _trade_from_record(record: Mapping[str, Any]) -> BaselineTrade:
    return BaselineTrade(
        case_id=str(record["case_id"]),
        case_record_hash=str(record["case_record_hash"]),
        session_code=str(record["session_code"]),
        session_date=date.fromisoformat(str(record["session_date"])),
        control_code=str(record["control_code"]),  # type: ignore[arg-type]
        side=str(record["side"]),  # type: ignore[arg-type]
        decision_at=_timestamp(record["decision_at"]),
        entry_time=_timestamp(record["entry_time"]),
        exit_time=_timestamp(record["exit_time"]),
        holding_minutes=int(record["holding_minutes"]),
        entry_bar_id=str(record["entry_bar_id"]),
        entry_bar_hash=str(record["entry_bar_hash"]),
        exit_bar_id=str(record["exit_bar_id"]),
        exit_bar_hash=str(record["exit_bar_hash"]),
        reference_entry_price=float(record["reference_entry_price"]),
        reference_exit_price=float(record["reference_exit_price"]),
        executed_entry_price=float(record["executed_entry_price"]),
        executed_exit_price=float(record["executed_exit_price"]),
        entry_spread_price=float(record["entry_spread_price"]),
        exit_spread_price=float(record["exit_spread_price"]),
        quantity_ounces=float(record["quantity_ounces"]),
        quantity_lots=float(record["quantity_lots"]),
        gross_pnl_usd=float(record["gross_pnl_usd"]),
        spread_cost_usd=float(record["spread_cost_usd"]),
        slippage_cost_usd=float(record["slippage_cost_usd"]),
        commission_usd=float(record["commission_usd"]),
        total_cost_usd=float(record["total_cost_usd"]),
        net_pnl_usd=float(record["net_pnl_usd"]),
        gross_return_basis_points=float(record["gross_return_basis_points"]),
        net_return_basis_points=float(record["net_return_basis_points"]),
        execution_manifest_hash=str(record["execution_manifest_hash"]),
    )


def _verify_guardrails(atlas: Mapping[str, Any]) -> None:
    expected = {
        "descriptive_only": True,
        "sessions_evaluated_independently": True,
        "session_pairing_performed": False,
        "explanatory_features_loaded": False,
        "feature_outcome_join_performed": False,
        "relationship_discovery_performed": False,
        "candidate_defined_or_evaluated": False,
        "execution_changed_or_optimized": False,
        "mae_mfe_or_intraperiod_path_loaded": False,
        "calendar_2025_loaded": False,
        "calendar_2026_loaded": False,
        "edge_claim_made": False,
    }
    if atlas["guardrails"] != expected:
        raise ValueError("Atlas guardrails differ")
    if atlas["next_milestone"] != {
        "code": "V2_M3_BOUNDED_RELATIONSHIP_DISCOVERY",
        "authorized": False,
    }:
        raise ValueError("Atlas incorrectly authorizes the next milestone")


def _render_markdown(
    *,
    atlas: Mapping[str, Any],
    bundle: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> str:
    london = atlas["sessions"]["LONDON"]["overall"]
    new_york = atlas["sessions"]["NEW_YORK"]["overall"]
    year_rows = "\n".join(
        _year_markdown_rows("London", atlas["sessions"]["LONDON"]["by_calendar_year"])
        + _year_markdown_rows(
            "New York",
            atlas["sessions"]["NEW_YORK"]["by_calendar_year"],
        )
    )
    control_rows = "\n".join(
        _control_markdown_rows("London", london) + _control_markdown_rows("New York", new_york)
    )
    london_clear = round(
        100 - london["cost_hurdle"]["NO_SIDE_NET_WIN"]["pct"],
        4,
    )
    new_york_clear = round(
        100 - new_york["cost_hurdle"]["NO_SIDE_NET_WIN"]["pct"],
        4,
    )
    return f"""# Gold Casebook Discovery V2 Milestone 2: Descriptive Outcome Atlas

## Decision

V2 Milestone 2 is complete.

The atlas describes the fixed 08:01-to-12:00 London and New York targets over
2021-08-01 through 2024-12-31. It does not test why a move occurred and does not
claim an edge.

- Calendar 2025 remained locked.
- Calendar 2026 was not accessed.
- London and New York remained separate.
- No macro, structure, positioning, event, session-state, or cross-market
  explanatory feature was loaded.
- No relationship discovery, candidate evaluation, session pairing, MFE/MAE,
  or execution optimization occurred.

## Overall fixed-clock behaviour

| Session | Cases | Up | Down | Neither side net-profitable | Median absolute move | 75th percentile | 90th percentile | Median frozen cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| London | {london["case_count"]} | {london["direction"]["UP"]["pct"]}% | {london["direction"]["DOWN"]["pct"]}% | {london["cost_hurdle"]["NO_SIDE_NET_WIN"]["pct"]}% | USD {london["absolute_move_usd_per_ounce"]["median"]:.2f}/oz | USD {london["absolute_move_usd_per_ounce"]["quantiles"]["p75"]:.2f}/oz | USD {london["absolute_move_usd_per_ounce"]["quantiles"]["p90"]:.2f}/oz | USD {london["cost_usd_per_ounce"]["median"]:.2f}/oz |
| New York | {new_york["case_count"]} | {new_york["direction"]["UP"]["pct"]}% | {new_york["direction"]["DOWN"]["pct"]}% | {new_york["cost_hurdle"]["NO_SIDE_NET_WIN"]["pct"]}% | USD {new_york["absolute_move_usd_per_ounce"]["median"]:.2f}/oz | USD {new_york["absolute_move_usd_per_ounce"]["quantiles"]["p75"]:.2f}/oz | USD {new_york["absolute_move_usd_per_ounce"]["quantiles"]["p90"]:.2f}/oz | USD {new_york["cost_usd_per_ounce"]["median"]:.2f}/oz |

`Neither side net-profitable` means the four-hour absolute price change did not
clear the frozen spread, slippage, and commission hurdle. It is not a trading
filter.

The observed move cleared that hurdle in {london_clear}% of London cases and
{new_york_clear}% of New York cases. Direction itself remained nearly balanced,
so this is evidence of opportunity frequency, not directional predictability.

## Absolute move-size distribution

| Session | Below USD 2 | USD 2-5 | USD 5-10 | USD 10-20 | USD 20 or more |
|---|---:|---:|---:|---:|---:|
| London | {london["absolute_move_bins_usd_per_ounce"]["ABS_LT_2"]["pct"]}% | {london["absolute_move_bins_usd_per_ounce"]["ABS_2_TO_LT_5"]["pct"]}% | {london["absolute_move_bins_usd_per_ounce"]["ABS_5_TO_LT_10"]["pct"]}% | {london["absolute_move_bins_usd_per_ounce"]["ABS_10_TO_LT_20"]["pct"]}% | {london["absolute_move_bins_usd_per_ounce"]["ABS_GE_20"]["pct"]}% |
| New York | {new_york["absolute_move_bins_usd_per_ounce"]["ABS_LT_2"]["pct"]}% | {new_york["absolute_move_bins_usd_per_ounce"]["ABS_2_TO_LT_5"]["pct"]}% | {new_york["absolute_move_bins_usd_per_ounce"]["ABS_5_TO_LT_10"]["pct"]}% | {new_york["absolute_move_bins_usd_per_ounce"]["ABS_10_TO_LT_20"]["pct"]}% | {new_york["absolute_move_bins_usd_per_ounce"]["ABS_GE_20"]["pct"]}% |

## Fixed-direction controls

| Session | Control | Mean net return | Net win rate | Profit factor |
|---|---|---:|---:|---:|
{control_rows}

These controls apply one direction every day. They describe unconditional
drift under the frozen execution and are not candidate strategies.

## Chronological atlas

The machine-readable atlas contains the same frozen summaries in ascending:

- calendar year;
- calendar quarter; and
- calendar month.

These buckets are not ranked or selected. They are descriptive stability
records for the later bounded-discovery milestone.

### Calendar-year summaries

| Session | Year | Cases | Up | Down | Neither side net-profitable | Mean signed move | Median absolute move | 90th-percentile absolute move |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{year_rows}

## Integrity and reproducibility

| Artifact | Hash |
|---|---|
| Pre-result measurement manifest | `{atlas["measurement_manifest"]["hash"]}` |
| Outcome ledger | `{atlas["outcome_ledger"]["sha256"]}` |
| Atlas document | `{atlas["document_hash"]}` |
| Bundle manifest | `{bundle["manifest_hash"]}` |
| Independent semantic validation | `{validation["validation_hash"]}` |

Independent validation reconstructed all
{atlas["record_counts"]["outcome_cases"]} outcome cases from
{atlas["record_counts"]["source_baseline_trades_read"]} frozen long/short
baseline records and reproduced every overall, year, quarter, and month
summary.

## What this milestone establishes

It establishes the size, sign balance, cost hurdle, and chronological
distribution of the target we will later try to explain. It does not establish
which information predicts direction.

## Next contracted step

V2 Milestone 3 is bounded relationship discovery. It remains unauthorized and
was not started.

## Reproduce

```powershell
docker compose --profile test run --rm `
  -v "${{PWD}}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python /workspace/backend/tools/run_gold_casebook_discovery_v2_outcome_atlas.py `
  --measurement-manifest /workspace/research_manifests/gold_casebook_discovery_v2_outcome_atlas_v01.json `
  --contract-manifest /workspace/research_manifests/gold_casebook_discovery_contract_v02.json `
  --execution-manifest /workspace/research_manifests/gold_casebook_constant_execution_v01.json `
  --casebook-manifest /workspace/research_artifacts/gold_casebook_v01/manifest.json `
  --coverage /workspace/research_artifacts/gold_casebook_discovery_v2_coverage.json `
  --baseline-root /workspace/research_artifacts/gold_casebook_baseline_v01 `
  --output-root /workspace/research_artifacts/gold_casebook_discovery_v2_outcome_atlas_repro_v01

docker compose --profile test run --rm `
  -v "${{PWD}}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python /workspace/backend/tools/validate_gold_casebook_discovery_v2_outcome_atlas.py `
  --measurement-manifest /workspace/research_manifests/gold_casebook_discovery_v2_outcome_atlas_v01.json `
  --baseline-root /workspace/research_artifacts/gold_casebook_baseline_v01 `
  --atlas-root /workspace/research_artifacts/gold_casebook_discovery_v2_outcome_atlas_repro_v01 `
  --markdown-output /workspace/GOLD_CASEBOOK_DISCOVERY_V2_MILESTONE_2_REPRO.md
```
"""


def _year_markdown_rows(
    session_label: str,
    years: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    return [
        (
            f"| {session_label} | {year} | {summary['case_count']} | "
            f"{summary['direction']['UP']['pct']}% | "
            f"{summary['direction']['DOWN']['pct']}% | "
            f"{summary['cost_hurdle']['NO_SIDE_NET_WIN']['pct']}% | "
            f"USD {summary['gross_move_usd_per_ounce']['mean']:.2f}/oz | "
            f"USD {summary['absolute_move_usd_per_ounce']['median']:.2f}/oz | "
            "USD "
            f"{summary['absolute_move_usd_per_ounce']['quantiles']['p90']:.2f}/oz |"
        )
        for year, summary in years.items()
    ]


def _control_markdown_rows(
    session_label: str,
    summary: Mapping[str, Any],
) -> list[str]:
    return [
        (
            f"| {session_label} | {control.replace('_', ' ').title()} | "
            f"{metrics['mean_net_return_basis_points']:+.4f} bps | "
            f"{float(metrics['net_win_rate_pct']):.4f}% | "
            f"{_format_optional(metrics['profit_factor'], 4)} |"
        )
        for control, metrics in summary["fixed_controls"].items()
    ]


def _format_optional(value: Any, decimals: int) -> str:
    return "n/a" if value is None else f"{float(value):.{decimals}f}"


def _verify_bundle_artifacts(root: Path, manifest: Mapping[str, Any]) -> None:
    for name in ("outcomes.jsonl.gz", "atlas.json"):
        artifact = _artifact(manifest, name)
        path = root / name
        if path.stat().st_size != artifact["bytes"]:
            raise ValueError(f"Bundle artifact size differs: {name}")
        _verify_file_hash(path, str(artifact["sha256"]))


def _artifact(manifest: Mapping[str, Any], path: str) -> Mapping[str, Any]:
    matches = [item for item in manifest["artifacts"] if item["path"] == path]
    if len(matches) != 1:
        raise ValueError(f"Manifest does not contain exactly one {path}")
    return matches[0]


def _verify_record_hash(record: Mapping[str, Any]) -> None:
    supplied = str(record["record_hash"])
    unhashed = {key: value for key, value in record.items() if key != "record_hash"}
    if canonical_hash(unhashed) != supplied:
        raise ValueError(f"Record hash mismatch: {record['record_id']}")


def _verify_hashed_document(
    document: Mapping[str, Any],
    *,
    hash_field: str,
    excluded_fields: Sequence[str],
    label: str,
) -> str:
    supplied = str(document[hash_field])
    unhashed = {
        key: value
        for key, value in document.items()
        if key != hash_field and key not in excluded_fields
    }
    if canonical_hash(unhashed) != supplied:
        raise ValueError(f"{label} hash mismatch")
    return supplied


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_ready(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _verify_file_hash(path: Path, expected: str) -> None:
    if _sha256(path) != expected:
        raise ValueError(f"Artifact SHA-256 mismatch: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"Naive timestamp: {value}")
    return parsed.astimezone(UTC)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Independently validate the V2 descriptive outcome atlas."
    )
    parser.add_argument("--measurement-manifest", required=True)
    parser.add_argument("--baseline-root", required=True)
    parser.add_argument("--atlas-root", required=True)
    parser.add_argument("--markdown-output", required=True)
    return parser


if __name__ == "__main__":
    main()
