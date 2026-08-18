from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from gold_intel.analytics.casebook import (
    CASEBOOK_VERSION,
    HOLDOUT_START,
    canonical_hash,
    finalize_record,
    json_ready,
)
from gold_intel.backtesting.casebook_baseline import (
    BaselineCase,
    BaselineExecutionConfig,
    BaselinePriceBar,
    BaselineTrade,
    ControlCode,
    calculate_baseline_metrics,
    simulate_baseline_case,
    trade_to_dict,
)

BASELINE_VERSION = "GOLD_CASEBOOK_BASELINE_V0_1"
BASELINE_SCHEMA_VERSION = "gold-casebook-baseline-schema-0.1.0"
CONTROL_CODES: tuple[ControlCode, ...] = (
    "ALWAYS_LONG",
    "ALWAYS_SHORT",
    "DETERMINISTIC_RANDOM",
)
SESSION_CODES = ("LONDON", "NEW_YORK")


@dataclass(frozen=True, slots=True)
class EligibleCase:
    case: BaselineCase
    entry_bar: BaselinePriceBar
    exit_bar: BaselinePriceBar


def main() -> None:
    args = _parser().parse_args()
    casebook_root = Path(args.casebook_bundle)
    execution_manifest_path = Path(args.execution_manifest)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(
            f"Refusing to overwrite immutable baseline bundle: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    execution_manifest = _load_json(execution_manifest_path)
    execution_hash = _verify_hashed_document(
        execution_manifest,
        hash_field="manifest_hash",
        label="execution manifest",
    )
    _verify_execution_manifest(execution_manifest)

    casebook_manifest = _load_json(casebook_root / "manifest.json")
    casebook_hash = _verify_hashed_document(
        casebook_manifest,
        hash_field="manifest_hash",
        label="casebook manifest",
    )
    _verify_casebook_manifest(
        casebook_manifest,
        execution_manifest=execution_manifest,
    )
    _progress(
        "SOURCE_MANIFESTS_VERIFIED",
        execution_manifest_hash=execution_hash,
        casebook_manifest_hash=casebook_hash,
    )

    sessions_artifact = _artifact(casebook_manifest, "sessions.jsonl.gz")
    prices_artifact = _artifact(casebook_manifest, "price_bars.jsonl.gz")
    sessions_path = casebook_root / sessions_artifact["path"]
    prices_path = casebook_root / prices_artifact["path"]
    _verify_file_hash(sessions_path, sessions_artifact["sha256"])
    _verify_file_hash(prices_path, prices_artifact["sha256"])
    _progress(
        "SOURCE_ARTIFACT_HASHES_VERIFIED",
        sessions_sha256=sessions_artifact["sha256"],
        price_sha256=prices_artifact["sha256"],
    )

    cases = _load_cases(
        sessions_path,
        execution_manifest=execution_manifest,
        expected_count=int(sessions_artifact["record_count"]),
    )
    required_times = {
        case.decision_at + timedelta(minutes=1)
        for case in cases
    } | {
        case.observation_end - timedelta(minutes=1)
        for case in cases
    }
    bars = _load_price_bars(prices_path, required_times=required_times)
    eligible, exclusions = _eligible_cases(cases, bars=bars)
    _progress(
        "ELIGIBILITY_FROZEN",
        input_cases=len(cases),
        eligible_cases=len(eligible),
        exclusions=len(exclusions),
    )

    config = _execution_config(execution_manifest)
    trades = _run_controls(eligible, config=config)
    expected_trades = len(eligible) * len(CONTROL_CODES)
    if len(trades) != expected_trades:
        raise AssertionError(
            f"Trade ledger count mismatch: {len(trades)} != {expected_trades}"
        )

    with tempfile.TemporaryDirectory(
        dir=output.parent,
        prefix=f".{output.name}.staging-",
    ) as temporary:
        staging = Path(temporary)
        trades_path = staging / "trades.jsonl.gz"
        trade_count = _write_trades(trades_path, trades)
        trades_sha = _sha256(trades_path)

        results = _build_results(
            cases=cases,
            eligible=eligible,
            exclusions=exclusions,
            trades=trades,
            execution_manifest=execution_manifest,
            execution_hash=execution_hash,
            casebook_manifest=casebook_manifest,
            casebook_hash=casebook_hash,
            trades_sha=trades_sha,
            trade_count=trade_count,
        )
        results["results_hash"] = canonical_hash(results)
        results_path = staging / "results.json"
        _write_json(results_path, results)

        artifact_manifest: dict[str, Any] = {
            "baseline_version": BASELINE_VERSION,
            "schema_version": BASELINE_SCHEMA_VERSION,
            "governing_contract": "GOLD_CASEBOOK_RESEARCH_CONTRACT.md",
            "milestone": "3_CONSTANT_EXECUTION_BASELINE",
            "source": {
                "casebook_manifest_hash": casebook_hash,
                "execution_manifest_hash": execution_hash,
            },
            "artifacts": [
                {
                    "path": "trades.jsonl.gz",
                    "sha256": trades_sha,
                    "bytes": trades_path.stat().st_size,
                    "record_count": trade_count,
                    "record_type_counts": {"BASELINE_TRADE": trade_count},
                },
                {
                    "path": "results.json",
                    "sha256": _sha256(results_path),
                    "bytes": results_path.stat().st_size,
                    "document_hash": results["results_hash"],
                },
            ],
            "integrity": {
                "casebook_manifest_verified": True,
                "execution_manifest_verified": True,
                "source_artifact_hashes_verified": 2,
                "trade_record_hashes_written": trade_count,
                "holdout_loaded": False,
                "execution_optimized": False,
                "rule_discovery_performed": False,
            },
        }
        artifact_manifest["manifest_hash"] = canonical_hash(artifact_manifest)
        _write_json(staging / "manifest.json", artifact_manifest)
        staging.rename(output)

    _progress(
        "BASELINE_BUNDLE_COMPLETE",
        output=str(output),
        manifest_hash=artifact_manifest["manifest_hash"],
        results_hash=results["results_hash"],
        eligible_cases=len(eligible),
        trades=trade_count,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen London/New York constant-execution controls against "
            "the immutable pre-2025 Gold casebook."
        )
    )
    parser.add_argument(
        "--casebook-bundle",
        default="research_artifacts/gold_casebook_v01",
    )
    parser.add_argument(
        "--execution-manifest",
        default="research_manifests/gold_casebook_constant_execution_v01.json",
    )
    parser.add_argument(
        "--output",
        default="research_artifacts/gold_casebook_baseline_v01",
    )
    return parser


