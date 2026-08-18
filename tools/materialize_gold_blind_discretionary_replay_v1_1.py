#!/usr/bin/env python3
"""Materialize Coverage-Amendment-A replay payloads without altering attempt 1.

This module deliberately reuses the frozen V1 transformations, changing only the
pre-value coverage dispositions authorized by Coverage Amendment A:

* a daily bar may be used when its observed quote path is >= 95% complete and
  contains at least 1,000 source minutes; and
* a weekly display bar requires at least four eligible daily bars.
"""

from __future__ import annotations

import bisect
import gzip
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import materialize_gold_blind_discretionary_replay_v1 as base


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "research_artifacts" / "gold_blind_discretionary_replay_v1"
PRIVATE_REGISTRY = ARTIFACT_DIR / "population_registry_v1_1.private.json"
POPULATION_FREEZE = ROOT / "research_manifests" / "gold_blind_discretionary_replay_v1_population_freeze_v1_1.json"
PRIMARY_PAYLOAD = ARTIFACT_DIR / "display_payloads_v1_1.primary.jsonl.gz"
REFERENCE_PAYLOAD = ARTIFACT_DIR / "display_payloads_v1_1.reference.jsonl.gz"
PRIMARY_PRACTICE = ARTIFACT_DIR / "practice_future_paths_v1_1.primary.jsonl.gz"
REFERENCE_PRACTICE = ARTIFACT_DIR / "practice_future_paths_v1_1.reference.jsonl.gz"
CERTIFICATION = ARTIFACT_DIR / "materialization_certification_v1_1.json"

MISSING_RE = re.compile(r'"missing_source_minutes":(\d+)')
SOURCE_COUNT_RE = re.compile(r'"source":\{[^}]*"source_count":(\d+)')
EXPECTED_CHARTS = {"1w": 52, **base.BAR_LIMITS}


