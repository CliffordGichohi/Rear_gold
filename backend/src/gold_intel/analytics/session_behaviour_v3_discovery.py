from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready

REGISTRY_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M4_REGISTRY_V0_1"
FEATURE_TRANSFORM_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M4_FEATURES_V0_1"
DISCOVERY_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M4_DISCOVERY_V0_1"

SESSIONS = ("LONDON", "NEW_YORK")
TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
ENGINE_COMPONENTS = (
    "FED_PATH",
    "REAL_YIELD",
    "USD",
    "TWO_YEAR_YIELD",
    "INFLATION_REGIME",
    "CATALYST_SURPRISE",
    "GROWTH_REGIME",
    "LABOUR_REGIME",
    "POSITIONING_FLOW",
    "EQUITY_RISK",
    "NOMINAL_DECOMPOSITION",
    "FINANCIAL_STRESS",
)

VALID_QUALITIES = {"VALID", "PARTIAL"}
COT_ALLOWED_QUALITIES = {"VALID", "PARTIAL", "UNVERIFIED_AVAILABILITY"}


@dataclass(frozen=True, slots=True)
class FeatureObservation:
    state: str
    source_signature: str
    epistemic_status: str
    quality: str


def _feature(
    feature_id: str,
    *,
    layer: str,
    family: str,
    traceability: Sequence[str],
    source_paths: Sequence[str],
    extractor: str,
    states: Sequence[str],
    tested_states: Sequence[str],
    parameters: Mapping[str, Any] | None = None,
    sessions: Sequence[str] = SESSIONS,
    epistemic_status: Sequence[str] = ("OBSERVED", "CALCULATED"),
    direction_hints: Mapping[str, int | None] | None = None,
    interaction_eligible: bool = True,
    limitation: str | None = None,
) -> dict[str, Any]:
    return {
        "direction_hints": dict(direction_hints or {}),
        "epistemic_status": list(epistemic_status),
        "extractor": extractor,
        "family": family,
        "feature_id": feature_id,
        "interaction_eligible": interaction_eligible,
        "layer": layer,
        "limitation": limitation,
        "parameters": dict(parameters or {}),
        "sessions": list(sessions),
        "source_paths": list(source_paths),
        "states": list(states),
        "tested_states": list(tested_states),
        "traceability_factor_ids": list(traceability),
    }


