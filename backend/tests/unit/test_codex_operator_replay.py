from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gold_intel.api.routes import codex_operator_replay
from gold_intel.application.blind_replay import ReplayIntegrityError
from gold_intel.application.codex_operator_replay import (
    CodexOperatorReplayService,
    canonical_bytes,
    canonical_hash,
)
from gold_intel.application.matched_human_replay import MatchedHumanReplayService

TIMEFRAMES = ("1w", "1d", "4h", "1h", "15m", "5m", "1m")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def bar(bar_id: str, open_at: str, close_at: str, value: float) -> dict[str, Any]:
    return {
        "bar_id": bar_id,
        "open_at": open_at,
        "close_at": close_at,
        "available_at": close_at,
        "open": value,
        "high": value + 0.4,
        "low": value - 0.4,
        "close": value + 0.1,
        "tick_volume": 10,
        "spread_price": 0.2,
    }


def stream(alias: str, day: str, sequence: int) -> dict[str, Any]:
    start = f"{day}T00:00:00Z"
    end = f"{day}T00:05:00Z"
    prior_open = f"{day}T00:00:00Z"
    prior_close = start
    charts: dict[str, list[dict[str, Any]]] = {}
    for timeframe in TIMEFRAMES:
        charts[timeframe] = [bar(f"{alias}-{timeframe}-past", prior_open, prior_close, 100.0)]
    charts["1m"] = [
        bar(f"{alias}-1m-past", prior_open, prior_close, 100.0),
        bar(f"{alias}-1m-001", f"{day}T00:01:00Z", f"{day}T00:02:00Z", 100.5),
        bar(f"{alias}-1m-002", f"{day}T00:02:00Z", f"{day}T00:03:00Z", 101.5),
        bar(f"{alias}-1m-003", f"{day}T00:03:00Z", f"{day}T00:04:00Z", 102.5),
    ]
    sessions = [
        {
            "record_id": f"{alias}-LONDON",
            "session_code": "LONDON",
            "session_date": day,
            "session_timezone": "UTC",
            "available_at": start,
            "decision_at": start,
            "observation_end": f"{day}T00:03:00Z",
            "epistemic_status": "OBSERVED",
            "known_levels": [],
            "windows": {},
            "record_hash": canonical_hash([alias, "LONDON"]),
        },
        {
            "record_id": f"{alias}-NEW_YORK",
            "session_code": "NEW_YORK",
            "session_date": day,
            "session_timezone": "UTC",
            "available_at": f"{day}T00:02:00Z",
            "decision_at": f"{day}T00:02:00Z",
            "observation_end": f"{day}T00:04:00Z",
            "epistemic_status": "OBSERVED",
            "known_levels": [],
            "windows": {},
            "record_hash": canonical_hash([alias, "NEW_YORK"]),
        },
    ]
    body = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_PRIVATE_STREAM_1_0",
        "case_alias": alias,
        "mode": "CODEX_BLIND",
        "mode_sequence": sequence,
        "trading_date_utc": day,
        "start_inclusive": start,
        "end_exclusive": end,
        "initial_cursor_at": start,
        "maximum_cursor_at": end,
        "research_credit": "SYNTHETIC_CERTIFICATION_ONLY",
        "timeframes": charts,
        "context_timeline": {
            "fundamentals": [{
                "available_at": start,
                "epistemic_status": "CALCULATED",
                "engine_state": {
                    "bias_label": "NEUTRAL",
                    "directional_score": 0,
                    "confidence": 50,
                    "regime_label": "SYNTHETIC",
                    "dominant_driver": "Synthetic driver",
                    "main_contradiction": "None",
                    "event_risk": "LOW",
                    "components": [],
                },
            }],
            "structure": [],
            "cross_market": [],
            "positioning": [],
            "events": [],
            "sessions": sessions,
        },
        "source_lineage": {"synthetic": True},
    }
    body["stream_sha256"] = canonical_hash(body)
    return body