def _verify_execution_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest["manifest_version"] != "GOLD_CASEBOOK_CONSTANT_EXECUTION_V0_1":
        raise ValueError("Unexpected execution-manifest version")
    if manifest["status"] != "FROZEN_BEFORE_FIRST_RESULT":
        raise ValueError("Execution manifest was not frozen before results")
    if manifest["research_interval"]["holdout_loaded"] is not False:
        raise ValueError("Execution manifest says the holdout was loaded")
    if manifest["research_interval"]["end_exclusive"] != HOLDOUT_START.isoformat():
        raise ValueError("Unexpected execution-manifest holdout boundary")
    if manifest["fill_rule"]["stop"] is not None:
        raise ValueError("Baseline execution manifest contains a stop")
    if manifest["fill_rule"]["target"] is not None:
        raise ValueError("Baseline execution manifest contains a target")
    if manifest["fill_rule"]["early_exit"] is not None:
        raise ValueError("Baseline execution manifest contains an early exit")
    prohibited = manifest["prohibited"]
    if not all(bool(value) for value in prohibited.values()):
        raise ValueError("A prohibited baseline action is not locked")
    if tuple(manifest["controls"]) != CONTROL_CODES:
        raise ValueError("Unexpected control order or set")


def _verify_casebook_manifest(
    manifest: Mapping[str, Any],
    *,
    execution_manifest: Mapping[str, Any],
) -> None:
    if manifest["casebook_version"] != CASEBOOK_VERSION:
        raise ValueError("Unexpected casebook version")
    if manifest["contract"]["holdout_loaded"] is not False:
        raise ValueError("Casebook manifest says the holdout was loaded")
    if manifest["contract"]["case_end_exclusive"] != HOLDOUT_START.isoformat():
        raise ValueError("Unexpected casebook holdout boundary")
    expected = execution_manifest["casebook"]
    if manifest["manifest_hash"] != expected["manifest_hash"]:
        raise ValueError("Execution manifest points to another casebook")
    sessions = _artifact(manifest, "sessions.jsonl.gz")
    prices = _artifact(manifest, "price_bars.jsonl.gz")
    if sessions["sha256"] != expected["sessions_artifact_sha256"]:
        raise ValueError("Session artifact differs from frozen execution manifest")
    if prices["sha256"] != expected["price_artifact_sha256"]:
        raise ValueError("Price artifact differs from frozen execution manifest")


