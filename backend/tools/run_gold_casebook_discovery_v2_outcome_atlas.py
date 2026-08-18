from __future__ import annotations

import argparse
import gzip
import hashlib
import io
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


def main() -> None:
    args = _parser().parse_args()
    output_root = Path(args.output_root)
    _prepare_output_root(output_root)

    measurement_path = Path(args.measurement_manifest)
    contract_path = Path(args.contract_manifest)
    execution_path = Path(args.execution_manifest)
    casebook_path = Path(args.casebook_manifest)
    coverage_path = Path(args.coverage)
    baseline_root = Path(args.baseline_root)
    baseline_manifest_path = baseline_root / "manifest.json"
    trades_path = baseline_root / "trades.jsonl.gz"

    measurement = _load_json(measurement_path)
    measurement_hash = _verify_hashed_document(
        measurement,
        hash_field="manifest_hash",
        excluded_fields=(),
        label="measurement manifest",
    )
    _verify_measurement_freeze(measurement)
    contract = _load_json(contract_path)
    contract_hash = _verify_hashed_document(
        contract,
        hash_field="manifest_hash",
        excluded_fields=(),
        label="V2 contract manifest",
    )
    execution = _load_json(execution_path)
    execution_hash = _verify_hashed_document(
        execution,
        hash_field="manifest_hash",
        excluded_fields=(),
        label="execution manifest",
    )
    casebook = _load_json(casebook_path)
    casebook_hash = _verify_hashed_document(
        casebook,
        hash_field="manifest_hash",
        excluded_fields=(),
        label="casebook manifest",
    )
    coverage = _load_json(coverage_path)
    coverage_hash = _verify_hashed_document(
        coverage,
        hash_field="data_hash",
        excluded_fields=("generated_at",),
        label="V2 coverage",
    )
    baseline_manifest = _load_json(baseline_manifest_path)
    baseline_hash = _verify_hashed_document(
        baseline_manifest,
        hash_field="manifest_hash",
        excluded_fields=(),
        label="baseline bundle manifest",
    )
    _verify_source_lineage(
        measurement=measurement,
        contract_hash=contract_hash,
        execution_hash=execution_hash,
        casebook_hash=casebook_hash,
        coverage_hash=coverage_hash,
        baseline_hash=baseline_hash,
        baseline_manifest=baseline_manifest,
    )
    trades_artifact = _artifact(baseline_manifest, "trades.jsonl.gz")
    _verify_file_hash(trades_path, str(trades_artifact["sha256"]))

    pairs, source_trade_count = _load_source_pairs(
        trades_path,
        execution_manifest_hash=execution_hash,
    )
    expected_cases = int(casebook["record_counts"]["session_cases"])
    if len(pairs) != expected_cases:
        raise ValueError(f"Outcome pair count mismatch: {len(pairs)} != {expected_cases}")

    outcomes, sessions = build_atlas(
        pairs,
        measurement_manifest_hash=measurement_hash,
    )
    outcomes_path = output_root / "outcomes.jsonl.gz"
    outcome_count = _write_outcomes(outcomes_path, outcomes)
    outcomes_sha = _sha256(outcomes_path)
    atlas = {
        "atlas_version": ATLAS_VERSION,
        "schema_version": ATLAS_SCHEMA_VERSION,
        "governing_contract": "GOLD_CASEBOOK_DISCOVERY_CONTRACT_V2.md",
        "milestone": "V2_M2_DESCRIPTIVE_OUTCOME_ATLAS",
        "measurement_manifest": {
            "path": ("research_manifests/gold_casebook_discovery_v2_outcome_atlas_v01.json"),
            "hash": measurement_hash,
        },
        "source": {
            "contract_manifest_hash": contract_hash,
            "execution_manifest_hash": execution_hash,
            "casebook_manifest_hash": casebook_hash,
            "coverage_data_hash": coverage_hash,
            "baseline_bundle_manifest_hash": baseline_hash,
            "baseline_trades_sha256": trades_artifact["sha256"],
        },
        "research_interval": {
            **measurement["research_interval"],
            "calendar_2025_loaded": False,
        },
        "record_counts": {
            "source_baseline_trades_read": source_trade_count,
            "outcome_cases": outcome_count,
            "london_cases": sum(outcome.session_code == "LONDON" for outcome in outcomes),
            "new_york_cases": sum(outcome.session_code == "NEW_YORK" for outcome in outcomes),
        },
        "sessions": sessions,
        "guardrails": {
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
        },
        "outcome_ledger": {
            "path": "outcomes.jsonl.gz",
            "sha256": outcomes_sha,
            "record_count": outcome_count,
        },
        "next_milestone": {
            "code": "V2_M3_BOUNDED_RELATIONSHIP_DISCOVERY",
            "authorized": False,
        },
    }
    atlas["document_hash"] = canonical_hash(atlas)
    atlas_path = output_root / "atlas.json"
    _write_json(atlas_path, atlas)
    atlas_sha = _sha256(atlas_path)

    bundle = {
        "atlas_version": ATLAS_VERSION,
        "schema_version": ATLAS_SCHEMA_VERSION,
        "governing_contract": "GOLD_CASEBOOK_DISCOVERY_CONTRACT_V2.md",
        "milestone": "V2_M2_DESCRIPTIVE_OUTCOME_ATLAS",
        "measurement_manifest_hash": measurement_hash,
        "source": atlas["source"],
        "artifacts": [
            {
                "path": "outcomes.jsonl.gz",
                "bytes": outcomes_path.stat().st_size,
                "sha256": outcomes_sha,
                "record_count": outcome_count,
                "record_type_counts": {"V2_OUTCOME_CASE": outcome_count},
            },
            {
                "path": "atlas.json",
                "bytes": atlas_path.stat().st_size,
                "sha256": atlas_sha,
                "document_hash": atlas["document_hash"],
            },
        ],
        "integrity": {
            "source_artifact_hashes_verified": 6,
            "source_baseline_trades_read": source_trade_count,
            "outcome_record_hashes_written": outcome_count,
            "sessions_separate": True,
            "execution_changed": False,
            "relationship_discovery_performed": False,
            "calendar_2025_loaded": False,
        },
    }
    bundle["manifest_hash"] = canonical_hash(bundle)
    _write_json(output_root / "manifest.json", bundle)
    print(
        json.dumps(
            {
                "atlas_document_hash": atlas["document_hash"],
                "bundle_manifest_hash": bundle["manifest_hash"],
                "calendar_2025_loaded": False,
                "measurement_manifest_hash": measurement_hash,
                "outcome_cases": outcome_count,
                "output_root": str(output_root),
                "relationship_discovery_performed": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _load_source_pairs(
    path: Path,
    *,
    execution_manifest_hash: str,
) -> tuple[list[OutcomePair], int]:
    grouped: dict[str, dict[str, SourceTrade]] = defaultdict(dict)
    source_count = 0
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
            if record["record_type"] != "BASELINE_TRADE":
                raise ValueError("Unexpected baseline record type")
            if record["holdout_loaded"] is not False:
                raise ValueError("Baseline record says holdout was loaded")
            trade = _trade_from_record(record)
            if trade.execution_manifest_hash != execution_manifest_hash:
                raise ValueError("Baseline execution hash changed")
            if trade.session_date.year >= 2025:
                raise ValueError("Baseline trade enters calendar 2025")
            side = trade.side
            if side in grouped[trade.case_id]:
                raise ValueError(f"Duplicate {side} source: {trade.case_id}")
            grouped[trade.case_id][side] = SourceTrade(
                record_id=str(record["record_id"]),
                record_hash=str(record["record_hash"]),
                trade=trade,
            )
            source_count += 1
    if any(set(sides) != {"LONG", "SHORT"} for sides in grouped.values()):
        raise ValueError("One or more outcome cases lacks both fixed directions")
    pairs = [
        OutcomePair(long=sides["LONG"], short=sides["SHORT"])
        for _, sides in sorted(
            grouped.items(),
            key=lambda item: (
                item[1]["LONG"].trade.decision_at,
                item[0],
            ),
        )
    ]
    return pairs, source_count


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


def _write_outcomes(path: Path, outcomes: Sequence[Any]) -> int:
    count = 0
    with (
        path.open("wb") as raw,
        gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=6,
            fileobj=raw,
            mtime=0,
        ) as compressed,
        io.TextIOWrapper(
            compressed,
            encoding="utf-8",
            newline="\n",
        ) as text_output,
    ):
        for outcome in outcomes:
            record = finalize_record(
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
            text_output.write(
                json.dumps(
                    json_ready(record),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            count += 1
    return count


def _verify_measurement_freeze(manifest: Mapping[str, Any]) -> None:
    if manifest["status"] != "FROZEN_BEFORE_OUTCOME_LEDGER_ACCESS":
        raise ValueError("Measurement manifest is not pre-result frozen")
    if manifest["milestone"] != "V2_M2_DESCRIPTIVE_OUTCOME_ATLAS":
        raise ValueError("Unexpected measurement milestone")
    if manifest["research_interval"] != {
        "end_exclusive": "2025-01-01T00:00:00+00:00",
        "independent_validation_credit": False,
        "start_inclusive": "2021-08-01T00:00:00+00:00",
    }:
        raise ValueError("Unexpected atlas research interval")
    if not all(bool(value) for value in manifest["prohibited"].values()):
        raise ValueError("One or more Milestone 2 prohibitions is not frozen")


def _verify_source_lineage(
    *,
    measurement: Mapping[str, Any],
    contract_hash: str,
    execution_hash: str,
    casebook_hash: str,
    coverage_hash: str,
    baseline_hash: str,
    baseline_manifest: Mapping[str, Any],
) -> None:
    source = measurement["source"]
    if measurement["contract"]["manifest_hash"] != contract_hash:
        raise ValueError("Measurement manifest points to another V2 contract")
    if measurement["execution"]["execution_manifest_hash"] != execution_hash:
        raise ValueError("Measurement manifest points to another execution")
    expected = {
        "casebook_manifest_hash": casebook_hash,
        "coverage_data_hash": coverage_hash,
        "baseline_bundle_manifest_hash": baseline_hash,
    }
    for key, value in expected.items():
        if source[key] != value:
            raise ValueError(f"Measurement source mismatch: {key}")
    if baseline_manifest["source"]["execution_manifest_hash"] != execution_hash:
        raise ValueError("Baseline bundle execution lineage differs")
    if baseline_manifest["source"]["casebook_manifest_hash"] != casebook_hash:
        raise ValueError("Baseline bundle casebook lineage differs")
    trades = _artifact(baseline_manifest, "trades.jsonl.gz")
    if trades["sha256"] != source["baseline_trades_sha256"]:
        raise ValueError("Measurement baseline-trade hash differs")


def _prepare_output_root(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise ValueError(f"Output directory is not empty: {path}")


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
    calculated = canonical_hash(unhashed)
    if supplied != calculated:
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
        description="Build the frozen Gold Casebook V2 descriptive outcome atlas."
    )
    parser.add_argument("--measurement-manifest", required=True)
    parser.add_argument("--contract-manifest", required=True)
    parser.add_argument("--execution-manifest", required=True)
    parser.add_argument("--casebook-manifest", required=True)
    parser.add_argument("--coverage", required=True)
    parser.add_argument("--baseline-root", required=True)
    parser.add_argument("--output-root", required=True)
    return parser


if __name__ == "__main__":
    main()
