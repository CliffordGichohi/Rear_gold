#!/usr/bin/env python3
"""Freeze and run the Autonomous Coherent-Auction Detector V1 audit."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import random
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import certify_gold_auction_plan_compiler_v1 as seal_tools  # noqa: E402
import materialize_gold_annotated_replay_v3 as replay  # noqa: E402
import materialize_gold_coherent_auction_blind_validation_v1 as materializer  # noqa: E402
from gold_intel.analytics.autonomous_auction_detector_v1 import (  # noqa: E402
    detect_autonomous_auction_signal_v1,
)
from gold_intel.analytics.autonomous_auction_execution_v1 import (  # noqa: E402
    MAXIMUM_RISK_USD,
    simulate_autonomous_auction_trade_v1,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
)


CONTRACT = ROOT / "GOLD_AUTONOMOUS_COHERENT_AUCTION_DETECTOR_AND_EDGE_AUDIT_V1.md"
DETECTOR = ROOT / "backend/src/gold_intel/analytics/autonomous_auction_detector_v1.py"
EXECUTION = ROOT / "backend/src/gold_intel/analytics/autonomous_auction_execution_v1.py"
DETECTOR_TESTS = ROOT / "backend/tests/unit/test_autonomous_auction_detector_v1.py"
EXECUTION_TESTS = ROOT / "backend/tests/unit/test_autonomous_auction_execution_v1.py"
SEMANTIC_FINAL_SEAL = (
    ROOT
    / "research_artifacts/gold_auction_plan_compiler_v1_semantic_amendment_a/final_seal.json"
)
SOURCE_REGISTRY = (
    ROOT
    / "research_artifacts/gold_blind_discretionary_replay_v1/population_registry_v1_1.private.json"
)
MATCHED_REGISTRY = ROOT / "research_artifacts/gold_matched_human_replay_v1/population_registry.private.json"
EXPOSED_GAV_REGISTRY = (
    ROOT / "research_artifacts/gold_coherent_auction_blind_validation_v1/population_registry.private.json"
)
CASEBOOK = ROOT / "research_artifacts/gold_casebook_v01"
PRICE = CASEBOOK / "price_bars.jsonl.gz"
CASEBOOK_MANIFEST = CASEBOOK / "manifest.json"

OUT = ROOT / "research_artifacts/gold_autonomous_coherent_auction_edge_audit_v1"
POPULATION = OUT / "population_registry.json"
COVERAGE = OUT / "metadata_coverage_audit.json"
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY_STREAMS = OUT / "streams.primary.jsonl.gz"
REFERENCE_STREAMS = OUT / "streams.reference.jsonl.gz"
STREAM_CERTIFICATION = OUT / "stream_certification.json"
PRIMARY_RESULT = OUT / "detector_result.primary.json"
REFERENCE_RESULT = OUT / "detector_result.reference.json"
RESULT = OUT / "final_result.json"
FINAL_SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_AUTONOMOUS_COHERENT_AUCTION_DETECTOR_AND_EDGE_AUDIT_V1_REPORT.md"

SESSIONS = ("LONDON", "NEW_YORK")
SESSION_TARGET = 25
MINIMUM_COVERAGE = 0.95
BOOTSTRAP_SEED = 20260821
BOOTSTRAP_DRAWS = 10_000


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"Required file is absent: {path}")
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": seal_tools.sha256_file(path),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise RuntimeError(f"Append-only artifact exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_text(path: Path, payload: str) -> None:
    if path.exists():
        raise RuntimeError(f"Append-only artifact exists: {path}")
    path.write_text(payload.rstrip() + "\n", encoding="utf-8", newline="\n")


def seal(payload: dict[str, Any], key: str) -> dict[str, Any]:
    payload[key] = canonical_hash(payload)
    return payload


def validate_seal(path: Path, key: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    submitted = payload.pop(key)
    if canonical_hash(payload) != submitted:
        raise RuntimeError(f"Seal differs: {path}")
    payload[key] = submitted
    return payload


def verify_semantic_predecessor() -> dict[str, Any]:
    payload = validate_seal(SEMANTIC_FINAL_SEAL, "seal_sha256")
    if payload["status"] != "PASS_SEMANTIC_AMENDMENT_A_CERTIFICATION":
        raise RuntimeError("Semantic Amendment A is not PASS")
    for item in payload["files"].values():
        path = ROOT / item["path"]
        if path.stat().st_size != item["bytes"] or seal_tools.sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"Semantic predecessor artifact differs: {path}")
    return payload


def verify_casebook() -> list[dict[str, Any]]:
    manifest = json.loads(CASEBOOK_MANIFEST.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for expected in manifest["artifacts"]:
        path = CASEBOOK / expected["path"]
        record = file_record(path)
        if record["bytes"] != expected["bytes"] or record["sha256"] != expected["sha256"]:
            raise RuntimeError(f"Casebook artifact differs: {path}")
        records.append(record)
    return records


def timestamp_metadata() -> tuple[set[datetime], int, str]:
    timestamps: set[datetime] = set()
    duplicates = 0
    start = datetime(2022, 1, 1, tzinfo=UTC)
    end = datetime(2025, 1, 1, tzinfo=UTC)
    with gzip.open(PRICE, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if (
                row.get("instrument_code") != "XAUUSD"
                or row.get("timeframe") != "1m"
                or row.get("complete") is not True
            ):
                continue
            close = parse_time(str(row["close_time"]))
            if not start <= close < end or parse_time(str(row["available_at"])) > close:
                continue
            if close in timestamps:
                duplicates += 1
            timestamps.add(close)
    identity = canonical_hash(
        [value.isoformat().replace("+00:00", "Z") for value in sorted(timestamps)]
    )
    return timestamps, duplicates, identity


def expected_closes(start: datetime, end: datetime) -> list[datetime]:
    count = int((end - start).total_seconds() // 60)
    return [start + timedelta(minutes=index) for index in range(1, count + 1)]


def build_population() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    source_records = verify_casebook()
    source = json.loads(SOURCE_REGISTRY.read_text(encoding="utf-8"))
    matched = json.loads(MATCHED_REGISTRY.read_text(encoding="utf-8"))
    gav = json.loads(EXPOSED_GAV_REGISTRY.read_text(encoding="utf-8"))
    if canonical_hash(source["cases"]) != source["population_sha256"]:
        raise RuntimeError("Source population seal differs")
    if canonical_hash(gav["cases"]) != gav["population_sha256"]:
        raise RuntimeError("Exposed GAV population seal differs")
    excluded_dates = {
        str(row["trading_date_utc"]) for row in matched["cases"]
    } | {str(row["trading_date_utc"]) for row in gav["cases"]}
    excluded_sources = {str(row["source_case_alias"]) for row in gav["cases"]}
    timestamps, duplicate_count, timestamp_sha256 = timestamp_metadata()
    candidates: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for row in source["cases"]:
        session_date = str(row.get("session_date", ""))
        if row.get("mode") != "SCORED" or not ("2022-01-01" <= session_date <= "2024-12-31"):
            continue
        start = parse_time(str(row["decision_at"]))
        end = parse_time(str(row["session_end"]))
        expected = expected_closes(start, end)
        observed = [value for value in expected if value in timestamps]
        coverage = len(observed) / len(expected) if expected else 0.0
        eligible = (
            row["session_code"] in SESSIONS
            and session_date not in excluded_dates
            and row["case_alias"] not in excluded_sources
            and coverage >= MINIMUM_COVERAGE
        )
        metadata = {
            "source_case_alias": row["case_alias"],
            "source_mode_sequence": int(row["mode_sequence"]),
            "session_code": row["session_code"],
            "session_date": session_date,
            "start_inclusive": start.isoformat().replace("+00:00", "Z"),
            "end_inclusive": end.isoformat().replace("+00:00", "Z"),
            "expected_m1_closes": len(expected),
            "observed_m1_closes": len(observed),
            "coverage_fraction": round(coverage, 8),
            "observed_identity_sha256": canonical_hash(
                [value.isoformat().replace("+00:00", "Z") for value in observed]
            ),
            "excluded_prior_date": session_date in excluded_dates,
            "excluded_prior_source": row["case_alias"] in excluded_sources,
            "eligible": eligible,
        }
        audit_rows.append(metadata)
        if eligible:
            candidates.append({**row, **metadata})

    selected: list[dict[str, Any]] = []
    for session in SESSIONS:
        eligible = sorted(
            (row for row in candidates if row["session_code"] == session),
            key=lambda row: int(row["source_mode_sequence"]),
        )
        if len(eligible) < SESSION_TARGET:
            raise RuntimeError(f"Insufficient eligible {session} cases: {len(eligible)}")
        selected.extend(eligible[:SESSION_TARGET])
    selected.sort(key=lambda row: int(row["source_mode_sequence"]))
    cases: list[dict[str, Any]] = []
    for index, row in enumerate(selected, start=1):
        cases.append(
            {
                "case_alias": f"GAD-V1-{index:03d}",
                "mode": "AUTONOMOUS_HISTORICAL_ROBUSTNESS",
                "mode_sequence": index,
                "source_case_alias": row["source_case_alias"],
                "source_mode_sequence": row["source_mode_sequence"],
                "source_session_record_id": row["session_record_id"],
                "source_session_record_hash": row["session_record_hash"],
                "session_code": row["session_code"],
                "trading_date_utc": row["session_date"],
                "start_inclusive": row["start_inclusive"],
                "end_inclusive": row["end_inclusive"],
                "expected_m1_closes": row["expected_m1_closes"],
                "observed_m1_closes": row["observed_m1_closes"],
                "coverage_fraction": row["coverage_fraction"],
                "observed_identity_sha256": row["observed_identity_sha256"],
                "research_credit": "HISTORICAL_RULE_ROBUSTNESS_ONLY",
            }
        )
    counts = Counter(row["session_code"] for row in cases)
    if counts != Counter({"LONDON": 25, "NEW_YORK": 25}):
        raise RuntimeError(f"Session balance differs: {counts}")
    population = seal(
        {
            "version": "GOLD_AUTONOMOUS_COHERENT_AUCTION_POPULATION_V1_0",
            "created_at": now(),
            "selection_semantics": "FIRST_25_REMAINING_PER_SESSION_IN_SEALED_V1_1_MODE_SEQUENCE",
            "case_count": 50,
            "cases": cases,
            "calendar_2025": "LOCKED",
            "calendar_2026": "LOCKED",
        },
        "population_sha256",
    )
    coverage_payload = seal(
        {
            "version": "GOLD_AUTONOMOUS_COHERENT_AUCTION_COVERAGE_V1_0",
            "performed_at": now(),
            "verdict": "PASS_METADATA_ONLY_POPULATION_SELECTION",
            "market_values_reported": False,
            "outcomes_accessed": False,
            "timestamp_universe_sha256": timestamp_sha256,
            "duplicate_price_timestamps": duplicate_count,
            "excluded_date_count": len(excluded_dates),
            "excluded_source_count": len(excluded_sources),
            "eligible_counts": dict(Counter(row["session_code"] for row in candidates)),
            "selected_counts": dict(counts),
            "selected_date_min": min(row["trading_date_utc"] for row in cases),
            "selected_date_max": max(row["trading_date_utc"] for row in cases),
            "minimum_selected_coverage": min(row["coverage_fraction"] for row in cases),
            "candidate_metadata": audit_rows,
            "gates": {
                "exact_50": len(cases) == 50,
                "exact_25_per_session": counts == Counter({"LONDON": 25, "NEW_YORK": 25}),
                "all_coverage_gte_95pct": all(row["coverage_fraction"] >= 0.95 for row in cases),
                "all_prior_dates_and_sources_excluded": all(
                    row["trading_date_utc"] not in excluded_dates
                    and row["source_case_alias"] not in excluded_sources
                    for row in cases
                ),
                "calendar_2025_2026_locked": True,
                "no_acquisition_or_charge": True,
            },
        },
        "coverage_sha256",
    )
    return population, coverage_payload, source_records


def prepare() -> None:
    if OUT.exists() or REPORT.exists():
        raise RuntimeError("Autonomous audit output already exists")
    semantic = verify_semantic_predecessor()
    population, coverage, source_records = build_population()
    if not all(coverage["gates"].values()):
        raise RuntimeError(f"Coverage gate failed: {coverage['gates']}")
    write_json(POPULATION, population)
    write_json(COVERAGE, coverage)
    inputs = {
        "contract": file_record(CONTRACT),
        "detector": file_record(DETECTOR),
        "execution": file_record(EXECUTION),
        "detector_tests": file_record(DETECTOR_TESTS),
        "execution_tests": file_record(EXECUTION_TESTS),
        "runner": file_record(Path(__file__).resolve()),
        "semantic_final_seal": file_record(SEMANTIC_FINAL_SEAL),
        "source_registry": file_record(SOURCE_REGISTRY),
        "matched_registry": file_record(MATCHED_REGISTRY),
        "exposed_gav_registry": file_record(EXPOSED_GAV_REGISTRY),
        "casebook_manifest": file_record(CASEBOOK_MANIFEST),
        "population": file_record(POPULATION),
        "coverage": file_record(COVERAGE),
    }
    freeze_payload = seal(
        {
            "version": "GOLD_AUTONOMOUS_COHERENT_AUCTION_PREVALUE_FREEZE_V1_0",
            "status": "SEALED_BEFORE_ROBUSTNESS_VALUES_AND_OUTCOMES",
            "frozen_at": now(),
            "semantic_predecessor_sha256": semantic["seal_sha256"],
            "population_sha256": population["population_sha256"],
            "case_count": 50,
            "pass_gates": {
                "minimum_trades": 20,
                "expectancy_gt": 0.0,
                "profit_factor_gte": 1.10,
                "bootstrap_lower_gt": 0.0,
                "stressed_net_gt": 0.0,
                "both_halves_positive": True,
                "maximum_session_positive_gross_share": 0.80,
                "maximum_drawdown_r": 30.0,
            },
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_draws": BOOTSTRAP_DRAWS,
            "inputs": inputs,
            "casebook_sources": source_records,
            "outcomes_opened": False,
            "calendar_2025_opened": False,
            "calendar_2026_opened": False,
            "charge_usd": 0.0,
        },
        "freeze_sha256",
    )
    write_json(FREEZE, freeze_payload)
    print(
        json.dumps(
            {
                "verdict": coverage["verdict"],
                "cases": 50,
                "sessions": coverage["selected_counts"],
                "date_min": coverage["selected_date_min"],
                "date_max": coverage["selected_date_max"],
                "freeze_sha256": freeze_payload["freeze_sha256"],
            },
            indent=2,
        )
    )


def verify_freeze() -> tuple[dict[str, Any], dict[str, Any]]:
    frozen = validate_seal(FREEZE, "freeze_sha256")
    if frozen["status"] != "SEALED_BEFORE_ROBUSTNESS_VALUES_AND_OUTCOMES":
        raise RuntimeError("Prevalue freeze status differs")
    verify_semantic_predecessor()
    for item in [*frozen["inputs"].values(), *frozen["casebook_sources"]]:
        path = ROOT / item["path"]
        if path.stat().st_size != item["bytes"] or seal_tools.sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"Frozen input differs: {path}")
    population = validate_seal(POPULATION, "population_sha256")
    if population["case_count"] != 50:
        raise RuntimeError("Population count differs")
    return frozen, population


def normalize_streams(rows: list[dict[str, Any]], population_sha256: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        row["version"] = "GOLD_AUTONOMOUS_COHERENT_AUCTION_STREAM_V1_0"
        row["mode"] = "AUTONOMOUS_HISTORICAL_ROBUSTNESS"
        row["research_credit"] = "HISTORICAL_RULE_ROBUSTNESS_ONLY"
        row["source_lineage"] = {
            **row["source_lineage"],
            "detector_population_sha256": population_sha256,
        }
        row["stream_sha256"] = None
        row["stream_sha256"] = canonical_hash(
            {key: value for key, value in row.items() if key != "stream_sha256"}
        )
        output.append(row)
    return output


def process_streams(
    streams: Sequence[dict[str, Any]], *, implementation: str
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for stream in streams:
        signal = detect_autonomous_auction_signal_v1(
            stream,
            implementation=implementation,  # type: ignore[arg-type]
            verify_prefix=True,
        )
        base = simulate_autonomous_auction_trade_v1(stream=stream, signal=signal)
        stress = simulate_autonomous_auction_trade_v1(
            stream=stream,
            signal=signal,
            cost_multiplier=1.5,
            quantity_override=(
                int(base["quantity_ounces"])
                if base["disposition"] == "EXECUTED"
                else None
            ),
        )
        plan = signal.get("plan")
        row = {
            "case_alias": stream["case_alias"],
            "trading_date_utc": stream["trading_date_utc"],
            "session_code": stream["session_code"],
            "source_stream_sha256": stream["stream_sha256"],
            "signal_disposition": signal["disposition"],
            "signal_at": signal["signal_at"],
            "direction": signal["direction"],
            "family": (
                plan["components"]["governing_auction"]["family"] if plan else None
            ),
            "signal_sha256": signal["signal_sha256"],
            "prefix_reproduction_exact": signal["prefix_reproduction_exact"],
            "candidate_checkpoint_count": signal["candidate_checkpoint_count"],
            "evaluated_checkpoint_count": signal["evaluated_checkpoint_count"],
            "ambiguous_checkpoint_count": signal["ambiguous_checkpoint_count"],
            "base_execution": base,
            "stressed_execution": stress,
            "row_sha256": None,
        }
        row["row_sha256"] = canonical_hash(
            {key: value for key, value in row.items() if key != "row_sha256"}
        )
        rows.append(row)
    payload = {
        "version": "GOLD_AUTONOMOUS_COHERENT_AUCTION_DETECTOR_RESULT_V1_0",
        "implementation": implementation,
        "rows": rows,
    }
    payload["payload_sha256"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "payload_sha256"}
    )
    return payload


def comparable(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in row.items() if key != "row_sha256"}
        for row in payload["rows"]
    ]


def maximum_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def bootstrap_interval(values: Sequence[float]) -> list[float] | None:
    if len(values) < 2:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    means = sorted(
        sum(values[rng.randrange(len(values))] for _ in values) / len(values)
        for _ in range(BOOTSTRAP_DRAWS)
    )
    return [means[int(0.025 * BOOTSTRAP_DRAWS)], means[int(0.975 * BOOTSTRAP_DRAWS)]]


def month_span(rows: Sequence[Mapping[str, Any]]) -> int:
    dates = [datetime.fromisoformat(str(row["trading_date_utc"])) for row in rows]
    first = min(dates)
    last = max(dates)
    return (last.year - first.year) * 12 + last.month - first.month + 1


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda row: (row["trading_date_utc"], row["session_code"], row["case_alias"]),
    )
    signals = [row for row in ordered if row["signal_disposition"] == "SIGNAL"]
    trades = [row for row in ordered if row["base_execution"]["disposition"] == "EXECUTED"]
    values = [float(row["base_execution"]["net_r50"]) for row in trades]
    stress_values = [float(row["stressed_execution"]["net_r50"]) for row in trades]
    positives = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    profit_factor = positives / losses if losses > 0 else None
    split = len(ordered) // 2
    halves = [
        sum(
            float(row["base_execution"]["net_r50"])
            for row in segment
            if row["base_execution"]["disposition"] == "EXECUTED"
        )
        for segment in (ordered[:split], ordered[split:])
    ]
    session_rows: dict[str, dict[str, Any]] = {}
    positive_by_session: dict[str, float] = {}
    for session in SESSIONS:
        members = [row for row in trades if row["session_code"] == session]
        session_values = [float(row["base_execution"]["net_r50"]) for row in members]
        positive = sum(value for value in session_values if value > 0)
        positive_by_session[session] = positive
        session_rows[session] = {
            "signals": sum(row["session_code"] == session for row in signals),
            "trades": len(members),
            "net_r50": sum(session_values),
            "expectancy_r50": sum(session_values) / len(session_values) if session_values else None,
        }
    total_positive = sum(positive_by_session.values())
    maximum_share = (
        max(positive_by_session.values()) / total_positive if total_positive > 0 else None
    )
    months = month_span(ordered)
    interval = bootstrap_interval(values)
    return {
        "cases": len(ordered),
        "signals": len(signals),
        "no_signals": len(ordered) - len(signals),
        "ambiguous_checkpoints": sum(int(row["ambiguous_checkpoint_count"]) for row in ordered),
        "risk_rejections": sum(
            row["base_execution"]["disposition"] == "REJECT_RISK_GEOMETRY"
            for row in ordered
        ),
        "execution_geometry_rejections": sum(
            row["base_execution"]["disposition"] == "REJECT_INVALID_EXECUTION_GEOMETRY"
            for row in ordered
        ),
        "trades": len(trades),
        "wins": sum(value > 0 for value in values),
        "losses": sum(value < 0 for value in values),
        "time_exits": sum(row["base_execution"].get("exit_reason") == "SESSION_TIME_EXIT" for row in trades),
        "win_rate": sum(value > 0 for value in values) / len(values) if values else None,
        "net_r50": sum(values),
        "net_usd": sum(float(row["base_execution"]["net_usd"]) for row in trades),
        "expectancy_r50": sum(values) / len(values) if values else None,
        "profit_factor": profit_factor,
        "maximum_drawdown_r50": maximum_drawdown(values),
        "bootstrap_95_expectancy_r50": interval,
        "stressed_net_r50": sum(stress_values),
        "chronological_half_net_r50": halves,
        "direction_counts": dict(sorted(Counter(row["direction"] for row in signals).items())),
        "family_counts": dict(sorted(Counter(row["family"] for row in signals).items())),
        "session": session_rows,
        "maximum_session_positive_gross_share": maximum_share,
        "calendar_month_span": months,
        "signals_per_month": len(signals) / months,
        "trades_per_month": len(trades) / months,
    }


def report_markdown(result: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> str:
    value = result["metrics"]
    interval = value["bootstrap_95_expectancy_r50"]
    lines = [
        "# Gold Autonomous Coherent-Auction Detector and Edge Audit V1 — Result",
        "",
        f"Formal verdict: **{result['verdict']}**",
        "",
        "This was a one-shot historical robustness audit of a frozen bidirectional rule. It is not pristine independent validation and does not authorize live trading.",
        "",
        "## Result",
        "",
        f"- Cases: **{value['cases']}**",
        f"- Signals / executed trades: **{value['signals']} / {value['trades']}**",
        f"- LONG / SHORT signals: **{value['direction_counts'].get('LONG', 0)} / {value['direction_counts'].get('SHORT', 0)}**",
        f"- Wins / losses: **{value['wins']} / {value['losses']}**",
        f"- Win rate: **{100 * (value['win_rate'] or 0):.2f}%**",
        f"- Net: **{value['net_r50']:+.4f}R / ${value['net_usd']:+.2f}**",
        f"- Expectancy: **{(value['expectancy_r50'] or 0):+.4f}R/trade**",
        f"- Profit factor: **{value['profit_factor'] if value['profit_factor'] is not None else 'N/A (no losses)'}**",
        f"- Maximum drawdown: **{value['maximum_drawdown_r50']:.4f}R**",
        f"- 95% bootstrap expectancy interval: **{interval if interval is not None else 'insufficient'}**",
        f"- 1.5×-cost net: **{value['stressed_net_r50']:+.4f}R**",
        f"- Chronological halves: **{value['chronological_half_net_r50']}**",
        f"- Trades per calendar month: **{value['trades_per_month']:.2f}**",
        "",
        "## Gates",
        "",
    ]
    lines.extend(
        f"- `{name}`: **{'PASS' if passed else 'FAIL'}**"
        for name, passed in result["gates"].items()
    )
    lines.extend(
        [
            "",
            "## Every case",
            "",
            "| Case | Date | Session | Signal | Direction | Family | Execution | Net R |",
            "|---|---|---|---|---|---|---|---:|",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['case_alias']} | {row['trading_date_utc']} | {row['session_code']} | "
            f"{row['signal_at'] or 'NONE'} | {row['direction'] or 'NONE'} | {row['family'] or 'NONE'} | "
            f"{row['base_execution']['disposition']} | {float(row['base_execution']['net_r50']):+.4f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "No threshold or rule was changed after the prevalue freeze. Calendar 2025 and 2026 were not opened. A PASS authorizes prospective paper tracking only; a rejection is a rejection of this exact autonomous selector and execution, not proof that gold is random.",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen, population = verify_freeze()
    targets = (
        PRIMARY_STREAMS,
        REFERENCE_STREAMS,
        STREAM_CERTIFICATION,
        PRIMARY_RESULT,
        REFERENCE_RESULT,
        RESULT,
        FINAL_SEAL,
        REPORT,
    )
    if any(path.exists() for path in targets):
        raise RuntimeError("Run artifact already exists")

    primary = normalize_streams(
        materializer.build_streams(population, materializer.load_prices_primary),
        population["population_sha256"],
    )
    reference = normalize_streams(
        materializer.build_streams(population, materializer.load_prices_reference),
        population["population_sha256"],
    )
    streams_exact = primary == reference
    if not streams_exact:
        raise RuntimeError("Primary/reference stream values differ")
    replay.write_gzip_new(PRIMARY_STREAMS, primary)
    replay.write_gzip_new(REFERENCE_STREAMS, reference)
    stream_bytes_exact = seal_tools.sha256_file(PRIMARY_STREAMS) == seal_tools.sha256_file(REFERENCE_STREAMS)
    certification = seal(
        {
            "version": "GOLD_AUTONOMOUS_COHERENT_AUCTION_STREAM_CERTIFICATION_V1_0",
            "completed_at": now(),
            "verdict": "PASS_STREAM_CERTIFICATION" if streams_exact and stream_bytes_exact else "FAIL",
            "case_count": len(primary),
            "population_sha256": population["population_sha256"],
            "primary_sha256": seal_tools.sha256_file(PRIMARY_STREAMS),
            "reference_sha256": seal_tools.sha256_file(REFERENCE_STREAMS),
            "structures_exact": streams_exact,
            "bytes_exact": stream_bytes_exact,
            "event_outcome_fields_absent": all(
                "fixed_horizon_reactions" not in event
                and "reaction_snapshots" not in event
                for stream in primary
                for event in stream["context_timeline"]["events"]
            ),
        },
        "certification_sha256",
    )
    write_json(STREAM_CERTIFICATION, certification)
    if certification["verdict"] != "PASS_STREAM_CERTIFICATION":
        raise RuntimeError("Stream certification failed")

    primary_result = process_streams(primary, implementation="primary")
    write_json(PRIMARY_RESULT, primary_result)
    reference_result = process_streams(reference, implementation="reference")
    write_json(REFERENCE_RESULT, reference_result)
    reproduction_exact = comparable(primary_result) == comparable(reference_result)
    value = metrics(primary_result["rows"])
    minimums = frozen["pass_gates"]
    interval = value["bootstrap_95_expectancy_r50"]
    pf_pass = (
        value["profit_factor"] is None and value["net_r50"] > 0
    ) or (
        value["profit_factor"] is not None
        and value["profit_factor"] >= minimums["profit_factor_gte"]
    )
    gates = {
        "predecessor_and_freeze_integrity": True,
        "stream_primary_reference_exact": streams_exact and stream_bytes_exact,
        "detector_primary_reference_exact": reproduction_exact,
        "all_signal_prefix_proofs_exact": all(
            row["signal_disposition"] != "SIGNAL" or row["prefix_reproduction_exact"] is True
            for row in primary_result["rows"]
        ),
        "zero_execution_geometry_integrity_rejections": value["execution_geometry_rejections"] == 0,
        "minimum_20_trades": value["trades"] >= minimums["minimum_trades"],
        "positive_expectancy": value["expectancy_r50"] is not None
        and value["expectancy_r50"] > minimums["expectancy_gt"],
        "profit_factor_gte_1p10": pf_pass,
        "positive_bootstrap_lower_bound": interval is not None
        and interval[0] > minimums["bootstrap_lower_gt"],
        "positive_at_1p5x_costs": value["stressed_net_r50"] > minimums["stressed_net_gt"],
        "both_chronological_halves_positive": all(
            member > 0 for member in value["chronological_half_net_r50"]
        ),
        "session_concentration_at_or_below_80pct": value["maximum_session_positive_gross_share"] is not None
        and value["maximum_session_positive_gross_share"]
        <= minimums["maximum_session_positive_gross_share"],
        "maximum_drawdown_at_or_below_30r": value["maximum_drawdown_r50"]
        <= minimums["maximum_drawdown_r"],
        "maximum_planned_risk_respected": all(
            row["base_execution"]["disposition"] != "EXECUTED"
            or float(row["base_execution"]["planned_risk_usd"]) <= MAXIMUM_RISK_USD + 1e-9
            for row in primary_result["rows"]
        ),
        "calendar_2025_2026_unopened": True,
        "no_acquisition_or_charge": True,
    }
    integrity_names = (
        "predecessor_and_freeze_integrity",
        "stream_primary_reference_exact",
        "detector_primary_reference_exact",
        "all_signal_prefix_proofs_exact",
        "zero_execution_geometry_integrity_rejections",
    )
    integrity_pass = all(gates[name] for name in integrity_names)
    negative = (
        value["expectancy_r50"] is None
        or value["expectancy_r50"] <= 0
        or (value["profit_factor"] is not None and value["profit_factor"] < 1.0)
    )
    if not integrity_pass or negative:
        verdict = "REJECT_AUTONOMOUS_EDGE_V1"
    elif all(gates.values()):
        verdict = "PROVISIONAL_EDGE_PASS"
    else:
        verdict = "INCONCLUSIVE_AUTONOMOUS_EDGE_V1"
    final_result = {
        "version": "GOLD_AUTONOMOUS_COHERENT_AUCTION_EDGE_RESULT_V1_0",
        "verdict": verdict,
        "completed_at": now(),
        "freeze_sha256": frozen["freeze_sha256"],
        "population_sha256": population["population_sha256"],
        "stream_certification_sha256": certification["certification_sha256"],
        "primary_result_sha256": primary_result["payload_sha256"],
        "reference_result_sha256": reference_result["payload_sha256"],
        "metrics": value,
        "gates": gates,
        "historical_robustness_only": True,
        "live_trading_authorized": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "charge_usd": 0.0,
    }
    write_json(RESULT, seal(final_result, "result_sha256"))
    write_text(REPORT, report_markdown(final_result, primary_result["rows"]))
    sealed_files = (
        POPULATION,
        COVERAGE,
        FREEZE,
        PRIMARY_STREAMS,
        REFERENCE_STREAMS,
        STREAM_CERTIFICATION,
        PRIMARY_RESULT,
        REFERENCE_RESULT,
        RESULT,
        REPORT,
    )
    final = {
        "version": "GOLD_AUTONOMOUS_COHERENT_AUCTION_EDGE_FINAL_SEAL_V1_0",
        "status": verdict,
        "sealed_at": now(),
        "files": {path.name: file_record(path) for path in sealed_files},
    }
    write_json(FINAL_SEAL, seal(final, "seal_sha256"))
    print(
        json.dumps(
            {
                "verdict": verdict,
                "metrics": value,
                "failed_gates": [name for name, passed in gates.items() if not passed],
                "report": str(REPORT),
            },
            indent=2,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "run"))
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare()
    else:
        run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
