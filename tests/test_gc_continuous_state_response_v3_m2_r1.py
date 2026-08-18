from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "audit_gc_continuous_state_response_v3_m2_r1.py"
SPEC = importlib.util.spec_from_file_location("gc_csr_v3_m2_r1", MODULE_PATH)
assert SPEC and SPEC.loader
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)


def test_synthetic_pre_access_proof_passes() -> None:
    result = M.synthetic_proof()
    assert result["status"] == "PASS_SYNTHETIC_PRE_ACCESS_PROOF"


def test_annual_gate_uses_frozen_denominator_and_ceiling() -> None:
    denominator = {"2022": 20, "2023": 60, "2024": 58}
    result, passed = M.annual_gate({"2022": 16, "2023": 48, "2024": 47}, denominator)
    assert passed
    assert result["2022"]["minimum_required_dates"] == 16
    assert result["2023"]["minimum_required_dates"] == 48
    assert result["2024"]["minimum_required_dates"] == math.ceil(0.8 * 58) == 47
    assert result["2024"]["denominator_frozen_oof_dates"] == 58


def test_annual_gate_rejects_one_date_below_threshold() -> None:
    result, passed = M.annual_gate(
        {"2022": 15, "2023": 48, "2024": 47},
        {"2022": 20, "2023": 60, "2024": 58},
    )
    assert not passed
    assert result["2022"]["status"] == "SUPPORT_FAIL"


def test_required_windows_are_exact_and_value_blind() -> None:
    decision = 20 * M.ONE_HOUR_NS
    structure = M.required_minutes("CSR_STRUCTURE_MOMENTUM_15M", decision)
    level = M.required_minutes("CSR_SESSION_LEVEL_TENSION", decision)
    assert len(structure) == 900
    assert len(level) == 900
    assert decision - M.ONE_MINUTE_NS in level
    assert min(structure) == decision - 15 * M.ONE_HOUR_NS
    assert max(structure) == decision - M.ONE_MINUTE_NS


def test_frozen_disposition_order() -> None:
    minute = M.ONE_MINUTE_NS
    envelopes = {"1970-01-01": (0, 10 * minute)}
    assert M.classify_missing([5 * minute], envelopes, M.AV_TECH_XAU) == "GENUINE_SOURCE_GAP"
    assert M.classify_missing([11 * minute], envelopes, M.AV_TECH_XAU) == "REQUIRES_ADDITIONAL_SOURCE"
    assert M.classify_missing([], envelopes, M.AV_TECH_XAU) == "RECOVERABLE_EXISTING_SEALED_SOURCE"
    assert M.classify_missing([], envelopes, M.AV_CONTEXT) == "DEFINITION_INDUCED_UNAVAILABLE"
    assert M.classify_missing([], envelopes, "UNKNOWN_UNREGISTERED") == "UNRESOLVED"


def test_protocol_preserves_locks_and_only_replaces_one_gate() -> None:
    protocol = M.load_json(M.PROTOCOL)
    replacement = protocol["sole_support_gate_replacement"]
    assert replacement["remove"] == "each_required_year_oof_dates_gte_35"
    assert replacement["add"] == "each_required_year_oof_coverage_gte_80pct"
    assert replacement["coverage_fraction"] == 0.8
    assert all(protocol["locked"].values())