def feature_registry() -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    series_specs = (
        (
            "MACRO_CPI_HEADLINE_CHANGE",
            "L1_MARKET_REGIME",
            "INFLATION",
            ("REGIME_CPI",),
            "decision_state.layers.market_regime.inflation.cpi_headline",
            None,
        ),
        (
            "MACRO_CPI_CORE_CHANGE",
            "L1_MARKET_REGIME",
            "INFLATION",
            ("REGIME_CPI",),
            "decision_state.layers.market_regime.inflation.cpi_core",
            None,
        ),
        (
            "MACRO_PCE_HEADLINE_CHANGE",
            "L1_MARKET_REGIME",
            "INFLATION",
            ("REGIME_PCE",),
            "decision_state.layers.market_regime.inflation.pce_headline",
            None,
        ),
        (
            "MACRO_PCE_CORE_CHANGE",
            "L1_MARKET_REGIME",
            "INFLATION",
            ("REGIME_PCE",),
            "decision_state.layers.market_regime.inflation.pce_core",
            None,
        ),
        (
            "MACRO_PAYROLLS_CHANGE",
            "L1_MARKET_REGIME",
            "LABOUR",
            ("REGIME_LABOUR",),
            "decision_state.layers.market_regime.labour.payrolls",
            -1,
        ),
        (
            "MACRO_UNEMPLOYMENT_CHANGE",
            "L1_MARKET_REGIME",
            "LABOUR",
            ("REGIME_LABOUR",),
            "decision_state.layers.market_regime.labour.unemployment",
            1,
        ),
        (
            "MACRO_WAGES_CHANGE",
            "L1_MARKET_REGIME",
            "LABOUR",
            ("REGIME_LABOUR",),
            "decision_state.layers.market_regime.labour.wages",
            -1,
        ),
        (
            "MACRO_CLAIMS_CHANGE",
            "L1_MARKET_REGIME",
            "LABOUR",
            ("REGIME_LABOUR",),
            "decision_state.layers.market_regime.labour.claims",
            1,
        ),
        (
            "MACRO_GDP_CHANGE",
            "L1_MARKET_REGIME",
            "GROWTH",
            ("REGIME_GROWTH",),
            "decision_state.layers.market_regime.growth.gdp",
            -1,
        ),
        (
            "MACRO_RETAIL_SALES_CHANGE",
            "L1_MARKET_REGIME",
            "GROWTH",
            ("REGIME_GROWTH",),
            "decision_state.layers.market_regime.growth.retail_sales",
            -1,
        ),
        (
            "MACRO_FED_POLICY_RATE_CHANGE",
            "L2_EXPECTATIONS",
            "RATES",
            ("REGIME_FED_RATE",),
            "decision_state.layers.market_regime.rates.fed_policy_rate",
            -1,
        ),
        (
            "MACRO_TREASURY_2Y_CHANGE",
            "L2_EXPECTATIONS",
            "RATES",
            ("RATES_TREASURY_2Y",),
            "decision_state.layers.market_regime.rates.treasury_2y",
            -1,
        ),
        (
            "MACRO_TREASURY_10Y_CHANGE",
            "L6_CROSS_MARKET",
            "RATES",
            ("RATES_TREASURY_10Y",),
            "decision_state.layers.market_regime.rates.treasury_10y",
            None,
        ),
        (
            "MACRO_REAL_YIELD_10Y_CHANGE",
            "L6_CROSS_MARKET",
            "RATES",
            ("RATES_REAL_YIELD_10Y",),
            "decision_state.layers.market_regime.rates.real_yield_10y",
            -1,
        ),
        (
            "MACRO_BREAKEVEN_10Y_CHANGE",
            "L6_CROSS_MARKET",
            "RATES",
            ("RATES_BREAKEVEN_10Y",),
            "decision_state.layers.market_regime.rates.breakeven_10y",
            None,
        ),
        (
            "MACRO_USD_BROAD_CHANGE",
            "L6_CROSS_MARKET",
            "USD",
            ("USD_CONTEXT",),
            "decision_state.layers.market_regime.usd",
            -1,
        ),
        (
            "MACRO_EQUITIES_CHANGE",
            "L6_CROSS_MARKET",
            "RISK",
            ("RISK_EQUITY_VOLATILITY",),
            "decision_state.layers.market_regime.risk.equities",
            None,
        ),
        (
            "MACRO_VOLATILITY_CHANGE",
            "L6_CROSS_MARKET",
            "RISK",
            ("RISK_EQUITY_VOLATILITY",),
            "decision_state.layers.market_regime.risk.volatility",
            1,
        ),
        (
            "MACRO_HIGH_YIELD_SPREAD_CHANGE",
            "L1_MARKET_REGIME",
            "RISK",
            ("RISK_CREDIT_FINANCIAL_STRESS",),
            "decision_state.layers.market_regime.risk.high_yield_spread",
            1,
        ),
        (
            "MACRO_FINANCIAL_STRESS_CHANGE",
            "L1_MARKET_REGIME",
            "RISK",
            ("RISK_CREDIT_FINANCIAL_STRESS",),
            "decision_state.layers.market_regime.risk.financial_stress",
            1,
        ),
    )
    for feature_id, layer, family, traceability, path, rising_hint in series_specs:
        hints = {
            "FALLING": -rising_hint if rising_hint is not None else None,
            "RISING": rising_hint,
            "UNCHANGED": None,
        }
        features.append(
            _feature(
                feature_id,
                layer=layer,
                family=family,
                traceability=traceability,
                source_paths=(path,),
                extractor="SERIES_CHANGE_SIGN",
                states=("RISING", "FALLING", "UNCHANGED", "UNKNOWN"),
                tested_states=("RISING", "FALLING"),
                direction_hints=hints,
                limitation=(
                    "The sign is the latest point-in-time observation-to-observation "
                    "change and can persist across multiple sessions."
                ),
            )
        )

    features.extend(
        (
            _feature(
                "MACRO_YIELD_CURVE_LEVEL",
                layer="L1_MARKET_REGIME",
                family="RATES",
                traceability=("RATES_YIELD_CURVE",),
                source_paths=(
                    "decision_state.layers.market_regime.rates.yield_curve_2s10s",
                ),
                extractor="SCALAR_BINARY",
                states=("INVERTED", "NON_INVERTED", "UNKNOWN"),
                tested_states=("INVERTED",),
                parameters={
                    "negative_state": "INVERTED",
                    "non_negative_state": "NON_INVERTED",
                    "threshold": 0.0,
                },
                direction_hints={"INVERTED": None},
            ),
            _feature(
                "MACRO_FINANCIAL_STRESS_LEVEL",
                layer="L1_MARKET_REGIME",
                family="RISK",
                traceability=("RISK_CREDIT_FINANCIAL_STRESS",),
                source_paths=(
                    "decision_state.layers.market_regime.risk.financial_stress",
                ),
                extractor="SERIES_LEVEL_BINARY",
                states=("POSITIVE", "NON_POSITIVE", "UNKNOWN"),
                tested_states=("POSITIVE",),
                parameters={
                    "positive_state": "POSITIVE",
                    "non_positive_state": "NON_POSITIVE",
                    "threshold": 0.0,
                },
                direction_hints={"POSITIVE": 1},
            ),
            _feature(
                "MACRO_REGIME_LABEL",
                layer="L1_MARKET_REGIME",
                family="REGIME",
                traceability=("REGIME_CLASSIFICATION",),
                source_paths=(
                    "decision_state.layers.market_regime.regime_state.value.regime_label",
                ),
                extractor="REGIME_LABEL",
                states=(
                    "GOLDILOCKS",
                    "SOFT_LANDING",
                    "OVERHEATING",
                    "SLOWDOWN",
                    "RECESSION_DISINFLATION",
                    "STAGFLATION",
                    "DEFLATIONARY_STRESS",
                    "FINANCIAL_CRISIS_OR_LIQUIDITY_STRESS",
                    "PARTIAL_RATES_USD_SUPPORTIVE",
                    "PARTIAL_RATES_USD_PRESSURE",
                    "PARTIAL_RATES_USD_MIXED",
                    "UNKNOWN",
                ),
                tested_states=(
                    "GOLDILOCKS",
                    "SOFT_LANDING",
                    "OVERHEATING",
                    "SLOWDOWN",
                    "RECESSION_DISINFLATION",
                    "STAGFLATION",
                    "DEFLATIONARY_STRESS",
                    "FINANCIAL_CRISIS_OR_LIQUIDITY_STRESS",
                    "PARTIAL_RATES_USD_SUPPORTIVE",
                    "PARTIAL_RATES_USD_PRESSURE",
                    "PARTIAL_RATES_USD_MIXED",
                ),
                epistemic_status=("INFERRED",),
                direction_hints={},
            ),
            _feature(
                "MACRO_REACTION_FUNCTION",
                layer="L1_MARKET_REGIME",
                family="REGIME",
                traceability=("REGIME_REACTION_FUNCTION",),
                source_paths=(
                    "decision_state.layers.market_regime.reaction_function",
                ),
                extractor="FACT_CATEGORY",
                states=(
                    "INFLATION_FOCUS",
                    "GROWTH_LABOUR_FOCUS",
                    "FINANCIAL_STRESS_FOCUS",
                    "EVENT_SURPRISE_WITH_PARTIAL_MACRO",
                    "UNKNOWN_WITHOUT_EVENT_AND_REGIME_CORE",
                    "BALANCED_REACTION_FUNCTION",
                    "UNKNOWN",
                ),
                tested_states=(
                    "INFLATION_FOCUS",
                    "GROWTH_LABOUR_FOCUS",
                    "FINANCIAL_STRESS_FOCUS",
                    "EVENT_SURPRISE_WITH_PARTIAL_MACRO",
                    "UNKNOWN_WITHOUT_EVENT_AND_REGIME_CORE",
                    "BALANCED_REACTION_FUNCTION",
                ),
                epistemic_status=("INFERRED",),
                direction_hints={},
            ),
            _feature(
                "MACRO_ENGINE_SCORE",
                layer="SYNTHESIS",
                family="SYNTHESIS",
                traceability=("SYNTHESIS_EVIDENCE_CHAIN",),
                source_paths=(
                    "decision_state.layers.market_regime.regime_state.value.directional_score",
                ),
                extractor="ENGINE_SCORE",
                states=("BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"),
                tested_states=("BULLISH", "BEARISH", "NEUTRAL"),
                parameters={"bearish_max": -5.0, "bullish_min": 5.0},
                epistemic_status=("INFERRED",),
                direction_hints={"BULLISH": 1, "BEARISH": -1, "NEUTRAL": None},
                limitation=(
                    "This is the pre-existing transparent engine score. It is a "
                    "research condition, not validated directional truth."
                ),
            ),
        )
    )

    component_traceability = {
        "FED_PATH": ("EXPECT_POLICY_PATH_SHAPE", "EXPECT_POLICY_REPRICING"),
        "REAL_YIELD": ("RATES_REAL_YIELD_10Y",),
        "USD": ("USD_CONTEXT",),
        "TWO_YEAR_YIELD": ("RATES_TREASURY_2Y",),
        "INFLATION_REGIME": ("REGIME_CPI", "REGIME_PCE"),
        "CATALYST_SURPRISE": ("EXPECT_ECONOMIC_SURPRISE", "CATALYST_IMPACT_INFERENCE"),
        "GROWTH_REGIME": ("REGIME_GROWTH",),
        "LABOUR_REGIME": ("REGIME_LABOUR",),
        "POSITIONING_FLOW": (
            "POSITION_COT_MANAGED_MONEY",
            "POSITION_PRICE_OI_INFERENCE",
        ),
        "EQUITY_RISK": ("RISK_EQUITY_VOLATILITY",),
        "NOMINAL_DECOMPOSITION": (
            "RATES_TREASURY_10Y",
            "RATES_BREAKEVEN_10Y",
            "CROSS_RATES_DRIVER",
        ),
        "FINANCIAL_STRESS": ("RISK_CREDIT_FINANCIAL_STRESS",),
    }
    for code in ENGINE_COMPONENTS:
        features.append(
            _feature(
                f"SYNTH_{code}_DIRECTION",
                layer="SYNTHESIS",
                family="SYNTHESIS_COMPONENT",
                traceability=component_traceability[code],
                source_paths=(
                    "decision_state.synthesis.supporting_evidence[]",
                    "decision_state.synthesis.contradicting_evidence[]",
                ),
                extractor="ENGINE_COMPONENT_DIRECTION",
                states=("BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"),
                tested_states=("BULLISH", "BEARISH"),
                parameters={"component_code": code},
                epistemic_status=("CALCULATED", "INFERRED"),
                direction_hints={"BULLISH": 1, "BEARISH": -1},
                limitation=(
                    "The component is an existing transparent interpretation and "
                    "is tested separately from its raw inputs."
                ),
            )
        )

    for timeframe in TIMEFRAMES:
        prefix = f"STRUCT_{timeframe.upper().replace('M', 'M').replace('H', 'H')}"
        base_path = (
            "decision_state.market_structure.timeframes"
            f"[timeframe={timeframe}]"
        )
        common = {
            "layer": "MARKET_STRUCTURE",
            "family": f"STRUCTURE_{timeframe}",
            "sessions": SESSIONS,
        }
        features.extend(
            (
                _feature(
                    f"{prefix}_TREND",
                    **common,
                    traceability=("STRUCT_TREND_RANGE",),
                    source_paths=(f"{base_path}.trend_state",),
                    extractor="STRUCTURE_TREND",
                    states=(
                        "BULLISH",
                        "BEARISH",
                        "MIXED_OR_TRANSITIONING",
                        "UNKNOWN",
                    ),
                    tested_states=(
                        "BULLISH",
                        "BEARISH",
                        "MIXED_OR_TRANSITIONING",
                    ),
                    parameters={"timeframe": timeframe},
                    direction_hints={
                        "BULLISH": 1,
                        "BEARISH": -1,
                        "MIXED_OR_TRANSITIONING": None,
                    },
                ),
                _feature(
                    f"{prefix}_LATEST_BOS",
                    **common,
                    traceability=("STRUCT_BOS_MSS",),
                    source_paths=(f"{base_path}.break_of_structure",),
                    extractor="STRUCTURE_LATEST_DIRECTIONAL_DETECTION",
                    states=("BULLISH", "BEARISH", "NONE", "UNKNOWN"),
                    tested_states=("BULLISH", "BEARISH"),
                    parameters={
                        "fact_name": "break_of_structure",
                        "timeframe": timeframe,
                        "bullish_token": "BREAK_OF_STRUCTURE_BULLISH",
                        "bearish_token": "BREAK_OF_STRUCTURE_BEARISH",
                    },
                    direction_hints={"BULLISH": 1, "BEARISH": -1},
                ),
                _feature(
                    f"{prefix}_LATEST_MSS",
                    **common,
                    traceability=("STRUCT_BOS_MSS",),
                    source_paths=(f"{base_path}.market_structure_shift",),
                    extractor="STRUCTURE_LATEST_DIRECTIONAL_DETECTION",
                    states=("BULLISH", "BEARISH", "NONE", "UNKNOWN"),
                    tested_states=("BULLISH", "BEARISH"),
                    parameters={
                        "fact_name": "market_structure_shift",
                        "timeframe": timeframe,
                        "bullish_token": "MARKET_STRUCTURE_SHIFT_BULLISH",
                        "bearish_token": "MARKET_STRUCTURE_SHIFT_BEARISH",
                    },
                    direction_hints={"BULLISH": 1, "BEARISH": -1},
                ),
                _feature(
                    f"{prefix}_MOMENTUM",
                    **common,
                    traceability=("STRUCT_COMPRESSION_EXPANSION_MOMENTUM",),
                    source_paths=(f"{base_path}.momentum",),
                    extractor="STRUCTURE_MOMENTUM_SIGN",
                    states=("POSITIVE", "NEGATIVE", "FLAT", "UNKNOWN"),
                    tested_states=("POSITIVE", "NEGATIVE"),
                    parameters={"timeframe": timeframe},
                    direction_hints={"POSITIVE": 1, "NEGATIVE": -1},
                ),
                _feature(
                    f"{prefix}_COMPRESSION",
                    **common,
                    traceability=("STRUCT_COMPRESSION_EXPANSION_MOMENTUM",),
                    source_paths=(f"{base_path}.compression",),
                    extractor="STRUCTURE_BOOLEAN_STATE",
                    states=("DETECTED", "NOT_DETECTED", "UNKNOWN"),
                    tested_states=("DETECTED",),
                    parameters={
                        "fact_name": "compression",
                        "timeframe": timeframe,
                    },
                    direction_hints={"DETECTED": None},
                ),
                _feature(
                    f"{prefix}_RANGE_LOCATION",
                    **common,
                    traceability=(
                        "STRUCT_TREND_RANGE",
                        "STRUCT_SUPPORT_RESISTANCE_LEVELS",
                    ),
                    source_paths=(f"{base_path}.range_state",),
                    extractor="STRUCTURE_RANGE_LOCATION",
                    states=(
                        "LOWER_THIRD",
                        "MIDDLE_THIRD",
                        "UPPER_THIRD",
                        "UNKNOWN",
                    ),
                    tested_states=(
                        "LOWER_THIRD",
                        "MIDDLE_THIRD",
                        "UPPER_THIRD",
                    ),
                    parameters={
                        "lower_fraction": 1 / 3,
                        "timeframe": timeframe,
                        "upper_fraction": 2 / 3,
                    },
                    direction_hints={},
                ),
            )
        )

    for instrument, traceability in (
        ("GOLD", ("MECH_XAUUSD_PRICE", "CROSS_SYNCHRONIZED_PANEL")),
        ("SILVER", ("CROSS_SILVER", "CROSS_SYNCHRONIZED_PANEL")),
    ):
        for horizon in ("1_HOUR", "4_HOURS", "1_DAY", "5_DAYS"):
            features.append(
                _feature(
                    f"CROSS_{instrument}_{horizon}_CHANGE",
                    layer="L6_CROSS_MARKET",
                    family=f"CROSS_{instrument}",
                    traceability=traceability,
                    source_paths=(
                        "decision_state.layers.cross_market."
                        f"{instrument.lower()}.value.changes.{horizon}",
                    ),
                    extractor="CROSS_CHANGE_SIGN",
                    states=("UP", "DOWN", "FLAT", "UNKNOWN"),
                    tested_states=("UP", "DOWN"),
                    parameters={
                        "horizon": horizon,
                        "instrument": instrument.lower(),
                    },
                    direction_hints={"UP": 1, "DOWN": -1},
                )
            )

    features.extend(
        (
            _feature(
                "SESSION_ASIA_DIRECTION",
                layer="L5_SESSIONS_LIQUIDITY",
                family="SESSION_ASIA",
                traceability=("SESSION_ASIA_STATE",),
                source_paths=(
                    "decision_state.layers.sessions_and_liquidity.asia_state",
                ),
                extractor="WINDOW_DIRECTION",
                states=("UP", "DOWN", "FLAT", "UNKNOWN"),
                tested_states=("UP", "DOWN"),
                parameters={"window": "asia_state"},
                direction_hints={"UP": 1, "DOWN": -1},
            ),
            _feature(
                "SESSION_ASIA_CLOSE_LOCATION",
                layer="L5_SESSIONS_LIQUIDITY",
                family="SESSION_ASIA",
                traceability=("SESSION_ASIA_STATE",),
                source_paths=(
                    "decision_state.layers.sessions_and_liquidity.asia_state",
                ),
                extractor="WINDOW_CLOSE_LOCATION",
                states=(
                    "LOWER_THIRD",
                    "MIDDLE_THIRD",
                    "UPPER_THIRD",
                    "UNKNOWN",
                ),
                tested_states=("LOWER_THIRD", "MIDDLE_THIRD", "UPPER_THIRD"),
                parameters={"window": "asia_state"},
                direction_hints={},
            ),
            _feature(
                "SESSION_ASIA_RANGE_TO_1H_ATR",
                layer="L5_SESSIONS_LIQUIDITY",
                family="SESSION_ASIA",
                traceability=("SESSION_ASIA_STATE", "STRUCT_TREND_RANGE"),
                source_paths=(
                    "decision_state.layers.sessions_and_liquidity.asia_state",
                    "decision_state.market_structure.timeframes[timeframe=1h].range_state",
                ),
                extractor="WINDOW_RANGE_TO_ATR",
                states=("COMPRESSED", "NORMAL", "EXPANDED", "UNKNOWN"),
                tested_states=("COMPRESSED", "NORMAL", "EXPANDED"),
                parameters={
                    "compressed_max": 0.75,
                    "expanded_min": 1.5,
                    "timeframe": "1h",
                    "window": "asia_state",
                },
                direction_hints={},
            ),
            _feature(
                "SESSION_ASIA_SPREAD_EXPANSION",
                layer="L5_SESSIONS_LIQUIDITY",
                family="LIQUIDITY",
                traceability=("SESSION_ROLLOVER_LIQUIDITY", "MECH_SPREAD"),
                source_paths=(
                    "decision_state.layers.sessions_and_liquidity.asia_state",
                ),
                extractor="WINDOW_SPREAD_RATIO",
                states=("WIDE", "NORMAL", "UNKNOWN"),
                tested_states=("WIDE",),
                parameters={"wide_min_ratio": 1.5, "window": "asia_state"},
                direction_hints={"WIDE": None},
            ),
            _feature(
                "LIQUIDITY_DECISION_SPREAD_TO_ASIA",
                layer="L5_SESSIONS_LIQUIDITY",
                family="LIQUIDITY",
                traceability=("MECH_SPREAD", "SESSION_ROLLOVER_LIQUIDITY"),
                source_paths=(
                    "decision_state.market_mechanics.spread",
                    "decision_state.layers.sessions_and_liquidity.asia_state",
                ),
                extractor="DECISION_SPREAD_TO_WINDOW",
                states=("WIDE", "NORMAL", "TIGHT", "UNKNOWN"),
                tested_states=("WIDE", "TIGHT"),
                parameters={
                    "tight_max_ratio": 0.75,
                    "wide_min_ratio": 1.5,
                    "window": "asia_state",
                },
                direction_hints={},
            ),
            _feature(
                "LEVEL_NEAREST_KNOWN_TO_1H_ATR",
                layer="MARKET_STRUCTURE",
                family="LEVELS",
                traceability=(
                    "STRUCT_SUPPORT_RESISTANCE_LEVELS",
                    "STRUCT_LIQUIDITY_STOP_ZONES",
                ),
                source_paths=(
                    "decision_state.levels[]",
                    "decision_state.market_mechanics.xauusd_price",
                    "decision_state.market_structure.timeframes[timeframe=1h].range_state",
                ),
                extractor="NEAREST_LEVEL_TO_ATR",
                states=("NEAR", "NOT_NEAR", "UNKNOWN"),
                tested_states=("NEAR",),
                parameters={"near_max_atr": 0.25, "timeframe": "1h"},
                epistemic_status=("CALCULATED",),
                direction_hints={"NEAR": None},
                limitation=(
                    "A known coordinate is not evidence of observed resting liquidity."
                ),
            ),
            _feature(
                "SESSION_DECISION_POSITION_VS_ASIA",
                layer="L5_SESSIONS_LIQUIDITY",
                family="SESSION_ASIA",
                traceability=(
                    "SESSION_ASIA_STATE",
                    "STRUCT_SUPPORT_RESISTANCE_LEVELS",
                ),
                source_paths=(
                    "decision_state.layers.sessions_and_liquidity.asia_state",
                    "decision_state.market_mechanics.xauusd_price",
                ),
                extractor="PRICE_VS_WINDOW_RANGE",
                states=(
                    "ABOVE",
                    "UPPER_THIRD",
                    "MIDDLE_THIRD",
                    "LOWER_THIRD",
                    "BELOW",
                    "UNKNOWN",
                ),
                tested_states=(
                    "ABOVE",
                    "UPPER_THIRD",
                    "MIDDLE_THIRD",
                    "LOWER_THIRD",
                    "BELOW",
                ),
                parameters={"window": "asia_state"},
                sessions=("NEW_YORK",),
                direction_hints={"ABOVE": 1, "BELOW": -1},
            ),
            _feature(
                "SESSION_LONDON_DIRECTION",
                layer="L5_SESSIONS_LIQUIDITY",
                family="SESSION_LONDON",
                traceability=("SESSION_LONDON_STATE",),
                source_paths=(
                    "decision_state.layers.sessions_and_liquidity.london_state",
                ),
                extractor="WINDOW_DIRECTION",
                states=("UP", "DOWN", "FLAT", "UNKNOWN"),
                tested_states=("UP", "DOWN"),
                parameters={"window": "london_state"},
                sessions=("NEW_YORK",),
                direction_hints={"UP": 1, "DOWN": -1},
            ),
            _feature(
                "SESSION_LONDON_CLOSE_LOCATION",
                layer="L5_SESSIONS_LIQUIDITY",
                family="SESSION_LONDON",
                traceability=("SESSION_LONDON_STATE",),
                source_paths=(
                    "decision_state.layers.sessions_and_liquidity.london_state",
                ),
                extractor="WINDOW_CLOSE_LOCATION",
                states=(
                    "LOWER_THIRD",
                    "MIDDLE_THIRD",
                    "UPPER_THIRD",
                    "UNKNOWN",
                ),
                tested_states=("LOWER_THIRD", "MIDDLE_THIRD", "UPPER_THIRD"),
                parameters={"window": "london_state"},
                sessions=("NEW_YORK",),
                direction_hints={},
            ),
            _feature(
                "SESSION_LONDON_RANGE_TO_1H_ATR",
                layer="L5_SESSIONS_LIQUIDITY",
                family="SESSION_LONDON",
                traceability=("SESSION_LONDON_STATE", "STRUCT_TREND_RANGE"),
                source_paths=(
                    "decision_state.layers.sessions_and_liquidity.london_state",
                    "decision_state.market_structure.timeframes[timeframe=1h].range_state",
                ),
                extractor="WINDOW_RANGE_TO_ATR",
                states=("COMPRESSED", "NORMAL", "EXPANDED", "UNKNOWN"),
                tested_states=("COMPRESSED", "NORMAL", "EXPANDED"),
                parameters={
                    "compressed_max": 0.75,
                    "expanded_min": 1.5,
                    "timeframe": "1h",
                    "window": "london_state",
                },
                sessions=("NEW_YORK",),
                direction_hints={},
            ),
            _feature(
                "SESSION_LONDON_INTERACTION_WITH_ASIA",
                layer="L5_SESSIONS_LIQUIDITY",
                family="SESSION_LONDON",
                traceability=(
                    "SESSION_ASIA_STATE",
                    "SESSION_LONDON_STATE",
                    "SESSION_HANDOVER_OVERLAP",
                ),
                source_paths=(
                    "decision_state.layers.sessions_and_liquidity.asia_state",
                    "decision_state.layers.sessions_and_liquidity.london_state",
                ),
                extractor="WINDOW_INTERACTION",
                states=(
                    "HIGH_ONLY",
                    "LOW_ONLY",
                    "BOTH_SIDES",
                    "INSIDE",
                    "UNKNOWN",
                ),
                tested_states=("HIGH_ONLY", "LOW_ONLY", "BOTH_SIDES", "INSIDE"),
                parameters={
                    "inner_window": "asia_state",
                    "outer_window": "london_state",
                },
                sessions=("NEW_YORK",),
                direction_hints={"HIGH_ONLY": 1, "LOW_ONLY": -1},
            ),
        )
    )

    cot_specs = (
        (
            "POSITION_MANAGED_MONEY_NET",
            "managed_money",
            ("POSITION_COT_MANAGED_MONEY",),
        ),
        (
            "POSITION_PRODUCER_MERCHANT_NET",
            "producer_merchant",
            ("POSITION_COT_OTHER_CATEGORIES",),
        ),
        (
            "POSITION_SWAP_DEALER_NET",
            "swap_dealer",
            ("POSITION_COT_OTHER_CATEGORIES",),
        ),
        (
            "POSITION_OTHER_REPORTABLE_NET",
            "other_reportable",
            ("POSITION_COT_OTHER_CATEGORIES",),
        ),
    )
    for feature_id, category, traceability in cot_specs:
        features.append(
            _feature(
                feature_id,
                layer="L3_POSITIONING",
                family="POSITIONING",
                traceability=traceability,
                source_paths=(
                    f"decision_state.layers.positioning.{category}",
                ),
                extractor="COT_CATEGORY_NET_SIGN",
                states=("NET_LONG", "NET_SHORT", "FLAT", "UNKNOWN"),
                tested_states=("NET_LONG", "NET_SHORT"),
                parameters={"category": category},
                direction_hints={},
                limitation=(
                    "CFTC categories are observed weekly positions; they do not "
                    "prove participant motive."
                ),
            )
        )

    inferred_specs = (
        (
            "POSITION_CROWDING_STATE",
            "crowding_state",
            ("CROWDED_LONGS", "CROWDED_SHORTS", "BALANCED", "UNKNOWN"),
            ("CROWDED_LONGS", "CROWDED_SHORTS", "BALANCED"),
            ("POSITION_CROWDING_RISK",),
        ),
        (
            "POSITION_PARTICIPATION_STATE",
            "participation_state",
            (
                "PROBABLE_FRESH_BULLISH_PARTICIPATION",
                "PROBABLE_SHORT_COVERING",
                "PROBABLE_FRESH_BEARISH_PARTICIPATION",
                "PROBABLE_LONG_LIQUIDATION",
                "INDETERMINATE",
                "UNKNOWN",
            ),
            (
                "PROBABLE_FRESH_BULLISH_PARTICIPATION",
                "PROBABLE_SHORT_COVERING",
                "PROBABLE_FRESH_BEARISH_PARTICIPATION",
                "PROBABLE_LONG_LIQUIDATION",
            ),
            ("POSITION_PRICE_OI_INFERENCE",),
        ),
        (
            "POSITION_LONG_LIQUIDATION_RISK",
            "long_liquidation_risk",
            ("ELEVATED", "NORMAL", "UNKNOWN"),
            ("ELEVATED",),
            ("POSITION_CROWDING_RISK",),
        ),
        (
            "POSITION_SHORT_COVERING_RISK",
            "short_covering_risk",
            ("ELEVATED", "NORMAL", "UNKNOWN"),
            ("ELEVATED",),
            ("POSITION_CROWDING_RISK",),
        ),
    )
    for feature_id, state_code, states, tested, traceability in inferred_specs:
        features.append(
            _feature(
                feature_id,
                layer="L3_POSITIONING",
                family="POSITIONING",
                traceability=traceability,
                source_paths=(
                    "decision_state.layers.positioning.inferred_states[]",
                ),
                extractor="COT_INFERRED_STATE",
                states=states,
                tested_states=tested,
                parameters={"state_code": state_code},
                epistemic_status=("INFERRED",),
                direction_hints={},
                limitation=(
                    "This is explicitly an inference from published CFTC data, "
                    "not observed institutional intent."
                ),
            )
        )

    features.extend(
        (
            _feature(
                "EXPECT_SOFR_WINDOW_CUT_HIKE_BALANCE",
                layer="L2_EXPECTATIONS",
                family="EXPECTATIONS",
                traceability=(
                    "EXPECT_POLICY_PATH_SHAPE",
                    "EXPECT_POLICY_REPRICING",
                ),
                source_paths=(
                    "decision_state.layers.expectations.policy_path.repricing",
                ),
                extractor="SOFR_WINDOW_BALANCE",
                states=("CUT_DOMINANT", "HIKE_DOMINANT", "BALANCED", "UNKNOWN"),
                tested_states=("CUT_DOMINANT", "HIKE_DOMINANT"),
                direction_hints={"CUT_DOMINANT": 1, "HIKE_DOMINANT": -1},
                limitation=(
                    "Atlanta Fed quarterly SOFR reference-window distributions "
                    "are not exact FOMC meeting probabilities."
                ),
            ),
            _feature(
                "CATALYST_IMPACT_DIRECTION",
                layer="L4_CATALYSTS",
                family="CATALYST",
                traceability=(
                    "EXPECT_ECONOMIC_SURPRISE",
                    "CATALYST_IMPACT_INFERENCE",
                ),
                source_paths=(
                    "decision_state.layers.catalysts.event_impact_state",
                ),
                extractor="COMPONENT_FACT_DIRECTION",
                states=("BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"),
                tested_states=("BULLISH", "BEARISH"),
                epistemic_status=("CALCULATED", "INFERRED"),
                direction_hints={"BULLISH": 1, "BEARISH": -1},
                limitation=(
                    "The direction is inferred from an already-released event and "
                    "must not be presented as an observed institutional response."
                ),
            ),
        )
    )
    validate_feature_registry(features)
    return sorted(features, key=lambda item: item["feature_id"])


