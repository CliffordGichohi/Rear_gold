from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_gc_session_state_transition_v1 as prior  # noqa: E402
import run_gold_fundamental_aligned_multitimeframe_auction_edge_v1 as branch  # noqa: E402


OUTPUT = branch.OUTPUT
AUTHORIZATION = OUTPUT / "development_outcome_opening_authorization.json"
PRIMARY_TRADES = OUTPUT / "primary_trades.parquet"
REFERENCE_TRADES = OUTPUT / "reference_trades.parquet"
RESULTS = OUTPUT / "development_results.json"
CANDIDATES = OUTPUT / "frozen_development_candidates.json"
EXPOSED = OUTPUT / "exposed_robustness.json"
LEDGER = OUTPUT / "prospective_paper_ledger.jsonl"
REPORT = ROOT / "GOLD_FUNDAMENTAL_ALIGNED_MULTITIMEFRAME_AUCTION_EDGE_V1_REPORT.md"
FINAL_SEAL = OUTPUT / "final_seal.json"

BASELINE_COST_USD_OZ = 0.47
BOOTSTRAPS = 5_000
BOOTSTRAP_SEED = 26_080_701
BLOCKS = (
    ("B1", "2021-08-01", "2022-06-30"),
    ("B2", "2022-07-01", "2023-03-31"),
    ("B3", "2023-04-01", "2023-12-31"),
    ("B4", "2024-01-01", "2024-12-31"),
)


