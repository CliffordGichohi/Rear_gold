from __future__ import annotations

import hashlib
import math
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

ControlCode = Literal["ALWAYS_LONG", "ALWAYS_SHORT", "DETERMINISTIC_RANDOM"]
Side = Literal["LONG", "SHORT"]


@dataclass(frozen=True, slots=True)
class BaselineExecutionConfig:
    execution_manifest_hash: str
    quantity_ounces: float = 1.0
    contract_size_ounces_per_lot: float = 100.0
    commission_usd_per_lot_round_turn: float = 7.0
    slippage_price_per_side: float = 0.05
    cost_multiplier: float = 1.0
    entry_latency_minutes: int = 1
    random_namespace: str = "GOLD_CASEBOOK_BASELINE_RANDOM_V0_1"

    @property
    def quantity_lots(self) -> float:
        return self.quantity_ounces / self.contract_size_ounces_per_lot


@dataclass(frozen=True, slots=True)
class BaselineCase:
    case_id: str
    case_record_hash: str
    session_code: str
    session_date: date
    decision_at: datetime
    observation_end: datetime


@dataclass(frozen=True, slots=True)
class BaselinePriceBar:
    record_id: str
    record_hash: str
    open_time: datetime
    close_time: datetime
    open: float
    close: float
    spread_price: float | None
    available_at: datetime


@dataclass(frozen=True, slots=True)
class BaselineTrade:
    case_id: str
    case_record_hash: str
    session_code: str
    session_date: date
    control_code: ControlCode
    side: Side
    decision_at: datetime
    entry_time: datetime
    exit_time: datetime
    holding_minutes: int
    entry_bar_id: str
    entry_bar_hash: str
    exit_bar_id: str
    exit_bar_hash: str
    reference_entry_price: float
    reference_exit_price: float
    executed_entry_price: float
    executed_exit_price: float
    entry_spread_price: float
    exit_spread_price: float
    quantity_ounces: float
    quantity_lots: float
    gross_pnl_usd: float
    spread_cost_usd: float
    slippage_cost_usd: float
    commission_usd: float
    total_cost_usd: float
    net_pnl_usd: float
    gross_return_basis_points: float
    net_return_basis_points: float
    execution_manifest_hash: str


def direction_for_control(
    control_code: ControlCode,
    *,
    case_id: str,
    random_namespace: str,
) -> Side:
    if control_code == "ALWAYS_LONG":
        return "LONG"
    if control_code == "ALWAYS_SHORT":
        return "SHORT"
    if control_code != "DETERMINISTIC_RANDOM":
        raise ValueError(f"Unsupported control: {control_code}")
    digest = hashlib.sha256(
        f"{random_namespace}|{case_id}".encode("ascii")
    ).digest()
    return "LONG" if digest[0] < 128 else "SHORT"


def simulate_baseline_case(
    case: BaselineCase,
    *,
    control_code: ControlCode,
    entry_bar: BaselinePriceBar,
    exit_bar: BaselinePriceBar,
    config: BaselineExecutionConfig,
) -> BaselineTrade:
    _validate_case_and_bars(case, entry_bar=entry_bar, exit_bar=exit_bar, config=config)
    if entry_bar.spread_price is None:
        raise ValueError("ENTRY_SPREAD_UNKNOWN")
    if exit_bar.spread_price is None:
        raise ValueError("EXIT_SPREAD_UNKNOWN")
    side = direction_for_control(
        control_code,
        case_id=case.case_id,
        random_namespace=config.random_namespace,
    )
    direction = 1 if side == "LONG" else -1
    entry_spread = entry_bar.spread_price
    exit_spread = exit_bar.spread_price
    adverse_entry_cost = (
        entry_spread / 2 + config.slippage_price_per_side
    ) * config.cost_multiplier
    adverse_exit_cost = (
        exit_spread / 2 + config.slippage_price_per_side
    ) * config.cost_multiplier
    executed_entry = entry_bar.open + direction * adverse_entry_cost
    executed_exit = exit_bar.close - direction * adverse_exit_cost
    quantity = config.quantity_ounces
    quantity_lots = config.quantity_lots
    gross_pnl = direction * (exit_bar.close - entry_bar.open) * quantity
    spread_cost = (
        (entry_spread + exit_spread)
        / 2
        * quantity
        * config.cost_multiplier
    )
    slippage_cost = (
        2
        * config.slippage_price_per_side
        * quantity
        * config.cost_multiplier
    )
    commission = (
        config.commission_usd_per_lot_round_turn
        * quantity_lots
        * config.cost_multiplier
    )
    execution_pnl = (
        direction * (executed_exit - executed_entry) * quantity
    )
    net_pnl = execution_pnl - commission
    total_cost = spread_cost + slippage_cost + commission
    if not math.isclose(gross_pnl - net_pnl, total_cost, abs_tol=1e-9):
        raise AssertionError("Execution cost identity failed")
    entry_notional = entry_bar.open * quantity
    gross_return_bps = (
        gross_pnl / entry_notional * 10_000 if entry_notional else 0.0
    )
    net_return_bps = (
        net_pnl / entry_notional * 10_000 if entry_notional else 0.0
    )
    return BaselineTrade(
        case_id=case.case_id,
        case_record_hash=case.case_record_hash,
        session_code=case.session_code,
        session_date=case.session_date,
        control_code=control_code,
        side=side,
        decision_at=case.decision_at,
        entry_time=entry_bar.open_time,
        exit_time=exit_bar.close_time,
        holding_minutes=int(
            (exit_bar.close_time - entry_bar.open_time).total_seconds() // 60
        ),
        entry_bar_id=entry_bar.record_id,
        entry_bar_hash=entry_bar.record_hash,
        exit_bar_id=exit_bar.record_id,
        exit_bar_hash=exit_bar.record_hash,
        reference_entry_price=entry_bar.open,
        reference_exit_price=exit_bar.close,
        executed_entry_price=executed_entry,
        executed_exit_price=executed_exit,
        entry_spread_price=entry_spread,
        exit_spread_price=exit_spread,
        quantity_ounces=quantity,
        quantity_lots=quantity_lots,
        gross_pnl_usd=gross_pnl,
        spread_cost_usd=spread_cost,
        slippage_cost_usd=slippage_cost,
        commission_usd=commission,
        total_cost_usd=total_cost,
        net_pnl_usd=net_pnl,
        gross_return_basis_points=gross_return_bps,
        net_return_basis_points=net_return_bps,
        execution_manifest_hash=config.execution_manifest_hash,
    )


