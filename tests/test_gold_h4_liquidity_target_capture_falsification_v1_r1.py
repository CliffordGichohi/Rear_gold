from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import run_gold_h4_liquidity_target_capture_falsification_v1_r1 as recovery


def test_attempt_one_failure_contains_no_research_result() -> None:
    failure = json.loads(recovery.FAILURE.read_text(encoding="utf-8"))
    assert failure["status"] == "FAIL_ATTEMPT_1_INFRASTRUCTURE_TIMEOUT_NO_RESULT"
    assert failure["partial_case_payload_written"] is False
    assert failure["partial_result_payload_written"] is False
    assert failure["research_verdict_produced"] is False


def test_cache_is_value_blind_and_query_identical() -> None:
    proof = recovery.cache_proof()
    assert proof["status"] == "PASS_SYNTHETIC_IMMUTABLE_RANGE_TREE_CACHE_PROOF"
    assert proof["same_object_reused"] is True
    assert proof["all_query_comparisons_equal"] is True