def _load_cases(
    path: Path,
    *,
    execution_manifest: Mapping[str, Any],
    expected_count: int,
) -> list[BaselineCase]:
    cases: list[BaselineCase] = []
    identifiers: set[str] = set()
    session_counts: Counter[str] = Counter()
    for record in _records(path):
        _verify_source_record(record)
        if record["record_type"] != "SESSION_CASE":
            raise ValueError(f"Unexpected session artifact record: {record['record_id']}")
        if record["research_policy"] != {
            "direction_label_assigned": False,
            "execution_optimized": False,
            "mae_calculated": False,
            "mfe_calculated": False,
            "return_calculated": False,
        }:
            raise ValueError(
                f"Session already contains an outcome: {record['record_id']}"
            )
        if record["data_quality"]["status"] != "COMPLETE":
            raise ValueError(
                f"Immutable casebook admitted an incomplete case: {record['record_id']}"
            )
        case_id = str(record["record_id"])
        if case_id in identifiers:
            raise ValueError(f"Duplicate session case ID: {case_id}")
        identifiers.add(case_id)
        session_code = str(record["session_code"])
        if session_code not in SESSION_CODES:
            raise ValueError(f"Unexpected session code: {session_code}")
        session_date = date.fromisoformat(record["session_date"])
        decision_at = _timestamp(record["decision_at"])
        observation_end = _timestamp(record["observation_end"])
        if decision_at >= HOLDOUT_START or observation_end > HOLDOUT_START:
            raise ValueError(f"Session enters the locked holdout: {case_id}")
        if _timestamp(record["availability_at"]) > decision_at:
            raise ValueError(f"Decision record was unavailable at decision: {case_id}")
        _verify_session_clocks(
            session_code=session_code,
            session_date=session_date,
            decision_at=decision_at,
            observation_end=observation_end,
            execution_manifest=execution_manifest,
        )
        cases.append(
            BaselineCase(
                case_id=case_id,
                case_record_hash=str(record["record_hash"]),
                session_code=session_code,
                session_date=session_date,
                decision_at=decision_at,
                observation_end=observation_end,
            )
        )
        session_counts[session_code] += 1
    if len(cases) != expected_count:
        raise ValueError(f"Session record count mismatch: {len(cases)} != {expected_count}")
    if not all(session_counts[code] for code in SESSION_CODES):
        raise ValueError("One baseline session has no cases")
    return sorted(cases, key=lambda item: (item.decision_at, item.case_id))


def _verify_session_clocks(
    *,
    session_code: str,
    session_date: date,
    decision_at: datetime,
    observation_end: datetime,
    execution_manifest: Mapping[str, Any],
) -> None:
    definition = execution_manifest["sessions"][session_code]
    zone = ZoneInfo(definition["timezone"])
    local_decision = decision_at.astimezone(zone)
    local_end = observation_end.astimezone(zone)
    if local_decision.date() != session_date or local_end.date() != session_date:
        raise ValueError(f"{session_code} session date does not match local clock")
    if local_decision.strftime("%H:%M") != definition["decision_clock_local"]:
        raise ValueError(f"{session_code} decision clock mismatch")
    if local_end.strftime("%H:%M") != definition["fixed_exit_clock_local"]:
        raise ValueError(f"{session_code} exit clock mismatch")
    if (
        local_decision + timedelta(minutes=1)
    ).strftime("%H:%M") != definition["entry_clock_local"]:
        raise ValueError(f"{session_code} entry clock mismatch")