def _interaction(
    interaction_id: str,
    left_feature: str,
    left_state: str,
    right_feature: str,
    right_state: str,
    *,
    rationale: str,
    sessions: Sequence[str] = SESSIONS,
) -> dict[str, Any]:
    return {
        "conditions": [
            {"feature_id": left_feature, "state": left_state},
            {"feature_id": right_feature, "state": right_state},
        ],
        "interaction_id": interaction_id,
        "rationale": rationale,
        "sessions": list(sessions),
    }


def interaction_registry() -> list[dict[str, Any]]:
    interactions = [
        _interaction(
            "INT_REAL_YIELD_USD_SUPPORT",
            "MACRO_REAL_YIELD_10Y_CHANGE",
            "FALLING",
            "MACRO_USD_BROAD_CHANGE",
            "FALLING",
            rationale="Book causal chain: falling real yield plus a weaker dollar.",
        ),
        _interaction(
            "INT_REAL_YIELD_USD_PRESSURE",
            "MACRO_REAL_YIELD_10Y_CHANGE",
            "RISING",
            "MACRO_USD_BROAD_CHANGE",
            "RISING",
            rationale="Book causal chain: rising real yield plus a stronger dollar.",
        ),
        _interaction(
            "INT_2Y_USD_SUPPORT",
            "MACRO_TREASURY_2Y_CHANGE",
            "FALLING",
            "MACRO_USD_BROAD_CHANGE",
            "FALLING",
            rationale="Dovish two-year-yield movement with a weaker dollar.",
        ),
        _interaction(
            "INT_2Y_USD_PRESSURE",
            "MACRO_TREASURY_2Y_CHANGE",
            "RISING",
            "MACRO_USD_BROAD_CHANGE",
            "RISING",
            rationale="Hawkish two-year-yield movement with a stronger dollar.",
        ),
        _interaction(
            "INT_GOLD_SILVER_4H_UP",
            "CROSS_GOLD_4_HOURS_CHANGE",
            "UP",
            "CROSS_SILVER_4_HOURS_CHANGE",
            "UP",
            rationale="Four-hour precious-metals confirmation.",
        ),
        _interaction(
            "INT_GOLD_SILVER_4H_DOWN",
            "CROSS_GOLD_4_HOURS_CHANGE",
            "DOWN",
            "CROSS_SILVER_4_HOURS_CHANGE",
            "DOWN",
            rationale="Four-hour precious-metals confirmation.",
        ),
        _interaction(
            "INT_DEFENSIVE_RISK_STATE",
            "MACRO_EQUITIES_CHANGE",
            "FALLING",
            "MACRO_VOLATILITY_CHANGE",
            "RISING",
            rationale="Defensive equity and volatility state.",
        ),
        _interaction(
            "INT_RISK_ON_STATE",
            "MACRO_EQUITIES_CHANGE",
            "RISING",
            "MACRO_VOLATILITY_CHANGE",
            "FALLING",
            rationale="Risk-on equity and volatility state.",
        ),
    ]
    for timeframe in ("15M", "1H", "4H"):
        interactions.extend(
            (
                _interaction(
                    f"INT_ENGINE_SCORE_{timeframe}_BULLISH",
                    "MACRO_ENGINE_SCORE",
                    "BULLISH",
                    f"STRUCT_{timeframe}_TREND",
                    "BULLISH",
                    rationale="Transparent macro score aligned with structure.",
                ),
                _interaction(
                    f"INT_ENGINE_SCORE_{timeframe}_BEARISH",
                    "MACRO_ENGINE_SCORE",
                    "BEARISH",
                    f"STRUCT_{timeframe}_TREND",
                    "BEARISH",
                    rationale="Transparent macro score aligned with structure.",
                ),
            )
        )
    interactions.extend(
        (
            _interaction(
                "INT_REAL_YIELD_15M_BULLISH",
                "MACRO_REAL_YIELD_10Y_CHANGE",
                "FALLING",
                "STRUCT_15M_TREND",
                "BULLISH",
                rationale="Real-yield support aligned with intraday structure.",
            ),
            _interaction(
                "INT_REAL_YIELD_15M_BEARISH",
                "MACRO_REAL_YIELD_10Y_CHANGE",
                "RISING",
                "STRUCT_15M_TREND",
                "BEARISH",
                rationale="Real-yield pressure aligned with intraday structure.",
            ),
            _interaction(
                "INT_USD_15M_BULLISH",
                "MACRO_USD_BROAD_CHANGE",
                "FALLING",
                "STRUCT_15M_TREND",
                "BULLISH",
                rationale="Dollar support aligned with intraday structure.",
            ),
            _interaction(
                "INT_USD_15M_BEARISH",
                "MACRO_USD_BROAD_CHANGE",
                "RISING",
                "STRUCT_15M_TREND",
                "BEARISH",
                rationale="Dollar pressure aligned with intraday structure.",
            ),
            _interaction(
                "INT_CATALYST_15M_BULLISH",
                "CATALYST_IMPACT_DIRECTION",
                "BULLISH",
                "STRUCT_15M_TREND",
                "BULLISH",
                rationale="Released-event interpretation aligned with structure.",
            ),
            _interaction(
                "INT_CATALYST_15M_BEARISH",
                "CATALYST_IMPACT_DIRECTION",
                "BEARISH",
                "STRUCT_15M_TREND",
                "BEARISH",
                rationale="Released-event interpretation aligned with structure.",
            ),
            _interaction(
                "INT_ENGINE_ASIA_UP",
                "MACRO_ENGINE_SCORE",
                "BULLISH",
                "SESSION_ASIA_DIRECTION",
                "UP",
                rationale="Transparent macro score aligned with the completed Asia path.",
            ),
            _interaction(
                "INT_ENGINE_ASIA_DOWN",
                "MACRO_ENGINE_SCORE",
                "BEARISH",
                "SESSION_ASIA_DIRECTION",
                "DOWN",
                rationale="Transparent macro score aligned with the completed Asia path.",
            ),
            _interaction(
                "INT_ENGINE_LONDON_UP",
                "MACRO_ENGINE_SCORE",
                "BULLISH",
                "SESSION_LONDON_DIRECTION",
                "UP",
                rationale="New York decision condition using completed London path.",
                sessions=("NEW_YORK",),
            ),
            _interaction(
                "INT_ENGINE_LONDON_DOWN",
                "MACRO_ENGINE_SCORE",
                "BEARISH",
                "SESSION_LONDON_DIRECTION",
                "DOWN",
                rationale="New York decision condition using completed London path.",
                sessions=("NEW_YORK",),
            ),
            _interaction(
                "INT_15M_1H_BULLISH",
                "STRUCT_15M_TREND",
                "BULLISH",
                "STRUCT_1H_TREND",
                "BULLISH",
                rationale="Multi-timeframe structure alignment.",
            ),
            _interaction(
                "INT_15M_1H_BEARISH",
                "STRUCT_15M_TREND",
                "BEARISH",
                "STRUCT_1H_TREND",
                "BEARISH",
                rationale="Multi-timeframe structure alignment.",
            ),
            _interaction(
                "INT_1H_4H_BULLISH",
                "STRUCT_1H_TREND",
                "BULLISH",
                "STRUCT_4H_TREND",
                "BULLISH",
                rationale="Multi-timeframe structure alignment.",
            ),
            _interaction(
                "INT_1H_4H_BEARISH",
                "STRUCT_1H_TREND",
                "BEARISH",
                "STRUCT_4H_TREND",
                "BEARISH",
                rationale="Multi-timeframe structure alignment.",
            ),
            _interaction(
                "INT_ENGINE_CROWDED_LONGS",
                "MACRO_ENGINE_SCORE",
                "BULLISH",
                "POSITION_CROWDING_STATE",
                "CROWDED_LONGS",
                rationale="Supportive macro state with long-liquidation crowding risk.",
            ),
            _interaction(
                "INT_ENGINE_CROWDED_SHORTS",
                "MACRO_ENGINE_SCORE",
                "BEARISH",
                "POSITION_CROWDING_STATE",
                "CROWDED_SHORTS",
                rationale="Bearish macro state with short-covering crowding risk.",
            ),
            _interaction(
                "INT_ENGINE_BALANCED_POSITIONING_BULLISH",
                "MACRO_ENGINE_SCORE",
                "BULLISH",
                "POSITION_CROWDING_STATE",
                "BALANCED",
                rationale="Supportive macro state without an extreme crowding label.",
            ),
            _interaction(
                "INT_ENGINE_BALANCED_POSITIONING_BEARISH",
                "MACRO_ENGINE_SCORE",
                "BEARISH",
                "POSITION_CROWDING_STATE",
                "BALANCED",
                rationale="Bearish macro state without an extreme crowding label.",
            ),
            _interaction(
                "INT_CATALYST_FRESH_BULLISH_PARTICIPATION",
                "CATALYST_IMPACT_DIRECTION",
                "BULLISH",
                "POSITION_PARTICIPATION_STATE",
                "PROBABLE_FRESH_BULLISH_PARTICIPATION",
                rationale="Released-event interpretation with inferred weekly participation.",
            ),
            _interaction(
                "INT_CATALYST_FRESH_BEARISH_PARTICIPATION",
                "CATALYST_IMPACT_DIRECTION",
                "BEARISH",
                "POSITION_PARTICIPATION_STATE",
                "PROBABLE_FRESH_BEARISH_PARTICIPATION",
                rationale="Released-event interpretation with inferred weekly participation.",
            ),
            _interaction(
                "INT_SOFR_CUT_2Y_FALLING",
                "EXPECT_SOFR_WINDOW_CUT_HIKE_BALANCE",
                "CUT_DOMINANT",
                "MACRO_TREASURY_2Y_CHANGE",
                "FALLING",
                rationale="Quarterly SOFR reference-window and two-year-yield alignment.",
            ),
            _interaction(
                "INT_SOFR_HIKE_2Y_RISING",
                "EXPECT_SOFR_WINDOW_CUT_HIKE_BALANCE",
                "HIKE_DOMINANT",
                "MACRO_TREASURY_2Y_CHANGE",
                "RISING",
                rationale="Quarterly SOFR reference-window and two-year-yield alignment.",
            ),
            _interaction(
                "INT_COMPRESSED_ASIA_GOLD_4H_UP",
                "SESSION_ASIA_RANGE_TO_1H_ATR",
                "COMPRESSED",
                "CROSS_GOLD_4_HOURS_CHANGE",
                "UP",
                rationale="Compressed completed Asia range with positive prior gold momentum.",
            ),
            _interaction(
                "INT_COMPRESSED_ASIA_GOLD_4H_DOWN",
                "SESSION_ASIA_RANGE_TO_1H_ATR",
                "COMPRESSED",
                "CROSS_GOLD_4_HOURS_CHANGE",
                "DOWN",
                rationale="Compressed completed Asia range with negative prior gold momentum.",
            ),
            _interaction(
                "INT_ENGINE_LONDON_ASIA_HIGH_BREAK",
                "MACRO_ENGINE_SCORE",
                "BULLISH",
                "SESSION_LONDON_INTERACTION_WITH_ASIA",
                "HIGH_ONLY",
                rationale="New York macro state with completed London Asia-high interaction.",
                sessions=("NEW_YORK",),
            ),
            _interaction(
                "INT_ENGINE_LONDON_ASIA_LOW_BREAK",
                "MACRO_ENGINE_SCORE",
                "BEARISH",
                "SESSION_LONDON_INTERACTION_WITH_ASIA",
                "LOW_ONLY",
                rationale="New York macro state with completed London Asia-low interaction.",
                sessions=("NEW_YORK",),
            ),
        )
    )
    validate_interaction_registry(interactions, feature_registry())
    return sorted(interactions, key=lambda item: item["interaction_id"])


