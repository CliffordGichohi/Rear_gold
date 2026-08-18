#!/usr/bin/env python3
"""Prepare and verify GC Session Trigger Edge Discovery Contract V1 Milestone 1.

This tool is deliberately metadata-only. It must never deserialize market rows,
event outcomes, 2025 values, or 2026 values.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from statistics import NormalDist
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
OUTPUT_DIR = ARTIFACTS / "gc_session_trigger_edge_m1_v01"

TAXONOMY_PATH = MANIFESTS / "gc_session_trigger_edge_taxonomy_v01.json"
OUTCOMES_PATH = MANIFESTS / "gc_session_trigger_edge_outcomes_v01.json"
FEATURES_PATH = MANIFESTS / "gc_session_trigger_edge_feature_traceability_v01.json"
STATISTICS_PATH = MANIFESTS / "gc_session_trigger_edge_statistics_v01.json"
CONTRACT_PATH = MANIFESTS / "gc_session_trigger_edge_contract_v01.json"
FREEZE_PATH = MANIFESTS / "gc_session_trigger_edge_m1_freeze_v01.json"
CONTRACT_DOC_PATH = ROOT / "GC_SESSION_TRIGGER_EDGE_DISCOVERY_CONTRACT_V1.md"
REPORT_PATH = ROOT / "GC_SESSION_TRIGGER_EDGE_MILESTONE_1.md"

IMPLEMENTATION_PATH = Path(__file__).resolve()

BOUND: dict[str, tuple[Path, str]] = {
    "reference_book": (
        ROOT / "Gold_USD_Market_Intelligence_Reference_Book.pdf",
        "3e7ddc561932a859a4c9043a38ff71b7003907963fb52247e41edaeefc8ac42a",
    ),
    "step5dr3_verdict": (
        ARTIFACTS / "gc_microstructure_step5dr3_v01" / "verdict.json",
        "6df80389517ff1056250f42d5e4da904460bdd0c9f66c26c7c459f3c48b94257",
    ),
    "step5dr3_manifest": (
        ARTIFACTS / "gc_microstructure_step5dr3_v01" / "manifest.json",
        "662629be8586bc5182bacec22e327116adb487a99edab2431590b4ab7cd7bcc0",
    ),
    "step5dr3_final_seal": (
        ARTIFACTS / "gc_microstructure_step5dr3_v01" / "final_seal.json",
        "5f72949acefe21f2a0d387bd72ec458808ed075a6c89ffbfa5f8780e79263ddc",
    ),
    "step5dr3_report": (
        ROOT / "GC_MICROSTRUCTURE_STEP_5D_R3_REPORT.md",
        "83567fd7591631b5705f2808716c74e8c45c2c7c2f0bbdf4f1a5c4a388fa8e18",
    ),
    "step5dr3_amendment": (
        MANIFESTS / "gc_microstructure_step_5dr3_amendment_v01.json",
        "335c39cf4ad459da85553ed698f5b926b50c1c0f208b7ecb79edc8b8ec233b60",
    ),
    "step5dr3_population": (
        MANIFESTS / "gc_microstructure_step_5dr3_population_v01.json",
        "67b31a1ddaa47c13f24d402a86b1f666e0d6bfe20ca1c3af86538d165f798667",
    ),
    "step5dr3_freeze": (
        MANIFESTS / "gc_microstructure_step_5dr3_freeze_v01.json",
        "4d9673a803b330758e320fb4094c168912459acba6c6d807f6fbf67f07c1f4f3",
    ),
    "step5dr2_certification": (
        ARTIFACTS / "gc_microstructure_step5dr2_v01" / "certification.json",
        "454638ff5b011c75f94ba690114c0552bb333902986b7fa24dbaf4b707292e67",
    ),
    "step5dr2_final_seal": (
        ARTIFACTS / "gc_microstructure_step5dr2_v01" / "final_seal.json",
        "65a7b19971eae1d434720f79d0dcd39d4c05d4fbb41ab995ac4632f49d80ad24",
    ),
    "microstructure_contract_v1": (
        MANIFESTS / "gc_microstructure_conditional_edge_discovery_contract_v01.json",
        "da9048f497c853ef3b1f2a4debe6c80f8c650217004bfe6df05e045751554fcb",
    ),
    "step5a_feature_registry": (
        MANIFESTS / "gc_microstructure_step_5a_feature_hypothesis_registry_v01.json",
        "4b207a1dec5aa78a904c86cf8c6a14bf0a517dd918f24c5270c254400c865f01",
    ),
    "step4a_feature_protocol": (
        MANIFESTS / "gc_microstructure_step_4a_protocol_v01.json",
        "8f1ba7230919b7422344253d4f3e55fea1e86495551cbbbf53f3e1bdcb9ec3a2",
    ),
    "step4a3_feature_freeze": (
        MANIFESTS / "gc_microstructure_step_4a3_freeze_v01.json",
        "b4968106e21ffd7836ccca4438b826f63237ffd2cd0dca17c1ad9ef45973b1bb",
    ),
    "budget_c_request_registry": (
        MANIFESTS / "gc_microstructure_step_5b_budget_c_request_registry_v01.json",
        "d8dfe8a04e0f824c98ec4e88b6c75b7e56214616e56124b76bdbfe0b20b0dd99",
    ),
    "budget_c_freeze": (
        MANIFESTS / "gc_microstructure_step_5b_budget_c_freeze_v01.json",
        "ddfe58d2a366410f649de89bc7081b0081d16717a7245fec83f5d2bfa9efa916",
    ),
    "step5b2_amendment": (
        MANIFESTS / "gc_microstructure_step_5b2_amendment_v01.json",
        "1a6dd3372f40b52d219b38e35504b9a96046ffc284117ed1ac6cc703d009f9d7",
    ),
    "step5b2_freeze": (
        MANIFESTS / "gc_microstructure_step_5b2_freeze_v01.json",
        "0c1e7b8db099ea4489c201dda9893da184a55f8159f89a4ce946e78a1485f918",
    ),
    "step5b2_manifest": (
        ARTIFACTS / "gc_microstructure_step_5b2_v01" / "step5b2_final" / "manifest.json",
        "3fedb586ce4f9621721575b748b82043f47a4f6630488c29e0b2f8e73b4c86f1",
    ),
    "step5b2_verdict": (
        ARTIFACTS / "gc_microstructure_step_5b2_v01" / "step5b2_final" / "verdict.json",
        "5f3bd13cc2336a50c09ecfcc44c7d63b226a4d212f9d08666d6a50e93e09a6cb",
    ),
    "step5b2_source_verification": (
        ARTIFACTS / "gc_microstructure_step_5b2_v01" / "step5b2_runs" / "source_verification.json",
        "f36180c5adcbf12f0c0d518ea6f3511593a6cb120a33a74f8fafe2a6f163e657",
    ),
    "step5c_protocol": (
        MANIFESTS / "gc_microstructure_step_5c_protocol_v01.json",
        "25e087ae505bd2b304b5d9533c9fb8dd8042b47e8e498ed82242ad48365e272d",
    ),
    "step5c_freeze": (
        MANIFESTS / "gc_microstructure_step_5c_freeze_v01.json",
        "5ad5d57af1fdab6a80e90cb872408f1f6df99d2d7a4a892a5f380c49aee9f82d",
    ),
    "step5c_row_registry": (
        MANIFESTS / "gc_microstructure_step_5c_row_registry_v01.json",
        "a0c2b6dff0dd6c57e25b5f194342c69202e02f2e642f6fe8ae75ac2ea1bbe225",
    ),
    "step5c_manifest": (
        ARTIFACTS / "gc_microstructure_step5c_v01" / "manifest.json",
        "f7150f861f4883e3f7c100822af527ba497b8343225c24ebe16ffe11107e31fb",
    ),
    "step5c_verdict": (
        ARTIFACTS / "gc_microstructure_step5c_v01" / "verdict.json",
        "f98702e5260f60fa258a8f5ed43adc944724075bf442f958677fdf8fe3dee2ad",
    ),
    "step5c_preflight": (
        ARTIFACTS / "gc_microstructure_step5c_v01" / "preflight.json",
        "9ff6e27e17c84dbd9e99e09eaccea376c84acd4fae6795caa1ba3f3a8309d78b",
    ),
    "v3_traceability": (
        MANIFESTS / "gold_session_behaviour_v3_traceability_v01.json",
        "9690360ed1c9eceac1b26428460e54ec4326b7ffb0ef94c73dd1574589a2bd92",
    ),
    "gold_casebook_manifest": (
        ARTIFACTS / "gold_casebook_v01" / "manifest.json",
        "38e4aadc43917a5b91d04d47ab18542d7514fe257cc030f959d34080865314d6",
    ),
    "gold_casebook_price_bars": (
        ARTIFACTS / "gold_casebook_v01" / "price_bars.jsonl.gz",
        "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e",
    ),
}

OUTPUT_PATHS = (
    TAXONOMY_PATH,
    OUTCOMES_PATH,
    FEATURES_PATH,
    STATISTICS_PATH,
    CONTRACT_PATH,
    FREEZE_PATH,
    CONTRACT_DOC_PATH,
    REPORT_PATH,
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def write_text_exclusive(path: Path, value: str) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def seal_record(value: dict[str, Any], field: str) -> dict[str, Any]:
    value[field] = canonical_hash(value)
    return value


def flatten_feature_columns(registry: Mapping[str, Any]) -> list[str]:
    sealed = registry["sealed_feature_columns"]
    groups = (
        "identity_and_time",
        "mbo_counts",
        "mbo_side_flow",
        "mbo_ratios_ppb",
        "mbp_counts_and_state",
        "mbp_price_features_fixed_1e9",
        "mbp_depth_features",
    )
    values: list[str] = []
    for group in groups:
        item = sealed[group]
        if not isinstance(item, list):
            raise TypeError(group)
        values.extend(str(name) for name in item)
    if len(values) != 85 or len(set(values)) != 85 or sealed["expected_count"] != 85:
        raise ValueError("Sealed 85-column feature registry changed")
    return values


def mde_one_sample(n: int, alpha: float, power: float = 0.80) -> float:
    normal = NormalDist()
    z_alpha = normal.inv_cdf(1.0 - alpha / 2.0)
    z_power = normal.inv_cdf(power)
    return (z_alpha + z_power) * 0.5 / (n ** 0.5)


def mde_two_sample(n_condition: int, n_comparison: int, alpha: float, power: float = 0.80) -> float:
    normal = NormalDist()
    z_alpha = normal.inv_cdf(1.0 - alpha / 2.0)
    z_power = normal.inv_cdf(power)
    standard_error = (0.25 * (1.0 / n_condition + 1.0 / n_comparison)) ** 0.5
    return (z_alpha + z_power) * standard_error


def verify_predecessors() -> dict[str, Any]:
    for name, (path, expected) in BOUND.items():
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"Predecessor hash failed: {name} {actual}")

    r3_verdict = load_json(BOUND["step5dr3_verdict"][0])
    r3_seal = load_json(BOUND["step5dr3_final_seal"][0])
    if r3_verdict.get("status") != "PASS_STEP_5D_R3_DISCOVERY_ZERO_CANDIDATES":
        raise ValueError("Step 5D-R3 zero-candidate verdict changed")
    if r3_verdict.get("summary", {}).get("shortlisted_provisional_candidates") != 0:
        raise ValueError("Step 5D-R3 candidate count changed")
    if r3_verdict.get("year_2025_or_2026_values_accessed") is not False:
        raise ValueError("Step 5D-R3 holdout access flag changed")
    if r3_seal.get("verdict_sha256") != BOUND["step5dr3_verdict"][1]:
        raise ValueError("Step 5D-R3 final seal no longer binds the verdict")

    request_registry = load_json(BOUND["budget_c_request_registry"][0])
    selected_rows = request_registry.get("selected_dates", [])
    request_intervals = request_registry.get("request_intervals", [])
    provider_requests = request_registry.get("provider_quote_requests", [])
    if len(selected_rows) != 188 or len(request_intervals) != 40 or len(provider_requests) != 80:
        raise ValueError("Budget C development registry changed")
    dates = [str(item["trade_date"]) for item in selected_rows]
    if len(set(dates)) != 188 or min(dates) != "2021-11-08" or max(dates) != "2024-12-13":
        raise ValueError("Budget C date population changed")
    weeks = [str(item["selected_month_week_id"]) for item in selected_rows]
    if len(set(weeks)) != 38:
        raise ValueError("Budget C month-week population changed")

    row_registry = load_json(BOUND["step5c_row_registry"][0])
    rows = row_registry.get("rows", [])
    dispositions = Counter(str(item["availability_disposition"]) for item in rows)
    if len(rows) != 376 or dispositions != {"EXPECTED_AVAILABLE": 374, "UNAVAILABLE_DOCUMENTED": 2}:
        raise ValueError(f"Step 5C session registry changed: {dispositions}")
    session_counts = Counter(str(item["session_code"]) for item in rows)
    if session_counts != {"LONDON": 188, "NEW_YORK": 188}:
        raise ValueError("Step 5C session counts changed")

    source_verification = load_json(BOUND["step5b2_source_verification"][0])["reproducible_payload"]
    if (
        source_verification.get("status") != "PASS_SOURCE_SEAL_VERIFICATION"
        or source_verification.get("formal_pass") is not True
        or source_verification.get("verified_provider_requests") != 80
        or source_verification.get("verified_files") != 936
        or source_verification.get("source_rows_or_market_values_accessed") is not False
    ):
        raise ValueError("Step 5B.2 source verification changed")

    preflight = load_json(BOUND["step5c_preflight"][0])
    source_records = preflight.get("source_records", [])
    records_by_schema = Counter()
    for item in source_records:
        records_by_schema[str(item["schema"])] += int(item["provider_records"])
    if records_by_schema != {"mbo": 457_669_373, "mbp-10": 369_061_881}:
        raise ValueError(f"Provider record metadata changed: {records_by_schema}")
    if (
        preflight.get("status") != "PASS_STEP_5C_PRE_MATERIALIZATION_READINESS"
        or preflight.get("session_date_count") != 188
        or preflight.get("decision_row_count") != 376
        or preflight.get("development_outcomes_accessed") is not False
    ):
        raise ValueError("Step 5C preflight metadata changed")

    feature_registry = load_json(BOUND["step5a_feature_registry"][0])
    feature_columns = flatten_feature_columns(feature_registry)
    if len(feature_registry.get("derived_microstructure_states", [])) != 8:
        raise ValueError("Derived microstructure state count changed")
    if len(feature_registry.get("eligible_fundamental_bias_contexts", [])) != 8:
        raise ValueError("Fundamental context count changed")
    if len(feature_registry.get("eligible_price_level_and_session_contexts", [])) != 7:
        raise ValueError("Price/session context count changed")

    casebook = load_json(BOUND["gold_casebook_manifest"][0])
    artifact_counts = {
        str(item["name"]): int(item["record_count"])
        for item in casebook.get("artifacts", [])
    }
    expected_artifact_counts = {
        "price_bars.jsonl.gz": 1_570_471,
        "structure_snapshots.jsonl.gz": 3_270,
        "cross_market_snapshots.jsonl.gz": 4_353,
        "positioning.jsonl.gz": 260,
        "events.jsonl.gz": 412,
        "fundamentals.jsonl.gz": 26_394,
        "sessions.jsonl.gz": 1_659,
    }
    if artifact_counts != expected_artifact_counts:
        raise ValueError("Gold casebook metadata counts changed")

    by_year = Counter(value[:4] for value in dates)
    if by_year != {"2021": 10, "2022": 60, "2023": 60, "2024": 58}:
        raise ValueError(f"Development year counts changed: {by_year}")
    available_dates = {
        str(item["session_date"])
        for item in rows
        if item["availability_disposition"] == "EXPECTED_AVAILABLE"
    }
    if len(available_dates) != 187 or "2022-04-15" in available_dates:
        raise ValueError("Available event-date metadata changed")

    return {
        "r3_verdict": r3_verdict,
        "request_registry": request_registry,
        "row_registry": row_registry,
        "source_verification": source_verification,
        "preflight": preflight,
        "feature_registry": feature_registry,
        "feature_columns": feature_columns,
        "casebook": casebook,
        "dates": dates,
        "weeks": sorted(set(weeks)),
        "available_dates": sorted(available_dates),
        "by_year": dict(sorted(by_year.items())),
        "records_by_schema": dict(sorted(records_by_schema.items())),
        "casebook_artifact_counts": artifact_counts,
    }


def build_taxonomy(frozen_at: str) -> dict[str, Any]:
    level_families = [
        {
            "level_family": "ASIA_RANGE",
            "sessions": ["LONDON", "NEW_YORK"],
            "upper": "ASIA_HIGH",
            "lower": "ASIA_LOW",
            "definition": "Frozen high and low of the completed casebook Asia session; both must be available before the event session opens.",
            "epistemic_class": "CALCULATED",
        },
        {
            "level_family": "PRIOR_DAY_RANGE",
            "sessions": ["LONDON", "NEW_YORK"],
            "upper": "PRIOR_DAY_HIGH",
            "lower": "PRIOR_DAY_LOW",
            "definition": "High and low of the preceding completed casebook gold day; neither may use a current-session bar.",
            "epistemic_class": "CALCULATED",
        },
        {
            "level_family": "LONDON_PRE_NEW_YORK_RANGE",
            "sessions": ["NEW_YORK"],
            "upper": "LONDON_PRE_NEW_YORK_HIGH",
            "lower": "LONDON_PRE_NEW_YORK_LOW",
            "definition": "XAUUSD high and low from London 08:00 local through the final complete one-minute bar ending no later than New York 08:00 local; freeze once at the New York session open.",
            "epistemic_class": "CALCULATED",
        },
        {
            "level_family": "SESSION_OPENING_RANGE_15",
            "sessions": ["LONDON", "NEW_YORK"],
            "upper": "SESSION_OR15_HIGH",
            "lower": "SESSION_OR15_LOW",
            "definition": "XAUUSD high and low of the first fifteen complete session minutes [08:00,08:15) local; usable only from 08:15 local onward.",
            "epistemic_class": "CALCULATED",
        },
    ]
    event_families = [
        {
            "event_family": "LEVEL_SWEEP_RECLAIM",
            "source_domain": "XAUUSD_PRICE_LEVEL",
            "applicable_level_families": [item["level_family"] for item in level_families],
            "upper_definition": "A complete one-minute bar trades strictly above the upper level and either that bar or the immediately following complete bar closes at or below the level, before any two-close acceptance is completed.",
            "lower_definition": "Exact mirror: a complete bar trades strictly below the lower level and that bar or the immediately following complete bar closes at or above the level before acceptance.",
            "confirmation_time": "Close time of the earliest reclaim-confirming bar.",
            "directional_prior": {"UPPER": "DOWN", "LOWER": "UP"},
            "epistemic_class": "CALCULATED",
            "causal_claim": False,
        },
        {
            "event_family": "LEVEL_BREAK_ACCEPT",
            "source_domain": "XAUUSD_PRICE_LEVEL",
            "applicable_level_families": [item["level_family"] for item in level_families],
            "upper_definition": "Two consecutive complete one-minute closes are strictly above the upper level.",
            "lower_definition": "Two consecutive complete one-minute closes are strictly below the lower level.",
            "confirmation_time": "Close time of the second qualifying bar.",
            "directional_prior": {"UPPER": "UP", "LOWER": "DOWN"},
            "epistemic_class": "CALCULATED",
            "causal_claim": False,
        },
        {
            "event_family": "LEVEL_FAILED_ACCEPTANCE",
            "source_domain": "XAUUSD_PRICE_LEVEL",
            "applicable_level_families": [item["level_family"] for item in level_families],
            "upper_definition": "After a confirmed upper LEVEL_BREAK_ACCEPT, the first complete close at or below the level occurs within the next five complete one-minute bars.",
            "lower_definition": "After a confirmed lower LEVEL_BREAK_ACCEPT, the first complete close at or above the level occurs within the next five complete one-minute bars.",
            "confirmation_time": "Close time of the first return bar; a return after five bars is not this event.",
            "directional_prior": {"UPPER": "DOWN", "LOWER": "UP"},
            "epistemic_class": "CALCULATED",
            "causal_claim": False,
        },
        {
            "event_family": "FLOW_DEPTH_ALIGNMENT_ONSET",
            "source_domain": "GC_MICROSTRUCTURE",
            "definition": "FLOW_PRESSURE_W60 and DEPTH_PRESSURE_W60 have the same directional state at two consecutive completed minute decisions and did not have that same joint direction at the immediately preceding minute decision.",
            "confirmation_time": "Second consecutive aligned minute decision.",
            "directional_prior": {"BULLISH": "UP", "BEARISH": "DOWN"},
            "epistemic_class": "INFERRED",
            "institution_or_motive_claim_permitted": False,
        },
        {
            "event_family": "ABSORPTION_ONSET",
            "source_domain": "GC_MICROSTRUCTURE",
            "definition": "The unchanged ABSORPTION_STATE_W60 is the same directional absorption state at two consecutive completed minute decisions and was not that state at the immediately preceding minute.",
            "confirmation_time": "Second consecutive absorption minute decision.",
            "directional_prior": {"BULLISH_ABSORPTION": "UP", "BEARISH_ABSORPTION": "DOWN"},
            "epistemic_class": "INFERRED",
            "institution_or_motive_claim_permitted": False,
        },
        {
            "event_family": "FRAGILITY_FLOW_ONSET",
            "source_domain": "GC_MICROSTRUCTURE",
            "definition": "LIQUIDITY_FRAGILITY is FRAGILE and FLOW_PRESSURE_W60 has the same directional state at two consecutive completed minute decisions; the exact pair was absent at the immediately preceding minute.",
            "confirmation_time": "Second consecutive qualifying minute decision.",
            "directional_prior": {"BULLISH_FLOW": "UP", "BEARISH_FLOW": "DOWN"},
            "epistemic_class": "INFERRED",
            "institution_or_motive_claim_permitted": False,
        },
    ]
    record = {
        "version": "GC_SESSION_TRIGGER_EDGE_EVENT_TAXONOMY_V1_0",
        "status": "FROZEN_BEFORE_EVENT_VALUE_MATERIALIZATION",
        "frozen_at_utc": frozen_at,
        "book_logic": [
            "Liquidity is spread, depth, resilience, and capacity to absorb flow; it is not merely a chart line.",
            "Acceptance means sustained trading beyond a level; rejection means price does not sustain the new area.",
            "Absorption is aggressive flow with limited price progress against opposite liquidity.",
            "Structure is evidence, not prophecy; macro, catalysts, session, and cross-market context remain separate.",
            "A supportive macro regime is bias context and never an automatic entry.",
        ],
        "research_units": {
            "sessions": {
                "LONDON": {"timezone": "Europe/London", "trigger_scan_local": "[08:00:00,12:00:00)"},
                "NEW_YORK": {"timezone": "America/New_York", "trigger_scan_local": "[08:00:00,12:00:00)"},
            },
            "dst": "Convert each local session independently with the IANA timezone database; never hard-code DST dates.",
            "decision_grid": "Completed XAUUSD one-minute bars. Candidate decisions occur at bar close from 08:01 through 12:00 local.",
            "decision_at": "The confirming bar close. The bar must be unique, complete, and available no later than its close; all GC inputs must have ts_recv strictly before or equal to their completed bucket boundary no later than decision_at.",
            "gc_market_state": "Only CONTINUOUS_MATCHING, authoritative two-sided, uncrossed MBP-10 bucket-close states are eligible.",
            "no_venue_price_mixing": "XAUUSD levels are compared only with XAUUSD bars. GC prices are never numerically compared with spot/broker levels.",
        },
        "level_families": level_families,
        "event_families": event_families,
        "canonicalization": {
            "per_level": "Retain only the first event for each session_date, session, event_family, direction, and level_family.",
            "microstructure": "Retain only the first event for each session_date, session, event_family, and direction.",
            "pooled_family_analysis": "At most three earliest canonical events per family and date may enter the primary analysis; simultaneous level events form one event with a sorted level-family list.",
            "first_event_sensitivity": "Every candidate must retain the same favorable sign when restricted to the first family event per date.",
            "no_rearming": "A retained key cannot rearm later in the same session date.",
            "missing_minute": "A missing, duplicate, incomplete, late, or lineage-invalid bar makes any event whose detection window intersects it UNKNOWN; never bridge the gap.",
        },
        "event_record_required_fields": [
            "event_id", "session_date", "session_code", "event_family", "source_domain",
            "directional_prior", "decision_at", "confirmation_evidence", "level_families",
            "feature_available_at_max", "epistemic_class", "quality_state", "lineage_hash",
        ],
        "prohibited_labels": ["smart_money_observed", "institution_identified", "dealer_intent_proven"],
        "outcomes_accessed": False,
        "year_2025_or_2026_values_accessed": False,
    }
    return seal_record(record, "taxonomy_receipt")


def build_outcomes(frozen_at: str) -> dict[str, Any]:
    record = {
        "version": "GC_SESSION_TRIGGER_EDGE_OUTCOME_REGISTRY_V1_0",
        "status": "FROZEN_BEFORE_EVENT_OR_OUTCOME_VALUE_MATERIALIZATION",
        "frozen_at_utc": frozen_at,
        "instrument": "IC_MARKETS_MT5_XAUUSD",
        "role": "NEUTRAL_FORWARD_BEHAVIOUR_MEASUREMENT_NOT_EXECUTION",
        "anchor": {
            "price": "Close of the complete XAUUSD one-minute bar that confirms the event.",
            "timestamp": "event decision_at",
            "availability": "The confirming bar must be complete and available by decision_at.",
            "not_a_fill": True,
        },
        "horizons_minutes": [5, 15, 30, 60],
        "primary_endpoint": {
            "outcome_id": "XAUUSD_FWD_15M_SIGNED_DISPLACEMENT",
            "formula": "XAUUSD close at decision_at+15 minutes minus anchor close, in USD per troy ounce.",
            "direction_states": {
                "UP": "signed displacement > +0.01",
                "DOWN": "signed displacement < -0.01",
                "FLAT": "absolute signed displacement <= 0.01",
                "UNKNOWN": "Any required timestamp, completeness, availability, uniqueness, or lineage gate fails.",
            },
            "favorable_transform": "Multiply signed displacement by +1 for an UP prior and -1 for a DOWN prior.",
            "binary_policy": "UP and DOWN enter directional hit-rate inference; retain and report FLAT but exclude it from binary hit rate.",
        },
        "secondary_endpoints": [
            {"outcome_id": "XAUUSD_FWD_5M_SIGNED_DISPLACEMENT", "role": "CONSISTENCY_ONLY"},
            {"outcome_id": "XAUUSD_FWD_30M_SIGNED_DISPLACEMENT", "role": "CONSISTENCY_ONLY"},
            {"outcome_id": "XAUUSD_FWD_60M_SIGNED_DISPLACEMENT", "role": "CONSISTENCY_ONLY"},
            {"outcome_id": "GC_MID_FWD_15M_SIGNED_TICKS", "role": "CROSS_VENUE_CONSISTENCY_ONLY"},
        ],
        "descriptive_path_measurements": [
            "maximum upward and downward XAUUSD displacement from the anchor at completed one-minute timestamps",
            "elapsed minutes to each maximum",
            "first completed-minute direction and whether it reversed by each registered horizon",
            "GC midpoint sign agreement at fifteen minutes",
        ],
        "path_measurement_semantics": "Descriptive market behaviour only; never call an excursion MFE or MAE and never infer a fill, stop, or target.",
        "temporal_integrity": {
            "feature_boundary": "No feature or event predicate may use a source fact available after decision_at.",
            "outcome_boundary": "Every outcome fact must be strictly after decision_at except the frozen anchor.",
            "complete_path": "Path measurements require every expected complete one-minute timestamp through the horizon; endpoint-only interpolation is forbidden.",
            "overlap": "Overlapping forward windows remain recorded and are handled through date/week clustering; they are never treated as independent.",
            "roll": "GC consistency outcomes must remain on the point-in-time mapped GC.v.0 instrument for the event date; a roll ambiguity makes GC consistency UNKNOWN, never the XAUUSD primary endpoint.",
        },
        "outcome_join_authority": "No outcome join is authorized in Milestone 1 or Milestone 2. A later sealed test registry and explicit instruction are required.",
        "execution_semantics_forbidden": [
            "entry", "fill", "stop", "target", "slippage", "commission", "position size",
            "trade", "PnL", "R multiple", "account return",
        ],
        "outcome_values_accessed": False,
        "year_2025_or_2026_values_accessed": False,
    }
    return seal_record(record, "outcome_registry_receipt")


def build_features(frozen_at: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
    prior = metadata["feature_registry"]
    fundamental_pass_gate = {
        "MACRO_ENGINE_BIAS_STATE": "ALIGNMENT_CONTEXT_IF_M2_COVERAGE_PASSES",
        "REAL_YIELD_USD_CONFIRMATION": "ALIGNMENT_CONTEXT_IF_M2_COVERAGE_PASSES",
        "RECENT_RELEASE_SURPRISE_DIRECTION": "ALIGNMENT_CONTEXT_IF_FORECAST_AND_RELEASE_AVAILABILITY_PASS",
    }
    fundamental_descriptive = {
        "REGIME_REACTION_FUNCTION_STATE": "REPORTING_AND_STABILITY_ONLY",
        "UPCOMING_CATALYST_RISK": "DESCRIPTIVE_ONLY_CURRENT_HISTORICAL_CALENDAR_LIMIT",
        "FINANCIAL_STRESS_STATE": "REPORTING_AND_STABILITY_ONLY",
        "COT_MANAGED_MONEY_CROWDING": "INFERRED_RISK_CONTEXT_NOT_A_PASS_GATE",
        "COT_WEEKLY_CHANGE_SIGN": "POSITIONING_CONTEXT_NOT_A_PASS_GATE",
    }
    micro_event_inputs = {
        "FLOW_PRESSURE": ["displayed_pressure_ppb", "trade_imbalance_ppb", "quote_ofi_raw", "quote_ofi_transition_count"],
        "DEPTH_PRESSURE": [
            "depth_imbalance_l1_ppb", "depth_imbalance_l5_ppb", "depth_imbalance_l10_ppb",
            "order_count_imbalance_l5_ppb", "midpoint_fixed_1e9", "microprice_fixed_1e9",
        ],
        "ABSORPTION": ["trade_qty_buy", "trade_qty_sell", "midpoint_fixed_1e9", "quote_ofi_raw", "depth_imbalance_l5_ppb"],
        "LIQUIDITY_FRAGILITY": ["spread_fixed_1e9", "book_age_ns", "bid_depth_l10", "ask_depth_l10", "depth_concentration_l1_ppb"],
    }
    record = {
        "version": "GC_SESSION_TRIGGER_EDGE_FEATURE_TRACEABILITY_V1_0",
        "status": "FROZEN_BEFORE_FULL_SESSION_FEATURE_OR_EVENT_MATERIALIZATION",
        "frozen_at_utc": frozen_at,
        "epistemic_classes": ["OBSERVED", "CALCULATED", "INFERRED", "UNKNOWN"],
        "unknown_policy": "UNKNOWN is never converted to zero, flat, normal, no-event, balance, confirmation, or safety.",
        "reference_book_domain_traceability": [
            {"book_domain": "MARKET_MECHANICS_AND_LIQUIDITY", "fields": ["GC_MBO", "GC_MBP10", "spread", "depth", "resilience", "event_flow"], "role": "TRIGGER_AND_CONFIRMATION"},
            {"book_domain": "MARKET_STRUCTURE_AND_LEVELS", "fields": ["ASIA_RANGE", "PRIOR_DAY_RANGE", "LONDON_PRE_NEW_YORK_RANGE", "SESSION_OPENING_RANGE_15", "STRUCTURE_15M_1H_ALIGNMENT"], "role": "LOCATION_AND_EVENT_DEFINITION"},
            {"book_domain": "MACRO_REGIME_AND_EXPECTATIONS", "fields": ["MACRO_ENGINE_BIAS_STATE", "REAL_YIELD_USD_CONFIRMATION", "REGIME_REACTION_FUNCTION_STATE"], "role": "POINT_IN_TIME_BIAS_CONTEXT"},
            {"book_domain": "POSITIONING", "fields": ["COT_MANAGED_MONEY_CROWDING", "COT_WEEKLY_CHANGE_SIGN"], "role": "INFERRED_RISK_CONTEXT_NOT_PASS_GATE"},
            {"book_domain": "CATALYSTS", "fields": ["RECENT_RELEASE_SURPRISE_DIRECTION", "UPCOMING_CATALYST_RISK"], "role": "EVENT_CONTEXT_SUBJECT_TO_FORECAST_AND_CALENDAR_AVAILABILITY"},
            {"book_domain": "SESSIONS", "fields": ["LONDON", "NEW_YORK", "SESSION_PHASE", "IANA_DST"], "role": "SEPARATE_RESEARCH_UNITS_AND_TIMING"},
            {"book_domain": "CROSS_MARKET_CONFIRMATION", "fields": ["REAL_YIELD_USD_CONFIRMATION", "FINANCIAL_STRESS_STATE", "GC_XAU_DIRECTION_AGREEMENT"], "role": "CONFIRMATION_OR_CONTRADICTION"},
            {"book_domain": "EXECUTION_AND_RISK", "fields": [], "role": "EXPLICITLY_OUT_OF_SCOPE_UNTIL_A_VALIDATED_EDGE_EXISTS"},
        ],
        "source_catalog": {
            "GC_MBO": {
                "provider": "Databento GLBX.MDP3",
                "schema": "mbo",
                "symbol": "GC.v.0",
                "timestamp_authority": "ts_recv",
                "role": "time-bucketed event flow only",
                "coverage_status": "SEALED_FULL_DATE_REQUESTS_FULL_SESSION_FEATURE_COVERAGE_NOT_YET_CERTIFIED",
            },
            "GC_MBP10": {
                "provider": "Databento GLBX.MDP3",
                "schema": "mbp-10",
                "symbol": "GC.v.0",
                "timestamp_authority": "ts_recv",
                "role": "authoritative top-ten state",
                "coverage_status": "SEALED_FULL_DATE_REQUESTS_FULL_SESSION_FEATURE_COVERAGE_NOT_YET_CERTIFIED",
            },
            "XAUUSD_PRICE": {
                "provider": "IC_MARKETS_MT5",
                "timeframe": "1m",
                "record_count_metadata": metadata["casebook_artifact_counts"]["price_bars.jsonl.gz"],
                "role": "level detection and neutral forward outcomes",
                "coverage_status": "PARTIAL_EXACT_EVENT_WINDOW_COVERAGE_REQUIRES_M2_AUDIT",
            },
            "CASEBOOK_FUNDAMENTALS": {
                "record_count_metadata": metadata["casebook_artifact_counts"]["fundamentals.jsonl.gz"],
                "role": "point-in-time macro and expectations context",
                "coverage_status": "PARTIAL_DYNAMIC_EVENT_TIME_JOIN_NOT_YET_MATERIALIZED",
            },
            "CASEBOOK_EVENTS": {
                "record_count_metadata": metadata["casebook_artifact_counts"]["events.jsonl.gz"],
                "role": "release surprise context only when pre-release forecast availability is verified",
                "coverage_status": "PARTIAL_NO_COMPLETE_VERIFIED_HISTORICAL_PRE_EVENT_CALENDAR",
            },
            "CASEBOOK_POSITIONING": {
                "record_count_metadata": metadata["casebook_artifact_counts"]["positioning.jsonl.gz"],
                "role": "published COT context with publication lag",
                "coverage_status": "DERIVABLE_M2_POINT_IN_TIME_JOIN_REQUIRED",
            },
            "CASEBOOK_STRUCTURE": {
                "record_count_metadata": metadata["casebook_artifact_counts"]["structure_snapshots.jsonl.gz"],
                "role": "15-minute and one-hour structure known by event decision",
                "coverage_status": "PARTIAL_DYNAMIC_EVENT_TIME_RECONSTRUCTION_REQUIRED",
            },
        },
        "sealed_85_microstructure_columns": {
            "count": len(metadata["feature_columns"]),
            "columns": metadata["feature_columns"],
            "source_registry_sha256": BOUND["step5a_feature_registry"][1],
            "formulas_sha256": BOUND["step4a_feature_protocol"][1],
            "full_session_generalization": "Formulas, one-second buckets, ts_recv authority, reset treatment, missing-data rules, and authoritative-source roles remain unchanged. Only date origin and session scan windows may generalize in M2.",
            "raw_threshold_search_permitted": False,
        },
        "registered_microstructure_state_inputs": micro_event_inputs,
        "prior_derived_states": prior["derived_microstructure_states"],
        "fundamental_contexts": {
            "definitions": prior["eligible_fundamental_bias_contexts"],
            "candidate_alignment_roles": fundamental_pass_gate,
            "descriptive_or_risk_roles": fundamental_descriptive,
            "availability_rule": "Recompute as of each event decision using only facts with available_at no later than decision_at; a session-open state may be carried only when its source facts remain the latest eligible vintage.",
        },
        "price_session_and_structure": {
            "prior_context_definitions": prior["eligible_price_level_and_session_contexts"],
            "new_event_time_fields": [
                {"field": "SESSION_PHASE", "definition": "OPENING [08:00,09:00), MID [09:00,10:30), LATE [10:30,12:00) local", "role": "STABILITY_REPORTING_ONLY"},
                {"field": "SESSION_OR15_HIGH_LOW", "definition": "First fifteen complete local session minutes", "role": "ELIGIBLE_LEVEL"},
                {"field": "EVENT_STRUCTURE_15M_1H_ALIGNMENT", "definition": "Unchanged frozen structure alignment recomputed with detected_at no later than event decision", "role": "STAGE_2_ALIGNMENT_IF_M2_COVERAGE_PASSES"},
            ],
        },
        "permitted_stage2_contexts": [
            "MACRO_ENGINE_ALIGNMENT",
            "REAL_YIELD_USD_ALIGNMENT",
            "RECENT_RELEASE_ALIGNMENT",
            "STRUCTURE_15M_1H_ALIGNMENT",
            "FLOW_DEPTH_CONFIRMATION_FOR_LEVEL_EVENTS_ONLY",
            "LIQUIDITY_FRAGILITY_FOR_LEVEL_EVENTS_ONLY",
        ],
        "prohibited": [
            "unregistered raw-column search",
            "outcome-conditioned threshold selection",
            "more than one Stage-2 context attached to an event test",
            "three-way or higher interactions",
            "COT or catalyst risk used to rescue a candidate",
            "institution identity or motive claims from anonymous flow",
            "outcome fields in any feature table",
        ],
        "outcome_fields_present": False,
        "year_2025_or_2026_values_accessed": False,
    }
    return seal_record(record, "traceability_receipt")


def build_statistics(frozen_at: str) -> dict[str, Any]:
    record = {
        "version": "GC_SESSION_TRIGGER_EDGE_STATISTICAL_PROTOCOL_V1_0",
        "status": "FROZEN_BEFORE_EVENT_SUPPORT_OR_OUTCOME_ACCESS",
        "frozen_at_utc": frozen_at,
        "analysis_separation": "London and New York are separate multiplicity families and separate candidate shortlists.",
        "independent_units": {
            "primary_cluster": "selected_month_week_id",
            "secondary_cluster": "session_date",
            "event_rows_are_not_independent": True,
            "within_date_cap": "At most three canonical events per event family and date in the primary analysis.",
            "first_event_sensitivity": True,
        },
        "milestone_2_support_only_admission": {
            "rule": "M2 may materialize trigger timestamps, feature/context availability, and support counts without forward outcomes. It may admit or exclude a future test only by these frozen support/completeness rules.",
            "market_direction_or_forward_path_access": False,
            "manual_preference_or_result_based_selection": False,
            "zero_admitted_tests_acceptable": True,
        },
        "stage_1": {
            "unit": "One pooled sign-normalized test per event family and session; bullish and bearish variants are not separate candidates.",
            "maximum_tests_per_session": 6,
            "support_floors": {
                "event_instances": 80,
                "distinct_session_dates": 50,
                "distinct_month_week_blocks": 20,
                "bullish_event_instances": 30,
                "bearish_event_instances": 30,
                "bullish_distinct_dates": 20,
                "bearish_distinct_dates": 20,
                "calendar_years": 3,
                "minimum_total_events_in_each_eligible_year": 8,
            },
            "directional_balance_rule": "A one-sided family is ASYMMETRIC_DESCRIPTIVE_ONLY and cannot advance in V1.",
            "benchmark": "Favorable direction probability 0.50 after multiplying each outcome by its preregistered event sign.",
        },
        "stage_2": {
            "unit": "One event family crossed with exactly one permitted context; no three-way interaction.",
            "maximum_tests_per_session": 33,
            "support_floors": {
                "condition_event_instances": 50,
                "condition_distinct_dates": 30,
                "condition_distinct_month_week_blocks": 15,
                "comparison_event_instances": 70,
                "comparison_distinct_dates": 40,
                "comparison_distinct_month_week_blocks": 18,
                "condition_bullish_distinct_dates": 12,
                "condition_bearish_distinct_dates": 12,
                "comparison_bullish_distinct_dates": 15,
                "comparison_bearish_distinct_dates": 15,
                "calendar_years": 3,
                "minimum_condition_dates_per_eligible_year": 5,
            },
            "comparison": "Same event family and session when the registered context is not aligned; UNKNOWN context rows are excluded and reported.",
        },
        "primary_endpoint_only_for_pass": "XAUUSD_FWD_15M_SIGNED_DISPLACEMENT",
        "effect_and_uncertainty_gates": {
            "stage1_favorable_hit_rate_minimum": 0.56,
            "stage1_cluster_bootstrap_95pct_lower_hit_rate": ">0.50",
            "stage1_cluster_bootstrap_95pct_lower_median_favorable_displacement": ">0",
            "stage2_condition_favorable_hit_rate_minimum": 0.56,
            "stage2_condition_minus_comparison_hit_rate_lift_pp_minimum": 10.0,
            "stage2_cluster_bootstrap_95pct_lower_lift_pp": ">0",
            "stage2_cluster_bootstrap_95pct_lower_median_favorable_difference": ">0",
            "flat_policy": "Retain and report; exclude only from binary hit-rate denominator, never from continuous displacement.",
        },
        "uncertainty": {
            "cluster_bootstrap_resamples": 20_000,
            "cluster_bootstrap_unit": "selected_month_week_id with all dates and events preserved inside the sampled block",
            "randomization_repetitions": 100_000,
            "randomization": "Deterministic date-cluster directional sign flips under the null; all events from a date flip together.",
            "confidence_level": 0.95,
            "seed": "uint64 from the first sixteen hex characters of SHA256(contract_version|session|stage|test_id|method)",
        },
        "multiplicity": {
            "method": "Benjamini-Hochberg",
            "q_threshold": 0.05,
            "families": "Separate by session and stage on every support-eligible primary-endpoint test.",
            "support_failures": "Recorded but not assigned a p-value; never silently removed from the complete registry.",
            "secondary_horizons": "Holm correction across 5, 30, and 60 minutes for reporting; secondary results cannot rescue or create a candidate.",
        },
        "stability_gates": {
            "calendar_years": "The favorable effect must have the same sign in every one of 2022, 2023, and 2024 that satisfies the frozen per-year support floor; 2021 is reported but cannot be required because it has only ten selected dates.",
            "ordered_block_segments": ["blocks_01_10", "blocks_11_20", "blocks_21_29", "blocks_30_38"],
            "block_segment_rule": "Favorable sign in at least three of four segments and no segment hit-rate lift below -5 percentage points when segment support is adequate.",
            "first_event_only": "Same favorable sign and at least 50 percent of the all-canonical-event effect magnitude.",
            "cross_venue": "Median GC fifteen-minute consistency displacement may be UNKNOWN but must not have a statistically supported opposite sign.",
        },
        "candidate_rules": {
            "verdicts": ["PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED", "REJECT", "SUPPORT_FAIL"],
            "maximum_candidates_per_session": 2,
            "zero_candidates_acceptable": True,
            "ranking_order": [
                "lowest BH q-value",
                "highest lower confidence bound on favorable hit-rate lift",
                "highest minimum of bullish and bearish distinct-date support",
                "largest favorable effect",
                "largest distinct-date support",
                "lexicographically smallest test_id",
            ],
            "retuning_inversion_repair_or_selective_filtering": False,
            "development_candidate_is_a_trading_edge": False,
        },
        "maximum_registered_tests": {
            "stage1_per_session": 6,
            "stage2_per_session": 33,
            "total_per_session": 39,
            "both_sessions": 78,
        },
        "outcome_values_accessed": False,
        "year_2025_or_2026_values_accessed": False,
    }
    return seal_record(record, "statistical_protocol_receipt")


def build_audit(frozen_at: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
    available_by_year = Counter(value[:4] for value in metadata["available_dates"])
    stage1_alpha_bonf = 0.05 / 6.0
    stage2_alpha_bonf = 0.05 / 33.0
    power_rows = []
    for n in (50, 80, 120, 187):
        power_rows.append({
            "design": "ONE_SAMPLE_DIRECTIONAL_HIT_RATE_VS_50",
            "n": n,
            "iid_mde_pp_alpha_0_05": round(mde_one_sample(n, 0.05) * 100.0, 1),
            "iid_mde_pp_bonferroni_6": round(mde_one_sample(n, stage1_alpha_bonf) * 100.0, 1),
        })
    for n_condition, n_comparison in ((30, 40), (40, 60), (60, 80), (90, 97)):
        power_rows.append({
            "design": "TWO_SAMPLE_CONTEXT_LIFT",
            "n_condition": n_condition,
            "n_comparison": n_comparison,
            "iid_mde_pp_alpha_0_05": round(mde_two_sample(n_condition, n_comparison, 0.05) * 100.0, 1),
            "iid_mde_pp_bonferroni_33": round(mde_two_sample(n_condition, n_comparison, stage2_alpha_bonf) * 100.0, 1),
        })
    record = {
        "version": "GC_SESSION_TRIGGER_EDGE_M1_COVERAGE_POWER_AUDIT_V1_0",
        "status": "PASS_M1_METADATA_AUDIT_CONDITIONAL_M2_READINESS",
        "completed_at_utc": frozen_at,
        "audit_classification": "METADATA_SCHEMA_AND_ANALYTIC_POWER_ONLY",
        "development_sample": {
            "selection": "Outcome-blind second complete CME week of each retained month under Budget Amendment C.",
            "start": min(metadata["dates"]),
            "end": max(metadata["dates"]),
            "selected_dates": len(metadata["dates"]),
            "available_nonholiday_session_dates_per_session": len(metadata["available_dates"]),
            "month_week_blocks": len(metadata["weeks"]),
            "selected_dates_by_year": metadata["by_year"],
            "available_dates_by_year": dict(sorted(available_by_year.items())),
            "full_2021_2024_calendar_coverage": False,
            "coverage_character": "Sparse calendar-selected development sample, not every trading day.",
        },
        "source_inventory": {
            "provider_requests": metadata["source_verification"]["verified_provider_requests"],
            "verified_files": metadata["source_verification"]["verified_files"],
            "verified_bytes": metadata["source_verification"]["verified_bytes"],
            "mbo_records_metadata": metadata["records_by_schema"]["mbo"],
            "mbp10_records_metadata": metadata["records_by_schema"]["mbp-10"],
            "total_gc_records_metadata": sum(metadata["records_by_schema"].values()),
            "xauusd_price_bar_records_metadata": metadata["casebook_artifact_counts"]["price_bars.jsonl.gz"],
            "fundamental_records_metadata": metadata["casebook_artifact_counts"]["fundamentals.jsonl.gz"],
            "event_records_metadata": metadata["casebook_artifact_counts"]["events.jsonl.gz"],
            "positioning_records_metadata": metadata["casebook_artifact_counts"]["positioning.jsonl.gz"],
            "structure_records_metadata": metadata["casebook_artifact_counts"]["structure_snapshots.jsonl.gz"],
            "market_rows_deserialized": 0,
        },
        "capacity_upper_bounds_not_observed_events": {
            "completed_minute_decision_points_per_available_session_date": 240,
            "maximum_minute_decision_points_per_session": len(metadata["available_dates"]) * 240,
            "maximum_minute_decision_points_both_sessions": len(metadata["available_dates"]) * 240 * 2,
            "one_second_feature_span_per_session_date_seconds": 18_900,
            "feature_span_definition": "900-second warmup + 4-hour trigger scan + 60-minute maximum forward observation",
            "maximum_one_second_bucket_rows_both_sessions": len(metadata["available_dates"]) * 18_900 * 2,
            "warning": "These are schedule capacities, not trigger counts, valid book-state counts, or outcome support.",
        },
        "readiness_gates": [
            {"gate": "STEP_5D_R3_ZERO_CANDIDATE_VERDICT_BOUND", "status": "PASS"},
            {"gate": "EIGHTY_GC_SOURCE_REQUEST_SEALS", "status": "PASS"},
            {"gate": "MBO_AND_MBP10_REQUIRED_SCHEMAS", "status": "PASS"},
            {"gate": "EXACT_188_DATE_38_BLOCK_REGISTRY", "status": "PASS"},
            {"gate": "PREVIOUS_374_PRESESSION_WINDOWS_FEATURE_CERTIFIED", "status": "PASS"},
            {"gate": "FULL_SESSION_PLUS_60M_TIMESTAMP_COVERAGE", "status": "NOT_YET_CERTIFIED_M2_REQUIRED"},
            {"gate": "DYNAMIC_EVENT_TIME_FUNDAMENTAL_CONTEXT", "status": "PARTIAL_M2_REQUIRED"},
            {"gate": "XAUUSD_TRIGGER_AND_FORWARD_WINDOW_COMPLETENESS", "status": "NOT_YET_CERTIFIED_M2_REQUIRED"},
            {"gate": "ACTUAL_EVENT_INCIDENCE_AND_DIRECTIONAL_SIDE_SUPPORT", "status": "UNKNOWN_BY_DESIGN_M2_REQUIRED"},
            {"gate": "2025_AND_2026_VALUES_LOCKED", "status": "PASS"},
        ],
        "known_blackouts": [
            {"session_date": "2022-04-15", "sessions": ["LONDON", "NEW_YORK"], "disposition": "DOCUMENTED_CME_GOOD_FRIDAY_UNAVAILABLE"},
            {"session_date": "2021-12-13", "session": "NEW_YORK", "missing_utc": ["16:32", "16:33"], "disposition": "PARTIAL_XAU_SOURCE_BLACKOUT"},
            {"session_date": "2023-03-15", "session": "NEW_YORK", "missing_utc": ["13:19-13:27"], "disposition": "PARTIAL_XAU_SOURCE_BLACKOUT"},
            {"session_date": "2023-08-15", "session": "LONDON", "missing_utc": ["08:05-08:40", "09:37-09:39", "10:05-10:08"], "disposition": "PARTIAL_XAU_SOURCE_BLACKOUT"},
            {"session_date": "2023-09-13", "session": "NEW_YORK", "missing_utc": ["14:48-14:50"], "disposition": "PARTIAL_XAU_SOURCE_BLACKOUT"},
        ],
        "blackout_policy": "Do not pre-delete a whole partial session. In M2, mark an event UNKNOWN whenever its detection, anchor, or registered horizon intersects a frozen blackout; never bridge, impute, or select around a gap.",
        "power_assumptions": {
            "method": "Normal approximation at worst-case Bernoulli variance 0.25, two-sided alpha, 80 percent power.",
            "interpretation": "Optimistic IID lower-bound MDE only. Week clustering, event overlap, missingness, and imbalance can only increase required effects.",
            "bh_note": "Bonferroni columns are conservative upper-multiplicity references; the frozen inferential method is BH, whose realized threshold is unknown before p-values.",
        },
        "power_table": power_rows,
        "power_verdict": {
            "status": "LIMITED_FOR_MODEST_EFFECTS",
            "finding": "The 187-date-per-session ceiling can test large, recurrent event effects. It is not reliably powered for small conditional lifts after multiplicity and week clustering.",
            "decision": "Proceed only to outcome-blind M2 trigger/support materialization. Do not open outcomes. If registered support is inadequate, stop or request an outcome-blind 2021-2024 sample-expansion amendment before any result access.",
        },
        "new_data_required_for_m2": False,
        "new_purchase_authorized": False,
        "market_values_or_outcomes_accessed": False,
        "year_2025_or_2026_values_accessed": False,
    }
    return seal_record(record, "audit_receipt")


def build_contract(
    frozen_at: str,
    taxonomy: Mapping[str, Any],
    outcomes: Mapping[str, Any],
    features: Mapping[str, Any],
    statistics: Mapping[str, Any],
) -> dict[str, Any]:
    predecessor_bindings = {
        name: {"path": rel(path), "sha256": expected}
        for name, (path, expected) in BOUND.items()
    }
    registry_bindings = {
        "event_taxonomy": {"path": rel(TAXONOMY_PATH), "sha256": sha256_file(TAXONOMY_PATH), "receipt": taxonomy["taxonomy_receipt"]},
        "outcomes": {"path": rel(OUTCOMES_PATH), "sha256": sha256_file(OUTCOMES_PATH), "receipt": outcomes["outcome_registry_receipt"]},
        "features": {"path": rel(FEATURES_PATH), "sha256": sha256_file(FEATURES_PATH), "receipt": features["traceability_receipt"]},
        "statistics": {"path": rel(STATISTICS_PATH), "sha256": sha256_file(STATISTICS_PATH), "receipt": statistics["statistical_protocol_receipt"]},
    }
    record = {
        "version": "GC_SESSION_TRIGGER_EDGE_DISCOVERY_CONTRACT_V1_0",
        "status": "FROZEN_MILESTONE_1_BEFORE_EVENT_OR_OUTCOME_VALUE_ACCESS",
        "classification": "EVENT_TRIGGERED_POINT_IN_TIME_CONDITIONAL_EDGE_RESEARCH",
        "frozen_at_utc": frozen_at,
        "research_question": "After a preregistered London or New York price-level or liquidity/order-flow event is fully observable, does its preregistered direction predict the next fifteen minutes of XAUUSD more often and by more than chance, and does point-in-time macro or structure alignment materially strengthen that relationship?",
        "book_role": "Primary business vocabulary and market-logic specification, not a predetermined empirical answer.",
        "preserved_history": {
            "all_prior_verdicts_artifacts_and_seals_immutable": True,
            "step5dr3_status": "PASS_STEP_5D_R3_DISCOVERY_ZERO_CANDIDATES",
            "step5dr3_registered_tests": 148,
            "step5dr3_candidates": 0,
            "step5dr3_interpretation": "Fixed pre-session snapshots did not establish a whole-session directional candidate. They are not repaired, inverted, renamed, or credited here.",
            "rejected_zn_and_v3_candidates_remain_rejected_or_inconclusive": True,
        },
        "time_partitions": {
            "development": {
                "calendar_boundary": "2021-01-01 through 2024-12-31 only",
                "effective_microstructure_sample": "188 outcome-blind calendar-selected dates from 2021-11-08 through 2024-12-13",
                "independent_month_week_blocks": 38,
                "independent_validation_credit": False,
            },
            "calendar_2025": {
                "status": "LOCKED",
                "classification_if_later_opened": "EXPOSED_HISTORICAL_FORWARD_NO_INDEPENDENT_VALIDATION_CREDIT",
                "unlock": "Candidate-specific sealed protocol plus explicit user authorization after development candidates exist.",
            },
            "calendar_2026": {
                "status": "LOCKED_INDEPENDENT_YEAR_AND_PROSPECTIVE",
                "unlock": "Candidate-specific sealed protocol plus explicit user authorization after 2025 disposition.",
            },
        },
        "research_boundary": {
            "bias": "Fundamental and cross-market states are context and alignment variables.",
            "trigger": "A completed price-level or microstructure event defined in the sealed taxonomy.",
            "outcome": "Neutral forward market behaviour, never a fill or trade.",
            "execution": "Entirely out of scope for V1 discovery.",
            "causal_claims": False,
        },
        "registry_bindings": registry_bindings,
        "predecessor_bindings": predecessor_bindings,
        "milestones": [
            {
                "milestone": 1,
                "name": "CONTRACT_AND_METADATA_READINESS",
                "authorized": True,
                "outputs": ["contract", "event taxonomy", "outcomes", "feature traceability", "statistics", "coverage/power audit", "freeze"],
                "value_access": "METADATA_AND_SCHEMAS_ONLY",
                "stop": "MANDATORY_AFTER_SEAL",
            },
            {
                "milestone": 2,
                "name": "OUTCOME_BLIND_TRIGGER_AND_SUPPORT_MATERIALIZATION",
                "authorized": False,
                "permitted_only_if_later_authorized": "Full-session technical coverage, event timestamps, feature/context availability, and support counts; forward outcomes remain unjoined and unopened.",
            },
            {
                "milestone": 3,
                "name": "FROZEN_TEST_REGISTRY_AND_DEVELOPMENT_DISCOVERY",
                "authorized": False,
                "precondition": "M2 passes and exact support-qualified tests are sealed before the one development outcome join.",
            },
            {
                "milestone": 4,
                "name": "CALENDAR_2025_FORWARD_PROTOCOL_AND_EVALUATION",
                "authorized": False,
                "precondition": "At least one unchanged provisional development candidate and explicit authorization.",
            },
            {
                "milestone": 5,
                "name": "CALENDAR_2026_INDEPENDENT_AND_PROSPECTIVE",
                "authorized": False,
                "precondition": "Frozen surviving candidate, exact 2026 protocol, and explicit authorization.",
            },
        ],
        "amendment_policy": {
            "new_event_family_threshold_context_or_outcome": "Requires a pre-value amendment and receives no retrospective validation credit.",
            "development_sample_expansion": "May be requested only outcome-blindly after M2 support audit; requires metadata cost/storage audit and explicit authorization before acquisition.",
            "failed_candidate": "May not be repaired, inverted, renamed, or selectively filtered.",
        },
        "prohibited": [
            "event or outcome value access in Milestone 1",
            "candidate discovery or ranking in Milestone 1",
            "2025 or 2026 value access",
            "execution optimization",
            "trades, PnL, R multiples, or account returns",
            "paid acquisition or charge",
            "opaque machine-learning selection",
            "unsupported institutional attribution",
        ],
        "milestone_1_mandatory_stop": True,
        "event_values_accessed": False,
        "outcome_values_accessed": False,
        "year_2025_or_2026_values_accessed": False,
    }
    return seal_record(record, "contract_receipt")


def build_contract_markdown(contract: Mapping[str, Any], audit: Mapping[str, Any]) -> str:
    return "\n".join([
        "# GC Session Trigger Edge Discovery Contract V1",
        "",
        f"Status: `{contract['status']}`",
        "",
        "## Objective",
        "",
        contract["research_question"],
        "",
        "This branch preserves the formal Step 5D-R3 zero-candidate result. It does not repair the failed fixed-cutoff tests. Fundamentals define context; an observable event defines the trigger; neutral forward behaviour defines the outcome. Execution remains separate.",
        "",
        "## Development and holdouts",
        "",
        "- Development is limited to the sealed 188-date sample from 8 November 2021 through 13 December 2024.",
        "- The sample contains 38 calendar-selected month-week blocks and is not every trading day.",
        "- Calendar 2025 remains locked and, if later opened, has exposed-historical-forward status only.",
        "- Calendar 2026 remains the locked independent/prospective period.",
        "",
        "## Trigger model",
        "",
        "London and New York are analysed separately. Decisions occur only after a complete XAUUSD minute bar confirms one of six frozen event families: level sweep/reclaim, level acceptance, failed acceptance, flow-depth alignment onset, absorption onset, or fragility-with-flow onset. GC order-book inputs retain the sealed 85-column engineering definitions and `ts_recv` availability authority.",
        "",
        "Price-level triggers may use the completed Asia range, prior-day range, London pre-New-York range, or the first fifteen session minutes. XAUUSD levels are never compared numerically with GC futures prices.",
        "",
        "## Outcome boundary",
        "",
        "The primary endpoint is signed XAUUSD displacement fifteen minutes after event confirmation. Five-, thirty-, and sixty-minute results and GC midpoint agreement are consistency outputs only. The anchor is a neutral measurement, not a fill. Stops, targets, trades, PnL, R multiples, and account returns are prohibited.",
        "",
        "## Statistical governance",
        "",
        "- Stage 1 permits at most six pooled, two-sided event-family tests per session.",
        "- Stage 2 permits at most 33 event-by-one-context tests per session; no three-way interactions.",
        "- Both bullish and bearish variants must meet support floors. A one-sided result cannot become a V1 candidate.",
        "- Inference uses week-block bootstrap, deterministic cluster randomization, and Benjamini-Hochberg control at `q <= 0.05`.",
        "- At most two provisional development candidates may advance per session; zero is acceptable.",
        "",
        "## Power limitation",
        "",
        audit["power_verdict"]["finding"],
        " Actual trigger support is intentionally unknown until an outcome-blind Milestone 2. If support is inadequate, the study must stop or seek a separately authorized outcome-blind sample expansion.",
        "",
        "## Milestone sequence",
        "",
        "1. Contract, registries, traceability, metadata coverage, and power audit — complete and sealed.",
        "2. Full-session technical certification and outcome-blind trigger/support materialization — not authorized.",
        "3. Exact test freeze followed by one development outcome join and discovery — not authorized.",
        "4. Frozen-candidate calendar-2025 forward evaluation — not authorized.",
        "5. Calendar-2026 independent/prospective evaluation — not authorized.",
        "",
        "Milestone 1 stops here. No event values, forward outcomes, candidates, execution, or returns were inspected or calculated.",
        "",
    ])


def build_report_markdown(audit: Mapping[str, Any], verdict_status: str) -> str:
    readiness = {item["gate"]: item["status"] for item in audit["readiness_gates"]}
    return "\n".join([
        "# GC Session Trigger Edge Discovery V1 — Milestone 1",
        "",
        f"Formal status: `{verdict_status}`",
        "",
        "## What is ready",
        "",
        "- Step 5D-R3 zero-candidate history and every bound predecessor hash passed.",
        "- 80 sealed GC requests and 936 source files are verified without opening rows.",
        "- The development registry contains 188 dates, 187 non-holiday dates per session, and 38 month-week clusters.",
        "- Six event families, four level families, the primary fifteen-minute endpoint, feature lineage, support floors, uncertainty, multiplicity, stability, and ranking are frozen.",
        "",
        "## What is not yet established",
        "",
        f"- Full-session plus sixty-minute source coverage: `{readiness['FULL_SESSION_PLUS_60M_TIMESTAMP_COVERAGE']}`.",
        f"- Dynamic event-time fundamental context: `{readiness['DYNAMIC_EVENT_TIME_FUNDAMENTAL_CONTEXT']}`.",
        f"- Actual event and directional-side support: `{readiness['ACTUAL_EVENT_INCIDENCE_AND_DIRECTIONAL_SIDE_SUPPORT']}`.",
        "- No relationship, candidate, hit rate, return, or edge has been calculated.",
        "",
        "## Honest power verdict",
        "",
        audit["power_verdict"]["finding"],
        " The analytic table is an optimistic IID lower bound; week clustering and overlapping events reduce effective power.",
        "",
        "## Disposition",
        "",
        "Milestone 1 passes as a design and metadata milestone with conditional readiness for an outcome-blind Milestone 2. Milestone 2 requires new explicit authorization. No purchase is required or authorized for that audit.",
        "",
    ])


def prepare() -> None:
    if OUTPUT_DIR.exists() or any(path.exists() for path in OUTPUT_PATHS):
        raise FileExistsError("GC Session Trigger Edge Milestone 1 outputs already exist")
    metadata = verify_predecessors()
    frozen_at = utc_now()

    taxonomy = build_taxonomy(frozen_at)
    outcomes = build_outcomes(frozen_at)
    features = build_features(frozen_at, metadata)
    statistics = build_statistics(frozen_at)
    write_json_exclusive(TAXONOMY_PATH, taxonomy)
    write_json_exclusive(OUTCOMES_PATH, outcomes)
    write_json_exclusive(FEATURES_PATH, features)
    write_json_exclusive(STATISTICS_PATH, statistics)

    contract = build_contract(frozen_at, taxonomy, outcomes, features, statistics)
    write_json_exclusive(CONTRACT_PATH, contract)
    audit = build_audit(frozen_at, metadata)
    write_json_exclusive(OUTPUT_DIR / "coverage_power_audit.json", audit)

    contract_doc = build_contract_markdown(contract, audit)
    report_status = "PASS_MILESTONE_1_CONTRACT_FROZEN_CONDITIONAL_M2_READINESS"
    report_doc = build_report_markdown(audit, report_status)
    write_text_exclusive(CONTRACT_DOC_PATH, contract_doc)
    write_text_exclusive(REPORT_PATH, report_doc)

    freeze = {
        "version": "GC_SESSION_TRIGGER_EDGE_M1_FREEZE_V1_0",
        "status": "SEALED_M1_BEFORE_EVENT_OR_OUTCOME_VALUE_ACCESS",
        "frozen_at_utc": frozen_at,
        "implementation": {"path": rel(IMPLEMENTATION_PATH), "sha256": sha256_file(IMPLEMENTATION_PATH)},
        "contract": {"path": rel(CONTRACT_PATH), "sha256": sha256_file(CONTRACT_PATH), "receipt": contract["contract_receipt"]},
        "registries": {
            "taxonomy": {"path": rel(TAXONOMY_PATH), "sha256": sha256_file(TAXONOMY_PATH), "receipt": taxonomy["taxonomy_receipt"]},
            "outcomes": {"path": rel(OUTCOMES_PATH), "sha256": sha256_file(OUTCOMES_PATH), "receipt": outcomes["outcome_registry_receipt"]},
            "features": {"path": rel(FEATURES_PATH), "sha256": sha256_file(FEATURES_PATH), "receipt": features["traceability_receipt"]},
            "statistics": {"path": rel(STATISTICS_PATH), "sha256": sha256_file(STATISTICS_PATH), "receipt": statistics["statistical_protocol_receipt"]},
        },
        "audit": {"path": rel(OUTPUT_DIR / "coverage_power_audit.json"), "sha256": sha256_file(OUTPUT_DIR / "coverage_power_audit.json"), "receipt": audit["audit_receipt"]},
        "documents": {
            "contract": {"path": rel(CONTRACT_DOC_PATH), "sha256": sha256_file(CONTRACT_DOC_PATH)},
            "report": {"path": rel(REPORT_PATH), "sha256": sha256_file(REPORT_PATH)},
        },
        "predecessor_hashes": {name: expected for name, (_, expected) in BOUND.items()},
        "market_event_values_accessed_before_freeze": False,
        "outcome_values_accessed_before_freeze": False,
        "year_2025_or_2026_values_accessed": False,
        "next_action_authorized": False,
    }
    seal_record(freeze, "freeze_receipt")
    write_json_exclusive(FREEZE_PATH, freeze)

    verdict = {
        "version": "GC_SESSION_TRIGGER_EDGE_M1_VERDICT_V1_0",
        "status": report_status,
        "formal_milestone_pass": True,
        "completed_at_utc": frozen_at,
        "contract_frozen": True,
        "event_families": 6,
        "level_families": 4,
        "sealed_microstructure_columns": 85,
        "development_selected_dates": 188,
        "available_nonholiday_dates_per_session": 187,
        "month_week_blocks": 38,
        "source_requests_verified": 80,
        "full_session_readiness": "CONDITIONAL_M2_TECHNICAL_CERTIFICATION_REQUIRED",
        "power": "LIMITED_FOR_MODEST_EFFECTS",
        "edge_or_candidate_found": False,
        "event_or_outcome_values_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "charge_incurred_usd": 0.0,
        "next_milestone_authorized": False,
        "mandatory_stop_satisfied": True,
    }
    seal_record(verdict, "verdict_receipt")
    write_json_exclusive(OUTPUT_DIR / "verdict.json", verdict)

    artifact_paths = [
        TAXONOMY_PATH,
        OUTCOMES_PATH,
        FEATURES_PATH,
        STATISTICS_PATH,
        CONTRACT_PATH,
        FREEZE_PATH,
        OUTPUT_DIR / "coverage_power_audit.json",
        OUTPUT_DIR / "verdict.json",
        CONTRACT_DOC_PATH,
        REPORT_PATH,
    ]
    manifest = {
        "version": "GC_SESSION_TRIGGER_EDGE_M1_MANIFEST_V1_0",
        "status": report_status,
        "sealed_at_utc": frozen_at,
        "artifacts": [
            {"path": rel(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in artifact_paths
        ],
        "predecessor_bindings_verified": len(BOUND),
        "metadata_only": True,
        "market_rows_deserialized": 0,
        "event_values_accessed": False,
        "outcome_values_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "candidate_discovery_performed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "charge_incurred_usd": 0.0,
    }
    seal_record(manifest, "manifest_receipt")
    write_json_exclusive(OUTPUT_DIR / "manifest.json", manifest)
    final_seal = {
        "version": "GC_SESSION_TRIGGER_EDGE_M1_FINAL_SEAL_V1_0",
        "status": report_status,
        "manifest_sha256": sha256_file(OUTPUT_DIR / "manifest.json"),
        "manifest_receipt": manifest["manifest_receipt"],
        "verdict_sha256": sha256_file(OUTPUT_DIR / "verdict.json"),
        "verdict_receipt": verdict["verdict_receipt"],
        "freeze_sha256": sha256_file(FREEZE_PATH),
        "freeze_receipt": freeze["freeze_receipt"],
        "sealed_at_utc": utc_now(),
    }
    seal_record(final_seal, "final_seal_receipt")
    write_json_exclusive(OUTPUT_DIR / "final_seal.json", final_seal)
    verify()
    print(json.dumps({
        "status": report_status,
        "development_dates": 188,
        "available_dates_per_session": 187,
        "month_week_blocks": 38,
        "event_families": 6,
        "maximum_future_tests_both_sessions": 78,
        "full_session_readiness": "CONDITIONAL_M2_TECHNICAL_CERTIFICATION_REQUIRED",
        "power": "LIMITED_FOR_MODEST_EFFECTS",
        "event_or_outcome_values_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "final_seal_sha256": sha256_file(OUTPUT_DIR / "final_seal.json"),
    }, indent=2, sort_keys=True))


def verify() -> None:
    metadata = verify_predecessors()
    del metadata
    manifest = load_json(OUTPUT_DIR / "manifest.json")
    verdict = load_json(OUTPUT_DIR / "verdict.json")
    freeze = load_json(FREEZE_PATH)
    final_seal = load_json(OUTPUT_DIR / "final_seal.json")
    manifest_copy = dict(manifest)
    receipt = manifest_copy.pop("manifest_receipt", None)
    if receipt != canonical_hash(manifest_copy):
        raise ValueError("Milestone 1 manifest receipt failed")
    verdict_copy = dict(verdict)
    verdict_receipt = verdict_copy.pop("verdict_receipt", None)
    if verdict_receipt != canonical_hash(verdict_copy):
        raise ValueError("Milestone 1 verdict receipt failed")
    freeze_copy = dict(freeze)
    freeze_receipt = freeze_copy.pop("freeze_receipt", None)
    if freeze_receipt != canonical_hash(freeze_copy):
        raise ValueError("Milestone 1 freeze receipt failed")
    for item in manifest["artifacts"]:
        path = ROOT / item["path"]
        if sha256_file(path) != item["sha256"] or path.stat().st_size != item["bytes"]:
            raise ValueError(f"Milestone 1 artifact changed: {path}")
    if sha256_file(OUTPUT_DIR / "manifest.json") != final_seal["manifest_sha256"]:
        raise ValueError("Milestone 1 final manifest seal failed")
    if sha256_file(OUTPUT_DIR / "verdict.json") != final_seal["verdict_sha256"]:
        raise ValueError("Milestone 1 final verdict seal failed")
    if sha256_file(FREEZE_PATH) != final_seal["freeze_sha256"]:
        raise ValueError("Milestone 1 final freeze seal failed")
    final_copy = dict(final_seal)
    final_receipt = final_copy.pop("final_seal_receipt", None)
    if final_receipt != canonical_hash(final_copy):
        raise ValueError("Milestone 1 final seal receipt failed")
    if verdict["event_or_outcome_values_accessed"] or verdict["year_2025_or_2026_values_accessed"]:
        raise ValueError("Milestone 1 access boundary failed")
    print(json.dumps({
        "status": verdict["status"],
        "all_artifact_hashes_verified": True,
        "predecessor_bindings_verified": len(BOUND),
        "market_rows_deserialized": 0,
        "event_or_outcome_values_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "next_milestone_authorized": False,
    }, indent=2, sort_keys=True))


def self_test() -> None:
    if not (0.15 < mde_one_sample(50, 0.05) < 0.25):
        raise AssertionError("One-sample power calculation failed")
    if not (0.25 < mde_two_sample(30, 40, 0.05) < 0.40):
        raise AssertionError("Two-sample power calculation failed")
    taxonomy = build_taxonomy("SELF_TEST")
    if len(taxonomy["event_families"]) != 6 or len(taxonomy["level_families"]) != 4:
        raise AssertionError("Taxonomy self-test failed")
    print(json.dumps({
        "status": "PASS_GC_SESSION_TRIGGER_EDGE_M1_SYNTHETIC_SELF_TEST",
        "market_or_outcome_values_accessed": False,
    }, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("self-test", "prepare", "verify"))
    args = parser.parse_args()
    if args.action == "self-test":
        self_test()
    elif args.action == "prepare":
        prepare()
    else:
        verify()


if __name__ == "__main__":
    main()