def _load_price_bars(
    path: Path,
    *,
    required_times: set[datetime],
) -> dict[datetime, BaselinePriceBar]:
    bars: dict[datetime, BaselinePriceBar] = {}
    saw_one_minute = False
    for record in _records(path):
        timeframe = record["timeframe"]
        if timeframe != "1m":
            if saw_one_minute:
                break
            continue
        saw_one_minute = True
        open_time = _timestamp(record["open_time"])
        if open_time not in required_times:
            continue
        _verify_source_record(record)
        if open_time in bars:
            raise ValueError(f"Duplicate required one-minute bar: {open_time.isoformat()}")
        if record["record_type"] != "PRICE_BAR":
            raise ValueError(f"Required source is not a price bar: {record['record_id']}")
        if record["instrument_code"] != "XAUUSD":
            raise ValueError(f"Required source is not XAUUSD: {record['record_id']}")
        if record["provider_code"] != "IC_MARKETS_MT5":
            raise ValueError(f"Required source provider changed: {record['record_id']}")
        if record["complete"] is not True:
            continue
        close_time = _timestamp(record["close_time"])
        available_at = _timestamp(record["available_at"])
        if open_time >= HOLDOUT_START or close_time > HOLDOUT_START:
            raise ValueError(f"Required price bar enters holdout: {record['record_id']}")
        if close_time != open_time + timedelta(minutes=1):
            raise ValueError(f"Required price bar is not one minute: {record['record_id']}")
        ohlc = record["ohlc"]
        bars[open_time] = BaselinePriceBar(
            record_id=str(record["record_id"]),
            record_hash=str(record["record_hash"]),
            open_time=open_time,
            close_time=close_time,
            open=float(ohlc["open"]),
            close=float(ohlc["close"]),
            spread_price=(
                float(record["spread_price"])
                if record["spread_price"] is not None
                else None
            ),
            available_at=available_at,
        )
        if len(bars) == len(required_times):
            break
    return bars


def _eligible_cases(
    cases: Sequence[BaselineCase],
    *,
    bars: Mapping[datetime, BaselinePriceBar],
) -> tuple[list[EligibleCase], list[dict[str, Any]]]:
    candidates: list[EligibleCase] = []
    exclusions: list[dict[str, Any]] = []
    for case in cases:
        entry_time = case.decision_at + timedelta(minutes=1)
        exit_open_time = case.observation_end - timedelta(minutes=1)
        entry_bar = bars.get(entry_time)
        exit_bar = bars.get(exit_open_time)
        reason: str | None = None
        if entry_bar is None:
            reason = "ENTRY_BAR_MISSING"
        elif exit_bar is None:
            reason = "EXIT_BAR_MISSING"
        elif entry_bar.spread_price is None:
            reason = "ENTRY_SPREAD_UNKNOWN"
        elif exit_bar.spread_price is None:
            reason = "EXIT_SPREAD_UNKNOWN"
        if reason is not None:
            exclusions.append(_exclusion(case, reason))
            continue
        candidates.append(
            EligibleCase(
                case=case,
                entry_bar=entry_bar,
                exit_bar=exit_bar,
            )
        )

    eligible: list[EligibleCase] = []
    prior_exit: datetime | None = None
    for item in sorted(
        candidates,
        key=lambda value: (value.entry_bar.open_time, value.case.case_id),
    ):
        if prior_exit is not None and item.entry_bar.open_time < prior_exit:
            exclusions.append(_exclusion(item.case, "OVERLAP_EARLIER_POSITION"))
            continue
        eligible.append(item)
        prior_exit = item.exit_bar.close_time
    return eligible, sorted(
        exclusions,
        key=lambda item: (item["decision_at"], item["case_id"]),
    )


