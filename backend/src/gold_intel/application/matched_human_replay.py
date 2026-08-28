from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from typing import Any

from gold_intel.application.blind_replay import ReplayIntegrityError
from gold_intel.application.codex_operator_replay import CodexOperatorReplayService
from gold_intel.config import get_settings

MATCHED_PROTOCOL = "GOLD_MATCHED_HUMAN_CODEX_REPLAY_COMPARISON_V1_PROTOCOL_1_0"


class MatchedHumanReplayService(CodexOperatorReplayService):
    """Isolated human replay over the exact frozen Codex early-stop cases."""

    def _verify_predecision_evidence(
        self,
        request: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> None:
        # The interactive human UI seals the complete server-visible state hash.
        # Drawings and the structured rationale remain inside the immutable
        # decision payload; deterministic rendering can reproduce the chart.
        if request["predecision_evidence_sha256"] != snapshot["visible_state_sha256"]:
            raise ReplayIntegrityError("Matched human decision-state seal differs")

    def _status_from(
        self,
        events: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        output = super()._status_from(events, state)
        output.update(
            {
                "protocol": MATCHED_PROTOCOL,
                "human_decisions": "CURRENT_OPERATOR_ONLY_CODEX_HIDDEN",
                "research_credit": "ZERO_CREDIT_MATCHED_METHOD_DIAGNOSTIC",
            }
        )
        return output

    def _snapshot(
        self,
        row: dict[str, Any],
        cursor_at: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = deepcopy(super()._snapshot(row, cursor_at, state))
        snapshot["mode"] = "MATCHED_HUMAN_DIAGNOSTIC"
        snapshot["display_policy"]["operator_input"] = "HUMAN_RENDERED_INTERFACE"
        snapshot["display_policy"]["codex_decisions_visible"] = False
        snapshot["display_policy"]["comparison_outcomes_visible"] = False
        return snapshot


@lru_cache(maxsize=1)
def get_matched_human_replay_service() -> MatchedHumanReplayService:
    settings = get_settings()
    return MatchedHumanReplayService(
        artifact_path=settings.matched_human_replay_artifact_path,
        visible_ledger_path=settings.matched_human_replay_visible_ledger_path,
        outcome_ledger_path=settings.matched_human_replay_outcome_ledger_path,
        human_ledger_path=settings.blind_replay_v3_ledger_path,
        expected_case_count=30,
    )