def calculate_baseline_metrics(
    trades: Sequence[BaselineTrade],
) -> dict[str, Any]:
    if not trades:
        return _empty_metrics()
    ordered = sorted(trades, key=lambda item: (item.entry_time, item.case_id))
    gross = [item.gross_pnl_usd for item in ordered]
    net = [item.net_pnl_usd for item in ordered]
    gross_returns = [item.gross_return_basis_points for item in ordered]
    net_returns = [item.net_return_basis_points for item in ordered]
    total_gross = math.fsum(gross)
    total_net = math.fsum(net)
    gains = math.fsum(value for value in net if value > 0)
    losses = math.fsum(value for value in net if value < 0)
    mean_return = statistics.fmean(net_returns)
    return_std = statistics.stdev(net_returns) if len(net_returns) >= 2 else 0.0
    standard_error = return_std / math.sqrt(len(net_returns))
    ci_half_width = 1.96 * standard_error
    sharpe = (
        mean_return / return_std * math.sqrt(252)
        if return_std > 0
        else None
    )
    direction_counts = Counter(item.side for item in ordered)
    results_by_year = {
        str(year): _year_metrics(
            [item for item in ordered if item.session_date.year == year]
        )
        for year in sorted({item.session_date.year for item in ordered})
    }
    return {
        "observations": len(ordered),
        "gross_win_rate_pct": _percentage(
            sum(value > 0 for value in gross),
            len(gross),
        ),
        "net_win_rate_pct": _percentage(
            sum(value > 0 for value in net),
            len(net),
        ),
        "mean_gross_pnl_usd_per_ounce": _rounded(
            statistics.fmean(gross)
        ),
        "median_gross_pnl_usd_per_ounce": _rounded(
            statistics.median(gross)
        ),
        "mean_net_pnl_usd_per_ounce": _rounded(
            statistics.fmean(net)
        ),
        "median_net_pnl_usd_per_ounce": _rounded(
            statistics.median(net)
        ),
        "mean_gross_return_basis_points": _rounded(
            statistics.fmean(gross_returns)
        ),
        "mean_net_return_basis_points": _rounded(mean_return),
        "mean_net_return_95pct_normal_ci_basis_points": [
            _rounded(mean_return - ci_half_width),
            _rounded(mean_return + ci_half_width),
        ],
        "total_gross_pnl_usd_per_ounce": _rounded(total_gross),
        "total_net_pnl_usd_per_ounce": _rounded(total_net),
        "profit_factor": (
            _rounded(gains / abs(losses))
            if losses < 0
            else None
        ),
        "maximum_drawdown_usd_per_ounce": _rounded(
            _maximum_drawdown(net)
        ),
        "session_return_sharpe_sqrt_252": _rounded(sharpe),
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
        "results_by_year": results_by_year,
    }