@pytest.fixture
def service(tmp_path: Path) -> CodexOperatorReplayService:
    root = tmp_path / "fixture-root"
    artifact = root / "research_artifacts" / "gold_blind_codex_operator_replay_v1"
    primary = artifact / "private_streams" / "primary"
    reference = artifact / "private_streams" / "reference"
    primary.mkdir(parents=True)
    reference.mkdir(parents=True)
    cases = []
    certified = []
    for index, day in enumerate(("2022-01-03", "2022-01-04"), start=1):
        alias = f"CBR-2022-{index:03d}"
        record = stream(alias, day, index)
        payload = canonical_bytes(record) + b"\n"
        items = []
        for directory in (primary, reference):
            path = directory / f"{alias}.json.gz"
            with path.open("wb") as raw, gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, mtime=0
            ) as zipped:
                zipped.write(payload)
            items.append({
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": file_sha(path),
                "stream_sha256": record["stream_sha256"],
            })
        certified.append({
            "case_alias": alias,
            "primary": items[0],
            "reference": items[1],
            "bytes_exact": items[0]["sha256"] == items[1]["sha256"],
        })
        cases.append({
            "case_alias": alias,
            "mode_sequence": index,
            "trading_date_utc": day,
            "start_inclusive": record["start_inclusive"],
            "end_exclusive": record["end_exclusive"],
        })
    population_sha = canonical_hash(cases)
    write_json(artifact / "population_registry.private.json", {
        "case_count": 2,
        "population_sha256": population_sha,
        "outcomes": "LOCKED_UNTIL_COMPLETE_POPULATION",
        "cases": cases,
    })
    write_json(artifact / "stream_materialization_certification.json", {
        "verdict": "PASS_CODEX_OPERATOR_PRIVATE_STREAM_MATERIALIZATION",
        "case_count": 2,
        "population_sha256": population_sha,
        "gates": {"synthetic_reproduction": True},
        "case_files": certified,
    })
    write_json(artifact / "decision_policy.json", {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_DECISION_POLICY_1_0",
    })
    write_json(artifact / "execution_policy.json", {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_EXECUTION_POLICY_1_0",
        "latency_minutes": 1,
        "market_and_stop_slippage_price": 0.05,
        "maximum_planned_risk_usd": 50.0,
        "maximum_effective_fill_to_stop_risk_usd": 55.0,
        "minimum_quantity_ounces": 1,
    })
    write_json(artifact / "ledger_policy.json", {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_LEDGER_POLICY_1_0",
    })
    human = root / "human-ledger.jsonl"
    human.write_bytes(b"preserved synthetic human ledger\n")
    return CodexOperatorReplayService(
        artifact,
        artifact / "ledgers" / "visible.jsonl",
        artifact / "outcome_vault" / "outcomes.jsonl",
        human,
        expected_case_count=2,
        expected_human_ledger_sha256=file_sha(human),
    )


def api(service: CodexOperatorReplayService) -> TestClient:
    app = FastAPI()
    app.include_router(codex_operator_replay.router, prefix="/api/v1")
    app.dependency_overrides[codex_operator_replay.get_codex_operator_replay_service] = lambda: service
    return TestClient(app)


def test_matched_human_replay_reuses_streams_but_isolates_state(
    service: CodexOperatorReplayService,
) -> None:
    matched = MatchedHumanReplayService(
        artifact_path=service.artifact_path,
        visible_ledger_path=service.artifact_path / "matched" / "visible.jsonl",
        outcome_ledger_path=service.artifact_path / "matched" / "outcomes.jsonl",
        human_ledger_path=service.human_ledger_path,
        expected_case_count=2,
        expected_human_ledger_sha256=service.expected_human_ledger_sha256,
    )

    payload = matched.case()
    assert payload is not None
    assert payload["case"]["mode"] == "MATCHED_HUMAN_DIAGNOSTIC"
    assert payload["case"]["display_policy"]["codex_decisions_visible"] is False
    assert payload["progress"]["cases_total"] == 2
    assert payload["progress"]["human_decisions"] == "CURRENT_OPERATOR_ONLY_CODEX_HIDDEN"
    assert payload["progress"]["research_credit"] == "ZERO_CREDIT_MATCHED_METHOD_DIAGNOSTIC"
    assert not matched.visible_ledger_path.exists()
    assert not matched.outcome_ledger_path.exists()

    request = {
        "predecision_evidence_sha256": payload["case"]["visible_state_sha256"],
    }
    matched._verify_predecision_evidence(request, payload["case"])
    request["predecision_evidence_sha256"] = "0" * 64
    with pytest.raises(ReplayIntegrityError, match="decision-state seal differs"):
        matched._verify_predecision_evidence(request, payload["case"])


def inspect_required(client: TestClient, snapshot: dict[str, Any]) -> dict[str, Any]:
    current = snapshot
    for timeframe in ("1w", "1d", "4h", "1h", "15m"):
        response = client.post(
            "/api/v1/codex-operator-replay-v1/inspect",
            headers={"Idempotency-Key": f"{snapshot['case_alias']}:inspect:{timeframe}"},
            json={
                "case_alias": snapshot["case_alias"],
                "expected_cursor_at": current["cursor_at"],
                "selected_timeframe": timeframe,
                "screenshot_sha256": None,
            },
        )
        assert response.status_code == 200, response.text
        current = response.json()["case"]
    return current


