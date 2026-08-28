from gold_intel.analytics.coherent_auction_human_policy_v2 import (
    contextual_veto_codes,
    core_runner_split,
    human_intent_fidelity,
    net_break_even_stop,
    simulate_track,
    thesis_family,
)


def decision(**overrides):
    payload = {
        "direction": "LONG",
        "fill_price": 100.0,
        "sealed_stop": 99.0,
        "sealed_target": 103.0,
        "annotation": {
            "higher_timeframe_context": "H4 bullish pullback at a prior decision zone",
            "preexisting_location": "H1 support response",
            "m15_transition": "M15 bullish transition",
            "invalidation_condition": "Opposite M15 structural break",
            "target_logic": "Next H1 opposing liquidity area",
            "thesis": "Directional continuation from a prior shift zone",
        },
    }
    payload.update(overrides)
    return payload


def test_semantic_fidelity_requires_ordered_geometry_and_reasoning():
    assert human_intent_fidelity(decision())["detected"] is True
    assert human_intent_fidelity(decision(sealed_stop=101.0))["detected"] is False


def test_m15_range_nested_in_h1_trend_is_continuation():
    item = decision()
    item["annotation"]["higher_timeframe_context"] = "bullish"
    item["annotation"]["thesis"] = (
        "price in a discounted M15 range on an H1 bullish trend"
    )
    assert thesis_family(item, None) == "CONTINUATION_WITH_ROOM"


def test_controlling_h1_range_is_range_rotation_and_damage_has_precedence():
    item = decision()
    item["annotation"]["higher_timeframe_context"] = "H1 was in a range at discount"
    assert thesis_family(item, None) == "RANGE_ROTATION"
    assert thesis_family(item, {"damage_type": "TWO_CLOSE_DAMAGE"}) == "STRUCTURAL_REPAIR"


def test_contextual_vetoes_are_conjunctive_not_single_factor_filters():
    normal = {
        "signed_range_location": 0.90,
        "signed_fifteen_bar_change_atr": 2.25,
    }
    codes = contextual_veto_codes(
        family="CONTINUATION_WITH_ROOM",
        h4=normal,
        m15={"available": True},
        event={"locked": False},
        damage=None,
    )
    assert codes == []

    extended = dict(normal, signed_fifteen_bar_change_atr=3.01)
    codes = contextual_veto_codes(
        family="CONTINUATION_WITH_ROOM",
        h4=extended,
        m15={"available": True},
        event={"locked": False},
        damage=None,
    )
    assert codes == ["EXTREME_HTF_EXTENSION_INTO_OPPOSING_AUCTION"]


def test_range_conflict_and_severe_damage_are_separate_states():
    h4 = {
        "signed_range_location": 0.81,
        "signed_fifteen_bar_change_atr": -3.10,
    }
    codes = contextual_veto_codes(
        family="RANGE_ROTATION",
        h4=h4,
        m15={"available": True},
        event={"locked": False},
        damage={"damage_type": "TWO_CLOSE_DAMAGE"},
    )
    assert codes == [
        "SEVERE_OPPOSING_HTF_IMPULSE",
        "HTF_PREMIUM_RANGE_ROTATION_CONFLICT",
    ]


def test_risk_helpers_are_deterministic():
    assert core_runner_split(9) == (8, 1)
    assert core_runner_split(4) == (4, 0)
    assert net_break_even_stop(fill=100.0, cost_per_ounce=0.1, direction="LONG") == 100.1
    assert net_break_even_stop(fill=100.0, cost_per_ounce=0.1, direction="SHORT") == 99.9


def test_protection_uses_completed_m15_close_and_resolves_at_net_break_even():
    classification = {
        "admitted": True,
        "primary_disposition": "ADMIT",
        "classification_hash": "synthetic",
        "direction": "LONG",
        "family": "CONTINUATION_WITH_ROOM",
        "fill": 100.0,
        "stop": 99.0,
        "target": 103.0,
        "quantity_ounces": 10,
        "cost_per_ounce": 0.1,
        "structural_price_risk_per_ounce": 1.0,
    }
    stream = {
        "end_exclusive": "2022-01-01T00:17:00Z",
        "timeframes": {
            "1m": [
                {
                    "open_at": "2022-01-01T00:01:00Z",
                    "close_at": "2022-01-01T00:02:00Z",
                    "available_at": "2022-01-01T00:02:00Z",
                    "open": 100.0,
                    "high": 101.3,
                    "low": 100.0,
                    "close": 101.3,
                    "complete": True,
                },
                {
                    "open_at": "2022-01-01T00:15:00Z",
                    "close_at": "2022-01-01T00:16:00Z",
                    "available_at": "2022-01-01T00:16:00Z",
                    "open": 100.2,
                    "high": 100.3,
                    "low": 100.0,
                    "close": 100.05,
                    "complete": True,
                },
            ],
            "15m": [
                {
                    "timeframe": "15m",
                    "open_at": "2022-01-01T00:00:00Z",
                    "close_at": "2022-01-01T00:15:00Z",
                    "available_at": "2022-01-01T00:15:00Z",
                    "open": 100.0,
                    "high": 101.5,
                    "low": 100.0,
                    "close": 101.3,
                    "complete": True,
                }
            ],
        },
    }
    fixed = simulate_track(
        classification=classification,
        stream=stream,
        fill_at="2022-01-01T00:01:00Z",
        track="FAITHFUL_FIXED_GEOMETRY",
    )
    protected = simulate_track(
        classification=classification,
        stream=stream,
        fill_at="2022-01-01T00:01:00Z",
        track="PROTECTED_FIXED_GEOMETRY",
    )
    assert fixed["protection_at"] is None
    assert protected["protection_at"] == "2022-01-01T00:15:00Z"
    assert protected["resolution"] == "PROTECTED_STOP"
    assert abs(protected["net_r50"]) < 1e-12