def trade_to_dict(trade: BaselineTrade) -> dict[str, Any]:
    return {
        "case_id": trade.case_id,
        "case_record_hash": trade.case_record_hash,
        "session_code": trade.session_code,
        "session_date": trade.session_date,
        "control_code": trade.control_code,
        "side": trade.side,
        "decision_at": trade.decision_at,
        "entry_time": trade.entry_time,
        "exit_time": trade.exit_time,
        "holding_minutes": trade.holding_minutes,
        "entry_bar_id": trade.entry_bar_id,
        "entry_bar_hash": trade.entry_bar_hash,
        "exit_bar_id": trade.exit_bar_id,
        "exit_bar_hash": trade.exit_bar_hash,
        "reference_entry_price": _rounded(trade.reference_entry_price),
        "reference_exit_price": _rounded(trade.reference_exit_price),
        "executed_entry_price": _rounded(trade.executed_entry_price),
        "executed_exit_price": _rounded(trade.executed_exit_price),
        "entry_spread_price": _rounded(trade.entry_spread_price),
        "exit_spread_price": _rounded(trade.exit_spread_price),
        "quantity_ounces": trade.quantity_ounces,
        "quantity_lots": trade.quantity_lots,
        "gross_pnl_usd": _rounded(trade.gross_pnl_usd),
        "spread_cost_usd": _rounded(trade.spread_cost_usd),
        "slippage_cost_usd": _rounded(trade.slippage_cost_usd),
        "commission_usd": _rounded(trade.commission_usd),
        "total_cost_usd": _rounded(trade.total_cost_usd),
        "net_pnl_usd": _rounded(trade.net_pnl_usd),
        "gross_return_basis_points": _rounded(
            trade.gross_return_basis_points
        ),
        "net_return_basis_points": _rounded(
            trade.net_return_basis_points
        ),
        "execution_manifest_hash": trade.execution_manifest_hash,
    }


def _validate_case_and_bars(
    case: BaselineCase,
    *,
    entry_bar: BaselinePriceBar,
    exit_bar: BaselinePriceBar,
    config: BaselineExecutionConfig,
) -> None:
    if case.decision_at.tzinfo is None or case.observation_end.tzinfo is None:
        raise ValueError("Case timestamps must be timezone-aware")
    expected_entry = case.decision_at + timedelta(
        minutes=config.entry_latency_minutes
    )
    if entry_bar.open_time != expected_entry:
        raise ValueError("ENTRY_BAR_TIME_MISMATCH")
    if exit_bar.open_time != case.observation_end - timedelta(minutes=1):
        raise ValueError("EXIT_BAR_TIME_MISMATCH")
    if exit_bar.close_time != case.observation_end:
        raise ValueError("EXIT_CLOSE_TIME_MISMATCH")
    if entry_bar.close_time > exit_bar.open_time:
        raise ValueError("ENTRY_EXIT_TIME_ORDER_INVALID")
    if entry_bar.open <= 0 or exit_bar.close <= 0:
        raise ValueError("NON_POSITIVE_REFERENCE_PRICE")
    if config.quantity_ounces <= 0:
        raise ValueError("quantity_ounces must be positive")
    if config.contract_size_ounces_per_lot <= 0:
        raise ValueError("contract_size_ounces_per_lot must be positive")
    if config.commission_usd_per_lot_round_turn < 0:
        raise ValueError("commission cannot be negative")
    if config.slippage_price_per_side < 0:
        raise ValueError("slippage cannot be negative")
    if config.cost_multiplier < 0:
        raise ValueError("cost multiplier cannot be negative")


def _year_metrics(trades: Sequence[BaselineTrade]) -> dict[str, Any]:
    net = [item.net_pnl_usd for item in trades]
    returns = [item.net_return_basis_points for item in trades]
    gains = math.fsum(value for value in net if value > 0)
    losses = math.fsum(value for value in net if value < 0)
    return {
        "observations": len(trades),
        "net_win_rate_pct": _percentage(
            sum(value > 0 for value in net),
            len(net),
        ),
        "mean_net_pnl_usd_per_ounce": _rounded(statistics.fmean(net)),
        "mean_net_return_basis_points": _rounded(
            statistics.fmean(returns)
        ),
        "total_net_pnl_usd_per_ounce": _rounded(math.fsum(net)),
        "profit_factor": (
            _rounded(gains / abs(losses))
            if losses < 0
            else None
        ),
    }


def _maximum_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _empty_metrics() -> dict[str, Any]:
    return {
        "observations": 0,
        "gross_win_rate_pct": None,
        "net_win_rate_pct": None,
        "mean_gross_pnl_usd_per_ounce": None,
        "median_gross_pnl_usd_per_ounce": None,
        "mean_net_pnl_usd_per_ounce": None,
        "median_net_pnl_usd_per_ounce": None,
        "mean_gross_return_basis_points": None,
        "mean_net_return_basis_points": None,
        "mean_net_return_95pct_normal_ci_basis_points": [None, None],
        "total_gross_pnl_usd_per_ounce": 0.0,
        "total_net_pnl_usd_per_ounce": 0.0,
        "profit_factor": None,
        "maximum_drawdown_usd_per_ounce": 0.0,
        "session_return_sharpe_sqrt_252": None,
        "total_spread_cost_usd_per_ounce": 0.0,
        "total_slippage_cost_usd_per_ounce": 0.0,
        "total_commission_usd_per_ounce": 0.0,
        "total_cost_usd_per_ounce": 0.0,
        "average_holding_minutes": None,
        "long_direction_count": 0,
        "short_direction_count": 0,
        "results_by_year": {},
    }


def _percentage(numerator: int, denominator: int) -> float | None:
    return _rounded(100 * numerator / denominator) if denominator else None


def _rounded(value: float | None) -> float | None:
    return round(value, 8) if value is not None else None