def evidence(service: CodexOperatorReplayService, snapshot: dict[str, Any]) -> str:
    alias = snapshot["case_alias"]
    directory = service.artifact_path / "evidence" / "predecision" / alias
    directory.mkdir(parents=True, exist_ok=True)
    specs = [
        ("INITIAL_FULL_PAGE_SCREENSHOT", None, "initial.png"),
        ("FINAL_PREDECISION_FULL_PAGE_SCREENSHOT", None, "final.png"),
        ("FINAL_PREDECISION_CHART_CROP", None, "chart.png"),
        ("COMPLETED_DECISION_FORM_SCREENSHOT", None, "form.png"),
        ("CHRONOLOGICAL_ACTION_LOG", None, "actions.jsonl"),
    ]
    specs.extend(("TIMEFRAME_SCREENSHOT", timeframe, f"timeframe-{timeframe}.png") for timeframe in snapshot["inspected_timeframes"])
    artifacts = []
    for kind, timeframe, filename in specs:
        path = directory / filename
        path.write_bytes(f"synthetic:{alias}:{kind}:{timeframe}".encode())
        item = {
            "kind": kind,
            "path": path.relative_to(service.artifact_path.parents[1]).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": file_sha(path),
        }
        if timeframe:
            item["timeframe"] = timeframe
        artifacts.append(item)
    manifest = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_PREDECISION_EVIDENCE_1_0",
        "case_alias": alias,
        "cursor_at": snapshot["cursor_at"],
        "visible_state_sha256": snapshot["visible_state_sha256"],
        "inspected_timeframes": snapshot["inspected_timeframes"],
        "artifacts": artifacts,
    }
    path = directory / "predecision_evidence_manifest.json"
    write_json(path, manifest)
    return file_sha(path)


def annotation(*, no_trade: bool = False) -> dict[str, Any]:
    return {
        "setup_class": None if no_trade else "MACRO_NEUTRAL_AUCTION_TRADE",
        "thesis": "The completed, visible auction evidence supports this frozen decision.",
        "macro_regime": "Synthetic neutral regime",
        "macro_directional_pressure": "Neutral",
        "macro_role": "NEUTRAL",
        "macro_freshness": "Point-in-time synthetic certification context",
        "dominant_driver": "Synthetic driver",
        "catalyst_risk": "LOW",
        "higher_timeframe_state": "RANGE",
        "higher_timeframe_context": "Completed higher-timeframe candles show a bounded range.",
        "location_timeframe": "1h",
        "preexisting_location": "The visible price is at a pre-existing range boundary.",
        "m15_transition": "A completed M15 transition is visible at the boundary.",
        "session_liquidity_context": "The decision is inside the frozen active session.",
        "invalidation_timeframe": "15m",
        "invalidation_condition": "The opposite completed M15 structure break invalidates the idea.",
        "target_timeframe": "1h",
        "target_type": "NOT_APPLICABLE" if no_trade else "EXTERNAL_LIQUIDITY",
        "target_logic": "No target because no setup qualified." if no_trade else "Target the visible opposing range liquidity.",
        "macro_confidence": 50,
        "setup_quality": 0 if no_trade else 65,
        "execution_quality": 0 if no_trade else 65,
        "no_trade_reason": "No complete eligible setup appeared by the terminal cursor." if no_trade else None,
    }


def trade_request(snapshot: dict[str, Any], evidence_sha: str) -> dict[str, Any]:
    entry, stop, target = 100.0, 99.0, 102.0
    cursor = snapshot["cursor_at"]
    drawing = {
        "drawing_id": "position-1",
        "kind": "LONG_POSITION",
        "created_at_cursor": cursor,
        "anchors": [
            {"anchor_at": cursor, "price": entry, "source_timeframe": "15m"},
            {"anchor_at": cursor, "price": stop, "source_timeframe": "15m"},
            {"anchor_at": cursor, "price": target, "source_timeframe": "15m"},
        ],
    }
    return {
        "case_alias": snapshot["case_alias"],
        "expected_cursor_at": cursor,
        "selected_timeframe": "15m",
        "client_visible_state_sha256": snapshot["visible_state_sha256"],
        "predecision_evidence_sha256": evidence_sha,
        "inspected_timeframes": snapshot["inspected_timeframes"],
        "action": "LONG",
        "entry": entry,
        "stop": stop,
        "target": target,
        "drawings": [drawing],
        "annotation": annotation(),
    }


def test_browser_snapshot_excludes_future_outcomes_and_private_lineage(service: CodexOperatorReplayService) -> None:
    snapshot = service.case()["case"]
    assert snapshot["cursor_at"] == "2022-01-03T00:00:00Z"
    assert len(snapshot["charts"]["1m"]) == 1
    serialized = json.dumps(snapshot, sort_keys=True)
    for forbidden in ("source_lineage", "POSITION_RESOLVED", "net_pnl_usd", "r50", "mfe_r50", "mae_r50"):
        assert forbidden not in serialized
    assert snapshot["display_policy"]["operator_input"] == "RENDERED_PIXELS_ONLY"
    assert [item["session_code"] for item in snapshot["context"]["session_schedule"]] == [
        "LONDON",
        "NEW_YORK",
    ]
    assert snapshot["context"]["session_schedule"][1] == {
        "session_code": "NEW_YORK",
        "decision_at": "2022-01-03T00:02:00Z",
        "observation_end": "2022-01-03T00:04:00Z",
        "session_timezone": "UTC",
    }