def _execution_config(
    manifest: Mapping[str, Any],
) -> BaselineExecutionConfig:
    return BaselineExecutionConfig(
        execution_manifest_hash=str(manifest["manifest_hash"]),
        quantity_ounces=float(manifest["notional"]["quantity_ounces"]),
        contract_size_ounces_per_lot=float(
            manifest["notional"]["contract_size_ounces_per_lot"]
        ),
        commission_usd_per_lot_round_turn=float(
            manifest["costs"]["commission_usd_per_lot_round_turn"]
        ),
        slippage_price_per_side=float(
            manifest["costs"]["slippage_price_usd_per_ounce_per_side"]
        ),
        cost_multiplier=float(manifest["costs"]["cost_multiplier"]),
        entry_latency_minutes=int(manifest["fill_rule"]["entry_latency_minutes"]),
        random_namespace=str(
            manifest["controls"]["DETERMINISTIC_RANDOM"]["namespace"]
        ),
    )


def _run_controls(
    eligible: Sequence[EligibleCase],
    *,
    config: BaselineExecutionConfig,
) -> list[BaselineTrade]:
    trades: list[BaselineTrade] = []
    for session_code in SESSION_CODES:
        session_cases = sorted(
            (
                item
                for item in eligible
                if item.case.session_code == session_code
            ),
            key=lambda item: (item.entry_bar.open_time, item.case.case_id),
        )
        for control_code in CONTROL_CODES:
            trades.extend(
                simulate_baseline_case(
                    item.case,
                    control_code=control_code,
                    entry_bar=item.entry_bar,
                    exit_bar=item.exit_bar,
                    config=config,
                )
                for item in session_cases
            )
    return trades


