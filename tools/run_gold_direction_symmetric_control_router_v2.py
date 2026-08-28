#!/usr/bin/env python3
"""Apply the mutually exclusive auction-control gate to the symmetric translator."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_auction_control_router_jan_jun_2022_v1 as v1  # noqa: E402
import run_gold_direction_symmetric_auction_gap_audit_v1 as symmetric  # noqa: E402
from gold_intel.analytics.auction_control_router_v1 import (  # noqa: E402
    control_state_at,
    prepare_control,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    parse_dt,
)
from gold_intel.analytics.direction_symmetric_control_router_v2 import (  # noqa: E402
    RULESET,
    earliest_trade,
    route_candidate,
)


CONTRACT = ROOT / "GOLD_DIRECTION_SYMMETRIC_AUCTION_CONTROL_ROUTER_V2.md"
IMPLEMENTATION = (
    ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "direction_symmetric_control_router_v2.py"
)
TESTS = (
    ROOT / "backend" / "tests" / "unit" / "test_direction_symmetric_control_router_v2.py"
)
RUNNER = Path(__file__).resolve()

SYMMETRIC_ROOT = ROOT / "research_artifacts" / "gold_direction_symmetric_auction_gap_audit_v1"
SYMMETRIC_PRIMARY = SYMMETRIC_ROOT / "primary.json"
SYMMETRIC_REFERENCE = SYMMETRIC_ROOT / "reference.json"
SYMMETRIC_RESULT = SYMMETRIC_ROOT / "final_result.json"
SYMMETRIC_SEAL = SYMMETRIC_ROOT / "final_seal.json"
TRANSLATOR = symmetric.TRANSLATOR

V1_ROOT = ROOT / "research_artifacts" / "gold_auction_control_router_jan_jun_2022_v1"
V1_RESULT = V1_ROOT / "final_result.json"
V1_SEAL = V1_ROOT / "final_seal.json"

OUT = ROOT / "research_artifacts" / "gold_direction_symmetric_control_router_v2"
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY = OUT / "primary.json"
REFERENCE = OUT / "reference.json"
FINAL = OUT / "final_result.json"
LEDGER = OUT / "daily_ledger.csv"
SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_DIRECTION_SYMMETRIC_AUCTION_CONTROL_ROUTER_V2_REPORT.md"

TRACKS = (
    "FROZEN_LONG_CONTROL",
    "BUYER_CONTROL_VETO_LONG",
    "DIRECTION_SYMMETRIC_UNGATED",
    "CONTROL_ROUTED_SYMMETRIC",
    "HELD_LONG_PLUS_ROUTED_SHORT",
)
STARTING_EQUITY_USD = 10_000.0
EPSILON = 1e-10


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


def verify_record(record: dict[str, Any]) -> None:
    path = ROOT / str(record["path"])
    require(path.is_file(), f"Sealed file missing: {path}")
    require(path.stat().st_size == int(record["bytes"]), f"Sealed size differs: {path}")
    require(sha256_file(path) == str(record["sha256"]), f"Sealed hash differs: {path}")


def write_new_json(path: Path, payload: dict[str, Any]) -> None:
    require(not path.exists(), f"Append-only output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def verify_seal(path: Path, verdict: str) -> dict[str, Any]:
    seal = load_json(path)
    require(seal["verdict"] == verdict, f"Unexpected predecessor verdict: {path}")
    for record in seal.get("files", []):
        verify_record(record)
    return seal


def verify_sources() -> dict[str, Any]:
    for path in (
        CONTRACT,
        IMPLEMENTATION,
        TESTS,
        RUNNER,
        SYMMETRIC_PRIMARY,
        SYMMETRIC_REFERENCE,
        SYMMETRIC_RESULT,
        SYMMETRIC_SEAL,
        TRANSLATOR,
        V1_RESULT,
        V1_SEAL,
        v1.JUNE_PRIMARY_STREAMS,
        v1.JUNE_REFERENCE_STREAMS,
    ):
        require(path.is_file(), f"Required source missing: {path}")
    verify_seal(
        SYMMETRIC_SEAL,
        "COMPLETE_EXPOSED_DIRECTION_SYMMETRY_AND_MONETIZATION_GAP_AUDIT",
    )
    verify_seal(
        V1_SEAL,
        "COMPLETE_EXPOSED_ROUTER_REGRESSION_ZERO_VALIDATION_CREDIT",
    )
    symmetric_primary = load_json(SYMMETRIC_PRIMARY)
    symmetric_reference = load_json(SYMMETRIC_REFERENCE)
    require(
        symmetric_primary["rows"] == symmetric_reference["rows"],
        "Sealed January–May symmetric rows differ",
    )
    require(len(symmetric_primary["rows"]) == 95, "Symmetric predecessor population differs")
    v1_result = load_json(V1_RESULT)
    require(v1_result["primary_reference_exact"] is True, "V1 reproduction differs")
    require(len(v1_result["rows"]) == 117, "V1 daily population differs")
    return {
        "symmetric_primary": file_record(SYMMETRIC_PRIMARY),
        "symmetric_reference": file_record(SYMMETRIC_REFERENCE),
        "symmetric_result": file_record(SYMMETRIC_RESULT),
        "symmetric_seal": file_record(SYMMETRIC_SEAL),
        "translator": file_record(TRANSLATOR),
        "v1_result": file_record(V1_RESULT),
        "v1_seal": file_record(V1_SEAL),
        "june_primary_streams": file_record(v1.JUNE_PRIMARY_STREAMS),
        "june_reference_streams": file_record(v1.JUNE_REFERENCE_STREAMS),
    }


def synthetic_proof() -> dict[str, Any]:
    def source(direction: str) -> dict[str, Any]:
        return {
            "row_sha256": f"row-{direction}",
            "signal_at": "2022-01-03T14:00:00Z",
            "direction": direction,
            "disposition": "SEALED_TARGET",
            "corrected": {
                "effective_result": {
                    "executed": True,
                    "net_r50": 1.0,
                    "result_hash": f"result-{direction}",
                }
            },
        }

    long = source("LONG")
    short = source("SHORT")
    checks = {
        "buyer_admits_long": route_candidate(
            candidate=long, control={"state": "BUYER_CONTROL"}
        )["admitted"],
        "seller_admits_short": route_candidate(
            candidate=short, control={"state": "SELLER_CONTROL"}
        )["admitted"],
        "seller_vetoes_long": not route_candidate(
            candidate=long, control={"state": "SELLER_CONTROL"}
        )["admitted"],
        "buyer_vetoes_short": not route_candidate(
            candidate=short, control={"state": "BUYER_CONTROL"}
        )["admitted"],
    }
    require(all(checks.values()), f"Synthetic direction gate failed: {checks}")
    return {"checks": checks, "proof_sha256": canonical_hash(checks)}


def freeze() -> None:
    require(not OUT.exists(), f"Output directory already exists: {OUT}")
    lineage = verify_sources()
    symmetric_rows = load_json(SYMMETRIC_PRIMARY)["rows"]
    identities = [
        {
            "case_alias": row["case_alias"],
            "trading_date_utc": row["trading_date_utc"],
            "source_row_sha256": row["row_sha256"],
        }
        for row in symmetric_rows
    ]
    payload: dict[str, Any] = {
        "version": "GOLD_DIRECTION_SYMMETRIC_AUCTION_CONTROL_ROUTER_V2_FREEZE_1_0",
        "sealed_at": now(),
        "status": "SEALED_BEFORE_EXPOSED_V2_ROUTER_REGRESSION",
        "implementation_files": [
            file_record(CONTRACT),
            file_record(IMPLEMENTATION),
            file_record(TESTS),
            file_record(RUNNER),
        ],
        "source_lineage": lineage,
        "jan_may_symmetric_identities": identities,
        "jan_may_symmetric_identities_sha256": canonical_hash(identities),
        "tracks": list(TRACKS),
        "routing": {
            "session": "NEW_YORK",
            "long_requires": "BUYER_CONTROL",
            "short_requires": "SELLER_CONTROL",
            "candidate_mutation_permitted": False,
            "additional_short_plan_permitted": False,
        },
        "synthetic_proof": synthetic_proof(),
        "all_results_exposed_zero_validation_credit": True,
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
                "jan_may_rows": len(identities),
                "freeze_sha256": payload["freeze_sha256"],
            },
            indent=2,
        )
    )


def verify_freeze() -> dict[str, Any]:
    require(FREEZE.is_file(), "V2 prevalue freeze is absent")
    payload = load_json(FREEZE)
    submitted = str(payload.pop("freeze_sha256"))
    require(canonical_hash(payload) == submitted, "V2 freeze payload differs")
    payload["freeze_sha256"] = submitted
    for record in payload["implementation_files"]:
        verify_record(record)
    require(verify_sources() == payload["source_lineage"], "V2 source lineage differs")
    return payload


def symmetric_rows(side: str, june_streams: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    jan_may_payload = load_json(
        SYMMETRIC_PRIMARY if side == "primary" else SYMMETRIC_REFERENCE
    )
    jan_may = jan_may_payload["rows"]
    translator = load_json(TRANSLATOR)
    june = symmetric.infer_group(streams=june_streams, translator=translator)
    rows = [*jan_may, *june]
    rows.sort(key=lambda row: (row["trading_date_utc"], row["case_alias"]))
    require(len(rows) == 117, "Expected 117 symmetric candidate rows")
    require(len({row["trading_date_utc"] for row in rows}) == 117, "Candidate dates differ")
    return rows


def wrapped_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    result = (row.get("corrected") or {}).get("effective_result")
    if result is None or not result.get("executed"):
        return None
    lifecycle = row.get("family_router") or {}
    geometry = lifecycle.get("geometry") or row.get("geometry") or {}
    fill_at = geometry.get("fill_at")
    require(fill_at is not None, f"Executed candidate lacks fill timestamp: {row['case_alias']}")
    return {
        "direction": row["direction"],
        "session": "NEW_YORK",
        "signal_at": row["signal_at"],
        "fill_at": fill_at,
        "family": lifecycle.get("family"),
        "result": result,
        "source_row_sha256": row["row_sha256"],
    }


def run_side(side: str) -> dict[str, Any]:
    all_streams = v1.load_streams(side)
    june_streams = {
        alias: stream for alias, stream in all_streams.items() if alias.startswith("JUN-")
    }
    candidates = symmetric_rows(side, june_streams)
    candidate_by_alias = {row["case_alias"]: row for row in candidates}
    v1_rows = {row["case_alias"]: row for row in load_json(V1_RESULT)["rows"]}
    require(set(all_streams) == set(candidate_by_alias) == set(v1_rows), "Daily identities differ")

    rows: list[dict[str, Any]] = []
    ordered = sorted(
        all_streams.values(), key=lambda row: (row["trading_date_utc"], row["case_alias"])
    )
    for index, stream in enumerate(ordered, start=1):
        alias = str(stream["case_alias"])
        source = candidate_by_alias[alias]
        prepared = prepare_control(stream)
        signal_at = source.get("signal_at")
        if signal_at is None:
            control = {
                "at": None,
                "state": "UNRESOLVED",
                "raw_state": "UNRESOLVED",
                "source_observation_at": None,
                "m5_event_identity": None,
                "m15_event_identity": None,
            }
        else:
            control = control_state_at(prepared["sessions"]["NEW_YORK"], signal_at)
        routed = route_candidate(candidate=source, control=control)
        ungated = wrapped_candidate(source)
        gated = wrapped_candidate(source) if routed["admitted"] else None

        prior = v1_rows[alias]
        frozen_long = prior["tracks"]["ORIGINAL_LONG_CONTROL"]
        held_long = prior["tracks"]["BUYER_CONTROL_VETO_LONG"]
        routed_short = gated if gated is not None and gated["direction"] == "SHORT" else None
        combined = earliest_trade(held_long, routed_short)
        tracks = {
            "FROZEN_LONG_CONTROL": frozen_long,
            "BUYER_CONTROL_VETO_LONG": held_long,
            "DIRECTION_SYMMETRIC_UNGATED": ungated,
            "CONTROL_ROUTED_SYMMETRIC": gated,
            "HELD_LONG_PLUS_ROUTED_SHORT": combined,
        }
        row: dict[str, Any] = {
            "case_alias": alias,
            "trading_date_utc": stream["trading_date_utc"],
            "source_symmetric_candidate": source,
            "auction_control_at_signal": control,
            "control_route": routed,
            "tracks": tracks,
        }
        row["row_sha256"] = canonical_hash(row)
        rows.append(row)
        print(
            f"{side} {index:03d}/{len(ordered):03d} {stream['trading_date_utc']}",
            flush=True,
        )
    return {
        "version": "GOLD_DIRECTION_SYMMETRIC_AUCTION_CONTROL_ROUTER_V2_SIDE_1_0",
        "side": side,
        "rows": rows,
        "rows_sha256": canonical_hash(rows),
    }


def result_of(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if candidate is None else candidate["result"]


def track_metrics(rows: list[dict[str, Any]], track: str) -> dict[str, Any]:
    executed: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    for row in rows:
        candidate = row["tracks"][track]
        result = result_of(candidate)
        if result is not None and result.get("executed"):
            executed.append((row, candidate, float(result["net_r50"])))
    wins = [value for _, _, value in executed if value > EPSILON]
    losses = [value for _, _, value in executed if value < -EPSILON]
    equity = peak = drawdown = 0.0
    monthly: dict[str, float] = defaultdict(float)
    directions: dict[str, float] = defaultdict(float)
    direction_trades: Counter[str] = Counter()
    families: dict[str, float] = defaultdict(float)
    stressed = 0.0
    for row, candidate, value in executed:
        monthly[str(row["trading_date_utc"])[:7]] += value
        directions[str(candidate["direction"])] += value
        direction_trades[str(candidate["direction"])] += 1
        families[str(candidate.get("family"))] += value
        stressed += float(candidate["result"]["stressed_1_5x_cost_r50"])
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    positive = sum(wins)
    negative = abs(sum(losses))
    return {
        "days": len(rows),
        "trades": len(executed),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(executed) - len(wins) - len(losses),
        "win_rate": len(wins) / len(executed) if executed else None,
        "net_r": sum(value for _, _, value in executed),
        "net_usd": sum(float(candidate["result"]["net_usd"]) for _, candidate, _ in executed),
        "expectancy_r": (
            sum(value for _, _, value in executed) / len(executed) if executed else 0.0
        ),
        "profit_factor": positive / negative if negative else None,
        "profit_factor_infinite": bool(wins and not losses),
        "maximum_drawdown_r": drawdown,
        "stressed_1p5x_cost_net_r": stressed,
        "monthly_net_r": dict(sorted(monthly.items())),
        "direction_trades": dict(sorted(direction_trades.items())),
        "direction_net_r": dict(sorted(directions.items())),
        "family_net_r": dict(sorted(families.items())),
    }


def routing_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dispositions = Counter(row["control_route"]["disposition"] for row in rows)
    by_direction: dict[str, Counter[str]] = defaultdict(Counter)
    admitted_family = Counter()
    for row in rows:
        direction = row["source_symmetric_candidate"].get("direction") or "NONE"
        by_direction[str(direction)][row["control_route"]["disposition"]] += 1
        if row["control_route"]["admitted"]:
            family = (row["source_symmetric_candidate"].get("family_router") or {}).get("family")
            admitted_family[str(family)] += 1
    return {
        "dispositions": dict(sorted(dispositions.items())),
        "by_direction": {
            direction: dict(sorted(values.items()))
            for direction, values in sorted(by_direction.items())
        },
        "admitted_family_counts": dict(sorted(admitted_family.items())),
    }


def ledger(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    equity = {track: STARTING_EQUITY_USD for track in TRACKS}
    output: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = {
            "trading_date_utc": row["trading_date_utc"],
            "case_alias": row["case_alias"],
            "candidate_direction": row["source_symmetric_candidate"].get("direction"),
            "candidate_signal_at": row["source_symmetric_candidate"].get("signal_at"),
            "control_state": row["auction_control_at_signal"].get("state"),
            "control_disposition": row["control_route"]["disposition"],
        }
        for track in TRACKS:
            candidate = row["tracks"][track]
            result = result_of(candidate)
            value_r = 0.0 if result is None else float(result["net_r50"])
            value_usd = 0.0 if result is None else float(result["net_usd"])
            equity[track] += value_usd
            prefix = track.lower()
            record[f"{prefix}_direction"] = None if candidate is None else candidate["direction"]
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
        "# Gold Direction-Symmetric Auction-Control Router V2 Report",
        "",
        f"Verdict: `{result['verdict']}`",
        "",
        "This is an exposed January–June semantic regression with zero validation credit.",
        "",
        "| Track | Trades | Direction trades | W/L/S | Win rate | Net R | Exp R | PF | Max DD R | 1.5x-cost R |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for track in TRACKS:
        metrics = result["metrics"][track]
        lines.append(
            f"| {track} | {metrics['trades']} | {json.dumps(metrics['direction_trades'], sort_keys=True)} | "
            f"{metrics['wins']}/{metrics['losses']}/{metrics['scratches']} | "
            f"{100 * float(metrics['win_rate'] or 0):.2f}% | {metrics['net_r']:+.4f} | "
            f"{metrics['expectancy_r']:+.4f} | {pf_text(metrics)} | "
            f"{metrics['maximum_drawdown_r']:.4f} | {metrics['stressed_1p5x_cost_net_r']:+.4f} |"
        )
    lines.extend(
        [
            "",
            "## Routing audit",
            "",
            f"- Dispositions: `{json.dumps(result['routing_audit']['dispositions'], sort_keys=True)}`",
            f"- By direction: `{json.dumps(result['routing_audit']['by_direction'], sort_keys=True)}`",
            f"- Admitted families: `{json.dumps(result['routing_audit']['admitted_family_counts'], sort_keys=True)}`",
            "",
            "No candidate geometry or result was changed. The only V2 operation was the direction-appropriate auction-control gate.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    for path in (PRIMARY, REFERENCE, FINAL, LEDGER, SEAL, REPORT):
        require(not path.exists(), f"One-shot output exists: {path}")
    primary = run_side("primary")
    write_new_json(PRIMARY, primary)
    reference = run_side("reference")
    write_new_json(REFERENCE, reference)
    require(primary["rows"] == reference["rows"], "Primary/reference V2 rows differ")
    require(primary["rows_sha256"] == reference["rows_sha256"], "V2 checksums differ")

    rows = primary["rows"]
    metrics = {track: track_metrics(rows, track) for track in TRACKS}
    audit = routing_audit(rows)
    daily = ledger(rows)
    write_ledger(daily)
    result: dict[str, Any] = {
        "version": "GOLD_DIRECTION_SYMMETRIC_AUCTION_CONTROL_ROUTER_V2_RESULT_1_0",
        "completed_at": now(),
        "verdict": "COMPLETE_EXPOSED_DIRECTION_SYMMETRIC_CONTROL_ROUTER_V2",
        "freeze_sha256": frozen["freeze_sha256"],
        "ruleset": RULESET,
        "days": len(rows),
        "primary_reference_exact": True,
        "rows_sha256": primary["rows_sha256"],
        "metrics": metrics,
        "routing_audit": audit,
        "daily_ledger": daily,
        "rows": rows,
        "all_results_exposed_zero_validation_credit": True,
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
        "version": "GOLD_DIRECTION_SYMMETRIC_AUCTION_CONTROL_ROUTER_V2_SEAL_1_0",
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
                "routing_audit": audit,
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
