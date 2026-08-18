from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from gold_intel.analytics.casebook import (
    CASEBOOK_VERSION,
    HOLDOUT_START,
    canonical_hash,
    json_ready,
)

VALIDATION_VERSION = "GOLD_CASEBOOK_BASELINE_VALIDATION_V0_1"
BASELINE_VERSION = "GOLD_CASEBOOK_BASELINE_V0_1"
BASELINE_SCHEMA_VERSION = "gold-casebook-baseline-schema-0.1.0"
CONTROL_CODES = (
    "ALWAYS_LONG",
    "ALWAYS_SHORT",
    "DETERMINISTIC_RANDOM",
)
SESSION_CODES = ("LONDON", "NEW_YORK")
FORBIDDEN_FIELDS = {
    "stop",
    "stop_price",
    "target",
    "target_price",
    "mfe",
    "mae",
    "r_multiple",
    "fundamental_filter",
    "structure_filter",
}
Role = Literal["ENTRY", "EXIT"]


@dataclass(frozen=True, slots=True)
class ValidatedTrade:
    case_id: str
    session_code: str
    session_date: date
    control_code: str
    side: str
    entry_time: datetime
    holding_minutes: int
    gross_pnl_usd: float
    net_pnl_usd: float
    gross_return_basis_points: float
    net_return_basis_points: float
    spread_cost_usd: float
    slippage_cost_usd: float
    commission_usd: float
    total_cost_usd: float


@dataclass(frozen=True, slots=True)
class SourceExpectation:
    record_hash: str
    role: Role
    open_time: datetime
    close_time: datetime
    reference_price: float
    spread_price: float