def _write_trades(path: Path, trades: Sequence[BaselineTrade]) -> int:
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
        ) as text,
    ):
        for trade in trades:
            record = finalize_record(
                {
                    "record_type": "BASELINE_TRADE",
                    "record_id": (
                        f"BASELINE-{trade.control_code}-{trade.case_id}"
                    ),
                    "baseline_version": BASELINE_VERSION,
                    "schema_version": BASELINE_SCHEMA_VERSION,
                    "epistemic_status": "CALCULATED",
                    "holdout_loaded": False,
                    "calculation_version": BASELINE_VERSION,
                    **trade_to_dict(trade),
                }
            )
            text.write(
                json.dumps(
                    json_ready(record),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            count += 1
    return count


def _build_results(
    *,
    cases: Sequence[BaselineCase],
    eligible: Sequence[EligibleCase],
    exclusions: Sequence[Mapping[str, Any]],
    trades: Sequence[BaselineTrade],
    execution_manifest: Mapping[str, Any],
    execution_hash: str,
    casebook_manifest: Mapping[str, Any],
    casebook_hash: str,
    trades_sha: str,
    trade_count: int,
) -> dict[str, Any]:
    input_counts = Counter(case.session_code for case in cases)
    eligible_counts = Counter(item.case.session_code for item in eligible)
    exclusion_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for exclusion in exclusions:
        exclusion_counts[str(exclusion["session_code"])][
            str(exclusion["reason"])
        ] += 1

    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for session_code in SESSION_CODES:
        grouped[session_code] = {}
        for control_code in CONTROL_CODES:
            selected = [
                trade
                for trade in trades
                if trade.session_code == session_code
                and trade.control_code == control_code
            ]
            grouped[session_code][control_code] = calculate_baseline_metrics(
                selected
            )

    return {
        "baseline_version": BASELINE_VERSION,
        "schema_version": BASELINE_SCHEMA_VERSION,
        "governing_contract": "GOLD_CASEBOOK_RESEARCH_CONTRACT.md",
        "milestone": "3_CONSTANT_EXECUTION_BASELINE",
        "source": {
            "casebook_version": casebook_manifest["casebook_version"],
            "casebook_manifest_path": execution_manifest["casebook"][
                "manifest_path"
            ],
            "casebook_manifest_hash": casebook_hash,
            "execution_manifest_path": (
                "research_manifests/"
                "gold_casebook_constant_execution_v01.json"
            ),
            "execution_manifest_hash": execution_hash,
            "sessions_artifact_sha256": execution_manifest["casebook"][
                "sessions_artifact_sha256"
            ],
            "price_artifact_sha256": execution_manifest["casebook"][
                "price_artifact_sha256"
            ],
        },
        "research_interval": {
            **execution_manifest["research_interval"],
            "holdout_loaded": False,
        },
        "execution_definition": {
            "decision_and_exit_clocks": execution_manifest["sessions"],
            "fill_rule": execution_manifest["fill_rule"],
            "notional": execution_manifest["notional"],
            "costs": execution_manifest["costs"],
            "incomplete_session_policy": execution_manifest[
                "incomplete_session_policy"
            ],
            "position_policy": execution_manifest["position_policy"],
        },
        "eligibility": {
            "input_cases": {
                code: input_counts[code] for code in SESSION_CODES
            },
            "eligible_cases": {
                code: eligible_counts[code] for code in SESSION_CODES
            },
            "excluded_cases": len(exclusions),
            "exclusions_by_session_and_reason": {
                code: dict(sorted(exclusion_counts[code].items()))
                for code in SESSION_CODES
            },
            "exclusions": list(exclusions),
        },
        "controls": grouped,
        "ledger": {
            "path": "trades.jsonl.gz",
            "sha256": trades_sha,
            "record_count": trade_count,
        },
        "research_guardrails": {
            "fixed_execution_applied_to_all_controls": True,
            "stops_or_targets_used": False,
            "entry_or_exit_optimized": False,
            "fundamental_or_structure_filtering_used": False,
            "relationship_discovery_performed": False,
            "calendar_2025_loaded": False,
            "account_scaling_or_leverage_assumed": False,
        },
    }


def _verify_source_record(record: Mapping[str, Any]) -> None:
    if record["casebook_version"] != CASEBOOK_VERSION:
        raise ValueError(f"Casebook version mismatch: {record['record_id']}")
    if record["holdout_loaded"] is not False:
        raise ValueError(f"Source record loads holdout: {record['record_id']}")
    supplied = record["record_hash"]
    unhashed = {key: value for key, value in record.items() if key != "record_hash"}
    if canonical_hash(unhashed) != supplied:
        raise ValueError(f"Source record hash mismatch: {record['record_id']}")


def _exclusion(case: BaselineCase, reason: str) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "session_code": case.session_code,
        "session_date": case.session_date.isoformat(),
        "decision_at": case.decision_at.isoformat(),
        "reason": reason,
    }


def _artifact(
    manifest: Mapping[str, Any],
    path: str,
) -> Mapping[str, Any]:
    matches = [item for item in manifest["artifacts"] if item["path"] == path]
    if len(matches) != 1:
        raise ValueError(f"Manifest does not contain exactly one {path} artifact")
    return matches[0]


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_ready(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _verify_hashed_document(
    value: Mapping[str, Any],
    *,
    hash_field: str,
    label: str,
) -> str:
    supplied = str(value[hash_field])
    unhashed = {key: item for key, item in value.items() if key != hash_field}
    calculated = canonical_hash(unhashed)
    if not _valid_sha256(supplied) or supplied != calculated:
        raise ValueError(f"{label} hash mismatch")
    return supplied


def _verify_file_hash(path: Path, expected: str) -> None:
    actual = _sha256(path)
    if actual != expected:
        raise ValueError(f"Artifact SHA-256 mismatch: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _records(path: Path) -> Iterable[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            yield json.loads(line)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Naive timestamp: {value}")
    return parsed.astimezone(UTC)


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _progress(stage: str, **values: Any) -> None:
    payload = {"stage": stage, **values}
    print(json.dumps(json_ready(payload), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
