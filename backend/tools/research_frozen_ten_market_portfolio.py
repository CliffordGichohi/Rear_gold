from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from research_cross_instrument_transfer import (
    EXPECTED_INSTRUMENTS,
    FROZEN_HYPOTHESES,
    FrozenHypothesis,
    _portfolio_bundle,
)
from research_daily_session_playbooks import Trade
from research_multi_asset_session_portfolio import _accepted_portfolio_trades
from research_session_state_transitions import Candidate

SOURCE_INSTRUMENTS = frozenset({"EURUSD", "US500", "XAGUSD", "XAUUSD"})
LOCKED_HOLDOUT = datetime(2025, 1, 1, tzinfo=UTC)
REQUIRED_COLUMNS = frozenset(
    {
        "playbook",
        "session_date",
        "side",
        "signal_time",
        "entry_time",
        "exit_time",
        "exit_reason",
        "manager",
        "cost_multiplier",
        "gross_r",
        "net_r",
        "cost_r",
        "mfe_r",
        "mae_r",
        "holding_minutes",
        "risk_distance",
        "instrument",
        "cluster",
        "signed_trend_240_atr",
        "volatility_ratio",
        "relative_volume",
    }
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the predeclared four-mechanism portfolio across the "
            "four source and six transfer instruments."
        ),
    )
    parser.add_argument("--source-cache", type=Path, required=True)
    parser.add_argument("--transfer-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    source = _load_cache(
        args.source_cache,
        expected_instruments=SOURCE_INSTRUMENTS,
    )
    transfer = _load_cache(
        args.transfer_cache,
        expected_instruments=EXPECTED_INSTRUMENTS,
    )
    source_candidates, source_trades = _candidate_results(source)
    transfer_candidates, transfer_trades = _candidate_results(transfer)
    combined = pd.concat([source, transfer], ignore_index=True)
    combined_candidates, combined_trades = _candidate_results(combined)

    source_bundle = _portfolio_bundle(
        source_candidates,
        candidate_trades=source_trades,
    )
    source_bundle["daily_return_correlation"] = _correlation_report(
        source_candidates,
        candidate_trades=source_trades,
    )
    source_bundle["risk_gate"] = _risk_gate(source_bundle)
    transfer_bundle = _portfolio_bundle(
        transfer_candidates,
        candidate_trades=transfer_trades,
    )
    transfer_bundle["daily_return_correlation"] = _correlation_report(
        transfer_candidates,
        candidate_trades=transfer_trades,
    )
    transfer_bundle["risk_gate"] = _risk_gate(transfer_bundle)
    combined_bundle = _portfolio_bundle(
        combined_candidates,
        candidate_trades=combined_trades,
    )
    combined_bundle["daily_return_correlation"] = _correlation_report(
        combined_candidates,
        candidate_trades=combined_trades,
    )
    combined_bundle["risk_gate"] = _risk_gate(combined_bundle)
    transfer_gate = _transfer_stability_gate(transfer_bundle)
    combined_gate = bool(
        combined_bundle["positive_each_development_year"]["passed"]
        and combined_bundle["ten_r_monthly_promotion_gate"]["passed_screen"]
        and combined_bundle["daily_return_correlation"]["passed"]
        and combined_bundle["risk_gate"]["passed"]
    )
    report = {
        "contract": {
            "version": "FROZEN_TEN_MARKET_PORTFOLIO_V0_1",
            "locked_holdout": "calendar year 2025 (not loaded)",
            "source_instruments": sorted(SOURCE_INSTRUMENTS),
            "transfer_instruments": sorted(EXPECTED_INSTRUMENTS),
            "construction": (
                "The four structures, context filters, targets, candidate "
                "priority, one-position-per-cluster rule, two-position account "
                "capacity, -3R daily stop, and cost model were frozen before "
                "the transfer results were read."
            ),
            "promotion": (
                "The six untouched instruments must first pass the annual and "
                "cost/stability transfer gate. The ten-market portfolio must "
                "then pass annual stability and average at least 10R/month in "
                "discovery, 2023, and 2024, with no absolute pairwise daily "
                "return correlation above 0.80, no segment drawdown above 15R, "
                "no full-period drawdown above 20R, and no month below -8R "
                "before calendar 2025 may be opened."
            ),
        },
        "frozen_hypotheses": [
            {
                "name": hypothesis.name,
                "family": hypothesis.family,
                "rule": hypothesis.rule,
                "manager": hypothesis.manager,
            }
            for hypothesis in FROZEN_HYPOTHESES
        ],
        "inputs": {
            "source_cache": _file_manifest(args.source_cache),
            "transfer_cache": _file_manifest(args.transfer_cache),
        },
        "source_market_development": source_bundle,
        "untouched_market_transfer": transfer_bundle,
        "combined_ten_market_portfolio": combined_bundle,
        "promotion_verdict": {
            "transfer_stability_passed": transfer_gate,
            "combined_10r_gate_passed": combined_gate,
            "passed": bool(transfer_gate and combined_gate),
            "open_2025_holdout": bool(transfer_gate and combined_gate),
        },
    }
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if args.output is None:
        print(serialized)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": True,
                    "output": str(args.output),
                    **report["promotion_verdict"],
                },
                indent=2,
            ),
        )