def validate_feature_registry(features: Sequence[Mapping[str, Any]]) -> None:
    ids = [str(item["feature_id"]) for item in features]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate feature IDs")
    for feature in features:
        if not set(feature["sessions"]).issubset(SESSIONS):
            raise ValueError(f"Invalid sessions for {feature['feature_id']}")
        if "UNKNOWN" not in feature["states"]:
            raise ValueError(f"UNKNOWN missing from {feature['feature_id']}")
        if not set(feature["tested_states"]).issubset(feature["states"]):
            raise ValueError(f"Invalid tested states for {feature['feature_id']}")
        if not feature["traceability_factor_ids"]:
            raise ValueError(f"Traceability missing for {feature['feature_id']}")


def validate_interaction_registry(
    interactions: Sequence[Mapping[str, Any]],
    features: Sequence[Mapping[str, Any]],
) -> None:
    feature_map = {str(item["feature_id"]): item for item in features}
    ids = [str(item["interaction_id"]) for item in interactions]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate interaction IDs")
    for interaction in interactions:
        conditions = list(interaction["conditions"])
        if len(conditions) != 2:
            raise ValueError(f"Interaction must contain two conditions: {interaction}")
        if conditions[0]["feature_id"] == conditions[1]["feature_id"]:
            raise ValueError(f"Self interaction is forbidden: {interaction}")
        for condition in conditions:
            feature = feature_map.get(str(condition["feature_id"]))
            if feature is None:
                raise ValueError(f"Unknown interaction feature: {condition}")
            if condition["state"] not in feature["tested_states"]:
                raise ValueError(f"Untested interaction state: {condition}")
            if not feature["interaction_eligible"]:
                raise ValueError(f"Interaction-ineligible feature: {condition}")
        allowed = set(conditions[0:1][0] and feature_map[conditions[0]["feature_id"]]["sessions"])
        allowed &= set(feature_map[conditions[1]["feature_id"]]["sessions"])
        if not set(interaction["sessions"]).issubset(allowed):
            raise ValueError(f"Interaction session mismatch: {interaction}")


