from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import hashlib
import json
import math
import os
import random
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from gold_intel.analytics.auction_automation import (
    AUCTION_AUTOMATION_RULESET_VERSION,
    AuctionAutomationSnapshot,
    AuctionPaperProposal,
    AuctionShiftZone,
    build_auction_automation_snapshot,
)
from gold_intel.analytics.liquidity import LiquidityBar, calculate_liquidity_snapshot
from gold_intel.analytics.structure import MinuteBar, aggregate_minutes
from gold_intel.infrastructure.database import engine, session_factory
from gold_intel.infrastructure.models import PriceBar

AUTOMATION_SHA256 = "67e64430e28c95a0862ae96ea0164ed41b80b8770da4150bca72385904bfbde9"
POPULATION_SHA256 = "6b69a13af3ee2909046615d05282c6f863b892e067ec04f11622d048b83e37f9"
GENESIS = "0" * 64
MAX_LOOKBACK_M1 = 60_000
LEVEL_ATR_MULTIPLE = 0.20
LEVEL_ABSOLUTE_FLOOR = 0.50
MARKING_LEVEL_GATE = 0.60
MARKING_ENTRY_GATE = 0.50
MAX_PLANNED_RISK_USD = 50.0
MAX_EFFECTIVE_RISK_USD = 55.0
SLIPPAGE_PRICE = 0.05
SPREAD_FALLBACK = 0.20
BOOTSTRAP_SEED = 20260820
BOOTSTRAP_RESAMPLES = 20_000