def _load_cache(
    path: Path,
    *,
    expected_instruments: frozenset[str],
) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        compression="infer",
        parse_dates=["signal_time", "entry_time", "exit_time"],
    )
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise RuntimeError(f"Context cache is missing columns: {sorted(missing)}")
    instruments = frozenset(frame["instrument"].astype(str).unique())
    if instruments != expected_instruments:
        raise RuntimeError(
            f"Cache instrument mismatch: expected={sorted(expected_instruments)}, "
            f"actual={sorted(instruments)}"
        )
    latest = frame["signal_time"].max()
    if latest.tzinfo is None or latest.to_pydatetime() >= LOCKED_HOLDOUT:
        raise RuntimeError("Locked calendar-2025 data leaked into a context cache")
    duplicate_columns = [
        "playbook",
        "signal_time",
        "side",
        "manager",
        "cost_multiplier",
    ]
    if frame.duplicated(duplicate_columns).any():
        raise RuntimeError("Duplicate signal-manager rows in context cache")
    return frame


def _candidate_results(
    frame: pd.DataFrame,
) -> tuple[list[Candidate], dict[tuple[str, float], list[Trade]]]:
    playbooks = sorted(frame["playbook"].astype(str).unique())
    candidates = [
        Candidate(playbook, hypothesis.rule, hypothesis.manager)
        for hypothesis in FROZEN_HYPOTHESES
        for playbook in playbooks
        if playbook.rsplit("|", 1)[-1] == hypothesis.family
    ]
    output: dict[tuple[str, float], list[Trade]] = {}
    for candidate in candidates:
        hypothesis = _hypothesis(candidate)
        scope = frame[
            (frame["playbook"] == candidate.archetype)
            & (frame["manager"] == candidate.manager)
            & _rule_mask(frame, hypothesis)
        ]
        for multiplier in (1.0, 1.5):
            output[(candidate.key, multiplier)] = [
                _trade(row)
                for _, row in scope[
                    scope["cost_multiplier"].round(2) == multiplier
                ].iterrows()
            ]
    return candidates, output


