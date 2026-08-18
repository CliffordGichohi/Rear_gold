#!/usr/bin/env python3
"""Outcome-blind coverage amendment for the scored replay population."""

from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from freeze_gold_blind_discretionary_replay_v1_population import (
    ROOT,
    SEED,
    boundary_metadata_primary,
    boundary_metadata_reference,
    candidate_rows,
    canonical_hash,
    load_sessions_primary,
    load_sessions_reference,
    parse_timestamp,
    rank,
    sha256_file,
    write_new_json,
)


CASEBOOK = ROOT / "research_artifacts" / "gold_casebook_v01"
PRICE_BARS = CASEBOOK / "price_bars.jsonl.gz"
ORIGINAL_FREEZE = ROOT / "research_manifests" / "gold_blind_discretionary_replay_v1_population_freeze.json"
ORIGINAL_REGISTRY = ROOT / "research_artifacts" / "gold_blind_discretionary_replay_v1" / "population_registry.private.json"
AMENDMENT = ROOT / "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_COVERAGE_AMENDMENT_A.md"
FAILURE = ROOT / "research_artifacts" / "gold_blind_discretionary_replay_v1" / "materialization_attempt1_coverage_failure.json"
PRIVATE_V11 = ROOT / "research_artifacts" / "gold_blind_discretionary_replay_v1" / "population_registry_v1_1.private.json"
PUBLIC_V11 = ROOT / "research_artifacts" / "gold_blind_discretionary_replay_v1" / "population_registry_v1_1.public.json"
AUDIT = ROOT / "research_artifacts" / "gold_blind_discretionary_replay_v1" / "coverage_amendment_a_audit.json"
FREEZE_V11 = ROOT / "research_manifests" / "gold_blind_discretionary_replay_v1_population_freeze_v1_1.json"

EXPECTED = {"1w": 52, "1d": 120, "4h": 90, "1h": 120, "15m": 160, "5m": 180, "1m": 180}
WINDOW_DAYS = {"1d": 420, "4h": 60, "1h": 21, "15m": 14, "5m": 7, "1m": 7}
NUMBER = r"(?:null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
PATTERNS = {
    "available_at": re.compile(r'"available_at":"([^"]+)"'),
    "complete": re.compile(r'"complete":(true|false)'),
    "missing": re.compile(r'"missing_source_minutes":(\d+)'),
    "open_time": re.compile(r'"open_time":"([^"]+)"'),
    "source_count": re.compile(r'"source":\{[^}]*"source_count":(\d+)'),
    "timeframe": re.compile(r'"timeframe":"([^"]+)"'),
}


def verify_original_freeze() -> dict[str, Any]:
    freeze = json.loads(ORIGINAL_FREEZE.read_text(encoding="utf-8"))
    failures = []
    for item in freeze["sealed_files"]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            failures.append(item["path"])
    if failures:
        raise RuntimeError(f"Original population freeze differs: {failures}")
    return freeze


def parse_primary(line: str) -> dict[str, Any]:
    row = json.loads(line)
    return {
        "available_at": str(row["available_at"]), "complete": bool(row["complete"]),
        "missing": int(row.get("missing_source_minutes") or 0), "open_time": str(row["open_time"]),
        "source_count": int(row.get("source", {}).get("source_count") or 0), "timeframe": str(row["timeframe"]),
    }


def parse_reference(line: str) -> dict[str, Any]:
    matches = {key: pattern.search(line) for key, pattern in PATTERNS.items()}
    if any(value is None for value in matches.values()):
        raise RuntimeError("Reference coverage parser failed")
    return {
        "available_at": matches["available_at"].group(1), "complete": matches["complete"].group(1) == "true",
        "missing": int(matches["missing"].group(1)), "open_time": matches["open_time"].group(1),
        "source_count": int(matches["source_count"].group(1)), "timeframe": matches["timeframe"].group(1),
    }


def quote_valid_daily(row: dict[str, Any]) -> bool:
    total = row["source_count"] + row["missing"]
    return row["source_count"] >= 1000 and total > 0 and row["source_count"] / total >= 0.95