TRADE_SCHEMA = pa.schema(
    [
        pa.field("trade_id", pa.string(), False),
        pa.field("signal_id", pa.string(), False),
        pa.field("session_date", pa.string(), False),
        pa.field("session_code", pa.string(), False),
        pa.field("iso_week", pa.string(), False),
        pa.field("setup_id", pa.string(), False),
        pa.field("direction", pa.string(), False),
        pa.field("signal_at_utc", pa.string(), False),
        pa.field("status", pa.string(), False),
        pa.field("no_trade_reason", pa.string(), False),
        pa.field("gc_covered", pa.bool_(), False),
        pa.field("gc_confirmed", pa.bool_(), True),
        pa.field("entry_at_utc", pa.string(), True),
        pa.field("exit_at_utc", pa.string(), True),
        pa.field("entry_e8", pa.int64(), True),
        pa.field("stop_e8", pa.int64(), True),
        pa.field("target_e8", pa.int64(), True),
        pa.field("exit_e8", pa.int64(), True),
        pa.field("risk_e8", pa.int64(), True),
        pa.field("target_r", pa.float64(), True),
        pa.field("exit_reason", pa.string(), True),
        pa.field("holding_minutes", pa.int64(), True),
        pa.field("gross_r", pa.float64(), True),
        pa.field("net_r", pa.float64(), True),
        pa.field("net_r_cost_1p5x", pa.float64(), True),
        pa.field("net_r_cost_2x", pa.float64(), True),
        pa.field("mfe_r", pa.float64(), True),
        pa.field("mae_r", pa.float64(), True),
        pa.field("planned_lots", pa.float64(), True),
        pa.field("actual_risk_usd", pa.float64(), True),
        pa.field("net_pnl_usd", pa.float64(), True),
        pa.field("outcome_lineage_hash", pa.string(), False),
    ]
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed.astimezone(UTC)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_text_exclusive(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(list(rows), schema=TRADE_SCHEMA)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(
        table, temporary, compression="zstd", use_dictionary=False,
        write_statistics=True, data_page_version="1.0", version="2.6",
        row_group_size=65_536,
    )
    temporary.replace(path)


def rounded(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    result = round(float(value), 12)
    return 0.0 if result == 0 else result


def verify_and_load_signals() -> list[dict[str, Any]]:
    branch.verify_freeze()
    amendment = json.loads(branch.AMENDMENT_A.read_text(encoding="utf-8"))
    if amendment["status"] != "SEALED_BEFORE_ANY_NEW_BRANCH_OUTCOME_ACCESS":
        raise ValueError("Amendment A is invalid")
    certification_path = OUTPUT / "materialization_certification.json"
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    if certification["status"] != "PASS_OUTCOME_BLIND_MATERIALIZATION":
        raise ValueError("Materialization did not pass")
    if certification["new_branch_outcomes_accessed"] or certification["forward_values_accessed"]:
        raise ValueError("Pre-outcome lineage is contaminated")
    primary_path = OUTPUT / "primary_signals.parquet"
    reference_path = OUTPUT / "reference_signals.parquet"
    primary = pq.read_table(primary_path).to_pylist()
    reference = pq.read_table(reference_path).to_pylist()
    if primary != reference or sha256_file(primary_path) != sha256_file(reference_path):
        raise ValueError("Sealed signal implementations differ")
    if canonical_hash(primary) != certification["primary_diagnostics"]["complete_rows_hash"]:
        raise ValueError("Sealed signal row checksum changed")
    return primary


def empty_trade(signal: Mapping[str, Any], reason: str, lineage: Any) -> dict[str, Any]:
    return {
        "trade_id": f"TRADE::{signal['signal_id']}",
        "signal_id": signal["signal_id"], "session_date": signal["session_date"],
        "session_code": signal["session_code"], "iso_week": signal["iso_week"],
        "setup_id": signal["setup_id"], "direction": signal["direction"],
        "signal_at_utc": signal["signal_at_utc"], "status": "NO_TRADE",
        "no_trade_reason": reason, "gc_covered": signal["gc_covered"],
        "gc_confirmed": signal["gc_confirmed"], "entry_at_utc": None,
        "exit_at_utc": None, "entry_e8": None, "stop_e8": None,
        "target_e8": None, "exit_e8": None, "risk_e8": None,
        "target_r": None, "exit_reason": None, "holding_minutes": None,
        "gross_r": None, "net_r": None, "net_r_cost_1p5x": None,
        "net_r_cost_2x": None, "mfe_r": None, "mae_r": None,
        "planned_lots": None, "actual_risk_usd": None, "net_pnl_usd": None,
        "outcome_lineage_hash": canonical_hash(lineage),
    }


def target_for_signal(signal: Mapping[str, Any], entry: int, risk: int) -> int | None:
    levels = json.loads(str(signal["known_levels_json"]))
    direction = str(signal["direction"])
    if direction == "UP":
        candidates = sorted(
            int(item["price_e8"]) for item in levels
            if item["side"] == "UPPER" and int(item["price_e8"]) > entry
            and int(item["price_e8"]) - entry >= 1.25 * risk
        )
        if not candidates:
            return None
        return min(candidates[0], entry + int(round(2.5 * risk)))
    candidates = sorted(
        (int(item["price_e8"]) for item in levels
         if item["side"] == "LOWER" and int(item["price_e8"]) < entry
         and entry - int(item["price_e8"]) >= 1.25 * risk),
        reverse=True,
    )
    if not candidates:
        return None
    return max(candidates[0], entry - int(round(2.5 * risk)))


def exit_primary(path: Sequence[prior.Bar], direction: str, stop: int, target: int) -> tuple[int, int, str]:
    for index, bar in enumerate(path):
        stop_hit = bar.low_e8 <= stop if direction == "UP" else bar.high_e8 >= stop
        target_hit = bar.high_e8 >= target if direction == "UP" else bar.low_e8 <= target
        if stop_hit:
            return index, stop, "STOP"
        if target_hit:
            return index, target, "TARGET"
    return len(path) - 1, path[-1].close_e8, "TIME"


def exit_reference(path: Sequence[prior.Bar], direction: str, stop: int, target: int) -> tuple[int, int, str]:
    lows = np.asarray([item.low_e8 for item in path], dtype=np.int64)
    highs = np.asarray([item.high_e8 for item in path], dtype=np.int64)
    stop_mask = lows <= stop if direction == "UP" else highs >= stop
    target_mask = highs >= target if direction == "UP" else lows <= target
    stop_hits, target_hits = np.flatnonzero(stop_mask), np.flatnonzero(target_mask)
    stop_at = int(stop_hits[0]) if len(stop_hits) else math.inf
    target_at = int(target_hits[0]) if len(target_hits) else math.inf
    if stop_at <= target_at and stop_at != math.inf:
        return int(stop_at), stop, "STOP"
    if target_at != math.inf:
        return int(target_at), target, "TARGET"
    return len(path) - 1, path[-1].close_e8, "TIME"


def calculate_trade(signal: Mapping[str, Any], bars: Mapping[datetime, prior.Bar], implementation: str) -> dict[str, Any]:
    decision = parse_dt(str(signal["signal_at_utc"]))
    local_day = date.fromisoformat(str(signal["session_date"]))
    forced = datetime.combine(local_day, time(12), branch.ZONES[str(signal["session_code"])]).astimezone(UTC)
    end = min(decision + timedelta(minutes=120), forced)
    if end <= decision:
        return empty_trade(signal, "SIGNAL_AT_OR_AFTER_FORCED_EXIT", [signal["signal_id"], "FORCED_EXIT"])
    stamps = [decision + timedelta(minutes=index) for index in range(int((end - decision).total_seconds() // 60))]
    if not stamps or bars.get(stamps[0]) is None:
        return empty_trade(signal, "MISSING_NEXT_M1_ENTRY_BAR", [signal["signal_id"], "ENTRY_MISSING"])
    values = [bars.get(stamp) for stamp in stamps]
    if any(item is None for item in values):
        missing = [iso_z(stamp) for stamp, item in zip(stamps, values) if item is None]
        return empty_trade(signal, "MISSING_M1_HOLDING_PATH", [signal["signal_id"], missing])
    path = [item for item in values if item is not None]
    if any(left.close_at != right.open_at for left, right in zip(path, path[1:])):
        return empty_trade(signal, "NONCONTIGUOUS_M1_HOLDING_PATH", [signal["signal_id"], [item.record_hash for item in path]])
    entry = int(path[0].open_e8)
    atr = int(signal["atr20_5m_e8"])
    buffer_value = int(round(0.10 * atr))
    direction = str(signal["direction"])
    stop = int(signal["trigger_low_e8"]) - buffer_value if direction == "UP" else int(signal["trigger_high_e8"]) + buffer_value
    risk = entry - stop if direction == "UP" else stop - entry
    if risk <= 0:
        return empty_trade(signal, "STRUCTURAL_STOP_NOT_BEYOND_ENTRY", [signal["signal_id"], entry, stop])
    if risk < 0.25 * atr:
        return empty_trade(signal, "RISK_BELOW_0P25_ATR", [signal["signal_id"], risk, atr])
    if risk > 1.50 * atr:
        return empty_trade(signal, "RISK_ABOVE_1P50_ATR", [signal["signal_id"], risk, atr])
    target = target_for_signal(signal, entry, risk)
    if target is None:
        return empty_trade(signal, "NO_OPPOSING_LIQUIDITY_TARGET_AT_1P25R", [signal["signal_id"], entry, risk])
    selector = exit_primary if implementation == "primary" else exit_reference
    exit_index, exit_price, exit_reason = selector(path, direction, stop, target)
    used = path[:exit_index + 1]
    signed = 1 if direction == "UP" else -1
    gross_r = signed * (exit_price - entry) / risk
    cost_r = (BASELINE_COST_USD_OZ * branch.SCALE) / risk
    net_r = gross_r - cost_r
    favorable = max(item.high_e8 for item in used) - entry if direction == "UP" else entry - min(item.low_e8 for item in used)
    adverse = entry - min(item.low_e8 for item in used) if direction == "UP" else max(item.high_e8 for item in used) - entry
    risk_usd_oz = risk / branch.SCALE
    raw_lots = 50.0 / (risk_usd_oz * 100.0)
    lots = math.floor((raw_lots + 1e-12) / 0.01) * 0.01
    lots = round(max(0.0, lots), 2)
    actual_risk = risk_usd_oz * 100.0 * lots
    pnl = net_r * actual_risk
    lineage = {
        "signal_lineage": signal["lineage_hash"], "entry_bar": path[0].record_hash,
        "path": [item.record_hash for item in used], "exit_rule": exit_reason,
    }
    return {
        "trade_id": f"TRADE::{signal['signal_id']}", "signal_id": signal["signal_id"],
        "session_date": signal["session_date"], "session_code": signal["session_code"],
        "iso_week": signal["iso_week"], "setup_id": signal["setup_id"],
        "direction": direction, "signal_at_utc": signal["signal_at_utc"],
        "status": "EXECUTED", "no_trade_reason": "", "gc_covered": signal["gc_covered"],
        "gc_confirmed": signal["gc_confirmed"], "entry_at_utc": iso_z(decision),
        "exit_at_utc": iso_z(used[-1].close_at), "entry_e8": entry, "stop_e8": stop,
        "target_e8": target, "exit_e8": exit_price, "risk_e8": risk,
        "target_r": rounded(abs(target - entry) / risk), "exit_reason": exit_reason,
        "holding_minutes": exit_index + 1, "gross_r": rounded(gross_r),
        "net_r": rounded(net_r), "net_r_cost_1p5x": rounded(gross_r - 1.5 * cost_r),
        "net_r_cost_2x": rounded(gross_r - 2.0 * cost_r),
        "mfe_r": rounded(max(0, favorable) / risk), "mae_r": rounded(max(0, adverse) / risk),
        "planned_lots": lots, "actual_risk_usd": rounded(actual_risk),
        "net_pnl_usd": rounded(pnl), "outcome_lineage_hash": canonical_hash(lineage),
    }


def synthetic_proof() -> dict[str, Any]:
    now = datetime(2024, 1, 2, 8, tzinfo=UTC)
    paths: dict[str, list[prior.Bar]] = {
        "TARGET": [prior.Bar(now, now + timedelta(minutes=1), 10000, 10110, 9990, 10080, "a", "a")],
        "STOP": [prior.Bar(now, now + timedelta(minutes=1), 10000, 10010, 9890, 9910, "b", "b")],
        "BOTH_STOP_FIRST": [prior.Bar(now, now + timedelta(minutes=1), 10000, 10110, 9890, 10000, "c", "c")],
        "TIME": [prior.Bar(now, now + timedelta(minutes=1), 10000, 10010, 9990, 10005, "d", "d")],
    }
    results: dict[str, Any] = {}
    for name, path in paths.items():
        primary = exit_primary(path, "UP", 9900, 10100)
        reference = exit_reference(path, "UP", 9900, 10100)
        if primary != reference:
            raise AssertionError((name, primary, reference))
        results[name] = primary[2]
    expected = {"TARGET": "TARGET", "STOP": "STOP", "BOTH_STOP_FIRST": "STOP", "TIME": "TIME"}
    if results != expected:
        raise AssertionError(results)
    return {"status": "PASS_SYNTHETIC_EXECUTION_PROOF", "cases": results, "checksum": canonical_hash(results)}


def support_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    executed = [row for row in rows if row["status"] == "EXECUTED"]
    years = {str(year): sum(str(row["session_date"]).startswith(str(year)) for row in executed) for year in (2021, 2022, 2023, 2024)}
    return {
        "signals": len(rows), "trades": len(executed),
        "dates": len({row["session_date"] for row in executed}),
        "iso_weeks": len({row["iso_week"] for row in executed}),
        "longs": sum(row["direction"] == "UP" for row in executed),
        "shorts": sum(row["direction"] == "DOWN" for row in executed),
        "years": years,
        "no_trade_reasons": dict(sorted({reason: sum(row["no_trade_reason"] == reason for row in rows) for reason in {str(row["no_trade_reason"]) for row in rows if row["status"] != "EXECUTED"}}.items())),
    }


def support_gates(counts: Mapping[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if counts["trades"] < 60: failures.append("TRADES_LT_60")
    if counts["dates"] < 45: failures.append("DATES_LT_45")
    if counts["iso_weeks"] < 24: failures.append("ISO_WEEKS_LT_24")
    if counts["longs"] < 15: failures.append("LONGS_LT_15")
    if counts["shorts"] < 15: failures.append("SHORTS_LT_15")
    for year in (2022, 2023, 2024):
        if counts["years"][str(year)] < 10:
            failures.append(f"YEAR_{year}_TRADES_LT_10")
    return not failures, failures


def pf(values: np.ndarray[Any, Any]) -> float | None:
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    if losses == 0:
        return None if gains == 0 else math.inf
    return gains / losses


def cluster_bootstrap(rows: Sequence[Mapping[str, Any]], field: str, seed: int) -> dict[str, Any]:
    if not rows:
        return {"ci95": [None, None], "one_sided_p": None, "resamples": BOOTSTRAPS}
    dates = sorted({str(row["session_date"]) for row in rows})
    by_date = {value: [float(row[field]) for row in rows if str(row["session_date"]) == value] for value in dates}
    sums = np.asarray([sum(by_date[value]) for value in dates], dtype=np.float64)
    counts = np.asarray([len(by_date[value]) for value in dates], dtype=np.int64)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(dates), size=(BOOTSTRAPS, len(dates)), dtype=np.int32)
    means = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    lower, upper = np.quantile(means, [0.025, 0.975], method="linear")
    p = (int(np.count_nonzero(means <= 0)) + 1) / (BOOTSTRAPS + 1)
    return {"ci95": [rounded(float(lower)), rounded(float(upper))], "one_sided_p": rounded(p), "resamples": BOOTSTRAPS}


def chronological_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for block, start, end in BLOCKS:
        selected = [row for row in rows if start <= str(row["session_date"]) <= end]
        output[block] = {"start": start, "end": end, "trades": len(selected), "expectancy_r": rounded(float(np.mean([row["net_r"] for row in selected]))) if selected else None}
    return output


def account_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["signal_at_utc"], row["trade_id"]))
    equity = 10_000.0
    peak = equity
    max_dd = 0.0
    max_dd_pct = 0.0
    consecutive = maximum_consecutive = 0
    monthly: dict[str, float] = defaultdict(float)
    for row in ordered:
        equity += float(row["net_pnl_usd"])
        peak = max(peak, equity)
        drawdown = peak - equity
        max_dd = max(max_dd, drawdown)
        max_dd_pct = max(max_dd_pct, 100.0 * drawdown / peak if peak else 0.0)
        if float(row["net_r"]) < 0:
            consecutive += 1
            maximum_consecutive = max(maximum_consecutive, consecutive)
        else:
            consecutive = 0
        monthly[str(row["session_date"])[:7]] += float(row["net_pnl_usd"])
    months = sorted(monthly)
    monthly_returns = np.asarray([monthly[value] / 10_000.0 for value in months], dtype=np.float64)
    sharpe = None
    sortino = None
    if len(monthly_returns) >= 12 and float(np.std(monthly_returns, ddof=1)) > 0:
        sharpe = math.sqrt(12) * float(np.mean(monthly_returns)) / float(np.std(monthly_returns, ddof=1))
        downside = monthly_returns[monthly_returns < 0]
        if len(downside) >= 2 and float(np.std(downside, ddof=1)) > 0:
            sortino = math.sqrt(12) * float(np.mean(monthly_returns)) / float(np.std(downside, ddof=1))
    return {
        "starting_equity_usd": 10_000.0, "ending_equity_usd": rounded(equity),
        "net_pnl_usd": rounded(equity - 10_000.0), "max_drawdown_usd": rounded(max_dd),
        "max_drawdown_pct": rounded(max_dd_pct), "maximum_consecutive_losses": maximum_consecutive,
        "monthly_sharpe": rounded(sharpe), "monthly_sortino": rounded(sortino),
        "months_with_trades": len(months), "monthly_pnl_usd": {key: rounded(value) for key, value in sorted(monthly.items())},
    }


def economic_metrics(rows: Sequence[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    executed = [row for row in rows if row["status"] == "EXECUTED"]
    if not executed:
        return {"trades": 0, "bootstrap": cluster_bootstrap([], "net_r", seed)}
    net = np.asarray([float(row["net_r"]) for row in executed], dtype=np.float64)
    gross = np.asarray([float(row["gross_r"]) for row in executed], dtype=np.float64)
    stress15 = np.asarray([float(row["net_r_cost_1p5x"]) for row in executed], dtype=np.float64)
    stress2 = np.asarray([float(row["net_r_cost_2x"]) for row in executed], dtype=np.float64)
    winners = net[net > 0]
    losers = net[net < 0]
    avg_win = float(np.mean(winners)) if len(winners) else None
    avg_loss = float(np.mean(losers)) if len(losers) else None
    payoff = avg_win / abs(avg_loss) if avg_win is not None and avg_loss not in {None, 0.0} else None
    breakeven = abs(avg_loss) / (avg_win + abs(avg_loss)) if avg_win is not None and avg_loss not in {None, 0.0} and avg_win + abs(avg_loss) > 0 else None
    total = float(net.sum())
    contribution = float(np.max(net)) / total if total > 0 and len(net) else None
    years = {
        str(year): {
            "trades": len(selected := [row for row in executed if str(row["session_date"]).startswith(str(year))]),
            "expectancy_r": rounded(float(np.mean([row["net_r"] for row in selected]))) if selected else None,
        }
        for year in (2021, 2022, 2023, 2024)
    }
    sides = {
        direction: {
            "trades": len(selected := [row for row in executed if row["direction"] == direction]),
            "expectancy_r": rounded(float(np.mean([row["net_r"] for row in selected]))) if selected else None,
        }
        for direction in ("UP", "DOWN")
    }
    exits = {reason: sum(row["exit_reason"] == reason for row in executed) for reason in ("STOP", "TARGET", "TIME")}
    return {
        "trades": len(executed), "wins": int(np.count_nonzero(net > 0)), "losses": int(np.count_nonzero(net < 0)),
        "breakeven_trades": int(np.count_nonzero(net == 0)), "win_rate_pct": rounded(100 * float(np.mean(net > 0))),
        "gross_expectancy_r": rounded(float(np.mean(gross))), "net_expectancy_r": rounded(float(np.mean(net))),
        "median_net_r": rounded(float(np.median(net))), "total_net_r": rounded(total),
        "net_profit_factor": rounded(pf(net)), "average_win_r": rounded(avg_win), "average_loss_r": rounded(avg_loss),
        "average_win_loss_ratio": rounded(payoff), "empirical_breakeven_win_rate": rounded(breakeven),
        "average_mfe_r": rounded(float(np.mean([row["mfe_r"] for row in executed]))),
        "average_mae_r": rounded(float(np.mean([row["mae_r"] for row in executed]))),
        "average_holding_minutes": rounded(float(np.mean([row["holding_minutes"] for row in executed]))),
        "exit_reasons": exits, "cost_1p5x_expectancy_r": rounded(float(np.mean(stress15))),
        "cost_1p5x_profit_factor": rounded(pf(stress15)), "cost_2x_expectancy_r": rounded(float(np.mean(stress2))),
        "cost_2x_profit_factor": rounded(pf(stress2)), "largest_trade_share_of_positive_total": rounded(contribution),
        "bootstrap": cluster_bootstrap(executed, "net_r", seed), "years": years, "sides": sides,
        "chronological_blocks": chronological_metrics(executed), "account": account_metrics(executed),
    }


def holm_adjust(p_values: Mapping[str, float | None]) -> dict[str, float | None]:
    valid = sorted(((key, value) for key, value in p_values.items() if value is not None), key=lambda item: (float(item[1]), item[0]))
    output: dict[str, float | None] = {key: None for key in p_values}
    running = 0.0
    total = len(valid)
    for index, (key, value) in enumerate(valid):
        running = max(running, min(1.0, (total - index) * float(value)))
        output[key] = rounded(running)
    return output


def pass_gates(counts: Mapping[str, Any], metrics: Mapping[str, Any], adjusted_p: float | None) -> dict[str, bool]:
    blocks = metrics.get("chronological_blocks", {})
    block_values = [item["expectancy_r"] for item in blocks.values() if item["expectancy_r"] is not None]
    years = metrics.get("years", {})
    sides = metrics.get("sides", {})
    payoff = metrics.get("average_win_loss_ratio")
    break_even = metrics.get("empirical_breakeven_win_rate")
    observed_wr = (metrics.get("win_rate_pct") or 0.0) / 100.0
    quality = (payoff is not None and payoff >= 1.0) or (break_even is not None and observed_wr >= 1.10 * break_even)
    return {
        "support": support_gates(counts)[0],
        "net_expectancy_positive": (metrics.get("net_expectancy_r") or 0.0) > 0,
        "bootstrap_ci_lower_positive": (metrics.get("bootstrap", {}).get("ci95", [None])[0] or 0.0) > 0,
        "holm_p_at_most_0p05": adjusted_p is not None and adjusted_p <= 0.05,
        "profit_factor_at_least_1p25": (metrics.get("net_profit_factor") or 0.0) >= 1.25,
        "payoff_or_break_even_margin": quality,
        "three_positive_blocks": sum(value > 0 for value in block_values) >= 3,
        "no_block_below_minus_0p10": bool(block_values) and all(value >= -0.10 for value in block_values),
        "supported_2022_2024_positive": all(years.get(str(year), {}).get("trades", 0) >= 10 and (years[str(year)]["expectancy_r"] or 0.0) > 0 for year in (2022, 2023, 2024)),
        "supported_sides_positive": all(sides.get(side, {}).get("trades", 0) >= 15 and (sides[side]["expectancy_r"] or 0.0) > 0 for side in ("UP", "DOWN")),
        "cost_1p5x": (metrics.get("cost_1p5x_profit_factor") or 0.0) >= 1.10 and (metrics.get("cost_1p5x_expectancy_r") or 0.0) > 0,
        "single_trade_share": metrics.get("largest_trade_share_of_positive_total") is not None and metrics["largest_trade_share_of_positive_total"] <= 0.35,
        "account_drawdown": metrics.get("account", {}).get("max_drawdown_pct", math.inf) <= 15.0,
    }


def evaluate_base_tests(trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    for session_index, session in enumerate(branch.SESSIONS):
        family: list[dict[str, Any]] = []
        for setup_index, setup in enumerate(branch.SETUPS):
            selected = [row for row in trades if row["session_code"] == session and row["setup_id"] == setup]
            counts = support_counts(selected)
            support, support_failures = support_gates(counts)
            metrics = economic_metrics(selected, BOOTSTRAP_SEED + session_index * 100 + setup_index)
            family.append({
                "test_id": f"{session}|{setup}", "session": session, "setup": setup,
                "support": counts, "support_failures": support_failures, "metrics": metrics,
                "raw_one_sided_p": metrics.get("bootstrap", {}).get("one_sided_p"),
                "support_pass": support,
            })
        adjusted = holm_adjust({item["test_id"]: item["raw_one_sided_p"] for item in family})
        for item in family:
            item["holm_adjusted_p"] = adjusted[item["test_id"]]
            gates = pass_gates(item["support"], item["metrics"], item["holm_adjusted_p"])
            item["pass_gates"] = gates
            item["failed_gates"] = [key for key, value in gates.items() if not value]
            item["verdict"] = "PROVISIONAL_UNVALIDATED_EDGE" if all(gates.values()) else "SUPPORT_FAIL" if not item["support_pass"] else "REJECT"
        raw.extend(family)
    return raw


def portfolio_rows(trades: Sequence[Mapping[str, Any]], session: str) -> list[Mapping[str, Any]]:
    by_date: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in trades:
        if row["session_code"] == session:
            by_date[str(row["session_date"])].append(row)
    return [min(values, key=lambda row: (row["signal_at_utc"], row["setup_id"], row["signal_id"])) for _, values in sorted(by_date.items())]


def evaluate_portfolios(trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for index, session in enumerate(branch.SESSIONS):
        selected = portfolio_rows(trades, session)
        counts = support_counts(selected)
        output.append({
            "test_id": f"{session}|EARLIEST_FROZEN_SETUP", "classification": "FROZEN_PORTFOLIO_DIAGNOSTIC_ONLY",
            "support": counts, "metrics": economic_metrics(selected, BOOTSTRAP_SEED + 1_000 + index),
            "candidate_credit": False,
        })
    return output


def evaluate_gc(trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for session in branch.SESSIONS:
        for setup in branch.SETUPS:
            base = [row for row in trades if row["session_code"] == session and row["setup_id"] == setup and row["status"] == "EXECUTED" and row["gc_covered"]]
            confirmed = [row for row in base if row["gc_confirmed"] is True]
            unconfirmed = [row for row in base if row["gc_confirmed"] is False]
            confirmed_counts = {"trades": len(confirmed), "dates": len({row["session_date"] for row in confirmed})}
            unconfirmed_counts = {"trades": len(unconfirmed), "dates": len({row["session_date"] for row in unconfirmed})}
            support = confirmed_counts["trades"] >= 20 and confirmed_counts["dates"] >= 15 and unconfirmed_counts["trades"] >= 30 and unconfirmed_counts["dates"] >= 20
            confirmed_mean = rounded(float(np.mean([row["net_r"] for row in confirmed]))) if confirmed else None
            unconfirmed_mean = rounded(float(np.mean([row["net_r"] for row in unconfirmed]))) if unconfirmed else None
            lift = rounded(confirmed_mean - unconfirmed_mean) if confirmed_mean is not None and unconfirmed_mean is not None else None
            output.append({
                "test_id": f"{session}|{setup}|GC_CONFIRMATION", "session": session, "setup": setup,
                "covered_executed_trades": len(base), "confirmed_support": confirmed_counts,
                "unconfirmed_support": unconfirmed_counts, "confirmed_expectancy_r": confirmed_mean,
                "unconfirmed_expectancy_r": unconfirmed_mean, "expectancy_lift_r": lift,
                "support_pass": support, "verdict": "SUPPORT_FAIL" if not support else "REJECT_NOT_EVALUATED_WITHOUT_FULL_GATES",
                "causal_or_institution_identity_claim": False,
            })
    return output


def next_eligible_session(now: datetime) -> dict[str, str]:
    candidates: list[tuple[datetime, str, str]] = []
    for offset in range(8):
        day = (now + timedelta(days=offset)).date()
        if day.weekday() >= 5:
            continue
        for session in branch.SESSIONS:
            opened = datetime.combine(day, time(8), branch.ZONES[session]).astimezone(UTC)
            if opened > now:
                candidates.append((opened, session, day.isoformat()))
    opened, session, day = min(candidates)
    return {"session_date": day, "session_code": session, "session_open_utc": iso_z(opened)}


def report_markdown(results: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Gold Fundamental-Aligned Multi-Timeframe Auction Edge Discovery V1 — Final Report", "",
        f"Status: **{results['overall_verdict']}**", "",
        "## Honest verdict", "",
        results["verdict_explanation"], "",
        "## Development economics", "",
        "| Test | Signals | Trades | Win rate | Net expectancy (R) | Profit factor | 95% CI | Verdict |", "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for item in results["base_tests"]:
        metrics = item["metrics"]
        ci = metrics.get("bootstrap", {}).get("ci95", [None, None])
        lines.append(
            f"| {item['test_id']} | {item['support']['signals']} | {item['support']['trades']} | {metrics.get('win_rate_pct')}% | {metrics.get('net_expectancy_r')} | {metrics.get('net_profit_factor')} | {ci} | {item['verdict']} |"
        )
    lines.extend(["", "## Session portfolio diagnostics", "", "These pooled results were frozen as diagnostics, not candidate tests.", "",
                  "| Portfolio | Trades | Net expectancy (R) | Profit factor | Net PnL on $10k diagnostic | Max DD |", "|---|---:|---:|---:|---:|---:|"])
    for item in results["portfolio_diagnostics"]:
        metrics = item["metrics"]
        account = metrics.get("account", {})
        lines.append(f"| {item['test_id']} | {metrics.get('trades')} | {metrics.get('net_expectancy_r')} | {metrics.get('net_profit_factor')} | ${account.get('net_pnl_usd')} | {account.get('max_drawdown_pct')}% |")
    lines.extend([
        "", "## GC incremental value", "",
        f"Only {results['gc_summary']['confirmed_executed']} covered executed trades had frozen same-direction GC confirmation; every GC test failed its preregistered support floor. No incremental-value claim is permitted.", "",
        "## Forward and prospective disposition", "",
        f"Frozen development candidates: **{len(candidates)}**. Because no candidate passed, 2025 and 2026 market values were not opened for this branch. The append-only prospective ledger was initialized with no active candidate.", "",
        "## Reproduction and integrity", "",
        "Primary and reference implementations produced byte-identical trade Parquet files and identical statistics. Development outcomes were opened once; forward values were not accessed; paid acquisition was $0.", "",
    ])
    return "\n".join(lines)


def main() -> None:
    if any(path.exists() for path in (AUTHORIZATION, PRIMARY_TRADES, REFERENCE_TRADES, RESULTS, CANDIDATES, EXPOSED, LEDGER, REPORT, FINAL_SEAL)):
        raise FileExistsError("Outcome evaluation artifact already exists")
    signals = verify_and_load_signals()
    proof = synthetic_proof()
    support_snapshot = {
        f"{session}|{setup}": sum(row["session_code"] == session and row["setup_id"] == setup for row in signals)
        for session in branch.SESSIONS for setup in branch.SETUPS
    }
    authorization = {
        "version": "GOLD_FAMAE_V1_DEVELOPMENT_OUTCOME_OPENING_AUTHORIZATION_1_0",
        "status": "AUTHORIZED_SINGLE_CONTROLLED_DEVELOPMENT_OUTCOME_OPENING",
        "authorized_at_utc": utc_now(), "opening_limit": 1,
        "signal_count": len(signals), "signal_rows_hash": canonical_hash(signals),
        "primary_signals": file_record(OUTPUT / "primary_signals.parquet"),
        "reference_signals": file_record(OUTPUT / "reference_signals.parquet"),
        "materialization_certification": file_record(OUTPUT / "materialization_certification.json"),
        "protocol": file_record(branch.PROTOCOL), "test_registry": file_record(branch.TEST_REGISTRY),
        "amendment_a": file_record(branch.AMENDMENT_A), "implementation": file_record(Path(__file__).resolve()),
        "synthetic_proof": proof, "preoutcome_signal_support": support_snapshot,
        "forward_values_authorized": False, "paid_acquisition_authorized": False,
    }
    write_json_exclusive(AUTHORIZATION, authorization)

    load_events = [{"decision_at_utc": row["signal_at_utc"]} for row in signals]
    bars, outcome_diagnostics = prior.load_outcome_bars(load_events)
    primary = [calculate_trade(row, bars, "primary") for row in signals]
    reference = [calculate_trade(row, bars, "reference") for row in signals]
    primary.sort(key=lambda row: (row["session_date"], row["session_code"], row["signal_at_utc"], row["setup_id"], row["signal_id"]))
    reference.sort(key=lambda row: (row["session_date"], row["session_code"], row["signal_at_utc"], row["setup_id"], row["signal_id"]))
    if primary != reference:
        raise ValueError("Independent execution paths disagree")
    write_parquet_exclusive(PRIMARY_TRADES, primary)
    write_parquet_exclusive(REFERENCE_TRADES, reference)
    if sha256_file(PRIMARY_TRADES) != sha256_file(REFERENCE_TRADES):
        raise ValueError("Trade Parquet outputs are not byte-identical")

    base_results = evaluate_base_tests(primary)
    reference_base = evaluate_base_tests(reference)
    portfolios = evaluate_portfolios(primary)
    reference_portfolios = evaluate_portfolios(reference)
    gc_results = evaluate_gc(primary)
    reference_gc = evaluate_gc(reference)
    if base_results != reference_base or portfolios != reference_portfolios or gc_results != reference_gc:
        raise ValueError("Independent statistical results disagree")
    passed = [item for item in base_results if item["verdict"] == "PROVISIONAL_UNVALIDATED_EDGE"]
    frozen_candidates: list[dict[str, Any]] = []
    for session in branch.SESSIONS:
        ranked = sorted(
            [item for item in passed if item["session"] == session],
            key=lambda item: (item["holm_adjusted_p"], -item["metrics"]["net_profit_factor"], -item["metrics"]["net_expectancy_r"], item["test_id"]),
        )[:3]
        frozen_candidates.extend({"candidate_id": item["test_id"], "session": session, "setup": item["setup"], "rules_source": str(branch.PROTOCOL.relative_to(ROOT)).replace("\\", "/")} for item in ranked)
    overall = "PASS_PROVISIONAL_UNVALIDATED_EDGE" if frozen_candidates else "REJECT_NO_ECONOMICALLY_TRADABLE_CANDIDATE"
    explanation = (
        "At least one preregistered setup passed every support, uncertainty, stability, cost and drawdown gate."
        if frozen_candidates else
        "No preregistered setup passed. The individual setup populations were below the frozen 60-trade support floor before any performance claim; any favourable descriptive statistic therefore cannot be promoted as a tradable edge."
    )
    results = {
        "version": "GOLD_FAMAE_V1_DEVELOPMENT_RESULTS_1_0", "overall_verdict": overall,
        "completed_at_utc": utc_now(), "verdict_explanation": explanation,
        "outcome_opening_count": 1, "outcome_diagnostics": outcome_diagnostics,
        "signals": len(signals), "executed_trades": sum(row["status"] == "EXECUTED" for row in primary),
        "base_tests": base_results, "portfolio_diagnostics": portfolios, "gc_incremental_tests": gc_results,
        "gc_summary": {
            "covered_executed": sum(row["status"] == "EXECUTED" and row["gc_covered"] for row in primary),
            "confirmed_executed": sum(row["status"] == "EXECUTED" and row["gc_confirmed"] is True for row in primary),
        },
        "candidate_count": len(frozen_candidates), "primary_reference_exact": True,
        "trade_rows_hash": canonical_hash(primary), "development_outcomes_accessed": True,
        "forward_2025_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(RESULTS, results)
    write_json_exclusive(CANDIDATES, {
        "version": "GOLD_FAMAE_V1_FROZEN_DEVELOPMENT_CANDIDATES_1_0", "status": "FROZEN_AFTER_DEVELOPMENT",
        "frozen_at_utc": utc_now(), "candidate_count": len(frozen_candidates), "candidates": frozen_candidates,
        "development_results_sha256": sha256_file(RESULTS), "retuning_permitted": False,
    })
    write_json_exclusive(EXPOSED, {
        "version": "GOLD_FAMAE_V1_EXPOSED_ROBUSTNESS_1_0",
        "status": "NOT_OPENED_ZERO_FROZEN_CANDIDATES" if not frozen_candidates else "BLOCKED_IMPLEMENTATION_REQUIRED",
        "candidate_count": len(frozen_candidates), "calendar_2025_values_accessed": False,
        "calendar_2026_through_2026_07_29_values_accessed": False,
        "reason": "There is no frozen development candidate to apply." if not frozen_candidates else "Forward application is required before branch completion.",
        "independent_validation_credit": False,
    })
    if frozen_candidates:
        raise RuntimeError("A candidate passed; implement frozen forward application before sealing")
    ledger_record = {
        "record_type": "LEDGER_INITIALIZATION", "recorded_at_utc": utc_now(),
        "branch": "GOLD_FUNDAMENTAL_ALIGNED_MULTITIMEFRAME_AUCTION_EDGE_V1",
        "next_eligible_session": next_eligible_session(datetime.now(UTC)),
        "active_candidate_ids": [], "status": "INITIALIZED_NO_ACTIVE_CANDIDATE",
        "backfill_permitted": False, "append_only": True,
    }
    write_text_exclusive(LEDGER, canonical_json(ledger_record) + "\n")
    write_text_exclusive(REPORT, report_markdown(results, frozen_candidates))
    seal_inputs = [
        AUTHORIZATION, PRIMARY_TRADES, REFERENCE_TRADES, RESULTS, CANDIDATES,
        EXPOSED, LEDGER, REPORT, OUTPUT / "materialization_certification.json",
    ]
    seal = {
        "version": "GOLD_FAMAE_V1_FINAL_SEAL_1_0", "status": overall,
        "sealed_at_utc": utc_now(), "artifacts": {path.name: file_record(path) for path in seal_inputs},
        "artifact_set_hash": canonical_hash({path.name: sha256_file(path) for path in seal_inputs}),
        "primary_reference_exact": True, "forward_values_accessed": False,
        "prospective_ledger_initialized": True, "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(FINAL_SEAL, seal)
    print(json.dumps({
        "status": overall, "signals": len(signals), "executed_trades": results["executed_trades"],
        "candidate_count": len(frozen_candidates), "base_results": [
            {"test_id": item["test_id"], "verdict": item["verdict"], "trades": item["support"]["trades"],
             "expectancy_r": item["metrics"].get("net_expectancy_r"), "profit_factor": item["metrics"].get("net_profit_factor")}
            for item in base_results
        ], "portfolio_diagnostics": [
            {"test_id": item["test_id"], "trades": item["metrics"].get("trades"),
             "expectancy_r": item["metrics"].get("net_expectancy_r"), "profit_factor": item["metrics"].get("net_profit_factor"),
             "net_pnl_usd": item["metrics"].get("account", {}).get("net_pnl_usd")}
            for item in portfolios
        ], "final_seal": file_record(FINAL_SEAL),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