def _hypothesis(candidate: Candidate) -> FrozenHypothesis:
    family = candidate.archetype.rsplit("|", 1)[-1]
    matches = [
        hypothesis
        for hypothesis in FROZEN_HYPOTHESES
        if hypothesis.family == family
        and hypothesis.rule == candidate.rule
        and hypothesis.manager == candidate.manager
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Candidate has no unique frozen hypothesis: {candidate.key}")
    return matches[0]


def _rule_mask(
    frame: pd.DataFrame,
    hypothesis: FrozenHypothesis,
) -> pd.Series:
    if hypothesis.rule == "RELATIVE_VOLUME_1_20X":
        return frame["relative_volume"] >= 1.20
    if hypothesis.rule == "TREND_240_ALIGNED":
        return frame["signed_trend_240_atr"] > 0
    if hypothesis.rule == "VOLATILITY_EXPANSION":
        return frame["volatility_ratio"] >= 1.10
    raise RuntimeError(f"Unsupported frozen rule: {hypothesis.rule}")


def _trade(row: pd.Series) -> Trade:
    signal_time = _timestamp(row["signal_time"])
    entry_time = _timestamp(row["entry_time"])
    exit_time = _timestamp(row["exit_time"])
    evidence = {
        "instrument": str(row["instrument"]),
        "cluster": str(row["cluster"]),
        "target_r": _optional_float(row.get("target_r")),
        "cost_multiplier": float(row["cost_multiplier"]),
    }
    return Trade(
        playbook=str(row["playbook"]),
        session_date=date.fromisoformat(str(row["session_date"])),
        side=str(row["side"]),
        signal_time=signal_time,
        entry_time=entry_time,
        exit_time=exit_time,
        exit_reason=str(row["exit_reason"]),
        risk_distance=float(row["risk_distance"]),
        gross_r=float(row["gross_r"]),
        net_r=float(row["net_r"]),
        cost_r=float(row["cost_r"]),
        mfe_r=float(row["mfe_r"]),
        mae_r=float(row["mae_r"]),
        holding_minutes=int(row["holding_minutes"]),
        evidence=evidence,
    )


def _timestamp(value: Any) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise RuntimeError(f"Timezone-naive timestamp in cache: {value}")
    return timestamp.to_pydatetime().astimezone(UTC)


def _optional_float(value: Any) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _transfer_stability_gate(bundle: dict[str, Any]) -> bool:
    target = bundle["ten_r_monthly_promotion_gate"]
    return bool(
        bundle["positive_each_development_year"]["passed"]
        and all(target["positive_expectancy_at_1_50x_costs"].values())
        and all(target["positive_median_and_55pct_positive_months"].values())
        and target["diversification_check"]
        and bundle["daily_return_correlation"]["passed"]
        and bundle["risk_gate"]["passed"]
    )


def _risk_gate(bundle: dict[str, Any]) -> dict[str, Any]:
    base = bundle["base_cost"]
    periods = ("discovery", "validation_2023", "forward_2024")
    checks = {
        period: {
            "max_drawdown_le_15r": (
                float(base[period]["maximum_drawdown_r"]) <= 15.0
            ),
            "worst_month_ge_minus_8r": (
                float(base[period]["worst_month_r"]) >= -8.0
            ),
            "max_consecutive_losses_le_12": (
                int(base[period]["maximum_consecutive_losses"]) <= 12
            ),
        }
        for period in periods
    }
    full_period = {
        "max_drawdown_le_20r": (
            float(base["all_pre_2025"]["maximum_drawdown_r"]) <= 20.0
        ),
        "worst_month_ge_minus_8r": (
            float(base["all_pre_2025"]["worst_month_r"]) >= -8.0
        ),
        "max_consecutive_losses_le_12": (
            int(base["all_pre_2025"]["maximum_consecutive_losses"]) <= 12
        ),
    }
    return {
        "one_r_account_risk_pct": 1.0,
        "period_checks": checks,
        "full_period_checks": full_period,
        "passed": bool(
            all(all(values.values()) for values in checks.values())
            and all(full_period.values())
        ),
    }


def _correlation_report(
    candidates: Sequence[Candidate],
    *,
    candidate_trades: dict[tuple[str, float], list[Trade]],
) -> dict[str, Any]:
    accepted, _ = _accepted_portfolio_trades(
        candidates,
        candidate_trades=candidate_trades,
        cost_multiplier=1.0,
    )
    instruments = sorted(
        {
            str(trade.evidence["instrument"])
            for trade in accepted
        }
    )
    calendar = pd.date_range(
        start="2021-08-01",
        end="2024-12-31",
        freq="D",
    )
    daily = pd.DataFrame(0.0, index=calendar, columns=instruments)
    active_days = {instrument: set() for instrument in instruments}
    for trade in accepted:
        instrument = str(trade.evidence["instrument"])
        timestamp = pd.Timestamp(trade.session_date)
        daily.loc[timestamp, instrument] += trade.net_r
        active_days[instrument].add(trade.session_date)
    correlation = daily.corr() if instruments else pd.DataFrame()
    pairs: list[dict[str, Any]] = []
    for left_index, left in enumerate(instruments):
        for right in instruments[left_index + 1 :]:
            raw_value = correlation.loc[left, right]
            value = None if pd.isna(raw_value) else round(float(raw_value), 6)
            pairs.append(
                {
                    "left": left,
                    "right": right,
                    "correlation": value,
                },
            )
    maximum = max(
        (
            abs(float(pair["correlation"]))
            for pair in pairs
            if pair["correlation"] is not None
        ),
        default=None,
    )
    return {
        "method": (
            "Pearson correlation of calendar-daily accepted net R with "
            "no-trade days filled by zero."
        ),
        "threshold_max_absolute_pairwise": 0.80,
        "max_absolute_pairwise": (
            round(maximum, 6) if maximum is not None else None
        ),
        "passed": bool(maximum is not None and maximum <= 0.80),
        "active_days_by_instrument": {
            instrument: len(days)
            for instrument, days in active_days.items()
        },
        "pairs": pairs,
    }


def _file_manifest(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


if __name__ == "__main__":
    main()