def registry_fingerprint(
    features: Sequence[Mapping[str, Any]],
    interactions: Sequence[Mapping[str, Any]],
) -> str:
    return canonical_hash(
        {
            "feature_transform_version": FEATURE_TRANSFORM_VERSION,
            "features": list(features),
            "interactions": list(interactions),
        }
    )


def extract_case_features(
    decision_state: Mapping[str, Any],
    *,
    session_code: str,
    features: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, FeatureObservation]:
    registry = list(features or feature_registry())
    output: dict[str, FeatureObservation] = {}
    for definition in registry:
        if session_code not in definition["sessions"]:
            continue
        observation = extract_feature(decision_state, definition)
        output[str(definition["feature_id"])] = observation
    return output


def extract_feature(
    decision_state: Mapping[str, Any],
    definition: Mapping[str, Any],
) -> FeatureObservation:
    extractor = str(definition["extractor"])
    params = dict(definition.get("parameters", {}))
    if extractor == "SERIES_CHANGE_SIGN":
        return _series_change_sign(decision_state, definition["source_paths"][0])
    if extractor == "SCALAR_BINARY":
        fact = _get_fact(decision_state, definition["source_paths"][0])
        if not _fact_eligible(fact):
            return _unknown()
        value = _number(fact["value"])
        if value is None:
            return _unknown()
        state = (
            str(params["negative_state"])
            if value < float(params["threshold"])
            else str(params["non_negative_state"])
        )
        return _observation(state, fact)
    if extractor == "SERIES_LEVEL_BINARY":
        fact = _get_fact(decision_state, definition["source_paths"][0])
        if not _fact_eligible(fact):
            return _unknown()
        value = _number(_mapping(fact["value"]).get("value"))
        if value is None:
            return _unknown()
        state = (
            str(params["positive_state"])
            if value > float(params["threshold"])
            else str(params["non_positive_state"])
        )
        return _observation(state, fact, signature_payload=_mapping(fact["value"]))
    if extractor == "REGIME_LABEL":
        fact = _get_fact(
            decision_state,
            "decision_state.layers.market_regime.regime_state",
        )
        if not _fact_eligible(fact):
            return _unknown()
        value = _mapping(fact["value"])
        state = str(value.get("regime_label") or "UNKNOWN")
        return _observation(state, fact, signature_payload=value)
    if extractor == "FACT_CATEGORY":
        fact = _get_fact(decision_state, definition["source_paths"][0])
        if not _fact_eligible(fact):
            return _unknown()
        return _observation(str(fact["value"]), fact)
    if extractor == "ENGINE_SCORE":
        fact = _get_fact(
            decision_state,
            "decision_state.layers.market_regime.regime_state",
        )
        if not _fact_eligible(fact):
            return _unknown()
        value = _mapping(fact["value"])
        score = _number(value.get("directional_score"))
        if score is None:
            return _unknown()
        state = (
            "BEARISH"
            if score <= float(params["bearish_max"])
            else "BULLISH"
            if score >= float(params["bullish_min"])
            else "NEUTRAL"
        )
        return _observation(state, fact, signature_payload=value)
    if extractor == "ENGINE_COMPONENT_DIRECTION":
        return _engine_component_direction(
            decision_state,
            str(params["component_code"]),
        )
    if extractor.startswith("STRUCTURE_"):
        return _structure_feature(decision_state, extractor, params)
    if extractor == "CROSS_CHANGE_SIGN":
        return _cross_change_sign(decision_state, params)
    if extractor == "WINDOW_DIRECTION":
        return _window_direction(decision_state, str(params["window"]))
    if extractor == "WINDOW_CLOSE_LOCATION":
        return _window_close_location(decision_state, str(params["window"]))
    if extractor == "WINDOW_RANGE_TO_ATR":
        return _window_range_to_atr(decision_state, params)
    if extractor == "WINDOW_SPREAD_RATIO":
        return _window_spread_ratio(decision_state, params)
    if extractor == "DECISION_SPREAD_TO_WINDOW":
        return _decision_spread_to_window(decision_state, params)
    if extractor == "NEAREST_LEVEL_TO_ATR":
        return _nearest_level_to_atr(decision_state, params)
    if extractor == "PRICE_VS_WINDOW_RANGE":
        return _price_vs_window_range(decision_state, str(params["window"]))
    if extractor == "WINDOW_INTERACTION":
        return _window_interaction(decision_state, params)
    if extractor == "COT_CATEGORY_NET_SIGN":
        return _cot_category_net_sign(decision_state, str(params["category"]))
    if extractor == "COT_INFERRED_STATE":
        return _cot_inferred_state(decision_state, str(params["state_code"]))
    if extractor == "SOFR_WINDOW_BALANCE":
        return _sofr_window_balance(decision_state)
    if extractor == "COMPONENT_FACT_DIRECTION":
        return _component_fact_direction(
            _get_fact(
                decision_state,
                "decision_state.layers.catalysts.event_impact_state",
            )
        )
    raise ValueError(f"Unsupported M4 extractor: {extractor}")


