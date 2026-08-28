from __future__ import annotations

from gold_intel.analytics.liquidity_shift_v4 import (
    build_liquidity_response_m5_state_study_v4,
)
from tests.unit.test_liquidity_shift_v2 import _scenario


def test_zone_reaction_can_activate_without_a_new_m15_transition() -> None:
    study = build_liquidity_response_m5_state_study_v4(_scenario())

    assert study.locations
    assert study.breaks
    assert study.activations
    assert all(
        activation.started_at < activation.terminal_at
        for activation in study.activations
    )
    assert all(
        activation.location_identity in {item.identity for item in study.locations}
        for activation in study.activations
    )


def test_v4_entries_are_causal_and_have_structural_geometry() -> None:
    study = build_liquidity_response_m5_state_study_v4(_scenario())
    activation_by_id = {item.identity: item for item in study.activations}

    assert len(study.entry_intents) == 2 * len(study.activations)
    for intent in study.entry_intents:
        activation = activation_by_id[intent.activation_identity]
        assert intent.order_at == activation.started_at
        assert intent.expires_at == activation.terminal_at
        assert intent.triggered_at is None or intent.triggered_at >= intent.order_at
        if intent.state != "INVALID_GEOMETRY":
            assert intent.entry_reference is not None
            assert intent.stop is not None
            if intent.direction == "BULLISH":
                assert intent.stop < intent.entry_reference
            else:
                assert intent.stop > intent.entry_reference


def test_v4_cutoff_blocks_future_activations() -> None:
    bars = _scenario()
    full = build_liquidity_response_m5_state_study_v4(bars)
    cutoff = full.locations[0].started_at

    truncated = build_liquidity_response_m5_state_study_v4(bars, cutoff=cutoff)

    assert all(item.started_at <= cutoff for item in truncated.locations)
    assert truncated.activations == ()
    assert truncated.entry_intents == ()


def test_v4_is_deterministic_for_reversed_input_order() -> None:
    bars = _scenario()
    primary = build_liquidity_response_m5_state_study_v4(bars)
    reference = build_liquidity_response_m5_state_study_v4(
        {key: list(reversed(value)) for key, value in bars.items()}
    )

    assert primary == reference