def test_decision_is_evidence_bound_idempotent_and_outcome_hidden(service: CodexOperatorReplayService) -> None:
    client = api(service)
    snapshot = client.get("/api/v1/codex-operator-replay-v1/next").json()["case"]
    snapshot = inspect_required(client, snapshot)
    payload = trade_request(snapshot, evidence(service, snapshot))
    first = client.post(
        "/api/v1/codex-operator-replay-v1/decisions",
        headers={"Idempotency-Key": "case-1-decision"},
        json=payload,
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["outcome_hidden"] is True
    assert body["progress"]["cases_completed"] == 1
    assert body["case"]["case_alias"] == "CBR-2022-002"
    serialized = json.dumps(body, sort_keys=True)
    assert "net_pnl_usd" not in serialized and "POSITION_RESOLVED" not in serialized
    repeated = client.post(
        "/api/v1/codex-operator-replay-v1/decisions",
        headers={"Idempotency-Key": "case-1-decision"},
        json=payload,
    )
    assert repeated.status_code == 201
    assert repeated.json()["idempotent_replay"] is True
    visible = service.visible_ledger_path.read_text(encoding="utf-8")
    assert "net_pnl_usd" not in visible and "POSITION_RESOLVED" not in visible
    assert service.outcome_ledger_path.is_file()


def test_no_trade_requires_exact_terminal_cursor(service: CodexOperatorReplayService) -> None:
    client = api(service)
    snapshot = inspect_required(client, client.get("/api/v1/codex-operator-replay-v1/next").json()["case"])
    premature = {
        "case_alias": snapshot["case_alias"],
        "expected_cursor_at": snapshot["cursor_at"],
        "selected_timeframe": "15m",
        "client_visible_state_sha256": snapshot["visible_state_sha256"],
        "predecision_evidence_sha256": evidence(service, snapshot),
        "inspected_timeframes": snapshot["inspected_timeframes"],
        "action": "NO_TRADE",
        "entry": None,
        "stop": None,
        "target": None,
        "drawings": [],
        "annotation": annotation(no_trade=True),
    }
    rejected = client.post(
        "/api/v1/codex-operator-replay-v1/decisions",
        headers={"Idempotency-Key": "premature-no-trade"},
        json=premature,
    )
    assert rejected.status_code == 409
    advanced = client.post(
        "/api/v1/codex-operator-replay-v1/advance",
        headers={"Idempotency-Key": "advance-to-terminal"},
        json={
            "case_alias": snapshot["case_alias"],
            "expected_cursor_at": snapshot["cursor_at"],
            "increment_minutes": 15,
            "selected_timeframe": "15m",
        },
    )
    assert advanced.status_code == 200
    terminal = advanced.json()["case"]
    assert terminal["cursor_at"] == "2022-01-03T00:04:00Z"


def test_restart_completes_only_an_already_sealed_decision(
    service: CodexOperatorReplayService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = service.case()["case"]
    for index, timeframe in enumerate(("1w", "1d", "4h", "1h", "15m"), start=1):
        snapshot = service.inspect_timeframe(
            request={
                "case_alias": snapshot["case_alias"],
                "expected_cursor_at": snapshot["cursor_at"],
                "selected_timeframe": timeframe,
                "screenshot_sha256": None,
            },
            idempotency_key=f"inspect-restart-{index}",
            recorded_at="2026-08-18T00:00:00Z",
        )["case"]
    payload = trade_request(snapshot, evidence(service, snapshot))
    original = service._seal_outcome

    def interrupt(*_: Any, **__: Any) -> str:
        raise RuntimeError("synthetic interruption after visible decision commit")

    monkeypatch.setattr(service, "_seal_outcome", interrupt)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        service.decide(payload, "interrupted-decision", "2026-08-18T00:00:01Z")
    assert "DECISION_SEALED" in service.visible_ledger_path.read_text(encoding="utf-8")
    assert "CASE_TERMINAL_HIDDEN" not in service.visible_ledger_path.read_text(encoding="utf-8")
    monkeypatch.setattr(service, "_seal_outcome", original)
    status = service.status()
    assert status["cases_completed"] == 1
    assert "CASE_TERMINAL_HIDDEN" in service.visible_ledger_path.read_text(encoding="utf-8")
    assert service.outcome_ledger_path.is_file()
