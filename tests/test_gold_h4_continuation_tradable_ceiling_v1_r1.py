from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_h4_continuation_tradable_ceiling_v1_r1 as subject  # noqa: E402


def test_recovery_preflight_preserves_original_failure() -> None:
    audit = subject.recovery_preflight()
    assert audit["failure"]["status"] == "FAIL_FROZEN_ORACLE_COVERAGE_ASSUMPTION"
    assert audit["amendment"]["documented_oracle_coverage"]["oracle_unavailable"] == 33


def test_recovery_uses_original_stop_first_proof() -> None:
    assert subject.base.synthetic_proof()["status"] == "PASS_SYNTHETIC_STOP_FIRST_AND_PREINVALIDATION_CEILING_PROOF"