def _series_change_sign(
    decision_state: Mapping[str, Any],
    path: str,
) -> FeatureObservation:
    fact = _get_fact(decision_state, path)
    if not _fact_eligible(fact):
        return _unknown()
    value = _mapping(fact["value"])
    if value.get("change_epistemic_status") == "UNKNOWN":
        return _unknown()
    change = _number(value.get("absolute_change"))
    if change is None:
        return _unknown()
    state = "RISING" if change > 0 else "FALLING" if change < 0 else "UNCHANGED"
    return _observation(
        state,
        fact,
        signature_payload={
            "absolute_change": change,
            "previous_record_id": value.get("previous_record_id"),
            "record_id": value.get("record_id"),
        },
    )


def _engine_component_direction(
    decision_state: Mapping[str, Any],
    component_code: str,
) -> FeatureObservation:
    synthesis = _mapping(decision_state.get("synthesis"))
    facts = [
        *_sequence(synthesis.get("supporting_evidence")),
        *_sequence(synthesis.get("contradicting_evidence")),
    ]
    matches = [
        fact
        for fact in facts
        if _mapping(_mapping(fact).get("value")).get("code") == component_code
    ]
    if len(matches) != 1 or not _fact_eligible(_mapping(matches[0])):
        return _unknown()
    fact = _mapping(matches[0])
    value = _mapping(fact["value"])
    direction = _number(value.get("direction"))
    if direction is None:
        return _unknown()
    state = "BULLISH" if direction > 0 else "BEARISH" if direction < 0 else "NEUTRAL"
    return _observation(state, fact, signature_payload=value.get("evidence", value))


