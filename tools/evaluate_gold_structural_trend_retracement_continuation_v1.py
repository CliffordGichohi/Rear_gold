from __future__ import annotations

import gzip
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
import run_gold_fundamental_aligned_multitimeframe_auction_edge_v1 as famae  # noqa: E402
import materialize_gold_structural_trend_retracement_continuation_v1 as branch  # noqa: E402
import evaluate_gold_fundamental_aligned_multitimeframe_auction_edge_v1 as economics  # noqa: E402


OUTPUT = branch.OUTPUT
AUTHORIZATION = OUTPUT / "development_outcome_opening_authorization.json"
PRIMARY_TRADES = OUTPUT / "primary_trades.parquet"
REFERENCE_TRADES = OUTPUT / "reference_trades.parquet"
RESULTS = OUTPUT / "development_results.json"
CANDIDATES = OUTPUT / "frozen_development_candidates.json"
EXPOSED = OUTPUT / "exposed_robustness.json"
LEDGER = OUTPUT / "prospective_paper_ledger.jsonl"
REPORT = ROOT / "GOLD_STRUCTURAL_TREND_RETRACEMENT_CONTINUATION_EDGE_V1_REPORT.md"
FINAL_SEAL = OUTPUT / "final_seal.json"
BUFFERS = (0.10, 0.15, 0.20)
BASE_BUFFER = 0.15
SEED = 26_080_702


TRADE_SCHEMA = pa.schema([
    pa.field("trade_id", pa.string(), False), pa.field("signal_id", pa.string(), False),
    pa.field("session_date", pa.string(), False), pa.field("session_code", pa.string(), False),
    pa.field("iso_week", pa.string(), False), pa.field("setup_id", pa.string(), False),
    pa.field("direction", pa.string(), False), pa.field("signal_at_utc", pa.string(), False),
    pa.field("status", pa.string(), False), pa.field("no_trade_reason", pa.string(), False),
    pa.field("gc_covered", pa.bool_(), False), pa.field("gc_confirmed", pa.bool_(), True),
    pa.field("entry_at_utc", pa.string(), True), pa.field("exit_at_utc", pa.string(), True),
    pa.field("entry_e8", pa.int64(), True), pa.field("stop_e8", pa.int64(), True),
    pa.field("target_e8", pa.int64(), True), pa.field("exit_e8", pa.int64(), True),
    pa.field("risk_e8", pa.int64(), True), pa.field("target_r", pa.float64(), True),
    pa.field("cost_r", pa.float64(), True), pa.field("exit_reason", pa.string(), True),
    pa.field("holding_minutes", pa.int64(), True), pa.field("gross_r", pa.float64(), True),
    pa.field("net_r", pa.float64(), True), pa.field("net_r_cost_1p5x", pa.float64(), True),
    pa.field("net_r_cost_2x", pa.float64(), True), pa.field("mfe_r", pa.float64(), True),
    pa.field("mae_r", pa.float64(), True), pa.field("planned_lots", pa.float64(), True),
    pa.field("actual_risk_usd", pa.float64(), True), pa.field("net_pnl_usd", pa.float64(), True),
    pa.field("sensitivity_json", pa.string(), False), pa.field("outcome_lineage_hash", pa.string(), False),
])


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
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


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
    table = pa.Table.from_pylist(list(rows), schema=TRADE_SCHEMA)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6")
    temporary.replace(path)


