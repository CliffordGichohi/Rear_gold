from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

BOOK_RULESET_VERSION: Final = "gold-reference-book-7-layer-v1"

# Chapters 12-18 define a priority order, not a static average. Layers 1-4 and 6
# contribute directional evidence. Layers 5 and 7 gate confidence and action.
# Every profile deliberately totals 100 so missing evidence reduces coverage
# rather than being redistributed over the remaining observations.
BASE_DIRECTIONAL_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "FED_PATH": 18.0,
        "REAL_YIELD": 15.0,
        "USD": 12.0,
        "TWO_YEAR_YIELD": 10.0,
        "INFLATION_REGIME": 10.0,
        "CATALYST_SURPRISE": 8.0,
        "GROWTH_REGIME": 6.0,
        "LABOUR_REGIME": 6.0,
        "POSITIONING_FLOW": 5.0,
        "EQUITY_RISK": 4.0,
        "NOMINAL_DECOMPOSITION": 4.0,
        "FINANCIAL_STRESS": 2.0,
    }
)

REACTION_WEIGHT_PROFILES: Mapping[str, Mapping[str, float]] = MappingProxyType(
    {
        "BASE": BASE_DIRECTIONAL_WEIGHTS,
        "INFLATION_FOCUS": MappingProxyType(
            {
                "FED_PATH": 20.0,
                "REAL_YIELD": 18.0,
                "USD": 10.0,
                "TWO_YEAR_YIELD": 10.0,
                "INFLATION_REGIME": 16.0,
                "CATALYST_SURPRISE": 10.0,
                "GROWTH_REGIME": 3.0,
                "LABOUR_REGIME": 7.0,
                "POSITIONING_FLOW": 3.0,
                "EQUITY_RISK": 1.0,
                "NOMINAL_DECOMPOSITION": 1.0,
                "FINANCIAL_STRESS": 1.0,
            }
        ),
        "GROWTH_LABOUR_FOCUS": MappingProxyType(
            {
                "FED_PATH": 20.0,
                "REAL_YIELD": 15.0,
                "USD": 10.0,
                "TWO_YEAR_YIELD": 12.0,
                "INFLATION_REGIME": 7.0,
                "CATALYST_SURPRISE": 10.0,
                "GROWTH_REGIME": 10.0,
                "LABOUR_REGIME": 10.0,
                "POSITIONING_FLOW": 3.0,
                "EQUITY_RISK": 1.0,
                "NOMINAL_DECOMPOSITION": 1.0,
                "FINANCIAL_STRESS": 1.0,
            }
        ),
        "FINANCIAL_STRESS_FOCUS": MappingProxyType(
            {
                "FED_PATH": 15.0,
                "REAL_YIELD": 15.0,
                "USD": 12.0,
                "TWO_YEAR_YIELD": 8.0,
                "INFLATION_REGIME": 5.0,
                "CATALYST_SURPRISE": 10.0,
                "GROWTH_REGIME": 7.0,
                "LABOUR_REGIME": 5.0,
                "POSITIONING_FLOW": 5.0,
                "EQUITY_RISK": 7.0,
                "NOMINAL_DECOMPOSITION": 2.0,
                "FINANCIAL_STRESS": 9.0,
            }
        ),
    }
)


def weights_for_reaction(reaction_function: str) -> tuple[str, Mapping[str, float]]:
    profile_name = (
        reaction_function
        if reaction_function in REACTION_WEIGHT_PROFILES
        else "BASE"
    )
    return profile_name, REACTION_WEIGHT_PROFILES[profile_name]


def validate_weight_profiles() -> None:
    expected_codes = set(BASE_DIRECTIONAL_WEIGHTS)
    for name, profile in REACTION_WEIGHT_PROFILES.items():
        if set(profile) != expected_codes:
            raise ValueError(f"Weight profile {name} does not contain the canonical drivers")
        if abs(sum(profile.values()) - 100.0) > 1e-9:
            raise ValueError(f"Weight profile {name} must total 100")


validate_weight_profiles()