def _structure_feature(
    decision_state: Mapping[str, Any],
    extractor: str,
    params: Mapping[str, Any],
) -> FeatureObservation:
    timeframe = _timeframe(decision_state, str(params["timeframe"]))
    if timeframe is None:
        return _unknown()
    if extractor == "STRUCTURE_TREND":
        fact = _mapping(timeframe.get("trend_state"))
        if not _fact_eligible(fact):
            return _unknown()
        return _observation(str(fact["value"]), fact)
    if extractor == "STRUCTURE_LATEST_DIRECTIONAL_DETECTION":
        fact = _mapping(timeframe.get(str(params["fact_name"])))
        if not _fact_eligible(fact):
            return _unknown()
        value = _mapping(fact["value"])
        detections = sorted(
            (_mapping(item) for item in _sequence(value.get("detections"))),
            key=lambda item: (
                str(item.get("detected_at", "")),
                str(item.get("timestamp", "")),
                str(item.get("kind", "")),
            ),
        )
        if not detections:
            return _observation("NONE", fact, signature_payload=value)
        kind = str(detections[-1].get("kind"))
        state = (
            "BULLISH"
            if kind == params["bullish_token"]
            else "BEARISH"
            if kind == params["bearish_token"]
            else "NONE"
        )
        return _observation(state, fact, signature_payload=detections[-1])
    if extractor == "STRUCTURE_MOMENTUM_SIGN":
        fact = _mapping(timeframe.get("momentum"))
        if not _fact_eligible(fact):
            return _unknown()
        value = _mapping(fact["value"])
        momentum = _number(value.get("momentum_atr"))
        if momentum is None:
            return _unknown()
        state = (
            "POSITIVE" if momentum > 0 else "NEGATIVE" if momentum < 0 else "FLAT"
        )
        return _observation(state, fact, signature_payload=value)
    if extractor == "STRUCTURE_BOOLEAN_STATE":
        fact = _mapping(timeframe.get(str(params["fact_name"])))
        if not _fact_eligible(fact):
            return _unknown()
        value = _mapping(fact["value"])
        detected = value.get("detected")
        if not isinstance(detected, bool):
            return _unknown()
        return _observation(
            "DETECTED" if detected else "NOT_DETECTED",
            fact,
            signature_payload=value,
        )
    if extractor == "STRUCTURE_RANGE_LOCATION":
        fact = _mapping(timeframe.get("range_state"))
        if not _fact_eligible(fact):
            return _unknown()
        value = _mapping(fact["value"])
        low = _number(value.get("range_low"))
        high = _number(value.get("range_high"))
        close = _number(value.get("last_close"))
        state = _third_state(close, low, high)
        if state == "UNKNOWN":
            return _unknown()
        return _observation(state, fact, signature_payload=value)
    raise ValueError(f"Unsupported structure extractor: {extractor}")


def _cross_change_sign(
    decision_state: Mapping[str, Any],
    params: Mapping[str, Any],
) -> FeatureObservation:
    fact = _get_fact(
        decision_state,
        f"decision_state.layers.cross_market.{params['instrument']}",
    )
    if not _fact_eligible(fact):
        return _unknown()
    instrument = _mapping(fact["value"])
    change = _mapping(_mapping(instrument.get("changes")).get(str(params["horizon"])))
    if change.get("status") != "READY" or change.get("epistemic_status") == "UNKNOWN":
        return _unknown()
    number = _number(change.get("percent_change"))
    if number is None:
        return _unknown()
    state = "UP" if number > 0 else "DOWN" if number < 0 else "FLAT"
    return _observation(state, fact, signature_payload=change)


def _window_fact(
    decision_state: Mapping[str, Any],
    window: str,
) -> Mapping[str, Any]:
    return _get_fact(
        decision_state,
        f"decision_state.layers.sessions_and_liquidity.{window}",
    )


def _window_direction(
    decision_state: Mapping[str, Any],
    window: str,
) -> FeatureObservation:
    fact = _window_fact(decision_state, window)
    if not _fact_eligible(fact):
        return _unknown()
    value = _mapping(fact["value"])
    open_value = _number(value.get("open"))
    close_value = _number(value.get("close"))
    if open_value is None or close_value is None:
        return _unknown()
    state = (
        "UP"
        if close_value > open_value
        else "DOWN"
        if close_value < open_value
        else "FLAT"
    )
    return _observation(state, fact, signature_payload=value)


def _window_close_location(
    decision_state: Mapping[str, Any],
    window: str,
) -> FeatureObservation:
    fact = _window_fact(decision_state, window)
    if not _fact_eligible(fact):
        return _unknown()
    value = _mapping(fact["value"])
    state = _third_state(
        _number(value.get("close")),
        _number(value.get("low")),
        _number(value.get("high")),
    )
    if state == "UNKNOWN":
        return _unknown()
    return _observation(state, fact, signature_payload=value)


def _window_range_to_atr(
    decision_state: Mapping[str, Any],
    params: Mapping[str, Any],
) -> FeatureObservation:
    window_fact = _window_fact(decision_state, str(params["window"]))
    timeframe = _timeframe(decision_state, str(params["timeframe"]))
    range_fact = _mapping(timeframe.get("range_state")) if timeframe else {}
    if not _fact_eligible(window_fact) or not _fact_eligible(range_fact):
        return _unknown()
    window_value = _mapping(window_fact["value"])
    range_value = _mapping(range_fact["value"])
    window_range = _number(window_value.get("range"))
    atr = _number(range_value.get("atr14"))
    if window_range is None or atr is None or atr <= 0:
        return _unknown()
    ratio = window_range / atr
    state = (
        "COMPRESSED"
        if ratio <= float(params["compressed_max"])
        else "EXPANDED"
        if ratio >= float(params["expanded_min"])
        else "NORMAL"
    )
    return _combined_observation(
        state,
        (window_fact, range_fact),
        {"atr": atr, "ratio": ratio, "window": window_value},
    )


def _window_spread_ratio(
    decision_state: Mapping[str, Any],
    params: Mapping[str, Any],
) -> FeatureObservation:
    fact = _window_fact(decision_state, str(params["window"]))
    if not _fact_eligible(fact):
        return _unknown()
    value = _mapping(fact["value"])
    average = _number(value.get("average_spread"))
    maximum = _number(value.get("maximum_spread"))
    if average is None or maximum is None or average <= 0:
        return _unknown()
    ratio = maximum / average
    state = "WIDE" if ratio >= float(params["wide_min_ratio"]) else "NORMAL"
    return _observation(
        state,
        fact,
        signature_payload={"ratio": ratio, "source_hash": value.get("source_hash")},
    )


def _decision_spread_to_window(
    decision_state: Mapping[str, Any],
    params: Mapping[str, Any],
) -> FeatureObservation:
    spread_fact = _get_fact(decision_state, "decision_state.market_mechanics.spread")
    window_fact = _window_fact(decision_state, str(params["window"]))
    if not _fact_eligible(spread_fact) or not _fact_eligible(window_fact):
        return _unknown()
    spread = _number(spread_fact["value"])
    window = _mapping(window_fact["value"])
    average = _number(window.get("average_spread"))
    if spread is None or average is None or average <= 0:
        return _unknown()
    ratio = spread / average
    state = (
        "TIGHT"
        if ratio <= float(params["tight_max_ratio"])
        else "WIDE"
        if ratio >= float(params["wide_min_ratio"])
        else "NORMAL"
    )
    return _combined_observation(
        state,
        (spread_fact, window_fact),
        {"ratio": ratio, "source_hash": window.get("source_hash")},
    )


