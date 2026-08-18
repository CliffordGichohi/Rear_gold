from __future__ import annotations

from tools import maoascr_v1_engine as engine


def test_chronological_fold_boundaries() -> None:
    assert engine.fold_for("2021-12-31") is None
    assert engine.fold_for("2022-01-01") == 1
    assert engine.fold_for("2022-07-01") == 2
    assert engine.fold_for("2024-12-31") == 6
    assert engine.fold_for("2025-01-01") is None


def test_multiplicity_adjustments_are_deterministic() -> None:
    pairs = [("a", 0.01), ("b", 0.04), ("c", 0.03)]
    assert engine.benjamini_hochberg(pairs) == {"a": 0.03, "b": 0.04, "c": 0.04}
    assert engine.holm_adjust(pairs) == {"a": 0.03, "b": 0.06, "c": 0.06}


def test_primary_endpoint_dispositions() -> None:
    assert engine.resolved_label({"exit_reason": "TARGET"}) == 1
    assert engine.resolved_label({"exit_reason": "STOP_FIRST_AMBIGUOUS"}) == 0
    assert engine.resolved_label({"exit_reason": "TIME_EXIT"}) is None


def _prediction(case_id: str, instrument: str, cluster: str, entry: int, exit_minute: int, timeframe: str = "M15") -> dict[str, object]:
    return {
        "case_id": case_id, "instrument": instrument, "cluster": cluster,
        "entry_minute": entry, "exit_minute": exit_minute, "timeframe": timeframe,
        "router_positive": True, "realized_net_r": 0.8,
        "realized_stress_net_r": 0.7, "realized_net_pnl_usd": 80.0,
    }


def test_router_uses_earliest_checkpoint_and_cluster_cap() -> None:
    rows = [
        _prediction("case-a", "EURUSD", "USD_FX", 100, 120, "H1"),
        _prediction("case-a", "EURUSD", "USD_FX", 90, 110, "M15"),
        _prediction("case-b", "USDJPY", "USD_FX", 100, 130),
        _prediction("case-c", "XAGUSD", "PRECIOUS_METALS", 100, 130),
    ]
    result = {row["case_id"]: row for row in engine.route_portfolio(rows)}
    assert result["case-a"]["timeframe"] == "M15"
    assert result["case-a"]["portfolio_accepted"] is True
    assert result["case-b"]["portfolio_accepted"] is False
    assert result["case-b"]["portfolio_rejection"] == "CONCURRENT_CLUSTER_RISK_CAP"
    assert result["case-c"]["portfolio_accepted"] is True


def test_registry_excludes_realised_outcomes() -> None:
    forbidden = {"archetype", "mfe", "mae", "future_extrema", "target_before_stop", "realized_net_r"}
    assert not forbidden.intersection({name.lower() for name in engine.NUMERIC_FEATURES})