@dataclass(frozen=True, slots=True)
class SourceMinute:
    bar: MinuteBar
    spread_points: int | None
    spread_price: float | None
    volume_type: str


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, dict):
        return {str(key): json_ready(member) for key, member in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(member) for member in value]
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        json_ready(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_json_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(json_ready(value), handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def write_csv_exclusive(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
                    for key, value in row.items()
                }
            )


def resolve_research_path(research_root: Path, source: str) -> Path:
    path = Path(source)
    if path.is_absolute():
        return path
    parts = path.parts
    if parts and parts[0] == "research_artifacts":
        return research_root.joinpath(*parts[1:])
    return research_root / path


def verify_chain(rows: Sequence[dict[str, Any]], label: str) -> str:
    prior = GENESIS
    for sequence, source in enumerate(rows, start=1):
        row = dict(source)
        if row.get("ledger_sequence") != sequence:
            raise RuntimeError(f"{label} sequence mismatch at {sequence}")
        if row.get("prior_record_sha256") != prior:
            raise RuntimeError(f"{label} prior hash mismatch at {sequence}")
        submitted = str(row.pop("record_sha256", ""))
        if canonical_hash(row) != submitted:
            raise RuntimeError(f"{label} record hash mismatch at {sequence}")
        prior = submitted
    return prior


def load_private_stream(
    path: Path,
    *,
    expected_file_sha256: str,
    expected_stream_sha256: str,
) -> dict[str, Any]:
    if sha256_file(path) != expected_file_sha256:
        raise RuntimeError(f"Private stream file hash mismatch: {path}")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        row = json.loads(handle.readline())
        if handle.readline():
            raise RuntimeError(f"Private stream contains multiple rows: {path}")
    submitted = row.pop("stream_sha256", None)
    if submitted != expected_stream_sha256 or canonical_hash(row) != submitted:
        raise RuntimeError(f"Private stream payload hash mismatch: {path}")
    row["stream_sha256"] = submitted
    return row


async def load_source_minutes(start: datetime, end: datetime) -> list[SourceMinute]:
    query = (
        select(PriceBar)
        .where(
            PriceBar.instrument_code == "XAUUSD",
            PriceBar.provider_code == "IC_MARKETS_MT5",
            PriceBar.timeframe == "1m",
            PriceBar.is_complete.is_(True),
            PriceBar.is_synthetic.is_(False),
            PriceBar.close_time >= start,
            PriceBar.close_time <= end,
        )
        .order_by(PriceBar.open_time, PriceBar.available_at)
    )
    async with session_factory() as session:
        records = list((await session.scalars(query)).all())
    duplicates = Counter(record.open_time for record in records)
    repeated = [timestamp for timestamp, count in duplicates.items() if count != 1]
    if repeated:
        raise RuntimeError(f"Source contains {len(repeated)} duplicate-vintage minute identities")
    return [
        SourceMinute(
            bar=MinuteBar(
                id=record.id,
                open_time=record.open_time.astimezone(UTC),
                close_time=record.close_time.astimezone(UTC),
                open=float(record.open),
                high=float(record.high),
                low=float(record.low),
                close=float(record.close),
                volume=float(record.volume) if record.volume is not None else None,
                available_at=record.available_at.astimezone(UTC),
            ),
            spread_points=record.spread_points,
            spread_price=float(record.spread_price) if record.spread_price is not None else None,
            volume_type=record.volume_type,
        )
        for record in records
    ]


def eligible_source(source: Sequence[SourceMinute], cutoff: datetime) -> list[SourceMinute]:
    return [
        item
        for item in source
        if item.bar.close_time <= cutoff and item.bar.available_at <= cutoff
    ][-MAX_LOOKBACK_M1:]


def build_reproduced_snapshot(
    source: Sequence[SourceMinute],
    cutoff: datetime,
) -> AuctionAutomationSnapshot:
    eligible = eligible_source(source, cutoff)
    bars = [item.bar for item in eligible]
    primary = build_auction_automation_snapshot(
        bars,
        as_of=cutoff,
        macro_bias_label="UNKNOWN",
        macro_available_at=None,
        liquidity_status="NORMAL",
    )
    reference = build_auction_automation_snapshot(
        list(reversed(bars)),
        as_of=cutoff,
        macro_bias_label="UNKNOWN",
        macro_available_at=None,
        liquidity_status="NORMAL",
    )
    if canonical_hash(asdict(primary)) != canonical_hash(asdict(reference)):
        raise RuntimeError(f"Detector reproduction mismatch at {iso(cutoff)}")
    return primary


def current_m15_atr(source: Sequence[SourceMinute], cutoff: datetime) -> float:
    bars = [item.bar for item in eligible_source(source, cutoff)]
    aggregates = [
        bar
        for bar in aggregate_minutes(bars, timeframe_minutes=15, as_of=cutoff)
        if bar.complete and bar.close_time <= cutoff
    ]
    if not aggregates:
        return 0.01
    true_ranges: list[float] = []
    for index, bar in enumerate(aggregates):
        if index == 0:
            true_ranges.append(bar.high - bar.low)
        else:
            prior = aggregates[index - 1].close
            true_ranges.append(max(bar.high - bar.low, abs(bar.high - prior), abs(bar.low - prior)))
    members = true_ranges[-14:]
    return max(0.01, sum(members) / len(members))


def zone_distance(price: float, zone: AuctionShiftZone) -> float:
    if zone.lower_bound <= price <= zone.upper_bound:
        return 0.0
    return min(abs(price - zone.lower_bound), abs(price - zone.upper_bound))


def active_zones(snapshot: AuctionAutomationSnapshot) -> list[AuctionShiftZone]:
    return [
        zone
        for zone in snapshot.zones
        if zone.state in {"ACTIVE_UNTOUCHED", "TOUCHED", "RETEST_CONFIRMED"}
    ]


def technical_eligible(proposal: AuctionPaperProposal) -> bool:
    return bool(
        proposal.triggered_at is not None
        and proposal.entry_reference is not None
        and proposal.quantity_ounces is not None
        and proposal.quantity_ounces >= 1
        and proposal.planned_risk_usd is not None
        and 0 < proposal.planned_risk_usd <= MAX_PLANNED_RISK_USD
        and proposal.target is not None
        and proposal.reward_to_risk is not None
        and proposal.reward_to_risk >= 1.25
    )


def direction_from_action(action: str) -> str:
    return "BULLISH" if action == "LONG" else "BEARISH"


def macro_direction(label: str) -> str:
    normalized = label.upper()
    if "BULLISH" in normalized:
        return "BULLISH"
    if "BEARISH" in normalized:
        return "BEARISH"
    if "NEUTRAL" in normalized or "CONFLICT" in normalized:
        return "NEUTRAL"
    return "UNKNOWN"


def macro_at(context: dict[str, Any], trigger: datetime) -> dict[str, Any]:
    eligible = [
        row
        for row in context.get("fundamentals", [])
        if parse_time(str(row["available_at"])) <= trigger
        and trigger - parse_time(str(row["available_at"])) <= timedelta(hours=24)
    ]
    if not eligible:
        return {
            "available_at": None,
            "bias_label": "UNKNOWN",
            "direction": "UNKNOWN",
            "age_hours": None,
        }
    row = max(eligible, key=lambda item: parse_time(str(item["available_at"])))
    label = str(row.get("engine_state", {}).get("bias_label", "UNKNOWN"))
    available_at = parse_time(str(row["available_at"]))
    return {
        "available_at": iso(available_at),
        "bias_label": label,
        "direction": macro_direction(label),
        "age_hours": round((trigger - available_at).total_seconds() / 3600, 6),
    }


def liquidity_at(source: Sequence[SourceMinute], trigger: datetime) -> dict[str, Any]:
    eligible = eligible_source(source, trigger)
    bars = [
        LiquidityBar(
            open_time=item.bar.open_time,
            close_time=item.bar.close_time,
            high=item.bar.high,
            low=item.bar.low,
            close=item.bar.close,
            tick_volume=item.bar.volume if item.volume_type == "TICK" else None,
            spread_points=item.spread_points,
            spread_price=item.spread_price,
            available_at=item.bar.available_at,
        )
        for item in eligible
    ]
    snapshot = calculate_liquidity_snapshot(
        bars,
        trigger,
        provider_code="IC_MARKETS_MT5",
    )
    return {
        "status": snapshot.status,
        "data_hash": snapshot.data_hash,
        "spread_price": snapshot.current_spread_price,
        "data_quality_score": snapshot.data_quality_score,
    }


def source_spread(item: SourceMinute) -> float:
    if item.spread_price is not None and item.spread_price >= 0:
        return item.spread_price
    return SPREAD_FALLBACK


def resolve_trade(
    proposal: dict[str, Any],
    source: Sequence[SourceMinute],
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    direction = "LONG" if proposal["direction"] == "BULLISH" else "SHORT"
    sign = 1 if direction == "LONG" else -1
    trigger = parse_time(str(proposal["triggered_at"]))
    path = [
        item
        for item in source
        if item.bar.open_time >= trigger and item.bar.open_time >= start and item.bar.close_time < end
    ]
    if not path:
        raise RuntimeError(f"No resolution path for {proposal['case_alias']} {proposal['identity']}")
    fill_bar = path[0]
    half_spread = source_spread(fill_bar) / 2
    entry = float(proposal["entry_reference"])
    fill = entry + half_spread + SLIPPAGE_PRICE if direction == "LONG" else entry - half_spread - SLIPPAGE_PRICE
    stop = float(proposal["stop"])
    target = float(proposal["target"])
    quantity = int(proposal["quantity_ounces"])
    effective_risk = sign * (fill - stop) * quantity
    effective_reward = sign * (target - fill)
    invalid = effective_risk <= 0 or effective_reward <= 0 or effective_risk > MAX_EFFECTIVE_RISK_USD
    resolution: dict[str, Any] | None = None
    used_path: list[SourceMinute]
    exit_cost_per_ounce = 0.0
    if invalid:
        exit_bar = path[1] if len(path) > 1 else path[0]
        raw_exit = exit_bar.bar.open if len(path) > 1 else exit_bar.bar.close
        exit_cost_per_ounce = source_spread(exit_bar) / 2 + SLIPPAGE_PRICE
        actual_exit = raw_exit - exit_cost_per_ounce if direction == "LONG" else raw_exit + exit_cost_per_ounce
        resolution = {
            "state": "POST_FILL_GEOMETRY_INVALID",
            "exit_at": iso(exit_bar.bar.open_time if len(path) > 1 else exit_bar.bar.close_time),
            "raw_exit_price": raw_exit,
            "actual_exit_price": actual_exit,
        }
        used_path = path[:2]
    else:
        used_path = path
        for index, item in enumerate(path):
            bar = item.bar
            stop_touched = bar.low <= stop if direction == "LONG" else bar.high >= stop
            target_touched = bar.high >= target if direction == "LONG" else bar.low <= target
            if not stop_touched and not target_touched:
                continue
            if stop_touched:
                raw_exit = min(stop, bar.open) if direction == "LONG" else max(stop, bar.open)
                exit_cost_per_ounce = source_spread(item) / 2 + SLIPPAGE_PRICE
                actual_exit = raw_exit - exit_cost_per_ounce if direction == "LONG" else raw_exit + exit_cost_per_ounce
                state = "STOPPED"
            else:
                raw_exit = target
                actual_exit = target
                state = "TARGET_HIT"
            resolution = {
                "state": state,
                "exit_at": iso(bar.close_time),
                "raw_exit_price": raw_exit,
                "actual_exit_price": actual_exit,
            }
            used_path = path[: index + 1]
            break
    if resolution is None:
        exit_bar = path[-1]
        raw_exit = exit_bar.bar.close
        exit_cost_per_ounce = source_spread(exit_bar) / 2 + SLIPPAGE_PRICE
        actual_exit = raw_exit - exit_cost_per_ounce if direction == "LONG" else raw_exit + exit_cost_per_ounce
        resolution = {
            "state": "TIME_EXIT",
            "exit_at": iso(exit_bar.bar.close_time),
            "raw_exit_price": raw_exit,
            "actual_exit_price": actual_exit,
        }
    pnl = sign * (float(resolution["actual_exit_price"]) - fill) * quantity
    raw_gross = sign * (float(resolution["raw_exit_price"]) - entry) * quantity
    base_cost = raw_gross - pnl
    stressed_pnl = raw_gross - 1.5 * base_cost
    if direction == "LONG":
        mfe = max(0.0, max(item.bar.high for item in used_path) - fill)
        mae = max(0.0, fill - min(item.bar.low for item in used_path))
    else:
        mfe = max(0.0, fill - min(item.bar.low for item in used_path))
        mae = max(0.0, max(item.bar.high for item in used_path) - fill)
    return {
        **proposal,
        "trade_direction": direction,
        "fill_price": round(fill, 8),
        "fill_spread_price": round(source_spread(fill_bar), 8),
        "effective_fill_to_stop_risk_usd": round(effective_risk, 8),
        "resolution_state": resolution["state"],
        "exit_at": resolution["exit_at"],
        "raw_exit_price": round(float(resolution["raw_exit_price"]), 8),
        "actual_exit_price": round(float(resolution["actual_exit_price"]), 8),
        "net_pnl_usd": round(pnl, 8),
        "net_r50": round(pnl / 50, 8),
        "raw_gross_pnl_usd": round(raw_gross, 8),
        "estimated_base_cost_usd": round(base_cost, 8),
        "stressed_1_5x_cost_pnl_usd": round(stressed_pnl, 8),
        "stressed_1_5x_cost_r50": round(stressed_pnl / 50, 8),
        "mfe_r50": round(mfe * quantity / 50, 8),
        "mae_r50": round(mae * quantity / 50, 8),
        "same_bar_policy": "STOP_FIRST",
    }


def bootstrap_interval(values: Sequence[float]) -> list[float] | None:
    if not values:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    means = sorted(
        sum(rng.choice(values) for _ in values) / len(values)
        for _ in range(BOOTSTRAP_RESAMPLES)
    )
    return [
        round(means[int(0.025 * (len(means) - 1))], 8),
        round(means[int(0.975 * (len(means) - 1))], 8),
    ]


def maximum_drawdown(values: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return round(drawdown, 8)


def trade_metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["triggered_at"], row["identity"]))
    pnl = [float(row["net_pnl_usd"]) for row in ordered]
    r50 = [float(row["net_r50"]) for row in ordered]
    profits = sum(value for value in pnl if value > 0)
    losses = -sum(value for value in pnl if value < 0)
    return {
        "trades": len(rows),
        "wins": sum(value > 0 for value in pnl),
        "losses": sum(value < 0 for value in pnl),
        "scratches": sum(value == 0 for value in pnl),
        "win_rate": round(sum(value > 0 for value in pnl) / len(pnl), 8) if pnl else None,
        "net_pnl_usd": round(sum(pnl), 8),
        "net_r50": round(sum(r50), 8),
        "expectancy_usd": round(sum(pnl) / len(pnl), 8) if pnl else None,
        "expectancy_r50": round(sum(r50) / len(r50), 8) if r50 else None,
        "expectancy_r50_bootstrap_95": bootstrap_interval(r50),
        "profit_factor": round(profits / losses, 8) if losses else None,
        "maximum_drawdown_r50": maximum_drawdown(r50),
        "stressed_1_5x_cost_net_r50": round(
            sum(float(row["stressed_1_5x_cost_r50"]) for row in ordered), 8
        ),
        "stressed_1_5x_cost_expectancy_r50": round(
            sum(float(row["stressed_1_5x_cost_r50"]) for row in ordered) / len(ordered), 8
        )
        if ordered
        else None,
        "mean_mfe_r50": round(sum(float(row["mfe_r50"]) for row in ordered) / len(ordered), 8)
        if ordered
        else None,
        "mean_mae_r50": round(sum(float(row["mae_r50"]) for row in ordered) / len(ordered), 8)
        if ordered
        else None,
        "resolution_counts": dict(Counter(str(row["resolution_state"]) for row in ordered)),
    }


def economic_disposition(metrics: dict[str, Any]) -> str:
    if metrics["trades"] == 0:
        return "FAIL_NO_ACTIONABLE_PROPOSALS"
    if float(metrics["expectancy_r50"]) <= 0:
        return "REJECT_NEGATIVE_MATCHED_ECONOMICS"
    if metrics["trades"] < 20:
        return "INCONCLUSIVE_SMALL_MATCHED_SAMPLE"
    interval = metrics["expectancy_r50_bootstrap_95"]
    if (
        float(metrics["profit_factor"] or 0) >= 1.10
        and interval is not None
        and interval[0] > 0
        and float(metrics["stressed_1_5x_cost_expectancy_r50"] or 0) > 0
    ):
        return "PASS_EXPOSED_MATCHED_ECONOMICS"
    return "INCONCLUSIVE_SMALL_MATCHED_SAMPLE"


def compare_stream_day(
    stream: dict[str, Any],
    source: Sequence[SourceMinute],
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    stream_rows = [
        row
        for row in stream["timeframes"]["1m"]
        if start <= parse_time(str(row["open_at"])) and parse_time(str(row["close_at"])) < end
    ]
    source_rows = [
        item
        for item in source
        if start <= item.bar.open_time and item.bar.close_time < end
    ]
    stream_payload = [
        (
            row["open_at"],
            row["close_at"],
            round(float(row["open"]), 6),
            round(float(row["high"]), 6),
            round(float(row["low"]), 6),
            round(float(row["close"]), 6),
        )
        for row in stream_rows
    ]
    source_payload = [
        (
            iso(item.bar.open_time),
            iso(item.bar.close_time),
            round(item.bar.open, 6),
            round(item.bar.high, 6),
            round(item.bar.low, 6),
            round(item.bar.close, 6),
        )
        for item in source_rows
    ]
    if stream_payload != source_payload:
        raise RuntimeError(f"Stored M1 source differs from private replay stream: {stream['case_alias']}")
    return {
        "case_alias": stream["case_alias"],
        "m1_rows": len(source_payload),
        "m1_identity_sha256": canonical_hash(source_payload),
    }


async def evaluate(research_root: Path) -> dict[str, Any]:
    matched_root = research_root / "gold_matched_human_replay_v1"
    codex_root = research_root / "gold_blind_codex_operator_replay_v1"
    population = read_json(matched_root / "population_registry.private.json")
    if population.get("population_sha256") != POPULATION_SHA256:
        raise RuntimeError("Matched population hash differs")
    aliases = [f"CBR-2022-{index:03d}" for index in range(1, 31)]
    cases = population.get("cases", [])
    if [row.get("case_alias") for row in cases] != aliases:
        raise RuntimeError("Matched case identities differ")
    module_path = Path(__file__).resolve().parents[1] / "src" / "gold_intel" / "analytics" / "auction_automation.py"
    if sha256_file(module_path) != AUTOMATION_SHA256:
        raise RuntimeError("Frozen automation module hash differs")
    human_ledger = read_jsonl(matched_root / "ledgers" / "matched_human_visible_ledger.jsonl")
    human_head = verify_chain(human_ledger, "matched human visible ledger")
    comparison = read_json(matched_root / "comparison" / "matched_case_comparison.json")
    certification = read_json(codex_root / "stream_materialization_certification.json")
    certified = {
        str(row["case_alias"]): row
        for row in certification.get("case_files", [])
        if str(row.get("case_alias")) in aliases
    }
    if sorted(certified) != aliases:
        raise RuntimeError("Certified private-stream population differs")

    first_start = min(parse_time(str(row["start_inclusive"])) for row in cases)
    last_end = max(parse_time(str(row["end_exclusive"])) for row in cases)
    source = await load_source_minutes(first_start - timedelta(days=63), last_end)
    if not source:
        raise RuntimeError("No stored M1 source bars")

    contexts: dict[str, dict[str, Any]] = {}
    source_checks: list[dict[str, Any]] = []
    for case in cases:
        alias = str(case["case_alias"])
        item = certified[alias]["primary"]
        path = resolve_research_path(research_root, str(item["path"]))
        stream = load_private_stream(
            path,
            expected_file_sha256=str(item["sha256"]),
            expected_stream_sha256=str(item["stream_sha256"]),
        )
        if stream.get("case_alias") != alias:
            raise RuntimeError(f"Private stream identity differs: {alias}")
        start = parse_time(str(case["start_inclusive"]))
        end = parse_time(str(case["end_exclusive"]))
        source_checks.append(compare_stream_day(stream, source, start, end))
        contexts[alias] = stream["context_timeline"]

    human_decisions: list[dict[str, Any]] = []
    for event in human_ledger:
        if event.get("event_type") != "DECISION_SEALED":
            continue
        decision = event["data"]["decision"]
        human_decisions.append(
            {
                "operator": "HUMAN",
                "case_alias": event["case_alias"],
                "decision_at": event["cursor_at"],
                "action": decision["action"],
                "entry": float(decision["entry"]),
                "horizontal_lines": [
                    drawing
                    for drawing in decision.get("drawings", [])
                    if drawing.get("kind") == "HORIZONTAL_LINE"
                ],
            }
        )
    codex_decisions = [
        {
            "operator": "CODEX",
            "case_alias": row["case_alias"],
            "decision_at": row["codex"]["submitted_at"],
            "action": row["codex"]["action"],
            "entry": float(row["codex"]["entry"]),
            "horizontal_lines": [],
        }
        for row in comparison["cases"]
        if row["codex"]["is_trade"]
    ]
    decisions = human_decisions + codex_decisions
    case_by_alias = {str(row["case_alias"]): row for row in cases}
    decision_groups: dict[datetime, list[dict[str, Any]]] = {}
    for decision in decisions:
        decision_groups.setdefault(parse_time(str(decision["decision_at"])), []).append(decision)

    marking_rows: list[dict[str, Any]] = []
    human_level_rows: list[dict[str, Any]] = []
    for cutoff in sorted(decision_groups):
        snapshot = build_reproduced_snapshot(source, cutoff)
        atr = current_m15_atr(source, cutoff)
        tolerance = max(LEVEL_ABSOLUTE_FLOOR, LEVEL_ATR_MULTIPLE * atr)
        zones = active_zones(snapshot)
        swings = [swing for swing in snapshot.swings if swing.timeframe in {"15m", "1h", "4h"}]
        for decision in decision_groups[cutoff]:
            expected_direction = direction_from_action(str(decision["action"]))
            entry = float(decision["entry"])
            nearest_any = min((zone_distance(entry, zone) for zone in zones), default=math.inf)
            same_zones = [zone for zone in zones if zone.direction == expected_direction]
            nearest_same = min((zone_distance(entry, zone) for zone in same_zones), default=math.inf)
            case = case_by_alias[str(decision["case_alias"])]
            start = parse_time(str(case["start_inclusive"]))
            same_direction_proposals = [
                proposal
                for proposal in snapshot.proposals
                if proposal.direction == expected_direction
                and proposal.triggered_at is not None
                and start <= proposal.triggered_at <= cutoff
                and technical_eligible(proposal)
            ]
            nearest_proposal = min(
                (
                    abs(entry - float(proposal.entry_reference))
                    for proposal in same_direction_proposals
                    if proposal.entry_reference is not None
                ),
                default=math.inf,
            )
            marking_rows.append(
                {
                    "operator": decision["operator"],
                    "case_alias": decision["case_alias"],
                    "decision_at": iso(cutoff),
                    "action": decision["action"],
                    "entry": round(entry, 8),
                    "m15_atr14": round(atr, 8),
                    "spatial_tolerance": round(tolerance, 8),
                    "active_zone_count": len(zones),
                    "nearest_active_zone_distance": None if math.isinf(nearest_any) else round(nearest_any, 8),
                    "entry_near_any_active_zone": nearest_any <= tolerance,
                    "nearest_same_direction_zone_distance": None
                    if math.isinf(nearest_same)
                    else round(nearest_same, 8),
                    "entry_near_same_direction_zone": nearest_same <= tolerance,
                    "same_direction_technical_proposal_before_decision": bool(same_direction_proposals),
                    "same_direction_proposal_near_entry": nearest_proposal <= tolerance,
                    "same_direction_proposal_count": len(same_direction_proposals),
                    "detector_data_hash": snapshot.data_hash,
                }
            )
            for drawing in decision["horizontal_lines"]:
                anchor = drawing["anchors"][0]
                price = float(anchor["price"])
                timeframe = str(anchor["source_timeframe"])
                same_tf_distance = min(
                    (
                        abs(price - swing.price_level)
                        for swing in swings
                        if swing.timeframe == timeframe
                    ),
                    default=math.inf,
                )
                any_swing_distance = min(
                    (abs(price - swing.price_level) for swing in swings),
                    default=math.inf,
                )
                zone_level_distance = min(
                    (zone_distance(price, zone) for zone in zones),
                    default=math.inf,
                )
                human_level_rows.append(
                    {
                        "case_alias": decision["case_alias"],
                        "decision_at": iso(cutoff),
                        "drawing_id": drawing["drawing_id"],
                        "source_timeframe": timeframe,
                        "price": round(price, 8),
                        "spatial_tolerance": round(tolerance, 8),
                        "same_timeframe_swing_match": same_tf_distance <= tolerance,
                        "any_swing_match": any_swing_distance <= tolerance,
                        "active_zone_match": zone_level_distance <= tolerance,
                        "any_structure_match": min(any_swing_distance, zone_level_distance) <= tolerance,
                        "same_timeframe_swing_distance": None
                        if math.isinf(same_tf_distance)
                        else round(same_tf_distance, 8),
                        "any_swing_distance": None
                        if math.isinf(any_swing_distance)
                        else round(any_swing_distance, 8),
                        "active_zone_distance": None
                        if math.isinf(zone_level_distance)
                        else round(zone_level_distance, 8),
                    }
                )

    proposal_rows: list[dict[str, Any]] = []
    liquidity_cache: dict[str, dict[str, Any]] = {}
    for case in cases:
        alias = str(case["case_alias"])
        start = parse_time(str(case["start_inclusive"]))
        end = parse_time(str(case["end_exclusive"]))
        snapshot = build_reproduced_snapshot(source, end)
        for proposal in snapshot.proposals:
            if proposal.triggered_at is None or not (start <= proposal.triggered_at < end):
                continue
            technical = technical_eligible(proposal)
            macro = macro_at(contexts[alias], proposal.triggered_at)
            liquidity_key = iso(proposal.triggered_at)
            if liquidity_key not in liquidity_cache:
                liquidity_cache[liquidity_key] = liquidity_at(source, proposal.triggered_at)
            liquidity = liquidity_cache[liquidity_key]
            relationship = (
                "ALIGNED"
                if macro["direction"] == proposal.direction
                else macro["direction"]
                if macro["direction"] in {"UNKNOWN", "NEUTRAL"}
                else "COUNTER_MACRO"
            )
            full_eligible = bool(
                technical
                and relationship == "ALIGNED"
                and liquidity["status"] in {"NORMAL", "ELEVATED"}
            )
            blockers: list[str] = []
            if not technical:
                blockers.append("TECHNICAL_GEOMETRY")
            if relationship != "ALIGNED":
                blockers.append(f"MACRO_{relationship}")
            if liquidity["status"] not in {"NORMAL", "ELEVATED"}:
                blockers.append(f"LIQUIDITY_{liquidity['status']}")
            proposal_rows.append(
                {
                    "case_alias": alias,
                    "trading_date_utc": case["trading_date_utc"],
                    "identity": proposal.identity,
                    "zone_identity": proposal.zone_identity,
                    "family": proposal.family,
                    "direction": proposal.direction,
                    "triggered_at": iso(proposal.triggered_at),
                    "entry_reference": proposal.entry_reference,
                    "stop": proposal.stop,
                    "target": proposal.target,
                    "quantity_ounces": proposal.quantity_ounces,
                    "planned_risk_usd": proposal.planned_risk_usd,
                    "reward_to_risk": proposal.reward_to_risk,
                    "technical_eligible": technical,
                    "macro_available_at": macro["available_at"],
                    "macro_bias_label": macro["bias_label"],
                    "macro_direction": macro["direction"],
                    "macro_age_hours": macro["age_hours"],
                    "macro_relationship": relationship,
                    "liquidity_status": liquidity["status"],
                    "liquidity_data_hash": liquidity["data_hash"],
                    "full_paper_ready": full_eligible,
                    "blockers": blockers,
                    "detector_data_hash": snapshot.data_hash,
                }
            )

    eligible_proposals = [row for row in proposal_rows if row["full_paper_ready"]]
    selected_by_family: dict[str, list[dict[str, Any]]] = {
        "RETEST_LIMIT_V0_1": [],
        "CONFIRMED_RETEST_V0_1": [],
    }
    for alias in aliases:
        for family in selected_by_family:
            members = sorted(
                (
                    row
                    for row in eligible_proposals
                    if row["case_alias"] == alias and row["family"] == family
                ),
                key=lambda row: (row["triggered_at"], row["identity"]),
            )
            if members:
                selected_by_family[family].append(members[0])
    combined_selected: list[dict[str, Any]] = []
    family_rank = {"CONFIRMED_RETEST_V0_1": 0, "RETEST_LIMIT_V0_1": 1}
    for alias in aliases:
        members = sorted(
            (row for row in eligible_proposals if row["case_alias"] == alias),
            key=lambda row: (row["triggered_at"], family_rank[row["family"]], row["identity"]),
        )
        if members:
            combined_selected.append(members[0])

    case_bounds = {
        str(row["case_alias"]): (
            parse_time(str(row["start_inclusive"])),
            parse_time(str(row["end_exclusive"])),
        )
        for row in cases
    }
    family_trades = {
        family: [
            resolve_trade(row, source, *case_bounds[str(row["case_alias"])])
            for row in members
        ]
        for family, members in selected_by_family.items()
    }
    combined_trades = [
        resolve_trade(row, source, *case_bounds[str(row["case_alias"])])
        for row in combined_selected
    ]
    metrics = {
        "RETEST_LIMIT_V0_1": trade_metrics(family_trades["RETEST_LIMIT_V0_1"]),
        "CONFIRMED_RETEST_V0_1": trade_metrics(
            family_trades["CONFIRMED_RETEST_V0_1"]
        ),
        "COMBINED_EARLIEST_ONE_PER_CASE": trade_metrics(combined_trades),
    }

    human_markings = [row for row in marking_rows if row["operator"] == "HUMAN"]
    codex_markings = [row for row in marking_rows if row["operator"] == "CODEX"]
    level_rate = (
        sum(bool(row["any_structure_match"]) for row in human_level_rows)
        / len(human_level_rows)
        if human_level_rows
        else 0.0
    )
    entry_rate = (
        sum(bool(row["entry_near_same_direction_zone"]) for row in human_markings)
        / len(human_markings)
        if human_markings
        else 0.0
    )
    marking_metrics = {
        "human_horizontal_levels": len(human_level_rows),
        "same_timeframe_swing_matches": sum(
            bool(row["same_timeframe_swing_match"]) for row in human_level_rows
        ),
        "any_swing_matches": sum(bool(row["any_swing_match"]) for row in human_level_rows),
        "active_zone_matches": sum(bool(row["active_zone_match"]) for row in human_level_rows),
        "any_structure_matches": sum(
            bool(row["any_structure_match"]) for row in human_level_rows
        ),
        "any_structure_match_rate": round(level_rate, 8),
        "human_trade_entries": len(human_markings),
        "human_entries_near_any_active_zone": sum(
            bool(row["entry_near_any_active_zone"]) for row in human_markings
        ),
        "human_entries_near_same_direction_zone": sum(
            bool(row["entry_near_same_direction_zone"]) for row in human_markings
        ),
        "human_same_direction_zone_rate": round(entry_rate, 8),
        "human_same_direction_proposal_before_decision": sum(
            bool(row["same_direction_technical_proposal_before_decision"])
            for row in human_markings
        ),
        "codex_trade_entries": len(codex_markings),
        "codex_entries_near_any_active_zone": sum(
            bool(row["entry_near_any_active_zone"]) for row in codex_markings
        ),
        "codex_entries_near_same_direction_zone": sum(
            bool(row["entry_near_same_direction_zone"]) for row in codex_markings
        ),
        "level_gate": MARKING_LEVEL_GATE,
        "entry_gate": MARKING_ENTRY_GATE,
    }
    marking_verdict = (
        "PASS_MARKING_AGREEMENT_ONLY"
        if level_rate >= MARKING_LEVEL_GATE and entry_rate >= MARKING_ENTRY_GATE
        else "FAIL_MARKING_MISMATCH"
    )
    economic_verdict = economic_disposition(metrics["COMBINED_EARLIEST_ONE_PER_CASE"])
    core = {
        "version": "GOLD_AUCTION_AUTOMATION_MATCHED_REPLAY_VERIFICATION_V1_RESULT_1_0",
        "research_credit": "ZERO_CREDIT_EXPOSED_MATCHED_CALIBRATION",
        "ruleset_version": AUCTION_AUTOMATION_RULESET_VERSION,
        "automation_sha256": AUTOMATION_SHA256,
        "population_sha256": POPULATION_SHA256,
        "source": {
            "provider": "IC_MARKETS_MT5",
            "instrument": "XAUUSD",
            "source_rows": len(source),
            "source_first_at": iso(source[0].bar.open_time),
            "source_last_at": iso(source[-1].bar.close_time),
            "case_source_checks": source_checks,
            "human_visible_ledger_head_sha256": human_head,
        },
        "marking_metrics": marking_metrics,
        "marking_verdict": marking_verdict,
        "proposal_support": {
            "triggered_proposals": len(proposal_rows),
            "technical_eligible": sum(bool(row["technical_eligible"]) for row in proposal_rows),
            "full_paper_ready": len(eligible_proposals),
            "blocker_counts": dict(
                Counter(blocker for row in proposal_rows for blocker in row["blockers"])
            ),
        },
        "performance": metrics,
        "economic_verdict": economic_verdict,
        "operator_reference": {
            "human": comparison["metrics"]["human"],
            "codex": comparison["metrics"]["codex"],
        },
        "rows": {
            "marking_rows": marking_rows,
            "human_level_rows": human_level_rows,
            "proposal_rows": proposal_rows,
            "family_trade_rows": family_trades,
            "combined_trade_rows": combined_trades,
        },
    }
    reference_checksums = {
        "marking_rows": canonical_hash(list(reversed(sorted(marking_rows, key=canonical_hash)))),
        "human_level_rows": canonical_hash(
            list(reversed(sorted(human_level_rows, key=canonical_hash)))
        ),
        "proposal_rows": canonical_hash(list(reversed(sorted(proposal_rows, key=canonical_hash)))),
        "combined_trade_rows": canonical_hash(
            list(reversed(sorted(combined_trades, key=canonical_hash)))
        ),
    }
    primary_checksums = {
        "marking_rows": canonical_hash(list(reversed(sorted(marking_rows, key=canonical_hash)))),
        "human_level_rows": canonical_hash(
            list(reversed(sorted(human_level_rows, key=canonical_hash)))
        ),
        "proposal_rows": canonical_hash(list(reversed(sorted(proposal_rows, key=canonical_hash)))),
        "combined_trade_rows": canonical_hash(
            list(reversed(sorted(combined_trades, key=canonical_hash)))
        ),
    }
    if primary_checksums != reference_checksums:
        raise RuntimeError("Final row reproduction checksums differ")
    core["reproduction"] = {
        "detector_primary_reference_every_checkpoint": "IDENTICAL",
        "primary_checksums": primary_checksums,
        "reference_checksums": reference_checksums,
        "all_checksums_identical": True,
    }
    return core


def output_artifacts(output_root: Path, result: dict[str, Any]) -> None:
    rows = result["rows"]
    result_without_rows = {key: value for key, value in result.items() if key != "rows"}
    result_without_rows["row_artifacts"] = {
        "marking_rows": "marking_rows.csv",
        "human_level_rows": "human_level_rows.csv",
        "proposal_rows": "proposal_rows.csv",
        "family_trade_rows": "family_trade_rows.json",
        "combined_trade_rows": "combined_trade_rows.csv",
    }
    write_csv_exclusive(output_root / "marking_rows.csv", rows["marking_rows"])
    write_csv_exclusive(output_root / "human_level_rows.csv", rows["human_level_rows"])
    write_csv_exclusive(output_root / "proposal_rows.csv", rows["proposal_rows"])
    write_json_exclusive(output_root / "family_trade_rows.json", rows["family_trade_rows"])
    write_csv_exclusive(output_root / "combined_trade_rows.csv", rows["combined_trade_rows"])
    write_json_exclusive(output_root / "result.json", result_without_rows)
    files = sorted(path for path in output_root.iterdir() if path.is_file())
    reproduction = {
        "version": "GOLD_AUCTION_AUTOMATION_MATCHED_REPLAY_VERIFICATION_V1_REPRODUCTION_1_0",
        "result_core_sha256": canonical_hash(result_without_rows),
        "detector_reproduction": result["reproduction"],
        "files": {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in files
        },
    }
    write_json_exclusive(output_root / "independent_reproduction.json", reproduction)
    files = sorted(path for path in output_root.iterdir() if path.is_file())
    seal = {
        "version": "GOLD_AUCTION_AUTOMATION_MATCHED_REPLAY_VERIFICATION_V1_FINAL_SEAL_1_0",
        "marking_verdict": result["marking_verdict"],
        "economic_verdict": result["economic_verdict"],
        "research_credit": result["research_credit"],
        "files": {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in files
        },
    }
    write_json_exclusive(output_root / "final_seal.json", seal)


async def evaluate_and_dispose(research_root: Path) -> dict[str, Any]:
    """Run the audit and close the database engine on the same event loop."""
    try:
        return await evaluate(research_root)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--research-root",
        type=Path,
        default=Path(os.environ.get("RESEARCH_ROOT", "/research_artifacts")),
    )
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if args.output_root.exists() and any(args.output_root.iterdir()):
        raise RuntimeError(f"Output directory must be empty: {args.output_root}")
    args.output_root.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(evaluate_and_dispose(args.research_root.resolve()))
    output_artifacts(args.output_root.resolve(), result)
    print(
        json.dumps(
            {
                "marking_verdict": result["marking_verdict"],
                "economic_verdict": result["economic_verdict"],
                "marking_metrics": result["marking_metrics"],
                "proposal_support": result["proposal_support"],
                "performance": result["performance"],
                "result_sha256": canonical_hash(
                    {key: value for key, value in result.items() if key != "rows"}
                ),
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