def _nearest_level_to_atr(
    decision_state: Mapping[str, Any],
    params: Mapping[str, Any],
) -> FeatureObservation:
    price_fact = _get_fact(
        decision_state,
        "decision_state.market_mechanics.xauusd_price",
    )
    timeframe = _timeframe(decision_state, str(params["timeframe"]))
    range_fact = _mapping(timeframe.get("range_state")) if timeframe else {}
    if not _fact_eligible(price_fact) or not _fact_eligible(range_fact):
        return _unknown()
    price_value = _mapping(price_fact["value"])
    price = _number(price_value.get("value"))
    atr = _number(_mapping(range_fact["value"]).get("atr14"))
    levels = _sequence(decision_state.get("levels"))
    eligible_levels: list[tuple[str, float, Mapping[str, Any]]] = []
    for level in levels:
        level_map = _mapping(level)
        level_fact = _mapping(level_map.get("price"))
        if not _fact_eligible(level_fact):
            continue
        level_price = _number(level_fact.get("value"))
        if level_price is not None:
            eligible_levels.append(
                (str(level_map.get("level_id")), level_price, level_fact)
            )
    if price is None or atr is None or atr <= 0 or not eligible_levels:
        return _unknown()
    nearest = min(eligible_levels, key=lambda item: abs(item[1] - price))
    ratio = abs(nearest[1] - price) / atr
    state = "NEAR" if ratio <= float(params["near_max_atr"]) else "NOT_NEAR"
    return _combined_observation(
        state,
        (price_fact, range_fact, nearest[2]),
        {"level_id": nearest[0], "ratio": ratio},
    )


def _price_vs_window_range(
    decision_state: Mapping[str, Any],
    window: str,
) -> FeatureObservation:
    price_fact = _get_fact(
        decision_state,
        "decision_state.market_mechanics.xauusd_price",
    )
    window_fact = _window_fact(decision_state, window)
    if not _fact_eligible(price_fact) or not _fact_eligible(window_fact):
        return _unknown()
    price = _number(_mapping(price_fact["value"]).get("value"))
    value = _mapping(window_fact["value"])
    low = _number(value.get("low"))
    high = _number(value.get("high"))
    if price is None or low is None or high is None or high <= low:
        return _unknown()
    state = (
        "ABOVE"
        if price > high
        else "BELOW"
        if price < low
        else _third_state(price, low, high)
    )
    return _combined_observation(
        state,
        (price_fact, window_fact),
        {"high": high, "low": low, "price": price},
    )


def _window_interaction(
    decision_state: Mapping[str, Any],
    params: Mapping[str, Any],
) -> FeatureObservation:
    inner_fact = _window_fact(decision_state, str(params["inner_window"]))
    outer_fact = _window_fact(decision_state, str(params["outer_window"]))
    if not _fact_eligible(inner_fact) or not _fact_eligible(outer_fact):
        return _unknown()
    inner = _mapping(inner_fact["value"])
    outer = _mapping(outer_fact["value"])
    inner_high = _number(inner.get("high"))
    inner_low = _number(inner.get("low"))
    outer_high = _number(outer.get("high"))
    outer_low = _number(outer.get("low"))
    if None in {inner_high, inner_low, outer_high, outer_low}:
        return _unknown()
    high_break = bool(outer_high > inner_high)
    low_break = bool(outer_low < inner_low)
    state = (
        "BOTH_SIDES"
        if high_break and low_break
        else "HIGH_ONLY"
        if high_break
        else "LOW_ONLY"
        if low_break
        else "INSIDE"
    )
    return _combined_observation(
        state,
        (inner_fact, outer_fact),
        {"inner": inner, "outer": outer},
    )


def _cot_category_net_sign(
    decision_state: Mapping[str, Any],
    category: str,
) -> FeatureObservation:
    fact = _get_fact(
        decision_state,
        f"decision_state.layers.positioning.{category}",
    )
    if not _fact_eligible(fact, allow_cot_unverified=True):
        return _unknown()
    value = _mapping(fact["value"])
    net = _number(value.get("net_contracts"))
    if net is None:
        return _unknown()
    state = "NET_LONG" if net > 0 else "NET_SHORT" if net < 0 else "FLAT"
    return _observation(state, fact, signature_payload=value)


def _cot_inferred_state(
    decision_state: Mapping[str, Any],
    state_code: str,
) -> FeatureObservation:
    facts = _sequence(
        _mapping(_mapping(decision_state.get("layers")).get("positioning")).get(
            "inferred_states"
        )
    )
    matches = [
        _mapping(item)
        for item in facts
        if _mapping(_mapping(item).get("value")).get("code") == state_code
    ]
    if len(matches) != 1 or not _fact_eligible(
        matches[0],
        allow_cot_unverified=True,
    ):
        return _unknown()
    fact = matches[0]
    value = _mapping(fact["value"])
    return _observation(str(value.get("state", "UNKNOWN")), fact, signature_payload=value)


def _sofr_window_balance(
    decision_state: Mapping[str, Any],
) -> FeatureObservation:
    fact = _get_fact(
        decision_state,
        "decision_state.layers.expectations.policy_path.repricing",
    )
    if not _fact_eligible(fact):
        return _unknown()
    value = _mapping(fact["value"])
    windows = [
        _mapping(item)
        for item in _sequence(value.get("windows"))
        if _number(_mapping(item).get("probability_cut")) is not None
        and _number(_mapping(item).get("probability_hike")) is not None
    ]
    if not windows:
        return _unknown()
    cut = math.fsum(float(item["probability_cut"]) for item in windows) / len(windows)
    hike = math.fsum(float(item["probability_hike"]) for item in windows) / len(windows)
    state = (
        "CUT_DOMINANT"
        if cut > hike
        else "HIKE_DOMINANT"
        if hike > cut
        else "BALANCED"
    )
    return _observation(
        state,
        fact,
        signature_payload={
            "observation_date": value.get("observation_date"),
            "window_record_ids": sorted(str(item.get("record_id")) for item in windows),
        },
    )


def _component_fact_direction(fact: Mapping[str, Any]) -> FeatureObservation:
    if not _fact_eligible(fact):
        return _unknown()
    value = _mapping(fact["value"])
    direction = _number(value.get("direction"))
    if direction is None:
        return _unknown()
    state = "BULLISH" if direction > 0 else "BEARISH" if direction < 0 else "NEUTRAL"
    return _observation(state, fact, signature_payload=value.get("evidence", value))


def _timeframe(
    decision_state: Mapping[str, Any],
    timeframe: str,
) -> Mapping[str, Any] | None:
    market_structure = _mapping(decision_state.get("market_structure"))
    matches = [
        _mapping(item)
        for item in _sequence(market_structure.get("timeframes"))
        if _mapping(item).get("timeframe") == timeframe
    ]
    return matches[0] if len(matches) == 1 else None


def _get_fact(
    decision_state: Mapping[str, Any],
    path: str,
) -> Mapping[str, Any]:
    prefix = "decision_state."
    if path.startswith(prefix):
        path = path[len(prefix) :]
    current: Any = decision_state
    for token in path.split("."):
        if "[" in token:
            raise ValueError(f"Parameterized paths require a dedicated extractor: {path}")
        current = _mapping(current).get(token)
        if current is None:
            return {}
    return _mapping(current)


def _fact_eligible(
    fact: Mapping[str, Any],
    *,
    allow_cot_unverified: bool = False,
) -> bool:
    if not fact or fact.get("value") is None:
        return False
    if fact.get("epistemic_status") == "UNKNOWN":
        return False
    qualities = COT_ALLOWED_QUALITIES if allow_cot_unverified else VALID_QUALITIES
    return fact.get("quality") in qualities


def _observation(
    state: str,
    fact: Mapping[str, Any],
    *,
    signature_payload: Any | None = None,
) -> FeatureObservation:
    if state == "UNKNOWN":
        return _unknown()
    payload = (
        signature_payload
        if signature_payload is not None
        else {
            "as_of": fact.get("as_of"),
            "available_at": fact.get("available_at"),
            "evidence": fact.get("evidence"),
            "value": fact.get("value"),
        }
    )
    return FeatureObservation(
        state=state,
        source_signature=canonical_hash(json_ready(payload)),
        epistemic_status=str(fact.get("epistemic_status")),
        quality=str(fact.get("quality")),
    )


def _combined_observation(
    state: str,
    facts: Sequence[Mapping[str, Any]],
    signature_payload: Any,
) -> FeatureObservation:
    if state == "UNKNOWN" or any(not fact for fact in facts):
        return _unknown()
    epistemic = (
        "INFERRED"
        if any(fact.get("epistemic_status") == "INFERRED" for fact in facts)
        else "CALCULATED"
    )
    quality = (
        "PARTIAL"
        if any(fact.get("quality") != "VALID" for fact in facts)
        else "VALID"
    )
    return FeatureObservation(
        state=state,
        source_signature=canonical_hash(json_ready(signature_payload)),
        epistemic_status=epistemic,
        quality=quality,
    )


def _unknown() -> FeatureObservation:
    return FeatureObservation(
        state="UNKNOWN",
        source_signature="UNKNOWN",
        epistemic_status="UNKNOWN",
        quality="MISSING",
    )


def _third_state(
    value: float | None,
    low: float | None,
    high: float | None,
) -> str:
    if value is None or low is None or high is None or high <= low:
        return "UNKNOWN"
    fraction = (value - low) / (high - low)
    if fraction <= 1 / 3:
        return "LOWER_THIRD"
    if fraction >= 2 / 3:
        return "UPPER_THIRD"
    return "MIDDLE_THIRD"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    return list(value) if isinstance(value, Sequence) and not isinstance(value, str) else []


def embedded_hash(document: Mapping[str, Any], hash_field: str) -> str:
    content = {key: value for key, value in document.items() if key != hash_field}
    return hashlib.sha256(
        json.dumps(
            json_ready(content),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