def verify_population_freeze() -> dict[str, Any]:
    freeze = json.loads(POPULATION_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "SEALED_AMENDMENT_A_BEFORE_HUMAN_LABELING":
        raise RuntimeError("Coverage Amendment A population is not sealed")
    failures: list[str] = []
    for item in freeze["sealed_files"]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or base.sha256_file(path) != item["sha256"]:
            failures.append(item["path"])
    if failures:
        raise RuntimeError(f"Coverage Amendment A freeze verification failed: {failures}")
    return freeze


def parse_price_primary(line: str) -> dict[str, Any]:
    parsed = base.parse_price_primary(line)
    source = json.loads(line)
    parsed["missing_source_minutes"] = int(source.get("missing_source_minutes") or 0)
    parsed["source_count"] = int(source.get("source", {}).get("source_count") or 0)
    return parsed


def parse_price_reference(line: str) -> dict[str, Any]:
    parsed = base.parse_price_reference(line)
    missing = MISSING_RE.search(line)
    source_count = SOURCE_COUNT_RE.search(line)
    if missing is None or source_count is None:
        raise RuntimeError("Reference parser failed Amendment A coverage extraction")
    parsed["missing_source_minutes"] = int(missing.group(1))
    parsed["source_count"] = int(source_count.group(1))
    return parsed


def daily_quote_path_valid(row: dict[str, Any]) -> bool:
    source_count = int(row["source_count"])
    total = source_count + int(row["missing_source_minutes"])
    return source_count >= 1000 and total > 0 and source_count / total >= 0.95


def build_price_inputs(
    cases: list[dict[str, Any]], parser: Callable[[str], dict[str, Any]]
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], dict[str, list[dict[str, Any]]]]:
    charts = {row["case_alias"]: {timeframe: [] for timeframe in base.BAR_LIMITS} for row in cases}
    practice = {row["case_alias"]: [] for row in cases if row["mode"] == "PRACTICE"}
    entries = sorted((base.parse_timestamp(row["checkpoint_at"]), row["case_alias"]) for row in cases)
    cutoffs = [item[0] for item in entries]
    practice_entries = sorted(
        (base.parse_timestamp(row["checkpoint_at"]), base.parse_timestamp(row["session_end"]), row["case_alias"])
        for row in cases if row["mode"] == "PRACTICE"
    )

    with gzip.open(base.CASEBOOK / "price_bars.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            row = parser(line)
            timeframe = row["timeframe"]
            if timeframe not in base.BAR_LIMITS:
                continue
            if timeframe == "1d":
                if not daily_quote_path_valid(row):
                    continue
            elif not row["complete"]:
                continue
            open_at = base.parse_timestamp(row["open_time"])
            available_at = base.parse_timestamp(row["available_at"])
            left = bisect.bisect_left(cutoffs, available_at)
            right = bisect.bisect_right(cutoffs, open_at + timedelta(days=base.WINDOW_DAYS[timeframe]))
            source = {**row, "_open_at": open_at, "_available_at": available_at}
            for cutoff, alias in entries[left:right]:
                if open_at < cutoff and available_at <= cutoff and open_at >= cutoff - timedelta(days=base.WINDOW_DAYS[timeframe]):
                    charts[alias][timeframe].append(source)
            if timeframe == "1m":
                for cutoff, end, alias in practice_entries:
                    if cutoff <= open_at < end and available_at <= end:
                        practice[alias].append(source)

    for alias in charts:
        for timeframe, limit in base.BAR_LIMITS.items():
            charts[alias][timeframe].sort(key=lambda item: (item["_open_at"], item["_available_at"]))
            keep = 400 if timeframe == "1d" else max(limit, 121 if timeframe == "15m" else limit)
            charts[alias][timeframe] = charts[alias][timeframe][-keep:]
    for alias in practice:
        practice[alias].sort(key=lambda item: item["_open_at"])
    return charts, practice


def weekly_view(daily_rows: list[dict[str, Any]], reference: float, cutoff: datetime) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    cutoff_iso = cutoff.date().isocalendar()
    cutoff_week = (cutoff_iso.year, cutoff_iso.week)
    for row in daily_rows:
        iso = row["_open_at"].date().isocalendar()
        key = (iso.year, iso.week)
        if key < cutoff_week:
            grouped[key].append(row)
    weeks = []
    for key in sorted(grouped):
        rows = sorted(grouped[key], key=lambda item: item["_open_at"])
        if len(rows) < 4:
            continue
        weeks.append({
            "open": rows[0]["open"], "high": max(item["high"] for item in rows),
            "low": min(item["low"] for item in rows), "close": rows[-1]["close"],
            "volume": sum(item["volume"] or 0 for item in rows),
        })
    weeks = weeks[-52:]
    return [{
        "ordinal": index + 1 - len(weeks),
        "open": base.normalized_price(row["open"], reference), "high": base.normalized_price(row["high"], reference),
        "low": base.normalized_price(row["low"], reference), "close": base.normalized_price(row["close"], reference),
        "volume": row["volume"],
    } for index, row in enumerate(weeks)]


def attach_availability(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for payload in payloads:
        counts = {timeframe: len(payload["charts"].get(timeframe, [])) for timeframe in EXPECTED_CHARTS}
        full = all(counts[timeframe] == required for timeframe, required in EXPECTED_CHARTS.items())
        if payload["mode"] == "SCORED" and not full:
            raise RuntimeError(f"Scored case lacks frozen display history: {payload['case_alias']} {counts}")
        payload["chart_availability"] = {
            "status": "FULL_FROZEN_HISTORY" if full else "PRACTICE_PARTIAL_HISTORY_ALLOWED_ZERO_CREDIT",
            "counts": counts,
            "required": EXPECTED_CHARTS,
        }
        payload["payload_sha256"] = base.canonical_hash({key: value for key, value in payload.items() if key != "payload_sha256"})
    return payloads


def leakage_audit(payloads: list[dict[str, Any]], practice: list[dict[str, Any]]) -> dict[str, Any]:
    result = base.leakage_audit(payloads, practice)
    result["checks"].update({
        "all_scored_exact_frozen_chart_counts": all(
            row["chart_availability"]["status"] == "FULL_FROZEN_HISTORY"
            and row["chart_availability"]["counts"] == EXPECTED_CHARTS
            for row in payloads if row["mode"] == "SCORED"
        ),
        "practice_partial_history_has_zero_research_credit": all(
            row["chart_availability"]["status"] in {"FULL_FROZEN_HISTORY", "PRACTICE_PARTIAL_HISTORY_ALLOWED_ZERO_CREDIT"}
            for row in payloads if row["mode"] == "PRACTICE"
        ),
    })
    result["pass"] = all(result["checks"].values())
    return result


def main() -> int:
    outputs = (PRIMARY_PAYLOAD, REFERENCE_PAYLOAD, PRIMARY_PRACTICE, REFERENCE_PRACTICE, CERTIFICATION)
    for path in outputs:
        if path.exists():
            raise RuntimeError(f"Append-only target already exists: {path.relative_to(ROOT)}")

    freeze = verify_population_freeze()
    registry = json.loads(PRIVATE_REGISTRY.read_text(encoding="utf-8"))
    cases = registry["cases"]
    if base.canonical_hash(cases) != freeze["population_sha256"]:
        raise RuntimeError("Amended private population hash differs from freeze")

    contexts = base.load_contexts(cases)
    gc, gc_diagnostics = base.gc_views(base.GC_PRIMARY, base.GC_REFERENCE)
    primary_charts, primary_future = build_price_inputs(cases, parse_price_primary)
    reference_charts, reference_future = build_price_inputs(cases, parse_price_reference)
    primary_inputs_hash = base.canonical_hash(primary_charts)
    reference_inputs_hash = base.canonical_hash(reference_charts)
    primary_future_hash = base.canonical_hash(primary_future)
    reference_future_hash = base.canonical_hash(reference_future)
    if primary_inputs_hash != reference_inputs_hash or primary_future_hash != reference_future_hash:
        raise RuntimeError("Independent Amendment A price materialization differs")

    original_weekly = base.weekly_view
    base.weekly_view = weekly_view
    try:
        primary_payloads = attach_availability(base.make_payloads(cases, primary_charts, contexts, gc))
        reference_payloads = attach_availability(base.make_payloads(cases, reference_charts, contexts, gc))
    finally:
        base.weekly_view = original_weekly
    primary_practice = base.make_practice_paths(cases, primary_future, primary_charts)
    reference_practice = base.make_practice_paths(cases, reference_future, reference_charts)
    if primary_payloads != reference_payloads or primary_practice != reference_practice:
        raise RuntimeError("Independent Amendment A replay payload reproduction differs")
    leakage = leakage_audit(primary_payloads, primary_practice)
    if not leakage["pass"]:
        raise RuntimeError(f"Amendment A replay leakage audit failed: {leakage}")

    base.write_jsonl_gzip(PRIMARY_PAYLOAD, primary_payloads)
    base.write_jsonl_gzip(REFERENCE_PAYLOAD, reference_payloads)
    base.write_jsonl_gzip(PRIMARY_PRACTICE, primary_practice)
    base.write_jsonl_gzip(REFERENCE_PRACTICE, reference_practice)
    gates = {
        "amended_population_freeze_verified": True,
        "case_count_260": len(primary_payloads) == 260,
        "price_inputs_independently_reproduced": primary_inputs_hash == reference_inputs_hash,
        "practice_inputs_independently_reproduced": primary_future_hash == reference_future_hash,
        "display_payloads_exact": primary_payloads == reference_payloads,
        "practice_payloads_exact": primary_practice == reference_practice,
        "display_gzip_byte_identical": base.sha256_file(PRIMARY_PAYLOAD) == base.sha256_file(REFERENCE_PAYLOAD),
        "practice_gzip_byte_identical": base.sha256_file(PRIMARY_PRACTICE) == base.sha256_file(REFERENCE_PRACTICE),
        "all_scored_full_frozen_history": all(
            row["chart_availability"]["status"] == "FULL_FROZEN_HISTORY"
            for row in primary_payloads if row["mode"] == "SCORED"
        ),
        "gc_primary_reference_exact": gc_diagnostics["primary_reference_exact"],
        "leakage_audit_pass": leakage["pass"],
        "scored_outcomes_not_materialized": True,
        "calendar_2025_2026_not_opened": True,
        "no_acquisition_or_charge": True,
    }
    certification = {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_MATERIALIZATION_CERTIFICATION_1_1",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "PASS_PAST_ONLY_DISPLAY_MATERIALIZATION_AMENDMENT_A" if all(gates.values()) else "FAIL_DISPLAY_MATERIALIZATION_AMENDMENT_A",
        "case_count": len(primary_payloads), "practice_future_case_count": len(primary_practice),
        "primary_inputs_sha256": primary_inputs_hash, "reference_inputs_sha256": reference_inputs_hash,
        "primary_payload_sha256": base.sha256_file(PRIMARY_PAYLOAD), "reference_payload_sha256": base.sha256_file(REFERENCE_PAYLOAD),
        "primary_practice_sha256": base.sha256_file(PRIMARY_PRACTICE), "reference_practice_sha256": base.sha256_file(REFERENCE_PRACTICE),
        "gc_diagnostics": gc_diagnostics, "leakage_audit": leakage, "gates": gates,
        "outcomes_calculated": False, "scored_future_paths_opened": False,
        "calendar_2025_opened": False, "calendar_2026_opened": False,
        "acquisition_performed": False, "charge_usd": 0.0,
    }
    base.write_new_json(CERTIFICATION, certification)
    print(json.dumps({"verdict": certification["verdict"], "cases": len(primary_payloads), "gates": gates}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
