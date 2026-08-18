from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MANAGERS = (
    "FIXED_1_50R",
    "FIXED_2_00R",
    "FIXED_3_00R",
    "FIXED_4_00R",
)


@dataclass(frozen=True, slots=True)
class Candidate:
    playbook: str
    permission: str
    manager: str

    @property
    def key(self) -> str:
        return f"{self.playbook}|{self.permission}|{self.manager}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cache", type=Path)
    args = parser.parse_args()
    frame = pd.read_csv(
        args.cache,
        parse_dates=["session_date", "signal_time", "entry_time", "exit_time"],
    )
    if frame.empty:
        raise RuntimeError("Context cache is empty")
    if (frame["session_date"] >= pd.Timestamp("2025-01-01")).any():
        raise RuntimeError("Locked 2025 records were loaded")
    frame = _add_permissions(frame)

    snapshots, base = _walk_forward(frame, cost_multiplier=1.0)
    _, stressed = _walk_forward(
        frame,
        cost_multiplier=1.5,
        frozen_snapshots=snapshots,
    )
    report = {
        "contract": {
            "version": "WALK_FORWARD_RATES_PORTFOLIO_V0_1",
            "source_cache_sha256": _sha256(args.cache),
            "locked_holdout": "calendar year 2025 absent",
            "training_window": "trailing 12 complete calendar months",
            "first_evaluation_month": "2022-08",
            "selection": (
                "At each month boundary, each playbook may select one permission "
                "and fixed-R exit using only the preceding 12 complete months. "
                "Training requires n>=20, expectancy>=0.10R, PF>=1.15, positive "
                "1.50x-cost expectancy, and both six-month halves above -0.05R."
            ),
            "execution": (
                "One open gold trade at a time; no new trade after -2R realized on a session date."
            ),
            "target": (
                "10R average per calendar month at 1% risk is a hard promotion "
                "hurdle, not an assumed return."
            ),
        },
        "candidate_count": _candidate_count(frame),
        "monthly_model_snapshots": snapshots,
        "base_cost": _report(base),
        "cost_stress_1_50x": _report(stressed),
        "promotion_gates": _promotion_gates(base, stressed),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def _add_permissions(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for horizon in (5, 15, 60):
        zt = output[f"ZT.v.0|aligned_{horizon}"]
        zn = output[f"ZN.v.0|aligned_{horizon}"]
        output[f"treasury_both_{horizon}"] = (zt > 0) & (zn > 0)
    output["permission_BASE"] = True
    output["permission_TREASURY_5_BOTH"] = output["treasury_both_5"]
    output["permission_TREASURY_15_BOTH"] = output["treasury_both_15"]
    output["permission_TREASURY_15_STRONG"] = output["treasury_both_15"] & (
        output["treasury_15"] >= 0.50
    )
    output["permission_TREASURY_15_60"] = output["treasury_both_15"] & output["treasury_both_60"]
    output["permission_MACRO_AND_TREASURY_15"] = (
        output["signed_fundamental_score"] >= -5
    ) & output["treasury_both_15"]
    output["permission_EVENT_CLEAR_TREASURY_15"] = (
        output["minutes_to_catalyst"].isna() | (output["minutes_to_catalyst"] > 30)
    ) & output["treasury_both_15"]
    output["permission_POST_EVENT_TREASURY_15"] = (
        output["event_age_hours"].between(0, 2, inclusive="both") & output["treasury_both_15"]
    )
    return output


def _permissions(frame: pd.DataFrame) -> list[str]:
    return sorted(
        column.removeprefix("permission_")
        for column in frame.columns
        if column.startswith("permission_")
    )


def _candidate_count(frame: pd.DataFrame) -> int:
    return frame["playbook"].nunique() * len(_permissions(frame)) * len(MANAGERS)


def _walk_forward(
    frame: pd.DataFrame,
    *,
    cost_multiplier: float,
    frozen_snapshots: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    months = pd.period_range("2022-08", "2024-12", freq="M")
    snapshots: list[dict[str, Any]] = []
    accepted_months: list[pd.DataFrame] = []
    frozen = {str(item["model_month"]): item for item in (frozen_snapshots or [])}
    for month in months:
        month_start = month.start_time
        month_end = (month + 1).start_time
        training_start = month_start - pd.DateOffset(months=12)
        if frozen_snapshots is None:
            selected = _select_candidates(
                frame,
                training_start=training_start,
                training_end=month_start,
            )
            snapshot = {
                "model_month": str(month),
                "training_start": training_start.date().isoformat(),
                "training_end_exclusive": month_start.date().isoformat(),
                "selected": [
                    {
                        "key": item.key,
                        "playbook": item.playbook,
                        "permission": item.permission,
                        "manager": item.manager,
                        **_training_metrics(
                            frame,
                            item,
                            start=training_start,
                            end=month_start,
                        ),
                    }
                    for item in selected
                ],
            }
            snapshots.append(snapshot)
        else:
            snapshot = frozen[str(month)]
            selected = [
                Candidate(
                    str(item["playbook"]),
                    str(item["permission"]),
                    str(item["manager"]),
                )
                for item in snapshot["selected"]
            ]
        members = _month_candidates(
            frame,
            selected,
            start=month_start,
            end=month_end,
            cost_multiplier=cost_multiplier,
        )
        accepted = _portfolio(members)
        if not accepted.empty:
            accepted_months.append(accepted)
    combined = (
        pd.concat(accepted_months, ignore_index=True) if accepted_months else frame.iloc[0:0].copy()
    )
    return snapshots, combined


def _select_candidates(
    frame: pd.DataFrame,
    *,
    training_start: pd.Timestamp,
    training_end: pd.Timestamp,
) -> list[Candidate]:
    selected: list[Candidate] = []
    for playbook in sorted(frame["playbook"].dropna().unique()):
        eligible: list[tuple[Candidate, dict[str, Any]]] = []
        for permission in _permissions(frame):
            for manager in MANAGERS:
                candidate = Candidate(str(playbook), permission, manager)
                metrics = _training_metrics(
                    frame,
                    candidate,
                    start=training_start,
                    end=training_end,
                )
                if bool(metrics["eligible"]):
                    eligible.append((candidate, metrics))
        if eligible:
            selected.append(
                max(
                    eligible,
                    key=lambda item: (
                        float(item[1]["expectancy_r"]),
                        float(item[1]["profit_factor"]),
                        int(item[1]["trades"]),
                    ),
                )[0],
            )
    return selected


def _training_metrics(
    frame: pd.DataFrame,
    candidate: Candidate,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    base = _candidate_rows(
        frame,
        candidate,
        start=start,
        end=end,
        cost_multiplier=1.0,
    )
    stressed = _candidate_rows(
        frame,
        candidate,
        start=start,
        end=end,
        cost_multiplier=1.5,
    )
    midpoint = start + (end - start) / 2
    first = base[base["session_date"] < midpoint]
    second = base[base["session_date"] >= midpoint]
    metrics = _metrics(base)
    stress_metrics = _metrics(stressed)
    first_expectancy = _expectancy(first)
    second_expectancy = _expectancy(second)
    eligible = bool(
        metrics["trades"] >= 20
        and metrics["expectancy_r"] is not None
        and float(metrics["expectancy_r"]) >= 0.10
        and metrics["profit_factor"] is not None
        and float(metrics["profit_factor"]) >= 1.15
        and stress_metrics["expectancy_r"] is not None
        and float(stress_metrics["expectancy_r"]) > 0
        and first_expectancy is not None
        and first_expectancy >= -0.05
        and second_expectancy is not None
        and second_expectancy >= -0.05
    )
    return {
        **metrics,
        "stress_expectancy_r": stress_metrics["expectancy_r"],
        "first_half_expectancy_r": first_expectancy,
        "second_half_expectancy_r": second_expectancy,
        "eligible": eligible,
    }


def _candidate_rows(
    frame: pd.DataFrame,
    candidate: Candidate,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cost_multiplier: float,
) -> pd.DataFrame:
    return frame[
        (frame["session_date"] >= start)
        & (frame["session_date"] < end)
        & (frame["playbook"] == candidate.playbook)
        & (frame["manager"] == candidate.manager)
        & np.isclose(frame["cost_multiplier"], cost_multiplier)
        & frame[f"permission_{candidate.permission}"]
    ]


def _month_candidates(
    frame: pd.DataFrame,
    selected: list[Candidate],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cost_multiplier: float,
) -> pd.DataFrame:
    members = [
        _candidate_rows(
            frame,
            candidate,
            start=start,
            end=end,
            cost_multiplier=cost_multiplier,
        ).assign(candidate_key=candidate.key, priority=index)
        for index, candidate in enumerate(selected)
    ]
    return pd.concat(members, ignore_index=True) if members else frame.iloc[0:0].copy()


def _portfolio(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    ordered = frame.sort_values(
        ["entry_time", "priority", "playbook"],
    )
    accepted: list[int] = []
    open_until: pd.Timestamp | None = None
    realized_by_day: dict[date, float] = defaultdict(float)
    for index, row in ordered.iterrows():
        entry_time = pd.Timestamp(row["entry_time"])
        session_day = pd.Timestamp(row["session_date"]).date()
        if open_until is not None and entry_time < open_until:
            continue
        if realized_by_day[session_day] <= -2.0:
            continue
        accepted.append(index)
        open_until = pd.Timestamp(row["exit_time"])
        realized_by_day[session_day] += float(row["net_r"])
    return ordered.loc[accepted].copy()


def _report(frame: pd.DataFrame) -> dict[str, Any]:
    metrics = _metrics(frame)
    months = pd.period_range("2022-08", "2024-12", freq="M")
    r_by_month = {
        str(month): float(
            frame.loc[
                frame["session_date"].dt.to_period("M") == month,
                "net_r",
            ].sum(),
        )
        for month in months
    }
    values = list(r_by_month.values())
    by_year = {
        str(year): _metrics(
            frame[frame["session_date"].dt.year == year],
        )
        for year in (2022, 2023, 2024)
    }
    return {
        **metrics,
        "calendar_months": len(months),
        "average_monthly_r": round(statistics.mean(values), 6),
        "median_monthly_r": round(statistics.median(values), 6),
        "positive_month_pct": round(
            sum(value > 0 for value in values) / len(values) * 100,
            4,
        ),
        "target_10r_month_pct": round(
            sum(value >= 10 for value in values) / len(values) * 100,
            4,
        ),
        "best_month_r": round(max(values), 6),
        "worst_month_r": round(min(values), 6),
        "by_year": by_year,
        "monthly_r": {key: round(value, 6) for key, value in r_by_month.items()},
        "maximum_drawdown_r": _maximum_drawdown(
            frame.sort_values("entry_time")["net_r"].astype(float).tolist(),
        ),
    }


def _promotion_gates(
    base: pd.DataFrame,
    stressed: pd.DataFrame,
) -> dict[str, Any]:
    base_report = _report(base)
    stress_report = _report(stressed)
    annual = {
        year: (
            base_report["by_year"][year]["trades"] >= 15
            and base_report["by_year"][year]["expectancy_r"] is not None
            and float(base_report["by_year"][year]["expectancy_r"]) > 0
        )
        for year in ("2022", "2023", "2024")
    }
    return {
        "positive_each_evaluation_year": annual,
        "profit_factor_ge_1_20": (
            base_report["profit_factor"] is not None and float(base_report["profit_factor"]) >= 1.20
        ),
        "positive_at_1_50x_cost": (
            stress_report["expectancy_r"] is not None and float(stress_report["expectancy_r"]) > 0
        ),
        "average_monthly_r_ge_10": base_report["average_monthly_r"] >= 10,
        "passed": bool(
            all(annual.values())
            and base_report["profit_factor"] is not None
            and float(base_report["profit_factor"]) >= 1.20
            and stress_report["expectancy_r"] is not None
            and float(stress_report["expectancy_r"]) > 0
            and base_report["average_monthly_r"] >= 10
        ),
    }


def _metrics(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "trades": 0,
            "win_rate_pct": None,
            "expectancy_r": None,
            "profit_factor": None,
            "total_net_r": 0.0,
        }
    net = frame["net_r"].astype(float)
    winners = net[net > 0]
    losers = net[net < 0]
    return {
        "trades": len(frame),
        "win_rate_pct": round(float((net > 0).mean() * 100), 4),
        "expectancy_r": round(float(net.mean()), 6),
        "profit_factor": (
            round(float(winners.sum() / abs(losers.sum())), 6)
            if not winners.empty and not losers.empty
            else None
        ),
        "total_net_r": round(float(net.sum()), 6),
    }


def _expectancy(frame: pd.DataFrame) -> float | None:
    return round(float(frame["net_r"].mean()), 6) if not frame.empty else None


def _maximum_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return round(maximum, 6)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