def coverage(candidates: list[dict[str, Any]], parser: Callable[[str], dict[str, Any]]) -> dict[str, dict[str, int]]:
    keys = [f"{row['session_date']}|{row['session_code']}" for row in candidates]
    by_key = {key: row for key, row in zip(keys, candidates)}
    entries = sorted((parse_timestamp(row["checkpoint_at"]), key) for key, row in by_key.items())
    cutoffs = [item[0] for item in entries]
    counts = {key: Counter() for key in keys}
    daily_weeks: dict[str, set[tuple[int, int]]] = {key: set() for key in keys}
    daily_week_days: dict[str, Counter[tuple[int, int]]] = {key: Counter() for key in keys}
    with gzip.open(PRICE_BARS, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = parser(line)
            timeframe = row["timeframe"]
            if timeframe not in WINDOW_DAYS:
                continue
            eligible = quote_valid_daily(row) if timeframe == "1d" else row["complete"]
            if not eligible:
                continue
            open_at, available = parse_timestamp(row["open_time"]), parse_timestamp(row["available_at"])
            left = bisect.bisect_left(cutoffs, available)
            right = bisect.bisect_right(cutoffs, open_at + timedelta(days=WINDOW_DAYS[timeframe]))
            for cutoff, key in entries[left:right]:
                if available <= cutoff and open_at < cutoff and open_at >= cutoff - timedelta(days=WINDOW_DAYS[timeframe]):
                    counts[key][timeframe] += 1
                    if timeframe == "1d":
                        iso = open_at.date().isocalendar()
                        cutoff_iso = cutoff.date().isocalendar()
                        week = (iso.year, iso.week)
                        if week < (cutoff_iso.year, cutoff_iso.week):
                            daily_week_days[key][week] += 1
    output = {}
    for key in keys:
        weekly = sum(value >= 4 for value in daily_week_days[key].values())
        output[key] = {**{timeframe: min(counts[key][timeframe], limit) for timeframe, limit in EXPECTED.items() if timeframe != "1w"}, "1w": min(weekly, 52)}
    return output


def eligible(counts: dict[str, int]) -> bool:
    return all(counts.get(timeframe, 0) >= required for timeframe, required in EXPECTED.items())


def select_amended(original: list[dict[str, Any]], candidates: list[dict[str, Any]], support: dict[str, dict[str, int]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected_dates = {row["session_date"] for row in original if row["mode"] == "PRACTICE"}
    output = [dict(row) for row in original if row["mode"] == "PRACTICE"]
    replacements = []
    for stratum in sorted({row["stratum"] for row in original if row["mode"] == "SCORED"}):
        originals = sorted((row for row in original if row["stratum"] == stratum), key=lambda row: row["mode_sequence"])
        _, year, session = stratum.split("|")
        pool = [row for row in candidates if row["session_date"].startswith(year) and row["session_code"] == session and eligible(support[f"{row['session_date']}|{row['session_code']}"])]
        pool.sort(key=lambda row: rank("GOLD_BLIND_REPLAY_V1_SELECT", "SCORED", year, session, row["session_date"]))
        for old in originals:
            old_key = f"{old['session_date']}|{old['session_code']}"
            if eligible(support[old_key]) and old["session_date"] not in selected_dates:
                chosen = {**old, "display_coverage": support[old_key], "population_version": "1.1"}
            else:
                candidate = next((row for row in pool if row["session_date"] not in selected_dates), None)
                if candidate is None:
                    raise RuntimeError(f"No eligible replacement remains for {stratum}")
                chosen = {
                    **candidate, "mode": "SCORED", "stratum": stratum,
                    "case_alias": old["case_alias"], "mode_sequence": old["mode_sequence"],
                    "global_sequence": old["global_sequence"], "display_coverage": support[f"{candidate['session_date']}|{candidate['session_code']}"],
                    "population_version": "1.1",
                }
                replacements.append({"case_alias": old["case_alias"], "stratum": stratum, "reason": "DISPLAY_HISTORY_COVERAGE", "selection_rank_preserved": True})
            selected_dates.add(chosen["session_date"])
            output.append(chosen)
    output.sort(key=lambda row: row["global_sequence"])
    return output, replacements


def main() -> int:
    for path in (PRIVATE_V11, PUBLIC_V11, AUDIT, FREEZE_V11):
        if path.exists():
            raise RuntimeError(f"Append-only target exists: {path.relative_to(ROOT)}")
    freeze = verify_original_freeze()
    original_payload = json.loads(ORIGINAL_REGISTRY.read_text(encoding="utf-8"))
    original = original_payload["cases"]
    primary_sessions, reference_sessions = load_sessions_primary(), load_sessions_reference()
    primary_boundaries, reference_boundaries = boundary_metadata_primary(), boundary_metadata_reference()
    if primary_sessions != reference_sessions or primary_boundaries != reference_boundaries:
        raise RuntimeError("Predecessor metadata reproduction failed")
    candidates = candidate_rows(primary_sessions, primary_boundaries)
    primary_coverage = coverage(candidates, parse_primary)
    reference_coverage = coverage(candidates, parse_reference)
    if primary_coverage != reference_coverage:
        raise RuntimeError("Independent coverage classifications differ")
    amended, replacements = select_amended(original, candidates, primary_coverage)
    scored = [row for row in amended if row["mode"] == "SCORED"]
    counts = Counter((row["session_date"][:4], row["session_code"]) for row in scored)
    gates = {
        "original_freeze_verified": freeze["population_sha256"] == canonical_hash(original),
        "coverage_independently_reproduced": primary_coverage == reference_coverage,
        "population_260": len(amended) == 260,
        "practice_unchanged": amended[:20] == original[:20],
        "scored_240": len(scored) == 240,
        "all_scored_full_display_coverage": all(eligible(row["display_coverage"]) for row in scored),
        "all_six_scored_strata_40": len(counts) == 6 and all(value == 40 for value in counts.values()),
        "unique_dates": len({row["session_date"] for row in amended}) == 260,
        "aliases_and_order_preserved": [(row["case_alias"], row["global_sequence"], row["session_code"]) for row in amended] == [(row["case_alias"], row["global_sequence"], row["session_code"]) for row in original],
        "no_outcome_used": True,
        "calendar_2025_2026_locked": all(row["checkpoint_at"] < "2025-01-01T00:00:00Z" for row in amended),
        "no_acquisition_or_charge": True,
    }
    private = {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_PRIVATE_POPULATION_1_1",
        "created_at": datetime.now(timezone.utc).isoformat(), "predecessor_population_sha256": freeze["population_sha256"],
        "selection_semantics": "ORIGINAL_OUTCOME_BLIND_ORDER_PLUS_COVERAGE_AMENDMENT_A",
        "case_count": len(amended), "replacement_count": len(replacements), "cases": amended,
        "population_sha256": canonical_hash(amended),
    }
    public_cases = [{
        "case_alias": row["case_alias"], "mode": row["mode"], "mode_sequence": row["mode_sequence"],
        "global_sequence": row["global_sequence"], "session_code": row["session_code"],
        "checkpoint_label": "SESSION_OPEN_PLUS_60_MINUTES",
    } for row in amended]
    public = {"version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_PUBLIC_POPULATION_1_1", "case_count": 260, "practice_count": 20, "scored_count": 240, "cases": public_cases, "public_population_sha256": canonical_hash(public_cases)}
    audit = {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_COVERAGE_AMENDMENT_A_AUDIT_1_0",
        "performed_at": datetime.now(timezone.utc).isoformat(), "verdict": "PASS_COVERAGE_AMENDMENT_A" if all(gates.values()) else "FAIL_COVERAGE_AMENDMENT_A",
        "replacement_count": len(replacements), "preserved_scored_count": 240 - len(replacements),
        "replacements": replacements, "gates": gates, "outcomes_accessed": False, "charge_usd": 0.0,
    }
    write_new_json(PRIVATE_V11, private)
    write_new_json(PUBLIC_V11, public)
    write_new_json(AUDIT, audit)
    if audit["verdict"] != "PASS_COVERAGE_AMENDMENT_A":
        raise RuntimeError("Coverage Amendment A failed")
    seal_paths = [AMENDMENT, FAILURE, Path(__file__), ORIGINAL_FREEZE, PRIVATE_V11, PUBLIC_V11, AUDIT]
    sealed = [{"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in seal_paths]
    write_new_json(FREEZE_V11, {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_POPULATION_FREEZE_1_1",
        "sealed_at": datetime.now(timezone.utc).isoformat(), "status": "SEALED_AMENDMENT_A_BEFORE_HUMAN_LABELING",
        "population_sha256": private["population_sha256"], "public_population_sha256": public["public_population_sha256"],
        "replacement_count": len(replacements), "sealed_files": sealed, "sealed_files_sha256": canonical_hash(sealed),
        "market_outcomes_opened": False, "human_decisions_collected": 0, "calendar_2025": "LOCKED", "calendar_2026": "LOCKED",
    })
    print(json.dumps({"verdict": audit["verdict"], "replacements": len(replacements), "gates": gates}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
