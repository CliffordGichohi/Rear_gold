from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cache", type=Path)
    args = parser.parse_args()
    frame = pd.read_csv(args.cache, parse_dates=["session_date"])
    if frame.empty:
        raise RuntimeError("Context cache is empty")
    if (frame["session_date"] >= pd.Timestamp("2025-01-01")).any():
        raise RuntimeError("Locked 2025 records were loaded")

    base = frame[frame["cost_multiplier"] == 1.0].copy()
    report = {
        "contract": {
            "version": "RATES_POLICY_TARGET_DIAGNOSTIC_V0_1",
            "purpose": (
                "Test whether same-direction intraday Treasury confirmation has "
                "a stable relationship with realized auction execution returns. "
                "This is a diagnostic, not a strategy selection."
            ),
            "cache_sha256": _sha256(args.cache),
            "locked_holdout": "calendar year 2025 absent",
        },
        "rows": len(base),
        "managers": {
            manager: _manager_report(members)
            for manager, members in base.groupby("manager", sort=True)
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def _manager_report(frame: pd.DataFrame) -> dict[str, Any]:
    output: dict[str, Any] = {
        "trades": len(frame),
        "by_horizon": {},
    }
    for horizon in (5, 15, 60):
        members = frame.copy()
        zt = members[f"ZT.v.0|aligned_{horizon}"]
        zn = members[f"ZN.v.0|aligned_{horizon}"]
        members["treasury_state"] = np.select(
            [
                zt.isna() | zn.isna(),
                (zt > 0) & (zn > 0),
                (zt < 0) & (zn < 0),
            ],
            ["UNKNOWN", "CONFIRM", "OPPOSE"],
            default="MIXED_OR_FLAT",
        )
        output["by_horizon"][str(horizon)] = {
            "all_pre_2025": _state_groups(members),
            "by_period": {
                label: _state_groups(_period(members, label))
                for label in ("discovery", "validation_2023", "forward_2024")
            },
            "rank_correlation": _rank_correlations(
                members,
                feature=f"treasury_{horizon}",
            ),
            "families": {
                family: _state_groups(group)
                for family, group in members.groupby("family", sort=True)
                if len(group) >= 20
            },
        }
    return output


def _state_groups(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        str(state): _metrics(group) for state, group in frame.groupby("treasury_state", sort=True)
    }


def _rank_correlations(
    frame: pd.DataFrame,
    *,
    feature: str,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    periods = {
        "all_pre_2025": frame,
        "2022": frame[frame["session_date"].dt.year == 2022],
        "2023": frame[frame["session_date"].dt.year == 2023],
        "2024": frame[frame["session_date"].dt.year == 2024],
    }
    for label, members in periods.items():
        clean = members[[feature, "net_r", "mfe_r", "mae_r"]].dropna()
        if len(clean) < 15 or clean[feature].nunique() < 3:
            output[label] = {"n": len(clean), "net_r": None, "mfe_r": None}
            continue
        feature_rank = clean[feature].rank(method="average")
        output[label] = {
            "n": len(clean),
            "net_r": _finite_round(feature_rank.corr(clean["net_r"].rank())),
            "mfe_r": _finite_round(feature_rank.corr(clean["mfe_r"].rank())),
            "mae_r": _finite_round(feature_rank.corr(clean["mae_r"].rank())),
        }
    return output


def _period(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    if label == "discovery":
        return frame[frame["session_date"] < pd.Timestamp("2023-01-01")]
    if label == "validation_2023":
        return frame[
            (frame["session_date"] >= pd.Timestamp("2023-01-01"))
            & (frame["session_date"] < pd.Timestamp("2024-01-01"))
        ]
    if label == "forward_2024":
        return frame[
            (frame["session_date"] >= pd.Timestamp("2024-01-01"))
            & (frame["session_date"] < pd.Timestamp("2025-01-01"))
        ]
    raise ValueError(label)


def _metrics(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"trades": 0}
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
        "average_mfe_r": round(float(frame["mfe_r"].mean()), 6),
        "average_mae_r": round(float(frame["mae_r"].mean()), 6),
    }


def _finite_round(value: float) -> float | None:
    return round(float(value), 6) if math.isfinite(float(value)) else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
