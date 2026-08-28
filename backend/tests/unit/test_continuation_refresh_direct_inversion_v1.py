from __future__ import annotations

from copy import deepcopy

from gold_intel.analytics.continuation_refresh_direct_inversion_v1 import (
    apply_inversion_population,
    invert_plan,
)


def _plan(direction: str, event_class: str = "CONTINUATION_REFRESH") -> dict:
    return {
        "event_identity": f"{direction.lower()}-event",
        "case_alias": "CBR-2022-001",
        "trading_date_utc": "2022-01-03",
        "decision_at": "2022-01-03T15:00:00Z",
        "session": "NEW_YORK",
        "direction": direction,
        "event_class": event_class,
        "context_family": "TREND_PULLBACK_WITH_LTF_CONTROL",
        "entry": 100.0,
        "stop": 98.0 if direction == "LONG" else 102.0,
        "target": {"level": 106.0 if direction == "LONG" else 94.0},
        "risk_price": 2.0,
        "reward_price": 6.0,
        "planned_r": 3.0,
        "plan_sha256": "original",
    }


def _compiled(plan: dict, executable: bool = True) -> dict:
    return {
        "event_identity": plan["event_identity"],
        "case_alias": plan["case_alias"],
        "trading_date_utc": plan["trading_date_utc"],
        "decision_at": plan["decision_at"],
        "session": plan["session"],
        "direction": plan["direction"],
        "event_class": plan["event_class"],
        "context_family": plan["context_family"],
        "mechanically_executable": executable,
        "disposition": "EXECUTABLE_ALL_TRANSITION" if executable else "HARD_INEXECUTABLE",
        "hard_inexecutable_reasons": [] if executable else ["NO_UNCONSUMED_H1_OR_H4_DESTINATION"],
        "ignored_former_quality_filters": [],
        "classification_sha256": "classification",
        "plan": plan if executable else None,
        "plan_sha256": plan["plan_sha256"],
        "compile_row_sha256": "old",
    }


def test_long_becomes_short_and_tp_becomes_sl_while_sl_becomes_tp():
    inverted = invert_plan(_plan("LONG"))
    assert inverted["direction"] == "SHORT"
    assert inverted["stop"] == 106.0
    assert inverted["target"]["level"] == 98.0
    assert inverted["planned_r"] == 2.0 / 6.0


def test_short_becomes_long_and_tp_becomes_sl_while_sl_becomes_tp():
    inverted = invert_plan(_plan("SHORT"))
    assert inverted["direction"] == "LONG"
    assert inverted["stop"] == 94.0
    assert inverted["target"]["level"] == 102.0
    assert inverted["planned_r"] == 2.0 / 6.0


def test_non_continuation_executable_plan_remains_byte_semantically_unchanged():
    plan = _plan("LONG", "REVERSAL_TRANSFER")
    source = _compiled(plan)
    output = apply_inversion_population([source])[0]
    assert output["continuation_directly_inverted"] is False
    assert output["direction"] == "LONG"
    assert output["plan"] == plan


def test_inexecutable_continuation_is_not_resurrected_or_inverted():
    source = _compiled(_plan("LONG"), executable=False)
    before = deepcopy(source)
    output = apply_inversion_population([source])[0]
    assert output["mechanically_executable"] is False
    assert output["plan"] is None
    assert output["continuation_directly_inverted"] is False
    assert output["source_direction"] == before["direction"]
