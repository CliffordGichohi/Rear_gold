#!/usr/bin/env python3
"""Run the frozen January–June exposed auction-control router regression."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_day_by_day_auction_confirmation_exposed_regression_v1 as baseline  # noqa: E402
from gold_intel.analytics.auction_control_router_v1 import (  # noqa: E402
    RULESET,
    accepted_state_sequence,
    control_state_at,
    earliest_candidate,
    prepare_control,
    seller_auction_short_plans,
    short_classification,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    complete_rows,
    iso,
    parse_dt,
)
from gold_intel.analytics.coherent_auction_human_policy_v2 import simulate_track  # noqa: E402


CONTRACT = ROOT / "GOLD_AUCTION_CONTROL_ROUTER_JAN_JUN_2022_EXPOSED_REGRESSION_V1.md"
IMPLEMENTATION = (
    ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_control_router_v1.py"
)
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_control_router_v1.py"
RUNNER = Path(__file__).resolve()

JAN_MAY_ROOT = ROOT / "research_artifacts" / "gold_long_multi_opportunity_auction_v1"
JAN_MAY_RESULT = JAN_MAY_ROOT / "final_result.json"
JAN_MAY_SEAL = JAN_MAY_ROOT / "final_seal_r2.json"
JUNE_ROOT = ROOT / "research_artifacts" / "gold_frozen_long_control_june_2022_v1"
JUNE_RESULT = JUNE_ROOT / "final_result.json"
JUNE_SEAL = JUNE_ROOT / "final_seal.json"
JUNE_PRIMARY_STREAMS = JUNE_ROOT / "june_streams.primary.jsonl.gz"
JUNE_REFERENCE_STREAMS = JUNE_ROOT / "june_streams.reference.jsonl.gz"

OUT = ROOT / "research_artifacts" / "gold_auction_control_router_jan_jun_2022_v1"
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY = OUT / "primary.json"
REFERENCE = OUT / "reference.json"
FINAL = OUT / "final_result.json"
LEDGER = OUT / "daily_ledger.csv"
SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_AUCTION_CONTROL_ROUTER_JAN_JUN_2022_EXPOSED_REGRESSION_V1_REPORT.md"

STARTING_EQUITY_USD = 10_000.0
RISK_USD = 50.0
EPSILON = 1e-10
TRACKS = (
    "ORIGINAL_LONG_CONTROL",
    "BUYER_CONTROL_VETO_LONG",
    "SELLER_AUCTION_SHORT",
    "BIDIRECTIONAL_ONE_PER_DAY",
)


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_new_json(path: Path, payload: dict[str, Any]) -> None:
    require(not path.exists(), f"Append-only output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def verify_file_record(record: dict[str, Any]) -> None:
    path = ROOT / str(record["path"])
    require(path.is_file(), f"Sealed file missing: {path}")
    require(path.stat().st_size == int(record["bytes"]), f"Sealed size differs: {path}")
    require(sha256_file(path) == str(record["sha256"]), f"Sealed hash differs: {path}")


def verify_sources() -> dict[str, Any]:
    baseline.verify_static_inputs()
    for path in (
        CONTRACT,
        IMPLEMENTATION,
        TESTS,
        RUNNER,
        JAN_MAY_RESULT,
        JAN_MAY_SEAL,
        JUNE_RESULT,
        JUNE_SEAL,
        JUNE_PRIMARY_STREAMS,
        JUNE_REFERENCE_STREAMS,
    ):
        require(path.is_file(), f"Required source missing: {path}")

    long_seal = load_json(JAN_MAY_SEAL)
    require(
        long_seal["verdict"] == "REJECT_ADDITIONS_PRESERVE_FROZEN_LONG_CONTROL",
        "January–May frozen LONG verdict differs",
    )
    verify_file_record(long_seal["final_result"])
    june_seal = load_json(JUNE_SEAL)
    require(
        june_seal["verdict"] == "FAIL_JUNE_2022_EXPOSED_ROBUSTNESS",
        "June frozen LONG verdict differs",
    )
    for record in june_seal.get("files", []):
        verify_file_record(record)
    return {
        "jan_may_result": file_record(JAN_MAY_RESULT),
        "jan_may_seal": file_record(JAN_MAY_SEAL),
        "june_result": file_record(JUNE_RESULT),
        "june_seal": file_record(JUNE_SEAL),
        "june_primary_streams": file_record(JUNE_PRIMARY_STREAMS),
        "june_reference_streams": file_record(JUNE_REFERENCE_STREAMS),
    }


def load_june_streams(path: Path) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            stream = json.loads(line)
            submitted = str(stream.pop("stream_sha256"))
            require(canonical_hash(stream) == submitted, "June stream payload differs")
            stream["stream_sha256"] = submitted
            alias = str(stream["case_alias"])
            require(alias not in output, f"Duplicate June stream: {alias}")
            output[alias] = stream
    require(len(output) == 22, "Expected 22 June streams")
    return output


def load_streams(side: str) -> dict[str, dict[str, Any]]:
    jan_may = baseline.load_all_streams(side)
    june = load_june_streams(
        JUNE_PRIMARY_STREAMS if side == "primary" else JUNE_REFERENCE_STREAMS
    )
    require(not (set(jan_may) & set(june)), "Duplicate aliases across source blocks")
    output = {**jan_may, **june}
    require(len(output) == 117, "Expected 117 January–June daily streams")
    return output


def long_control_population() -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    jan_may = load_json(JAN_MAY_RESULT)
    require(len(jan_may["rows"]) == 95, "January–May LONG population differs")
    for row in jan_may["rows"]:
        alias = str(row["case_alias"])
        track = row["tracks"]["FROZEN_LONG_CONTROL"]
        require(int(track["trade_count"]) in {0, 1}, f"Unexpected LONG count: {alias}")
        output[alias] = {
            "case_alias": alias,
            "trading_date_utc": row["trading_date_utc"],
            "signal_at": row.get("original_signal_at") if track["trade_count"] else None,
            "session": row.get("original_session") if track["trade_count"] else None,
            "result": track["trades"][0] if track["trade_count"] else None,
            "source": "JAN_MAY_FROZEN_LONG_CONTROL",
        }

    june = load_json(JUNE_RESULT)
    require(len(june["rows"]) == 22, "June LONG population differs")
    for row in june["rows"]:
        alias = str(row["case_alias"])
        result = row["corrected"].get("effective_result")
        output[alias] = {
            "case_alias": alias,
            "trading_date_utc": row["trading_date_utc"],
            "signal_at": row.get("signal_at") if result is not None else None,
            "session": row["family_router"].get("session") if result is not None else None,
            "result": result,
            "source": "JUNE_FROZEN_LONG_CONTROL",
        }
    require(len(output) == 117, "Expected 117 frozen LONG population rows")
    dates = [str(row["trading_date_utc"]) for row in output.values()]
    require(len(set(dates)) == 117, "Frozen population dates are not unique")
    return output


def first_fill_after_signal(stream: dict[str, Any], signal_at: str) -> str:
    signal = parse_dt(signal_at)
    row = next(
        (
            bar
            for bar in complete_rows(stream["timeframes"]["1m"], stream["end_exclusive"])
            if parse_dt(bar["open_at"]) > signal
        ),
        None,
    )
    require(row is not None, f"No M1 fill after frozen LONG signal: {stream['case_alias']}")
    return iso(row["open_at"])


def synthetic_proof() -> dict[str, Any]:
    state_input = [
        "BUYER_CONTROL",
        "BUYER_CONTROL",
        "CONFLICTED",
        "SELLER_CONTROL",
        "SELLER_CONTROL",
    ]
    expected = [
        "UNRESOLVED",
        "BUYER_CONTROL",
        "CONFLICTED",
        "UNRESOLVED",
        "SELLER_CONTROL",
    ]
    checks = {
        "two_close_acceptance": accepted_state_sequence(state_input) == expected,
        "short_precedes_long": earliest_candidate(
            {"direction": "LONG", "fill_at": "2022-01-03T14:01:00Z"},
            {"direction": "SHORT", "fill_at": "2022-01-03T13:01:00Z"},
        )["direction"]
        == "SHORT",
        "long_tie_break_is_deterministic": earliest_candidate(
            {"direction": "LONG", "fill_at": "2022-01-03T14:01:00Z"},
            {"direction": "SHORT", "fill_at": "2022-01-03T14:01:00Z"},
        )["direction"]
        == "LONG",
    }
    require(all(checks.values()), f"Synthetic router proof failed: {checks}")
    return {"checks": checks, "proof_sha256": canonical_hash(checks)}


def freeze() -> None:
    require(not OUT.exists(), f"Output directory already exists: {OUT}")
    lineage = verify_sources()
    controls = long_control_population()
    identities = sorted(
        [
            {
                "case_alias": row["case_alias"],
                "trading_date_utc": row["trading_date_utc"],
                "long_signal_at": row["signal_at"],
            }
            for row in controls.values()
        ],
        key=lambda row: (row["trading_date_utc"], row["case_alias"]),
    )
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_CONTROL_ROUTER_JAN_JUN_2022_V1_FREEZE_1_0",
        "sealed_at": now(),
        "status": "SEALED_BEFORE_EXPOSED_JAN_JUN_ROUTER_REGRESSION",
        "implementation_files": [
            file_record(CONTRACT),
            file_record(IMPLEMENTATION),
            file_record(TESTS),
            file_record(RUNNER),
        ],
        "source_lineage": lineage,
        "population": identities,
        "population_sha256": canonical_hash(identities),
        "tracks": list(TRACKS),
        "synthetic_proof": synthetic_proof(),
        "risk_usd": RISK_USD,
        "maximum_trades_per_day": 1,
        "all_periods_exposed_zero_validation_credit": True,
        "february_17_28_opened": False,
        "july_2022_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_new_json(FREEZE, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "days": len(identities),
                "freeze_sha256": payload["freeze_sha256"],
            },
            indent=2,
        )
    )


def verify_freeze() -> dict[str, Any]:
    require(FREEZE.is_file(), "Prevalue freeze is absent")
    payload = load_json(FREEZE)
    submitted = str(payload.pop("freeze_sha256"))
    require(canonical_hash(payload) == submitted, "Prevalue freeze payload differs")
    payload["freeze_sha256"] = submitted
    for record in payload["implementation_files"]:
        verify_file_record(record)
    current = verify_sources()
    require(current == payload["source_lineage"], "Frozen source lineage differs")
    controls = long_control_population()
    identities = sorted(
        [
            {
                "case_alias": row["case_alias"],
                "trading_date_utc": row["trading_date_utc"],
                "long_signal_at": row["signal_at"],
            }
            for row in controls.values()
        ],
        key=lambda row: (row["trading_date_utc"], row["case_alias"]),
    )
    require(identities == payload["population"], "Frozen population differs")
    return payload


def result_candidate(
    *,
    direction: str,
    session: str,
    signal_at: str,
    fill_at: str,
    result: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "direction": direction,
        "session": session,
        "signal_at": signal_at,
        "fill_at": fill_at,
        "result": result,
        "evidence": evidence,
    }


def run_day(
    stream: dict[str, Any], long_control: dict[str, Any]
) -> dict[str, Any]:
    prepared = prepare_control(stream)
    long_original: dict[str, Any] | None = None
    long_veto: dict[str, Any] | None = None
    long_state: dict[str, Any] | None = None
    if long_control["result"] is not None:
        signal_at = str(long_control["signal_at"])
        session = str(long_control["session"])
        require(session in {"LONDON", "NEW_YORK"}, "Frozen LONG session unavailable")
        fill_at = first_fill_after_signal(stream, signal_at)
        long_state = control_state_at(prepared["sessions"][session], signal_at)
        long_original = result_candidate(
            direction="LONG",
            session=session,
            signal_at=signal_at,
            fill_at=fill_at,
            result=long_control["result"],
            evidence={"auction_control": long_state, "source": long_control["source"]},
        )
        if long_state["state"] == "BUYER_CONTROL":
            long_veto = long_original

    session_audits = [
        seller_auction_short_plans(stream, prepared, "LONDON"),
        seller_auction_short_plans(stream, prepared, "NEW_YORK"),
    ]
    short_plans = [row["first_admitted"] for row in session_audits if row["first_admitted"]]
    short_plan = (
        min(short_plans, key=lambda row: (parse_dt(row["fill_at"]), row["plan_sha256"]))
        if short_plans
        else None
    )
    short_candidate: dict[str, Any] | None = None
    if short_plan is not None:
        classification = short_classification(short_plan)
        result = simulate_track(
            classification=classification,
            stream=stream,
            fill_at=short_plan["fill_at"],
            track="FAITHFUL_FIXED_GEOMETRY",
        )
        short_candidate = result_candidate(
            direction="SHORT",
            session=short_plan["session"],
            signal_at=short_plan["confirmation"]["confirmation_at"],
            fill_at=short_plan["fill_at"],
            result=result,
            evidence={"plan": short_plan, "classification": classification},
        )

    combined = earliest_candidate(long_veto, short_candidate)
    tracks = {
        "ORIGINAL_LONG_CONTROL": long_original,
        "BUYER_CONTROL_VETO_LONG": long_veto,
        "SELLER_AUCTION_SHORT": short_candidate,
        "BIDIRECTIONAL_ONE_PER_DAY": combined,
    }
    row: dict[str, Any] = {
        "case_alias": stream["case_alias"],
        "trading_date_utc": stream["trading_date_utc"],
        "long_control_at_signal": long_state,
        "long_veto_disposition": (
            "NO_FROZEN_LONG_TRADE"
            if long_original is None
            else "RETAIN_BUYER_CONTROL"
            if long_veto is not None
            else f"VETO_{long_state['state']}"
        ),
        "short_session_audits": session_audits,
        "tracks": tracks,
    }
    row["row_sha256"] = canonical_hash(row)
    return row


def run_side(side: str) -> dict[str, Any]:
    streams = load_streams(side)
    controls = long_control_population()
    require(set(streams) == set(controls), "Stream and frozen control identities differ")
    ordered = sorted(
        streams.values(), key=lambda row: (row["trading_date_utc"], row["case_alias"])
    )
    rows: list[dict[str, Any]] = []
    for index, stream in enumerate(ordered, start=1):
        row = run_day(stream, controls[str(stream["case_alias"])])
        rows.append(row)
        print(
            f"{side} {index:03d}/{len(ordered):03d} {stream['trading_date_utc']}",
            flush=True,
        )
    return {
        "version": "GOLD_AUCTION_CONTROL_ROUTER_JAN_JUN_2022_SIDE_1_0",
        "side": side,
        "rows": rows,
        "rows_sha256": canonical_hash(rows),
    }


def result_of(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if candidate is None else candidate["result"]


def track_metrics(rows: list[dict[str, Any]], track: str) -> dict[str, Any]:
    values: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    for row in rows:
        candidate = row["tracks"][track]
        result = result_of(candidate)
        if result is not None and result.get("executed"):
            values.append((row, candidate, float(result["net_r50"])))
    wins = [value for _, _, value in values if value > EPSILON]
    losses = [value for _, _, value in values if value < -EPSILON]
    equity = peak = maximum_drawdown = 0.0
    monthly: dict[str, float] = defaultdict(float)
    monthly_trades: Counter[str] = Counter()
    sessions: dict[str, float] = defaultdict(float)
    directions: dict[str, float] = defaultdict(float)
    stressed = 0.0
    for row, candidate, value in values:
        month = str(row["trading_date_utc"])[:7]
        monthly[month] += value
        monthly_trades[month] += 1
        sessions[str(candidate["session"])] += value
        directions[str(candidate["direction"])] += value
        stressed += float(candidate["result"]["stressed_1_5x_cost_r50"])
        equity += value
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
    positive = sum(wins)
    negative = abs(sum(losses))
    return {
        "days": len(rows),
        "trades": len(values),
        "no_trade_days": len(rows) - len(values),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(values) - len(wins) - len(losses),
        "win_rate": len(wins) / len(values) if values else None,
        "net_r": sum(value for _, _, value in values),
        "net_usd": sum(
            float(candidate["result"]["net_usd"]) for _, candidate, _ in values
        ),
        "expectancy_r": (
            sum(value for _, _, value in values) / len(values) if values else 0.0
        ),
        "profit_factor": positive / negative if negative else None,
        "profit_factor_infinite": bool(wins and not losses),
        "maximum_drawdown_r": maximum_drawdown,
        "stressed_1p5x_cost_net_r": stressed,
        "monthly_net_r": dict(sorted(monthly.items())),
        "monthly_trades": dict(sorted(monthly_trades.items())),
        "session_net_r": dict(sorted(sessions.items())),
        "direction_net_r": dict(sorted(directions.items())),
    }


def audit_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    veto = Counter()
    veto_r = defaultdict(float)
    short_rejections = Counter()
    transitions = Counter()
    for row in rows:
        original = row["tracks"]["ORIGINAL_LONG_CONTROL"]
        retained = row["tracks"]["BUYER_CONTROL_VETO_LONG"]
        if original is not None:
            value = float(original["result"]["net_r50"])
            if retained is not None:
                category = "RETAINED_WIN" if value > EPSILON else "RETAINED_LOSS" if value < -EPSILON else "RETAINED_SCRATCH"
            else:
                category = "VETOED_WIN" if value > EPSILON else "VETOED_LOSS" if value < -EPSILON else "VETOED_SCRATCH"
            veto[category] += 1
            veto_r[category] += value
        for audit in row["short_session_audits"]:
            transitions[audit["session"]] += int(audit["seller_control_transitions"])
            for attempt in audit["attempts"]:
                if not attempt.get("admitted"):
                    short_rejections[str(attempt["disposition"])] += 1
    return {
        "long_veto_counts": dict(sorted(veto.items())),
        "long_veto_net_r": dict(sorted(veto_r.items())),
        "seller_control_transitions": dict(sorted(transitions.items())),
        "short_rejection_reasons": dict(sorted(short_rejections.items())),
    }


def ledger(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    equity = {track: STARTING_EQUITY_USD for track in TRACKS}
    output: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = {
            "trading_date_utc": row["trading_date_utc"],
            "case_alias": row["case_alias"],
            "long_control_state": (row.get("long_control_at_signal") or {}).get("state"),
            "long_veto_disposition": row["long_veto_disposition"],
        }
        for track in TRACKS:
            candidate = row["tracks"][track]
            result = result_of(candidate)
            value_r = 0.0 if result is None else float(result["net_r50"])
            value_usd = 0.0 if result is None else float(result["net_usd"])
            equity[track] += value_usd
            prefix = track.lower()
            record[f"{prefix}_direction"] = None if candidate is None else candidate["direction"]
            record[f"{prefix}_session"] = None if candidate is None else candidate["session"]
            record[f"{prefix}_fill_at"] = None if candidate is None else candidate["fill_at"]
            record[f"{prefix}_net_r"] = value_r
            record[f"{prefix}_equity_usd"] = equity[track]
        output.append(record)
    return output


def write_ledger(rows: list[dict[str, Any]]) -> None:
    require(not LEDGER.exists(), f"Append-only ledger exists: {LEDGER}")
    with LEDGER.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def pf_text(metrics: dict[str, Any]) -> str:
    if metrics["profit_factor_infinite"]:
        return "INF"
    if metrics["profit_factor"] is None:
        return "N/A"
    return f"{metrics['profit_factor']:.3f}"


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Gold Auction-Control Router — January–June 2022 Exposed Regression V1 Report",
        "",
        f"Verdict: `{result['verdict']}`",
        "",
        "All six months are exposed historical data and receive zero validation credit.",
        "",
        "| Track | Trades | W/L/S | Win rate | Net R | Net USD | Exp R | PF | Max DD R | 1.5x-cost R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for track in TRACKS:
        metrics = result["metrics"][track]
        lines.append(
            f"| {track} | {metrics['trades']} | {metrics['wins']}/{metrics['losses']}/{metrics['scratches']} | "
            f"{100 * float(metrics['win_rate'] or 0):.2f}% | {metrics['net_r']:+.4f} | "
            f"{metrics['net_usd']:+.2f} | {metrics['expectancy_r']:+.4f} | {pf_text(metrics)} | "
            f"{metrics['maximum_drawdown_r']:.4f} | {metrics['stressed_1p5x_cost_net_r']:+.4f} |"
        )
    lines.extend(["", "## Monthly net R", "", "| Month | Original LONG | Veto LONG | SHORT | Combined |", "|---|---:|---:|---:|---:|"])
    months = sorted(
        {
            month
            for track in TRACKS
            for month in result["metrics"][track]["monthly_net_r"]
        }
    )
    for month in months:
        values = [result["metrics"][track]["monthly_net_r"].get(month, 0.0) for track in TRACKS]
        lines.append(f"| {month} | {values[0]:+.4f} | {values[1]:+.4f} | {values[2]:+.4f} | {values[3]:+.4f} |")
    audit = result["audit"]
    lines.extend(
        [
            "",
            "## Router audit",
            "",
            f"- LONG veto counts: `{json.dumps(audit['long_veto_counts'], sort_keys=True)}`",
            f"- LONG veto R: `{json.dumps(audit['long_veto_net_r'], sort_keys=True)}`",
            f"- Seller-control transitions: `{json.dumps(audit['seller_control_transitions'], sort_keys=True)}`",
            f"- SHORT rejection reasons: `{json.dumps(audit['short_rejection_reasons'], sort_keys=True)}`",
            "",
            "The original LONG results were not reconstructed or altered. The veto changed admission only. Every SHORT required the complete frozen seller-auction plan; a bearish break alone was insufficient.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    for path in (PRIMARY, REFERENCE, FINAL, LEDGER, SEAL, REPORT):
        require(not path.exists(), f"One-shot output already exists: {path}")

    primary = run_side("primary")
    write_new_json(PRIMARY, primary)
    reference = run_side("reference")
    write_new_json(REFERENCE, reference)
    require(primary["rows"] == reference["rows"], "Primary/reference rows differ")
    require(primary["rows_sha256"] == reference["rows_sha256"], "Row checksums differ")

    rows = primary["rows"]
    metrics = {track: track_metrics(rows, track) for track in TRACKS}
    audit = audit_metrics(rows)
    daily = ledger(rows)
    write_ledger(daily)
    result: dict[str, Any] = {
        "version": "GOLD_AUCTION_CONTROL_ROUTER_JAN_JUN_2022_V1_RESULT_1_0",
        "completed_at": now(),
        "verdict": "COMPLETE_EXPOSED_ROUTER_REGRESSION_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "ruleset": RULESET,
        "days": len(rows),
        "primary_reference_exact": True,
        "rows_sha256": primary["rows_sha256"],
        "metrics": metrics,
        "audit": audit,
        "daily_ledger": daily,
        "rows": rows,
        "all_periods_exposed_zero_validation_credit": True,
        "february_17_28_opened": False,
        "july_2022_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "retuning_performed": False,
        "paid_acquisition": False,
    }
    result["result_sha256"] = canonical_hash(result)
    write_new_json(FINAL, result)
    REPORT.write_text(markdown(result), encoding="utf-8", newline="\n")
    seal: dict[str, Any] = {
        "version": "GOLD_AUCTION_CONTROL_ROUTER_JAN_JUN_2022_V1_SEAL_1_0",
        "sealed_at": now(),
        "verdict": result["verdict"],
        "primary_reference_exact": True,
        "result_sha256": result["result_sha256"],
        "files": [
            file_record(FREEZE),
            file_record(PRIMARY),
            file_record(REFERENCE),
            file_record(FINAL),
            file_record(LEDGER),
            file_record(REPORT),
        ],
        "july_2022_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    write_new_json(SEAL, seal)
    print(
        json.dumps(
            {
                "verdict": result["verdict"],
                "primary_reference_exact": True,
                "metrics": metrics,
                "audit": audit,
                "result_sha256": result["result_sha256"],
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "run", "all"))
    args = parser.parse_args()
    if args.action in {"freeze", "all"}:
        freeze()
    if args.action in {"run", "all"}:
        run()


if __name__ == "__main__":
    main()
