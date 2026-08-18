from __future__ import annotations

from tools.external_evidence_replication_v1_engine import (
    CANDIDATE_ORDER,
    candidate_direction,
    floor_step,
    holm_adjust,
    select_portfolio,
)


def test_published_direction_rules() -> None:
    positive = {"r1": 0.01, "r12": 0.02}
    mixed = {"r1": 0.01, "r12": -0.02}
    negative = {"r1": -0.01, "r12": 0.0}
    assert candidate_direction(CANDIDATE_ORDER[0], positive) == 1
    assert candidate_direction(CANDIDATE_ORDER[0], negative) == -1
    assert candidate_direction(CANDIDATE_ORDER[1], positive) == 1
    assert candidate_direction(CANDIDATE_ORDER[1], mixed) == 0
    assert candidate_direction(CANDIDATE_ORDER[1], negative) == -1


def test_holm_is_order_safe() -> None:
    adjusted = holm_adjust([0.01, 0.04, 0.03])
    assert adjusted == [0.03, 0.06, 0.06]


def test_volume_rounding_never_rounds_up() -> None:
    assert floor_step(1.09, 0.1) == 1.0
    assert floor_step(0.49, 0.5) == 0.0


def test_frozen_family_priority() -> None:
    results = [
        {"candidate_id": CANDIDATE_ORDER[0], "verdict": "PASS"},
        {"candidate_id": CANDIDATE_ORDER[1], "verdict": "PASS"},
        {"candidate_id": CANDIDATE_ORDER[2], "verdict": "PASS"},
    ]
    assert select_portfolio(results) == [CANDIDATE_ORDER[0], CANDIDATE_ORDER[2]]

