from gold_intel.analytics.direction_symmetric_control_router_v2 import (
    earliest_trade,
    required_control,
    route_candidate,
)


def candidate(direction: str, *, executable: bool = True) -> dict:
    result = (
        {"executed": True, "net_r50": 1.0, "result_hash": f"result-{direction}"}
        if executable
        else None
    )
    return {
        "row_sha256": f"row-{direction}",
        "signal_at": "2022-01-03T14:00:00Z",
        "direction": direction,
        "disposition": "TARGET" if executable else "ORIGINAL_CONTEXT_REJECTED",
        "corrected": {"effective_result": result},
    }


def test_direction_requires_the_semantic_opposite_control() -> None:
    assert required_control("LONG") == "BUYER_CONTROL"
    assert required_control("SHORT") == "SELLER_CONTROL"


def test_long_and_short_are_gated_symmetrically() -> None:
    long = candidate("LONG")
    short = candidate("SHORT")

    admitted_long = route_candidate(
        candidate=long, control={"state": "BUYER_CONTROL"}
    )
    admitted_short = route_candidate(
        candidate=short, control={"state": "SELLER_CONTROL"}
    )
    vetoed_long = route_candidate(
        candidate=long, control={"state": "SELLER_CONTROL"}
    )
    vetoed_short = route_candidate(
        candidate=short, control={"state": "BUYER_CONTROL"}
    )

    assert admitted_long["admitted"] is True
    assert admitted_short["admitted"] is True
    assert vetoed_long["disposition"] == "VETO_SELLER_CONTROL"
    assert vetoed_short["disposition"] == "VETO_BUYER_CONTROL"


def test_gate_never_repairs_a_source_rejection() -> None:
    routed = route_candidate(
        candidate=candidate("SHORT", executable=False),
        control={"state": "SELLER_CONTROL"},
    )
    assert routed["admitted"] is False
    assert routed["effective_result"] is None
    assert routed["disposition"].startswith("SOURCE_NOT_EXECUTABLE::")


def test_combined_track_selects_earliest_fill_without_outcome_input() -> None:
    long = {"direction": "LONG", "fill_at": "2022-01-03T15:00:00Z"}
    short = {"direction": "SHORT", "fill_at": "2022-01-03T14:00:00Z"}
    assert earliest_trade(long, short) is short
    short["fill_at"] = long["fill_at"]
    assert earliest_trade(long, short) is long
