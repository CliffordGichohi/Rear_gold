from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gold_intel.api.routes import blind_replay_v2
from gold_intel.application.blind_replay import (
    ReplayConflictError,
    ReplayIntegrityError,
    canonical_bytes,
    canonical_hash,
    sha256_file,
)
from gold_intel.application.blind_replay_v2 import (
    BlindReplayV2Service,
    get_blind_replay_v2_service,
)

TIMEFRAMES = ("1w", "1d", "4h", "1h", "15m", "5m", "1m")


def _write_gzip(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with (
        path.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as compressed,
    ):
        for row in rows:
            compressed.write(canonical_bytes(row) + b"\n")


def _bar(alias: str, timeframe: str, offset: int, price: float) -> dict[str, object]:
    body: dict[str, object] = {
        "close_offset_minutes": offset,
        "available_offset_minutes": offset,
        "open": round(price - 0.02, 6),
        "high": round(price + 0.1, 6),
        "low": round(price - 0.1, 6),
        "close": round(price, 6),
        "volume": 10.0,
    }
    return {"bar_id": canonical_hash({"alias": alias, "timeframe": timeframe, **body}), **body}


def _artifacts(tmp_path: Path) -> Path:
    rows: list[dict[str, object]] = []
    durations = {"1w": 10_080, "1d": 1_440, "4h": 240, "1h": 60, "15m": 15, "5m": 5, "1m": 1}
    for case_number in range(1, 21):
        alias = f"P-{case_number:03d}"
        timelines: dict[str, list[dict[str, object]]] = {}
        for timeframe in TIMEFRAMES:
            duration = durations[timeframe]
            timelines[timeframe] = [
                _bar(alias, timeframe, -duration * index, 100 - index * 0.01)
                for index in range(15, -1, -1)
            ]
        timelines["1m"].extend(
            _bar(alias, "1m", offset, 100 + offset * 0.01) for offset in range(1, 181)
        )
        context = {
            "m15_atr_index": 0.2,
            "fundamental": {"bias_label": "CONFLICTED"},
            "display_policy": {"future_scored_path_present": False},
        }
        row: dict[str, object] = {
            "version": "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_TIMELINE_1_0",
            "case_alias": alias,
            "mode": "PRACTICE",
            "mode_sequence": case_number,
            "session_code": "LONDON" if case_number % 2 else "NEW_YORK",
            "initial_cursor_minute": 0,
            "maximum_cursor_minute": 180,
            "reference_index": 100.0,
            "context": context,
            "context_sha256": canonical_hash(context),
            "timelines": timelines,
            "source_lineage": {"test": True},
        }
        row["timeline_sha256"] = canonical_hash(row)
        rows.append(row)

    primary = tmp_path / "practice_timelines_v2.primary.jsonl.gz"
    reference = tmp_path / "practice_timelines_v2.reference.jsonl.gz"
    _write_gzip(primary, rows)
    shutil.copyfile(primary, reference)
    certification = {
        "verdict": "PASS_V2_PRACTICE_TIMELINE_MATERIALIZATION",
        "gates": {"practice_only": True, "independent_reproduction": True},
        "primary_sha256": sha256_file(primary),
        "reference_sha256": sha256_file(reference),
        "complete_timeline_set_sha256": canonical_hash(rows),
    }
    (tmp_path / "timeline_materialization_certification.json").write_text(
        json.dumps(certification), encoding="utf-8"
    )
    (tmp_path / "preimplementation_state.json").write_text(
        json.dumps(
            {
                "status": "FROZEN_BEFORE_V2_VALUE_MATERIALIZATION_OR_IMPLEMENTATION",
                "human_decisions_collected": 0,
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def _client(service: BlindReplayV2Service) -> TestClient:
    app = FastAPI()
    app.include_router(blind_replay_v2.router, prefix="/api/v1")
    app.dependency_overrides[get_blind_replay_v2_service] = lambda: service
    return TestClient(app)


def _directional(snapshot: dict[str, object]) -> dict[str, object]:
    cursor = int(snapshot["cursor_minute"])
    charts = snapshot["charts"]
    assert isinstance(charts, dict)
    m1 = charts["1m"]
    assert isinstance(m1, list)
    latest_bar = m1[-1]
    entry = float(latest_bar["close"])
    atr = float(snapshot["latest_point_in_time_m15_atr_index"])
    stop = entry - atr
    target = entry + 2 * atr
    return {
        "case_alias": snapshot["case_alias"],
        "expected_cursor_minute": cursor,
        "selected_timeframe": "1m",
        "client_visible_charts_sha256": snapshot["visible_charts_sha256"],
        "action": "LONG",
        "confidence": 70,
        "entry_trigger": "MARKET",
        "entry_index": entry,
        "stop_index": stop,
        "target_index": target,
        "drawings": [
            {
                "drawing_id": "position-1",
                "kind": "LONG_POSITION",
                "placed_at_cursor_minute": cursor,
                "anchors": [
                    {"relative_minute": cursor, "price_index": entry, "source_timeframe": "1m"},
                    {"relative_minute": cursor, "price_index": stop, "source_timeframe": "1m"},
                    {"relative_minute": cursor, "price_index": target, "source_timeframe": "1m"},
                ],
            }
        ],
        "evidence_codes": ["HTF_TREND", "SUPPORT_RESISTANCE"],
        "trade_reason": "Trend and location align at the current replay cursor.",
        "trigger_condition": "Completed candle confirms acceptance.",
        "invalidation": "The structural low is lost.",
        "target_explanation": "Target is the known opposing liquidity.",
    }


def test_cursor_is_server_filtered_monotonic_and_idempotent(tmp_path: Path) -> None:
    service = BlindReplayV2Service(_artifacts(tmp_path))
    client = _client(service)
    initial = client.get("/api/v1/blind-replay-v2/next").json()
    assert initial["case"]["cursor_minute"] == 0
    assert max(bar["close_offset_minutes"] for bar in initial["case"]["charts"]["1m"]) == 0
    assert "timelines" not in json.dumps(initial)

    request = {
        "case_alias": "P-001",
        "expected_cursor_minute": 0,
        "increment_minutes": 5,
        "selected_timeframe": "15m",
    }
    advanced = client.post(
        "/api/v1/blind-replay-v2/advance",
        headers={"Idempotency-Key": "advance-one"},
        json=request,
    )
    assert advanced.status_code == 200
    payload = advanced.json()
    assert payload["case"]["cursor_minute"] == 5
    assert max(bar["close_offset_minutes"] for bar in payload["case"]["charts"]["1m"]) == 5
    replayed = client.post(
        "/api/v1/blind-replay-v2/advance",
        headers={"Idempotency-Key": "advance-one"},
        json=request,
    )
    assert replayed.status_code == 200
    assert replayed.json()["case"]["visible_charts_sha256"] == payload["case"]["visible_charts_sha256"]
    stale = client.post(
        "/api/v1/blind-replay-v2/advance",
        headers={"Idempotency-Key": "advance-stale"},
        json=request,
    )
    assert stale.status_code == 409
    assert "Stale cursor" in stale.json()["detail"]


def test_place_and_play_seals_complete_setup_before_future_disclosure(tmp_path: Path) -> None:
    service = BlindReplayV2Service(_artifacts(tmp_path))
    client = _client(service)
    advance = client.post(
        "/api/v1/blind-replay-v2/advance",
        headers={"Idempotency-Key": "advance-5"},
        json={
            "case_alias": "P-001",
            "expected_cursor_minute": 0,
            "increment_minutes": 5,
            "selected_timeframe": "1m",
        },
    ).json()
    decision = _directional(advance["case"])
    locked = client.post(
        "/api/v1/blind-replay-v2/decisions",
        headers={"Idempotency-Key": "setup-one"},
        json=decision,
    )
    assert locked.status_code == 201
    payload = locked.json()
    assert payload["locked_cursor_minute"] == 5
    assert payload["practice_feedback"]["bars"][0]["close_offset_minutes"] == 6
    record = json.loads(service.setup_ledger_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["submitted_setup"]["trade_reason"] == decision["trade_reason"]
    assert record["submitted_setup"]["drawings"] == decision["drawings"]
    assert record["execution_policy"]["maximum_planned_risk_usd"] == 50.0
    assert record["execution_policy"]["same_bar_ambiguity"] == "STOP_FIRST"
    assert record["visible_charts_sha256"] == decision["client_visible_charts_sha256"]
    assert record["context_sha256"] == canonical_hash(record["point_in_time_context"])
    assert service.status()["next_case_alias"] == "P-002"
    assert service.status()["cursor_minute"] == 0


def test_future_anchor_stale_snapshot_and_ledger_tampering_are_rejected(tmp_path: Path) -> None:
    service = BlindReplayV2Service(_artifacts(tmp_path))
    snapshot = service.next_case()["case"]  # type: ignore[index]
    decision = _directional(snapshot)
    decision["drawings"][0]["anchors"][0]["relative_minute"] = 1  # type: ignore[index]
    with pytest.raises(ReplayConflictError, match="unrevealed"):
        service.submit_decision(
            request=decision, idempotency_key="future-anchor", locked_at="lock"
        )

    good = _directional(snapshot)
    good["client_visible_charts_sha256"] = "f" * 64
    with pytest.raises(ReplayConflictError, match="snapshot differs"):
        service.submit_decision(request=good, idempotency_key="stale", locked_at="lock")

    service.advance(
        request={
            "case_alias": "P-001",
            "expected_cursor_minute": 0,
            "increment_minutes": 1,
            "selected_timeframe": "1m",
        },
        idempotency_key="cursor",
        advanced_at="now",
    )
    content = service.cursor_ledger_path.read_text(encoding="utf-8")
    service.cursor_ledger_path.write_text(
        content.replace('"to_cursor_minute":1', '"to_cursor_minute":2'), encoding="utf-8"
    )
    with pytest.raises(ReplayIntegrityError, match="record hash"):
        service.status()