def main() -> None:
    args = _parser().parse_args()
    bundle = Path(args.bundle)
    casebook_root = Path(args.casebook_bundle)
    execution_path = Path(args.execution_manifest)
    output = Path(args.output) if args.output else bundle / "semantic_validation.json"
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite validation evidence: {output}")

    artifact_manifest = _load_json(bundle / "manifest.json")
    baseline_manifest_hash = _verify_document_hash(
        artifact_manifest,
        hash_field="manifest_hash",
        label="baseline artifact manifest",
    )
    results = _load_json(bundle / "results.json")
    results_hash = _verify_document_hash(
        results,
        hash_field="results_hash",
        label="baseline results",
    )
    execution = _load_json(execution_path)
    execution_hash = _verify_document_hash(
        execution,
        hash_field="manifest_hash",
        label="execution manifest",
    )
    casebook = _load_json(casebook_root / "manifest.json")
    casebook_hash = _verify_document_hash(
        casebook,
        hash_field="manifest_hash",
        label="casebook manifest",
    )
    _verify_manifest_chain(
        artifact_manifest=artifact_manifest,
        results=results,
        execution=execution,
        execution_hash=execution_hash,
        casebook=casebook,
        casebook_hash=casebook_hash,
    )

    artifact_hashes = 0
    for artifact in artifact_manifest["artifacts"]:
        path = bundle / artifact["path"]
        if _sha256(path) != artifact["sha256"]:
            raise ValueError(f"Baseline artifact hash mismatch: {artifact['path']}")
        artifact_hashes += 1
    _progress(
        "BASELINE_ARTIFACTS_VERIFIED",
        artifact_hashes=artifact_hashes,
        manifest_hash=baseline_manifest_hash,
        results_hash=results_hash,
    )

    case_records = _load_source_cases(
        casebook_root / "sessions.jsonl.gz",
        expected_sha=execution["casebook"]["sessions_artifact_sha256"],
        execution=execution,
    )
    (
        validated_trades,
        price_expectations,
        trade_ids,
    ) = _validate_trade_ledger(
        bundle / "trades.jsonl.gz",
        execution=execution,
        execution_hash=execution_hash,
        cases=case_records,
        expected_count=int(results["ledger"]["record_count"]),
    )
    verified_price_records = _verify_source_prices(
        casebook_root / "price_bars.jsonl.gz",
        expected_sha=execution["casebook"]["price_artifact_sha256"],
        expectations=price_expectations,
    )
    _verify_control_matrix(
        validated_trades,
        results=results,
        cases=case_records,
    )
    _verify_aggregates(validated_trades, results=results)

    control_counts = Counter(
        (trade.session_code, trade.control_code)
        for trade in validated_trades
    )
    report: dict[str, Any] = {
        "validation_version": VALIDATION_VERSION,
        "baseline_version": BASELINE_VERSION,
        "baseline_manifest_hash": baseline_manifest_hash,
        "results_hash": results_hash,
        "execution_manifest_hash": execution_hash,
        "casebook_manifest_hash": casebook_hash,
        "holdout_loaded": False,
        "verified": {
            "baseline_artifact_hashes": artifact_hashes,
            "baseline_trade_record_hashes": len(trade_ids),
            "unique_baseline_trade_ids": len(trade_ids),
            "source_session_record_hashes": len(case_records),
            "source_price_record_hashes": verified_price_records,
            "control_counts": {
                session: {
                    control: control_counts[(session, control)]
                    for control in CONTROL_CODES
                }
                for session in SESSION_CODES
            },
        },
        "semantic_assertions": {
            "manifest_chain_matches_frozen_casebook_and_execution": True,
            "all_source_artifact_hashes_match": True,
            "all_trade_record_hashes_match": True,
            "all_trade_case_hashes_join_to_immutable_cases": True,
            "all_fill_bar_hashes_join_to_immutable_prices": True,
            "decision_entry_exit_clocks_and_dst_match": True,
            "always_long_always_short_and_seeded_random_directions_match": True,
            "spread_slippage_commission_and_net_cost_identities_match": True,
            "same_eligible_cases_receive_each_control": True,
            "reported_aggregates_recomputed_from_ledger": True,
            "stops_targets_and_rr_fields_absent": True,
            "calendar_2025_absent": True,
            "relationship_discovery_absent": True,
        },
    }
    report["validation_hash"] = canonical_hash(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(json_ready(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _progress(
        "BASELINE_SEMANTIC_VALIDATION_COMPLETE",
        output=str(output),
        validation_hash=report["validation_hash"],
        trades=len(validated_trades),
        source_price_records=verified_price_records,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently validate the frozen Gold casebook baseline ledger, "
            "source joins, costs, clocks, controls, and aggregates."
        )
    )
    parser.add_argument(
        "--bundle",
        default="research_artifacts/gold_casebook_baseline_v01",
    )
    parser.add_argument(
        "--casebook-bundle",
        default="research_artifacts/gold_casebook_v01",
    )
    parser.add_argument(
        "--execution-manifest",
        default="research_manifests/gold_casebook_constant_execution_v01.json",
    )
    parser.add_argument("--output")
    return parser


def _verify_manifest_chain(
    *,
    artifact_manifest: Mapping[str, Any],
    results: Mapping[str, Any],
    execution: Mapping[str, Any],
    execution_hash: str,
    casebook: Mapping[str, Any],
    casebook_hash: str,
) -> None:
    if artifact_manifest["baseline_version"] != BASELINE_VERSION:
        raise ValueError("Baseline manifest version mismatch")
    if artifact_manifest["schema_version"] != BASELINE_SCHEMA_VERSION:
        raise ValueError("Baseline manifest schema mismatch")
    if results["baseline_version"] != BASELINE_VERSION:
        raise ValueError("Results version mismatch")
    if results["schema_version"] != BASELINE_SCHEMA_VERSION:
        raise ValueError("Results schema mismatch")
    if execution["status"] != "FROZEN_BEFORE_FIRST_RESULT":
        raise ValueError("Execution manifest is not frozen")
    if casebook["casebook_version"] != CASEBOOK_VERSION:
        raise ValueError("Casebook version mismatch")
    if execution["research_interval"]["holdout_loaded"] is not False:
        raise ValueError("Execution manifest loads the holdout")
    if casebook["contract"]["holdout_loaded"] is not False:
        raise ValueError("Casebook manifest loads the holdout")
    if results["research_interval"]["holdout_loaded"] is not False:
        raise ValueError("Results load the holdout")
    if results["research_interval"]["end_exclusive"] != HOLDOUT_START.isoformat():
        raise ValueError("Results holdout boundary mismatch")
    if execution["casebook"]["manifest_hash"] != casebook_hash:
        raise ValueError("Execution-to-casebook manifest chain mismatch")
    if results["source"]["casebook_manifest_hash"] != casebook_hash:
        raise ValueError("Results-to-casebook manifest chain mismatch")
    if results["source"]["execution_manifest_hash"] != execution_hash:
        raise ValueError("Results-to-execution manifest chain mismatch")
    source = artifact_manifest["source"]
    if source["casebook_manifest_hash"] != casebook_hash:
        raise ValueError("Artifact manifest-to-casebook chain mismatch")
    if source["execution_manifest_hash"] != execution_hash:
        raise ValueError("Artifact manifest-to-execution chain mismatch")
    guardrails = results["research_guardrails"]
    expected_guardrails = {
        "fixed_execution_applied_to_all_controls": True,
        "stops_or_targets_used": False,
        "entry_or_exit_optimized": False,
        "fundamental_or_structure_filtering_used": False,
        "relationship_discovery_performed": False,
        "calendar_2025_loaded": False,
        "account_scaling_or_leverage_assumed": False,
    }
    if guardrails != expected_guardrails:
        raise ValueError("Research guardrails changed")
    if execution["fill_rule"]["stop"] is not None:
        raise ValueError("Execution contains a stop")
    if execution["fill_rule"]["target"] is not None:
        raise ValueError("Execution contains a target")


def _load_source_cases(
    path: Path,
    *,
    expected_sha: str,
    execution: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    if _sha256(path) != expected_sha:
        raise ValueError("Immutable session artifact hash mismatch")
    output: dict[str, dict[str, Any]] = {}
    for record in _records(path):
        _verify_record_hash(record)
        if record["record_type"] != "SESSION_CASE":
            raise ValueError(f"Unexpected session record: {record['record_id']}")
        if record["holdout_loaded"] is not False:
            raise ValueError(f"Session loads holdout: {record['record_id']}")
        case_id = str(record["record_id"])
        if case_id in output:
            raise ValueError(f"Duplicate case: {case_id}")
        decision = _timestamp(record["decision_at"])
        observation_end = _timestamp(record["observation_end"])
        session = str(record["session_code"])
        session_date = date.fromisoformat(record["session_date"])
        _verify_local_clocks(
            session=session,
            session_date=session_date,
            decision_at=decision,
            entry_time=decision + timedelta(minutes=1),
            exit_time=observation_end,
            execution=execution,
        )
        if observation_end > HOLDOUT_START:
            raise ValueError(f"Session enters holdout: {case_id}")
        output[case_id] = {
            "record_hash": record["record_hash"],
            "session_code": session,
            "session_date": session_date,
            "decision_at": decision,
            "observation_end": observation_end,
        }
    return output


def _validate_trade_ledger(
    path: Path,
    *,
    execution: Mapping[str, Any],
    execution_hash: str,
    cases: Mapping[str, Mapping[str, Any]],
    expected_count: int,
) -> tuple[
    list[ValidatedTrade],
    dict[str, list[SourceExpectation]],
    set[str],
]:
    trades: list[ValidatedTrade] = []
    price_expectations: dict[str, list[SourceExpectation]] = defaultdict(list)
    identifiers: set[str] = set()
    for record in _records(path):
        _verify_record_hash(record)
        record_id = str(record["record_id"])
        if record_id in identifiers:
            raise ValueError(f"Duplicate baseline trade ID: {record_id}")
        identifiers.add(record_id)
        if record["record_type"] != "BASELINE_TRADE":
            raise ValueError(f"Unexpected baseline record: {record_id}")
        if record["baseline_version"] != BASELINE_VERSION:
            raise ValueError(f"Baseline version mismatch: {record_id}")
        if record["schema_version"] != BASELINE_SCHEMA_VERSION:
            raise ValueError(f"Baseline schema mismatch: {record_id}")
        if record["holdout_loaded"] is not False:
            raise ValueError(f"Baseline trade loads holdout: {record_id}")
        forbidden = FORBIDDEN_FIELDS.intersection(record)
        if forbidden:
            raise ValueError(f"Forbidden execution fields in {record_id}: {forbidden}")
        if record["execution_manifest_hash"] != execution_hash:
            raise ValueError(f"Execution hash mismatch: {record_id}")
        case_id = str(record["case_id"])
        case = cases.get(case_id)
        if case is None:
            raise ValueError(f"Unknown source case: {case_id}")
        if record["case_record_hash"] != case["record_hash"]:
            raise ValueError(f"Source case hash mismatch: {record_id}")
        session = str(record["session_code"])
        session_date = date.fromisoformat(record["session_date"])
        decision_at = _timestamp(record["decision_at"])
        entry_time = _timestamp(record["entry_time"])
        exit_time = _timestamp(record["exit_time"])
        if (
            session != case["session_code"]
            or session_date != case["session_date"]
            or decision_at != case["decision_at"]
            or exit_time != case["observation_end"]
        ):
            raise ValueError(f"Trade-to-case fields mismatch: {record_id}")
        _verify_local_clocks(
            session=session,
            session_date=session_date,
            decision_at=decision_at,
            entry_time=entry_time,
            exit_time=exit_time,
            execution=execution,
        )
        control = str(record["control_code"])
        if control not in CONTROL_CODES:
            raise ValueError(f"Unknown control: {record_id}")
        side = str(record["side"])
        expected_side = _expected_side(
            control,
            case_id=case_id,
            namespace=execution["controls"]["DETERMINISTIC_RANDOM"]["namespace"],
        )
        if side != expected_side:
            raise ValueError(f"Control direction mismatch: {record_id}")
        if record_id != f"BASELINE-{control}-{case_id}":
            raise ValueError(f"Baseline record ID is not deterministic: {record_id}")

        validated = _verify_costs(
            record,
            execution=execution,
            session_date=session_date,
            entry_time=entry_time,
        )
        trades.append(validated)
        entry_id = str(record["entry_bar_id"])
        exit_id = str(record["exit_bar_id"])
        price_expectations[entry_id].append(
            SourceExpectation(
                record_hash=str(record["entry_bar_hash"]),
                role="ENTRY",
                open_time=entry_time,
                close_time=entry_time + timedelta(minutes=1),
                reference_price=float(record["reference_entry_price"]),
                spread_price=float(record["entry_spread_price"]),
            )
        )
        price_expectations[exit_id].append(
            SourceExpectation(
                record_hash=str(record["exit_bar_hash"]),
                role="EXIT",
                open_time=exit_time - timedelta(minutes=1),
                close_time=exit_time,
                reference_price=float(record["reference_exit_price"]),
                spread_price=float(record["exit_spread_price"]),
            )
        )
    if len(trades) != expected_count:
        raise ValueError(f"Baseline trade count mismatch: {len(trades)} != {expected_count}")
    return trades, price_expectations, identifiers


def _verify_costs(
    record: Mapping[str, Any],
    *,
    execution: Mapping[str, Any],
    session_date: date,
    entry_time: datetime,
) -> ValidatedTrade:
    side = str(record["side"])
    direction = 1 if side == "LONG" else -1
    quantity = float(execution["notional"]["quantity_ounces"])
    lot_size = float(execution["notional"]["contract_size_ounces_per_lot"])
    quantity_lots = quantity / lot_size
    multiplier = float(execution["costs"]["cost_multiplier"])
    slippage_per_side = float(
        execution["costs"]["slippage_price_usd_per_ounce_per_side"]
    )
    commission_per_lot = float(
        execution["costs"]["commission_usd_per_lot_round_turn"]
    )
    entry_reference = float(record["reference_entry_price"])
    exit_reference = float(record["reference_exit_price"])
    entry_spread = float(record["entry_spread_price"])
    exit_spread = float(record["exit_spread_price"])
    expected_entry = entry_reference + direction * (
        entry_spread / 2 + slippage_per_side
    ) * multiplier
    expected_exit = exit_reference - direction * (
        exit_spread / 2 + slippage_per_side
    ) * multiplier
    gross = direction * (exit_reference - entry_reference) * quantity
    spread_cost = (
        (entry_spread + exit_spread) / 2 * quantity * multiplier
    )
    slippage_cost = 2 * slippage_per_side * quantity * multiplier
    commission = commission_per_lot * quantity_lots * multiplier
    total_cost = spread_cost + slippage_cost + commission
    net = direction * (expected_exit - expected_entry) * quantity - commission
    entry_notional = entry_reference * quantity
    gross_return = gross / entry_notional * 10_000
    net_return = net / entry_notional * 10_000
    expected = {
        "quantity_ounces": quantity,
        "quantity_lots": quantity_lots,
        "executed_entry_price": expected_entry,
        "executed_exit_price": expected_exit,
        "gross_pnl_usd": gross,
        "spread_cost_usd": spread_cost,
        "slippage_cost_usd": slippage_cost,
        "commission_usd": commission,
        "total_cost_usd": total_cost,
        "net_pnl_usd": net,
        "gross_return_basis_points": gross_return,
        "net_return_basis_points": net_return,
    }
    for field, value in expected.items():
        if not math.isclose(
            float(record[field]),
            value,
            rel_tol=0,
            abs_tol=5e-8,
        ):
            raise ValueError(
                f"{field} cost identity mismatch: {record['record_id']}"
            )
    if not math.isclose(gross - net, total_cost, rel_tol=0, abs_tol=1e-9):
        raise ValueError(f"Gross/net cost identity mismatch: {record['record_id']}")
    holding_minutes = int(record["holding_minutes"])
    exit_time = _timestamp(record["exit_time"])
    if holding_minutes != int(
        (exit_time - entry_time).total_seconds() // 60
    ):
        raise ValueError(f"Holding clock mismatch: {record['record_id']}")
    return ValidatedTrade(
        case_id=str(record["case_id"]),
        session_code=str(record["session_code"]),
        session_date=session_date,
        control_code=str(record["control_code"]),
        side=side,
        entry_time=entry_time,
        holding_minutes=holding_minutes,
        gross_pnl_usd=gross,
        net_pnl_usd=net,
        gross_return_basis_points=gross_return,
        net_return_basis_points=net_return,
        spread_cost_usd=spread_cost,
        slippage_cost_usd=slippage_cost,
        commission_usd=commission,
        total_cost_usd=total_cost,
    )


def _verify_source_prices(
    path: Path,
    *,
    expected_sha: str,
    expectations: Mapping[str, Sequence[SourceExpectation]],
) -> int:
    if _sha256(path) != expected_sha:
        raise ValueError("Immutable price artifact hash mismatch")
    remaining = set(expectations)
    verified = 0
    for record in _records(path):
        if record["timeframe"] != "1m":
            break
        record_id = str(record["record_id"])
        if record_id not in remaining:
            continue
        _verify_record_hash(record)
        ohlc = record["ohlc"]
        open_time = _timestamp(record["open_time"])
        close_time = _timestamp(record["close_time"])
        for expectation in expectations[record_id]:
            if record["record_hash"] != expectation.record_hash:
                raise ValueError(f"Source price hash mismatch: {record_id}")
            if (
                open_time != expectation.open_time
                or close_time != expectation.close_time
            ):
                raise ValueError(f"Source price clock mismatch: {record_id}")
            source_price = (
                float(ohlc["open"])
                if expectation.role == "ENTRY"
                else float(ohlc["close"])
            )
            if source_price != expectation.reference_price:
                raise ValueError(f"Source reference price mismatch: {record_id}")
            if float(record["spread_price"]) != expectation.spread_price:
                raise ValueError(f"Source spread mismatch: {record_id}")
        remaining.remove(record_id)
        verified += 1
        if not remaining:
            break
    if remaining:
        sample = sorted(remaining)[:5]
        raise ValueError(f"Missing source price records: {sample}")
    return verified


def _verify_control_matrix(
    trades: Sequence[ValidatedTrade],
    *,
    results: Mapping[str, Any],
    cases: Mapping[str, Mapping[str, Any]],
) -> None:
    matrix: dict[tuple[str, str], set[str]] = defaultdict(set)
    for trade in trades:
        key = (trade.session_code, trade.control_code)
        if trade.case_id in matrix[key]:
            raise ValueError(f"Duplicate case/control trade: {key} {trade.case_id}")
        matrix[key].add(trade.case_id)
    excluded_ids = {
        str(item["case_id"]) for item in results["eligibility"]["exclusions"]
    }
    for session in SESSION_CODES:
        expected = {
            case_id
            for case_id, item in cases.items()
            if item["session_code"] == session and case_id not in excluded_ids
        }
        declared = int(results["eligibility"]["eligible_cases"][session])
        if len(expected) != declared:
            raise ValueError(f"Declared eligibility count mismatch: {session}")
        for control in CONTROL_CODES:
            if matrix[(session, control)] != expected:
                raise ValueError(f"Control case matrix mismatch: {session}/{control}")


def _verify_aggregates(
    trades: Sequence[ValidatedTrade],
    *,
    results: Mapping[str, Any],
) -> None:
    for session in SESSION_CODES:
        for control in CONTROL_CODES:
            selected = [
                trade
                for trade in trades
                if trade.session_code == session
                and trade.control_code == control
            ]
            recomputed = _metrics(selected)
            reported = results["controls"][session][control]
            if recomputed != reported:
                raise ValueError(
                    f"Aggregate result mismatch: {session}/{control}"
                )


def _metrics(trades: Sequence[ValidatedTrade]) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda item: (item.entry_time, item.case_id))
    gross = [item.gross_pnl_usd for item in ordered]
    net = [item.net_pnl_usd for item in ordered]
    gross_returns = [item.gross_return_basis_points for item in ordered]
    net_returns = [item.net_return_basis_points for item in ordered]
    gains = math.fsum(value for value in net if value > 0)
    losses = math.fsum(value for value in net if value < 0)
    mean_return = statistics.fmean(net_returns)
    return_std = statistics.stdev(net_returns)
    ci_half_width = 1.96 * return_std / math.sqrt(len(ordered))
    direction_counts = Counter(item.side for item in ordered)
    return {
        "observations": len(ordered),
        "gross_win_rate_pct": _percentage(sum(value > 0 for value in gross), len(gross)),
        "net_win_rate_pct": _percentage(sum(value > 0 for value in net), len(net)),
        "mean_gross_pnl_usd_per_ounce": _rounded(statistics.fmean(gross)),
        "median_gross_pnl_usd_per_ounce": _rounded(statistics.median(gross)),
        "mean_net_pnl_usd_per_ounce": _rounded(statistics.fmean(net)),
        "median_net_pnl_usd_per_ounce": _rounded(statistics.median(net)),
        "mean_gross_return_basis_points": _rounded(
            statistics.fmean(gross_returns)
        ),
        "mean_net_return_basis_points": _rounded(mean_return),
        "mean_net_return_95pct_normal_ci_basis_points": [
            _rounded(mean_return - ci_half_width),
            _rounded(mean_return + ci_half_width),
        ],
        "total_gross_pnl_usd_per_ounce": _rounded(math.fsum(gross)),
        "total_net_pnl_usd_per_ounce": _rounded(math.fsum(net)),
        "profit_factor": _rounded(gains / abs(losses)) if losses < 0 else None,
        "maximum_drawdown_usd_per_ounce": _rounded(_maximum_drawdown(net)),
        "session_return_sharpe_sqrt_252": _rounded(
            mean_return / return_std * math.sqrt(252)
        ),
        "total_spread_cost_usd_per_ounce": _rounded(
            math.fsum(item.spread_cost_usd for item in ordered)
        ),
        "total_slippage_cost_usd_per_ounce": _rounded(
            math.fsum(item.slippage_cost_usd for item in ordered)
        ),
        "total_commission_usd_per_ounce": _rounded(
            math.fsum(item.commission_usd for item in ordered)
        ),
        "total_cost_usd_per_ounce": _rounded(
            math.fsum(item.total_cost_usd for item in ordered)
        ),
        "average_holding_minutes": _rounded(
            statistics.fmean(item.holding_minutes for item in ordered)
        ),
        "long_direction_count": direction_counts["LONG"],
        "short_direction_count": direction_counts["SHORT"],
        "results_by_year": {
            str(year): _year_metrics(
                [item for item in ordered if item.session_date.year == year]
            )
            for year in sorted({item.session_date.year for item in ordered})
        },
    }


def _year_metrics(trades: Sequence[ValidatedTrade]) -> dict[str, Any]:
    net = [item.net_pnl_usd for item in trades]
    returns = [item.net_return_basis_points for item in trades]
    gains = math.fsum(value for value in net if value > 0)
    losses = math.fsum(value for value in net if value < 0)
    return {
        "observations": len(trades),
        "net_win_rate_pct": _percentage(sum(value > 0 for value in net), len(net)),
        "mean_net_pnl_usd_per_ounce": _rounded(statistics.fmean(net)),
        "mean_net_return_basis_points": _rounded(statistics.fmean(returns)),
        "total_net_pnl_usd_per_ounce": _rounded(math.fsum(net)),
        "profit_factor": _rounded(gains / abs(losses)) if losses < 0 else None,
    }


def _verify_local_clocks(
    *,
    session: str,
    session_date: date,
    decision_at: datetime,
    entry_time: datetime,
    exit_time: datetime,
    execution: Mapping[str, Any],
) -> None:
    definition = execution["sessions"][session]
    zone = ZoneInfo(definition["timezone"])
    local_decision = decision_at.astimezone(zone)
    local_entry = entry_time.astimezone(zone)
    local_exit = exit_time.astimezone(zone)
    if not (
        local_decision.date()
        == local_entry.date()
        == local_exit.date()
        == session_date
    ):
        raise ValueError(f"{session} local dates mismatch")
    if local_decision.strftime("%H:%M") != definition["decision_clock_local"]:
        raise ValueError(f"{session} decision clock mismatch")
    if local_entry.strftime("%H:%M") != definition["entry_clock_local"]:
        raise ValueError(f"{session} entry clock mismatch")
    if local_exit.strftime("%H:%M") != definition["fixed_exit_clock_local"]:
        raise ValueError(f"{session} exit clock mismatch")
    if entry_time != decision_at + timedelta(
        minutes=int(execution["fill_rule"]["entry_latency_minutes"])
    ):
        raise ValueError(f"{session} entry latency mismatch")


def _expected_side(
    control: str,
    *,
    case_id: str,
    namespace: str,
) -> str:
    if control == "ALWAYS_LONG":
        return "LONG"
    if control == "ALWAYS_SHORT":
        return "SHORT"
    digest = hashlib.sha256(f"{namespace}|{case_id}".encode("ascii")).digest()
    return "LONG" if digest[0] < 128 else "SHORT"


def _maximum_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _percentage(numerator: int, denominator: int) -> float:
    return _rounded(100 * numerator / denominator)


def _rounded(value: float) -> float:
    return round(value, 8)


def _verify_record_hash(record: Mapping[str, Any]) -> None:
    supplied = str(record["record_hash"])
    unhashed = {key: value for key, value in record.items() if key != "record_hash"}
    if canonical_hash(unhashed) != supplied:
        raise ValueError(f"Record hash mismatch: {record['record_id']}")


def _verify_document_hash(
    value: Mapping[str, Any],
    *,
    hash_field: str,
    label: str,
) -> str:
    supplied = str(value[hash_field])
    unhashed = {key: item for key, item in value.items() if key != hash_field}
    if canonical_hash(unhashed) != supplied:
        raise ValueError(f"{label} hash mismatch")
    return supplied


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _records(path: Path) -> Iterable[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            yield json.loads(line)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Naive timestamp: {value}")
    return parsed.astimezone(UTC)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _progress(stage: str, **values: Any) -> None:
    print(
        json.dumps(json_ready({"stage": stage, **values}), sort_keys=True),
        flush=True,
    )


if __name__ == "__main__":
    main()