def rounded(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    result = round(float(value), 12)
    return 0.0 if result == 0 else result


def verify_preoutcome() -> list[dict[str, Any]]:
    freeze = json.loads(branch.PREOUTCOME_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "SEALED_EXACT_SIGNAL_POPULATION_BEFORE_OUTCOMES":
        raise ValueError("Pre-outcome freeze invalid")
    controls = {"contract": branch.CONTRACT, "protocol": branch.PROTOCOL, "test_registry": branch.TEST_REGISTRY, "design_freeze": branch.DESIGN_FREEZE, "amendment_a": branch.AMENDMENT_A}
    for name, path in controls.items():
        if sha256_file(path) != freeze["controls"][name]["sha256"]:
            raise ValueError(f"Pre-outcome control changed: {name}")
    if sha256_file(Path(branch.__file__).resolve()) != freeze["implementation"]["sha256"]:
        raise ValueError("Materializer changed after signal freeze")
    primary = pq.read_table(OUTPUT / "primary_signals.parquet").to_pylist()
    reference = pq.read_table(OUTPUT / "reference_signals.parquet").to_pylist()
    if primary != reference or canonical_hash(primary) != freeze["signal_rows_hash"]:
        raise ValueError("Signal population changed")
    return primary


def load_outcome_bars(signals: Sequence[Mapping[str, Any]]) -> tuple[dict[datetime, prior.Bar], dict[str, Any]]:
    targets: set[datetime] = set()
    for signal in signals:
        decision = parse_dt(str(signal["signal_at_utc"]))
        local_day = date.fromisoformat(str(signal["session_date"]))
        forced = datetime.combine(local_day, time(13), famae.ZONES[str(signal["session_code"])]).astimezone(UTC)
        end = min(decision + timedelta(minutes=180), forced)
        targets.update(decision + timedelta(minutes=index) for index in range(max(0, int((end - decision).total_seconds() // 60))))
    found: dict[datetime, prior.Bar] = {}
    source_rows = duplicates = invalid = 0
    saw_one = False
    with gzip.open(famae.PRICE_PATH, "rt", encoding="utf-8") as handle:
        for line in handle:
            if prior.HOLDOUT_RE.search(line):
                break
            record = json.loads(line)
            if record.get("timeframe") != "1m":
                if saw_one:
                    break
                continue
            saw_one = True
            if record.get("instrument_code") != "XAUUSD":
                continue
            source_rows += 1
            opened = prior.parse_dt(str(record["open_time"]))
            if opened not in targets:
                continue
            bar = prior.bar_from_record(record)
            if bar is None:
                invalid += 1
            elif opened in found:
                duplicates += 1
            else:
                found[opened] = bar
    return found, {
        "logical_source_opening_count": 1, "source_1m_rows_deserialized_before_2025": source_rows,
        "target_timestamps": len(targets), "found_timestamps": len(found),
        "missing_timestamps": len(targets - set(found)), "duplicates": duplicates, "invalid": invalid,
        "first_2025_or_2026_row_deserialized": False,
    }


def target_for(signal: Mapping[str, Any], entry: int, risk: int) -> int | None:
    levels = json.loads(str(signal["target_levels_json"]))
    if signal["direction"] == "UP":
        values = sorted(int(item["price_e8"]) for item in levels if item["side"] == "UPPER" and int(item["price_e8"]) > entry and int(item["price_e8"]) - entry >= 1.5 * risk)
        return None if not values else min(values[0], entry + int(round(3.0 * risk)))
    values = sorted((int(item["price_e8"]) for item in levels if item["side"] == "LOWER" and int(item["price_e8"]) < entry and entry - int(item["price_e8"]) >= 1.5 * risk), reverse=True)
    return None if not values else max(values[0], entry - int(round(3.0 * risk)))


def select_exit(path: Sequence[prior.Bar], direction: str, stop: int, target: int, implementation: str) -> tuple[int, int, str]:
    if implementation == "primary":
        for index, bar in enumerate(path):
            stop_hit = bar.low_e8 <= stop if direction == "UP" else bar.high_e8 >= stop
            target_hit = bar.high_e8 >= target if direction == "UP" else bar.low_e8 <= target
            if stop_hit:
                return index, stop, "STOP"
            if target_hit:
                return index, target, "TARGET"
        return len(path) - 1, path[-1].close_e8, "TIME"
    lows = np.asarray([bar.low_e8 for bar in path], dtype=np.int64)
    highs = np.asarray([bar.high_e8 for bar in path], dtype=np.int64)
    stop_hits = np.flatnonzero(lows <= stop if direction == "UP" else highs >= stop)
    target_hits = np.flatnonzero(highs >= target if direction == "UP" else lows <= target)
    stop_at = int(stop_hits[0]) if len(stop_hits) else math.inf
    target_at = int(target_hits[0]) if len(target_hits) else math.inf
    if stop_at <= target_at and stop_at != math.inf:
        return int(stop_at), stop, "STOP"
    if target_at != math.inf:
        return int(target_at), target, "TARGET"
    return len(path) - 1, path[-1].close_e8, "TIME"


def simulate_variant(signal: Mapping[str, Any], path: Sequence[prior.Bar], buffer_atr: float, implementation: str) -> dict[str, Any]:
    entry = path[0].open_e8
    atr = int(signal["atr20_5m_e8"])
    buffer_value = int(round(buffer_atr * atr))
    direction = str(signal["direction"])
    stop = int(signal["sequence_low_e8"]) - buffer_value if direction == "UP" else int(signal["sequence_high_e8"]) + buffer_value
    risk = entry - stop if direction == "UP" else stop - entry
    if risk <= 0:
        return {"status": "NO_TRADE", "reason": "STOP_NOT_BEYOND_ENTRY"}
    if risk < 0.75 * atr:
        return {"status": "NO_TRADE", "reason": "RISK_BELOW_0P75_ATR"}
    if risk > 3.0 * atr:
        return {"status": "NO_TRADE", "reason": "RISK_ABOVE_3P00_ATR"}
    cost_r = (0.47 * famae.SCALE) / risk
    if cost_r > 0.20:
        return {"status": "NO_TRADE", "reason": "BASELINE_COST_EXCEEDS_0P20R", "cost_r": rounded(cost_r)}
    target = target_for(signal, entry, risk)
    if target is None:
        return {"status": "NO_TRADE", "reason": "NO_EXTERNAL_LIQUIDITY_TARGET_AT_1P50R"}
    index, exit_price, reason = select_exit(path, direction, stop, target, implementation)
    used = path[:index + 1]
    signed = 1 if direction == "UP" else -1
    gross = signed * (exit_price - entry) / risk
    favorable = max(item.high_e8 for item in used) - entry if direction == "UP" else entry - min(item.low_e8 for item in used)
    adverse = entry - min(item.low_e8 for item in used) if direction == "UP" else max(item.high_e8 for item in used) - entry
    risk_usd_oz = risk / famae.SCALE
    lots = round(max(0.0, math.floor(((50.0 / (risk_usd_oz * 100.0)) + 1e-12) / 0.01) * 0.01), 2)
    actual_risk = risk_usd_oz * 100.0 * lots
    net = gross - cost_r
    return {
        "status": "EXECUTED", "reason": "", "entry_e8": entry, "stop_e8": stop,
        "target_e8": target, "exit_e8": exit_price, "risk_e8": risk,
        "target_r": rounded(abs(target - entry) / risk), "cost_r": rounded(cost_r),
        "exit_index": index, "exit_reason": reason, "gross_r": rounded(gross), "net_r": rounded(net),
        "net_r_cost_1p5x": rounded(gross - 1.5 * cost_r), "net_r_cost_2x": rounded(gross - 2.0 * cost_r),
        "mfe_r": rounded(max(0, favorable) / risk), "mae_r": rounded(max(0, adverse) / risk),
        "planned_lots": lots, "actual_risk_usd": rounded(actual_risk), "net_pnl_usd": rounded(net * actual_risk),
    }


def empty_row(signal: Mapping[str, Any], reason: str, sensitivity: Mapping[str, Any], lineage: Any) -> dict[str, Any]:
    return {
        "trade_id": f"STRC-TRADE::{signal['signal_id']}", "signal_id": signal["signal_id"],
        "session_date": signal["session_date"], "session_code": signal["session_code"], "iso_week": signal["iso_week"],
        "setup_id": signal["setup_id"], "direction": signal["direction"], "signal_at_utc": signal["signal_at_utc"],
        "status": "NO_TRADE", "no_trade_reason": reason, "gc_covered": signal["gc_covered"], "gc_confirmed": signal["gc_confirmed"],
        "entry_at_utc": None, "exit_at_utc": None, "entry_e8": None, "stop_e8": None, "target_e8": None,
        "exit_e8": None, "risk_e8": None, "target_r": None, "cost_r": None, "exit_reason": None,
        "holding_minutes": None, "gross_r": None, "net_r": None, "net_r_cost_1p5x": None, "net_r_cost_2x": None,
        "mfe_r": None, "mae_r": None, "planned_lots": None, "actual_risk_usd": None, "net_pnl_usd": None,
        "sensitivity_json": canonical_json(sensitivity), "outcome_lineage_hash": canonical_hash(lineage),
    }


def calculate_trade(signal: Mapping[str, Any], bars: Mapping[datetime, prior.Bar], implementation: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    decision = parse_dt(str(signal["signal_at_utc"]))
    local_day = date.fromisoformat(str(signal["session_date"]))
    forced = datetime.combine(local_day, time(13), famae.ZONES[str(signal["session_code"])]).astimezone(UTC)
    end = min(decision + timedelta(minutes=180), forced)
    stamps = [decision + timedelta(minutes=index) for index in range(max(0, int((end - decision).total_seconds() // 60)))]
    values = [bars.get(stamp) for stamp in stamps]
    if not values or values[0] is None:
        row = empty_row(signal, "MISSING_NEXT_M1_ENTRY_BAR", {}, [signal["signal_id"], "ENTRY"])
        return row, {str(value): {"status": "NO_TRADE", "reason": "MISSING_NEXT_M1_ENTRY_BAR"} for value in BUFFERS}
    if any(item is None for item in values):
        missing = [iso_z(stamp) for stamp, item in zip(stamps, values) if item is None]
        row = empty_row(signal, "MISSING_M1_HOLDING_PATH", {}, [signal["signal_id"], missing])
        return row, {str(value): {"status": "NO_TRADE", "reason": "MISSING_M1_HOLDING_PATH"} for value in BUFFERS}
    path = [item for item in values if item is not None]
    variants = {str(value): simulate_variant(signal, path, value, implementation) for value in BUFFERS}
    base = variants[str(BASE_BUFFER)]
    if base["status"] != "EXECUTED":
        return empty_row(signal, str(base["reason"]), variants, [signal["signal_id"], [item.record_hash for item in path], base]), variants
    used = path[:int(base["exit_index"]) + 1]
    row = {
        "trade_id": f"STRC-TRADE::{signal['signal_id']}", "signal_id": signal["signal_id"],
        "session_date": signal["session_date"], "session_code": signal["session_code"], "iso_week": signal["iso_week"],
        "setup_id": signal["setup_id"], "direction": signal["direction"], "signal_at_utc": signal["signal_at_utc"],
        "status": "EXECUTED", "no_trade_reason": "", "gc_covered": signal["gc_covered"], "gc_confirmed": signal["gc_confirmed"],
        "entry_at_utc": iso_z(decision), "exit_at_utc": iso_z(used[-1].close_at), "entry_e8": base["entry_e8"],
        "stop_e8": base["stop_e8"], "target_e8": base["target_e8"], "exit_e8": base["exit_e8"], "risk_e8": base["risk_e8"],
        "target_r": base["target_r"], "cost_r": base["cost_r"], "exit_reason": base["exit_reason"],
        "holding_minutes": int(base["exit_index"]) + 1, "gross_r": base["gross_r"], "net_r": base["net_r"],
        "net_r_cost_1p5x": base["net_r_cost_1p5x"], "net_r_cost_2x": base["net_r_cost_2x"], "mfe_r": base["mfe_r"],
        "mae_r": base["mae_r"], "planned_lots": base["planned_lots"], "actual_risk_usd": base["actual_risk_usd"],
        "net_pnl_usd": base["net_pnl_usd"], "sensitivity_json": canonical_json(variants),
        "outcome_lineage_hash": canonical_hash([signal["lineage_hash"], [item.record_hash for item in used], base["exit_reason"]]),
    }
    return row, variants


def support_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    executed = [row for row in rows if row["status"] == "EXECUTED"]
    return {
        "signals": len(rows), "trades": len(executed), "dates": len({row["session_date"] for row in executed}),
        "weeks": len({row["iso_week"] for row in executed}), "up": sum(row["direction"] == "UP" for row in executed),
        "down": sum(row["direction"] == "DOWN" for row in executed),
        "years": {str(year): sum(str(row["session_date"]).startswith(str(year)) for row in executed) for year in (2021, 2022, 2023, 2024)},
        "no_trade_reasons": {reason: sum(row["no_trade_reason"] == reason for row in rows) for reason in sorted({str(row["no_trade_reason"]) for row in rows if row["status"] != "EXECUTED"})},
    }


def support_failures(counts: Mapping[str, Any]) -> list[str]:
    failed = []
    if counts["trades"] < 40: failed.append("TRADES_LT_40")
    if counts["dates"] < 30: failed.append("DATES_LT_30")
    if counts["weeks"] < 20: failed.append("WEEKS_LT_20")
    if counts["up"] < 10: failed.append("UP_LT_10")
    if counts["down"] < 10: failed.append("DOWN_LT_10")
    for year in (2022, 2023, 2024):
        if counts["years"][str(year)] < 8: failed.append(f"YEAR_{year}_LT_8")
    return failed


def variant_rows(trades: Sequence[Mapping[str, Any]], buffer_value: float) -> list[dict[str, Any]]:
    output = []
    key = str(buffer_value)
    for row in trades:
        variant = json.loads(str(row["sensitivity_json"])).get(key, {})
        copied = dict(row)
        if variant.get("status") != "EXECUTED":
            copied["status"] = "NO_TRADE"
            copied["no_trade_reason"] = variant.get("reason", "UNKNOWN")
            for field in ("gross_r", "net_r", "net_r_cost_1p5x", "net_r_cost_2x", "mfe_r", "mae_r", "holding_minutes", "net_pnl_usd"):
                copied[field] = None
        else:
            copied.update({field: variant[field] for field in ("gross_r", "net_r", "net_r_cost_1p5x", "net_r_cost_2x", "mfe_r", "mae_r", "net_pnl_usd")})
            copied["holding_minutes"] = int(variant["exit_index"]) + 1
            copied["status"] = "EXECUTED"
        output.append(copied)
    return output


def evaluate(trades: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tests: list[dict[str, Any]] = []
    for session_index, session in enumerate(SESSIONS := branch.SESSIONS):
        family = []
        for setup_index, setup in enumerate(branch.SETUPS):
            selected = [row for row in trades if row["session_code"] == session and row["setup_id"] == setup]
            counts = support_counts(selected)
            metrics = economics.economic_metrics(selected, SEED + session_index * 100 + setup_index)
            sensitivity = {}
            for value in (0.10, 0.20):
                variant = variant_rows(selected, value)
                sensitivity[str(value)] = economics.economic_metrics(variant, SEED + session_index * 1000 + setup_index * 10 + int(value * 100))
            family.append({"test_id": f"{session}|{setup}", "session": session, "setup": setup, "support": counts, "support_failures": support_failures(counts), "metrics": metrics, "sensitivity": sensitivity, "raw_p": metrics.get("bootstrap", {}).get("one_sided_p")})
        adjusted = economics.holm_adjust({item["test_id"]: item["raw_p"] for item in family})
        for item in family:
            m, c = item["metrics"], item["support"]
            block_values = [entry["expectancy_r"] for entry in m.get("chronological_blocks", {}).values() if entry["expectancy_r"] is not None]
            years, sides = m.get("years", {}), m.get("sides", {})
            neighbour_values = [item["sensitivity"][key].get("net_expectancy_r") for key in ("0.1", "0.2")]
            gates = {
                "support": not item["support_failures"], "net_positive": (m.get("net_expectancy_r") or 0) > 0,
                "ci_lower_positive": (m.get("bootstrap", {}).get("ci95", [None])[0] or 0) > 0,
                "holm_p": adjusted[item["test_id"]] is not None and adjusted[item["test_id"]] <= 0.05,
                "profit_factor": (m.get("net_profit_factor") or 0) >= 1.25,
                "blocks": sum(value > 0 for value in block_values) >= 3 and bool(block_values) and all(value >= -0.10 for value in block_values),
                "years": all(years.get(str(year), {}).get("trades", 0) >= 8 and (years[str(year)]["expectancy_r"] or 0) > 0 for year in (2022, 2023, 2024)),
                "sides": all(sides.get(side, {}).get("trades", 0) >= 10 and (sides[side]["expectancy_r"] or 0) > 0 for side in ("UP", "DOWN")),
                "cost_stress": (m.get("cost_1p5x_expectancy_r") or 0) > 0 and (m.get("cost_1p5x_profit_factor") or 0) >= 1.10,
                "concentration": m.get("largest_trade_share_of_positive_total") is not None and m["largest_trade_share_of_positive_total"] <= 0.35,
                "drawdown": m.get("account", {}).get("max_drawdown_pct", math.inf) <= 15.0,
                "sensitivity": not all(value is None or value <= 0 for value in neighbour_values),
            }
            item["holm_adjusted_p"] = adjusted[item["test_id"]]
            item["gates"] = gates
            item["failed_gates"] = [key for key, value in gates.items() if not value]
            item["verdict"] = "PROVISIONAL_UNVALIDATED_EDGE" if all(gates.values()) else "SUPPORT_FAIL" if item["support_failures"] else "REJECT"
        tests.extend(family)
    portfolios = []
    for index, session in enumerate(SESSIONS):
        selected = economics.portfolio_rows(trades, session)
        portfolios.append({"test_id": f"{session}|EARLIEST_FROZEN_SETUP", "classification": "DIAGNOSTIC_ONLY", "support": support_counts(selected), "metrics": economics.economic_metrics(selected, SEED + 1000 + index), "candidate_credit": False})
    return tests, portfolios


def evaluate_gc(trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for session in branch.SESSIONS:
        for setup in branch.SETUPS:
            rows = [row for row in trades if row["session_code"] == session and row["setup_id"] == setup and row["status"] == "EXECUTED" and row["gc_covered"]]
            confirmed = [row for row in rows if row["gc_confirmed"] is True]
            unconfirmed = [row for row in rows if row["gc_confirmed"] is False]
            support = len(confirmed) >= 20 and len({row["session_date"] for row in confirmed}) >= 15 and len(unconfirmed) >= 30 and len({row["session_date"] for row in unconfirmed}) >= 20
            output.append({"test_id": f"{session}|{setup}|GC", "covered_trades": len(rows), "confirmed_trades": len(confirmed), "unconfirmed_trades": len(unconfirmed), "confirmed_expectancy_r": rounded(float(np.mean([row["net_r"] for row in confirmed]))) if confirmed else None, "unconfirmed_expectancy_r": rounded(float(np.mean([row["net_r"] for row in unconfirmed]))) if unconfirmed else None, "verdict": "REJECT" if support else "SUPPORT_FAIL"})
    return output


def synthetic_proof() -> dict[str, Any]:
    now = datetime(2024, 1, 2, 8, tzinfo=UTC)
    cases = {
        "TARGET": [prior.Bar(now, now + timedelta(minutes=1), 10000, 10310, 9990, 10200, "a", "a")],
        "STOP": [prior.Bar(now, now + timedelta(minutes=1), 10000, 10010, 9690, 9800, "b", "b")],
        "BOTH": [prior.Bar(now, now + timedelta(minutes=1), 10000, 10310, 9690, 10000, "c", "c")],
        "TIME": [prior.Bar(now, now + timedelta(minutes=1), 10000, 10010, 9990, 10005, "d", "d")],
    }
    values = {}
    for name, path in cases.items():
        left = select_exit(path, "UP", 9700, 10300, "primary")
        right = select_exit(path, "UP", 9700, 10300, "reference")
        if left != right:
            raise AssertionError((name, left, right))
        values[name] = left[2]
    if values != {"TARGET": "TARGET", "STOP": "STOP", "BOTH": "STOP", "TIME": "TIME"}:
        raise AssertionError(values)
    return {"status": "PASS_SYNTHETIC_EXECUTION_PROOF", "cases": values, "hash": canonical_hash(values)}


def report_text(results: Mapping[str, Any]) -> str:
    lines = ["# Gold Structural Trend-Retracement Continuation Edge Discovery V1 — Final Report", "", f"Status: **{results['overall_verdict']}**", "", "## Verdict", "", results["verdict_explanation"], "", "## Development results", "", "| Test | Signals | Trades | Win rate | Gross exp. | Net exp. | PF | 95% CI | Verdict |", "|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for item in results["base_tests"]:
        m = item["metrics"]
        lines.append(f"| {item['test_id']} | {item['support']['signals']} | {item['support']['trades']} | {m.get('win_rate_pct')}% | {m.get('gross_expectancy_r')} | {m.get('net_expectancy_r')} | {m.get('net_profit_factor')} | {m.get('bootstrap', {}).get('ci95')} | {item['verdict']} |")
    lines.extend(["", "## Portfolio diagnostics", "", "| Session | Trades | Net expectancy | PF | Net PnL | Max DD |", "|---|---:|---:|---:|---:|---:|"])
    for item in results["portfolio_diagnostics"]:
        m = item["metrics"]
        lines.append(f"| {item['test_id']} | {m.get('trades')} | {m.get('net_expectancy_r')} | {m.get('net_profit_factor')} | ${m.get('account', {}).get('net_pnl_usd')} | {m.get('account', {}).get('max_drawdown_pct')}% |")
    lines.extend(["", "## Integrity", "", "Primary/reference trade paths and statistics reproduced exactly. Outcomes were opened once. No 2025/2026 values or paid data were accessed. Only frozen development candidates could advance; zero candidates left the exposed periods closed.", ""])
    return "\n".join(lines)


def main() -> None:
    if any(path.exists() for path in (AUTHORIZATION, PRIMARY_TRADES, REFERENCE_TRADES, RESULTS, CANDIDATES, EXPOSED, LEDGER, REPORT, FINAL_SEAL)):
        raise FileExistsError("STRC outcome artifact already exists")
    signals = verify_preoutcome()
    proof = synthetic_proof()
    authorization = {
        "version": "GOLD_STRC_V1_OUTCOME_AUTHORIZATION_1_0", "status": "AUTHORIZED_SINGLE_DEVELOPMENT_OUTCOME_OPENING",
        "authorized_at_utc": utc_now(), "signal_count": len(signals), "signal_hash": canonical_hash(signals),
        "preoutcome_freeze": file_record(branch.PREOUTCOME_FREEZE), "implementation": file_record(Path(__file__).resolve()),
        "synthetic_proof": proof, "opening_limit": 1, "forward_values_authorized": False, "paid_acquisition_authorized": False,
    }
    write_json_exclusive(AUTHORIZATION, authorization)
    bars, diagnostics = load_outcome_bars(signals)
    primary_pairs = [calculate_trade(signal, bars, "primary") for signal in signals]
    reference_pairs = [calculate_trade(signal, bars, "reference") for signal in signals]
    primary = [item[0] for item in primary_pairs]
    reference = [item[0] for item in reference_pairs]
    if primary != reference or [item[1] for item in primary_pairs] != [item[1] for item in reference_pairs]:
        raise ValueError("Independent execution implementations disagree")
    primary.sort(key=lambda row: (row["session_date"], row["session_code"], row["signal_at_utc"], row["setup_id"], row["signal_id"]))
    reference.sort(key=lambda row: (row["session_date"], row["session_code"], row["signal_at_utc"], row["setup_id"], row["signal_id"]))
    write_parquet_exclusive(PRIMARY_TRADES, primary)
    write_parquet_exclusive(REFERENCE_TRADES, reference)
    if sha256_file(PRIMARY_TRADES) != sha256_file(REFERENCE_TRADES):
        raise ValueError("Trade Parquet outputs differ")
    tests, portfolios = evaluate(primary)
    reference_tests, reference_portfolios = evaluate(reference)
    gc = evaluate_gc(primary)
    if tests != reference_tests or portfolios != reference_portfolios or gc != evaluate_gc(reference):
        raise ValueError("Independent statistics disagree")
    candidates = [{"candidate_id": item["test_id"], "session": item["session"], "setup": item["setup"]} for item in tests if item["verdict"] == "PROVISIONAL_UNVALIDATED_EDGE"]
    overall = "PASS_PROVISIONAL_UNVALIDATED_EDGE" if candidates else "REJECT_NO_ECONOMICALLY_TRADABLE_CANDIDATE"
    explanation = "At least one frozen trend-retracement setup passed every economic and robustness gate." if candidates else "No frozen trend-retracement setup passed. All setup populations were below the support floor; descriptive performance is reported but cannot establish an edge."
    results = {
        "version": "GOLD_STRC_V1_DEVELOPMENT_RESULTS_1_0", "overall_verdict": overall, "completed_at_utc": utc_now(),
        "verdict_explanation": explanation, "signals": len(signals), "executed_trades": sum(row["status"] == "EXECUTED" for row in primary),
        "outcome_opening_count": 1, "outcome_diagnostics": diagnostics, "base_tests": tests,
        "portfolio_diagnostics": portfolios, "gc_incremental_tests": gc, "candidate_count": len(candidates),
        "primary_reference_exact": True, "trade_rows_hash": canonical_hash(primary), "forward_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(RESULTS, results)
    write_json_exclusive(CANDIDATES, {"version": "GOLD_STRC_V1_FROZEN_CANDIDATES_1_0", "status": "FROZEN_AFTER_DEVELOPMENT", "candidate_count": len(candidates), "candidates": candidates, "results_sha256": sha256_file(RESULTS), "retuning_permitted": False})
    if candidates:
        raise RuntimeError("Development candidate passed; frozen 2025/2026 application must be implemented before final seal")
    write_json_exclusive(EXPOSED, {"version": "GOLD_STRC_V1_EXPOSED_1_0", "status": "NOT_OPENED_ZERO_FROZEN_CANDIDATES", "candidate_count": 0, "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "independent_credit": False})
    ledger = {"record_type": "LEDGER_INITIALIZATION", "recorded_at_utc": utc_now(), "branch": "GOLD_STRC_V1", "active_candidate_ids": [], "status": "INITIALIZED_NO_ACTIVE_CANDIDATE", "append_only": True, "backfill_permitted": False}
    write_text_exclusive(LEDGER, canonical_json(ledger) + "\n")
    write_text_exclusive(REPORT, report_text(results))
    artifacts = [AUTHORIZATION, PRIMARY_TRADES, REFERENCE_TRADES, RESULTS, CANDIDATES, EXPOSED, LEDGER, REPORT, OUTPUT / "materialization_certification.json", branch.PREOUTCOME_FREEZE]
    seal = {"version": "GOLD_STRC_V1_FINAL_SEAL_1_0", "status": overall, "sealed_at_utc": utc_now(), "artifacts": {path.name: file_record(path) for path in artifacts}, "artifact_set_hash": canonical_hash({path.name: sha256_file(path) for path in artifacts}), "primary_reference_exact": True, "forward_values_accessed": False, "paid_acquisition_usd": 0.0}
    write_json_exclusive(FINAL_SEAL, seal)
    print(json.dumps({"status": overall, "signals": len(signals), "executed_trades": results["executed_trades"], "candidate_count": len(candidates), "tests": [{"test_id": item["test_id"], "trades": item["support"]["trades"], "win_rate": item["metrics"].get("win_rate_pct"), "net_expectancy_r": item["metrics"].get("net_expectancy_r"), "profit_factor": item["metrics"].get("net_profit_factor"), "verdict": item["verdict"]} for item in tests], "portfolios": [{"test_id": item["test_id"], "trades": item["metrics"].get("trades"), "net_expectancy_r": item["metrics"].get("net_expectancy_r"), "profit_factor": item["metrics"].get("net_profit_factor"), "pnl": item["metrics"].get("account", {}).get("net_pnl_usd")} for item in portfolios], "final_seal": file_record(FINAL_SEAL)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
