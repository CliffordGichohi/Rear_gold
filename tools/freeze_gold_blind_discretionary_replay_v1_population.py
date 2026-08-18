#!/usr/bin/env python3
"""Freeze the outcome-blind Gold discretionary replay population."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASEBOOK = ROOT / "research_artifacts" / "gold_casebook_v01"
SESSIONS = CASEBOOK / "sessions.jsonl.gz"
PRICE_BARS = CASEBOOK / "price_bars.jsonl.gz"
CASEBOOK_MANIFEST = CASEBOOK / "manifest.json"
GC_PRIMARY = ROOT / "research_artifacts" / "gc_microstructure_step5c_v01" / "primary_decision_features.parquet"
GC_REFERENCE = ROOT / "research_artifacts" / "gc_microstructure_step5c_v01" / "reference_decision_features.parquet"
CONTRACT = ROOT / "GOLD_BLIND_POINT_IN_TIME_DISCRETIONARY_REPLAY_EDGE_AUDIT_CONTRACT_V1.md"
PROTOCOL = ROOT / "research_manifests" / "gold_blind_discretionary_replay_v1_protocol.json"
PRIVATE_REGISTRY = ROOT / "research_artifacts" / "gold_blind_discretionary_replay_v1" / "population_registry.private.json"
PUBLIC_REGISTRY = ROOT / "research_artifacts" / "gold_blind_discretionary_replay_v1" / "population_registry.public.json"
READINESS = ROOT / "research_artifacts" / "gold_blind_discretionary_replay_v1" / "population_readiness.json"
FREEZE = ROOT / "research_manifests" / "gold_blind_discretionary_replay_v1_population_freeze.json"
SEED = 20260813

TIMEFRAME_PATTERN = re.compile(r'"timeframe":"([^"]+)"')
CLOSE_PATTERN = re.compile(r'"close_time":"([^"]+)"')
AVAILABLE_PATTERN = re.compile(r'"available_at":"([^"]+)"')
COMPLETE_PATTERN = re.compile(r'"complete":(true|false)')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_new_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def rank(label: str, *parts: str) -> str:
    return hashlib.sha256("|".join((label, *parts, str(SEED))).encode("utf-8")).hexdigest()


def verify_casebook() -> list[dict[str, Any]]:
    manifest = json.loads(CASEBOOK_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("casebook_version") != "GOLD_CASEBOOK_V0_1":
        raise RuntimeError("Unexpected casebook version")
    if manifest.get("contract", {}).get("holdout_loaded") is not False:
        raise RuntimeError("Casebook holdout boundary is not sealed")
    checks = []
    for item in manifest["artifacts"]:
        path = CASEBOOK / item["path"]
        actual = sha256_file(path)
        check = {
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "expected_sha256": item["sha256"],
            "actual_sha256": actual,
            "verified": actual == item["sha256"] and path.stat().st_size == item["bytes"],
        }
        checks.append(check)
    if not all(item["verified"] for item in checks):
        raise RuntimeError("A sealed casebook artifact failed hash verification")
    return checks


def load_sessions_primary() -> dict[str, dict[str, dict[str, Any]]]:
    by_day: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    with gzip.open(SESSIONS, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("data_quality", {}).get("status") != "COMPLETE":
                continue
            code = row.get("session_code")
            if code not in {"LONDON", "NEW_YORK"}:
                continue
            by_day[str(row["session_date"])][code] = {
                "session_date": str(row["session_date"]),
                "session_code": code,
                "session_timezone": str(row["session_timezone"]),
                "decision_at": iso(parse_timestamp(str(row["decision_at"]))),
                "session_end": iso(parse_timestamp(str(row["observation_end"]))),
                "session_record_id": str(row["record_id"]),
                "session_record_hash": str(row["record_hash"]),
            }
    return dict(by_day)


def load_sessions_reference() -> dict[str, dict[str, dict[str, Any]]]:
    """Independent extraction through a second source traversal and canonical tuples."""
    records: list[tuple[str, str, str, str, str, str, str]] = []
    with gzip.GzipFile(filename=SESSIONS, mode="rb") as binary:
        for raw in binary:
            row = json.loads(raw.decode("utf-8"))
            if row["data_quality"]["status"] == "COMPLETE" and row["session_code"] in {"LONDON", "NEW_YORK"}:
                records.append(
                    (
                        str(row["session_date"]), str(row["session_code"]), str(row["session_timezone"]),
                        iso(parse_timestamp(str(row["decision_at"]))), iso(parse_timestamp(str(row["observation_end"]))),
                        str(row["record_id"]), str(row["record_hash"]),
                    )
                )
    output: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for day, code, zone, decision, end, record_id, record_hash in sorted(records):
        output[day][code] = {
            "session_date": day,
            "session_code": code,
            "session_timezone": zone,
            "decision_at": decision,
            "session_end": end,
            "session_record_id": record_id,
            "session_record_hash": record_hash,
        }
    return dict(output)


def boundary_metadata_primary() -> set[str]:
    boundaries: set[str] = set()
    with gzip.open(PRICE_BARS, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("timeframe") != "1m" or row.get("complete") is not True:
                continue
            close = parse_timestamp(str(row["close_time"]))
            available = parse_timestamp(str(row["available_at"]))
            if available <= close:
                boundaries.add(iso(close))
    return boundaries


def boundary_metadata_reference() -> set[str]:
    boundaries: set[str] = set()
    with gzip.open(PRICE_BARS, "rt", encoding="utf-8") as handle:
        for line in handle:
            timeframe = TIMEFRAME_PATTERN.search(line)
            complete = COMPLETE_PATTERN.search(line)
            if timeframe is None or timeframe.group(1) != "1m" or complete is None or complete.group(1) != "true":
                continue
            close_match, available_match = CLOSE_PATTERN.search(line), AVAILABLE_PATTERN.search(line)
            if close_match is None or available_match is None:
                raise RuntimeError("Reference metadata parser could not extract required fields")
            close = parse_timestamp(close_match.group(1))
            available = parse_timestamp(available_match.group(1))
            if available <= close:
                boundaries.add(iso(close))
    return boundaries


def assigned_session(day: str) -> str:
    digest = hashlib.sha256(f"GOLD_BLIND_REPLAY_V1_ASSIGN|{day}|{SEED}".encode("utf-8")).digest()
    return "LONDON" if digest[-1] % 2 == 0 else "NEW_YORK"


def candidate_rows(
    sessions: dict[str, dict[str, dict[str, Any]]], boundaries: set[str]
) -> list[dict[str, Any]]:
    output = []
    for day in sorted(sessions):
        if set(sessions[day]) != {"LONDON", "NEW_YORK"}:
            continue
        code = assigned_session(day)
        source = sessions[day][code]
        checkpoint = parse_timestamp(source["decision_at"]) + timedelta(minutes=60)
        if iso(checkpoint) not in boundaries:
            continue
        output.append({**source, "checkpoint_at": iso(checkpoint)})
    return output


def select_population(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    strata: list[tuple[str, str, str, str, int]] = [
        ("PRACTICE", "2021", "2021-08-01", "2022-01-01", 10),
    ]
    for year in ("2022", "2023", "2024"):
        strata.append(("SCORED", year, f"{year}-01-01", f"{int(year) + 1}-01-01", 40))
    for mode, year, start, end, count in strata:
        for session in ("LONDON", "NEW_YORK"):
            rows = [row for row in candidates if start <= row["session_date"] < end and row["session_code"] == session]
            rows.sort(key=lambda row: rank("GOLD_BLIND_REPLAY_V1_SELECT", mode, year, session, row["session_date"]))
            if len(rows) < count:
                raise RuntimeError(f"Insufficient outcome-blind candidates for {mode}/{year}/{session}: {len(rows)}")
            selected.extend({**row, "mode": mode, "stratum": f"{mode}|{year}|{session}"} for row in rows[:count])

    if len({row["session_date"] for row in selected}) != len(selected):
        raise RuntimeError("Population violates unique-date gate")
    ordered: list[dict[str, Any]] = []
    for mode, prefix in (("PRACTICE", "P"), ("SCORED", "S")):
        rows = [row for row in selected if row["mode"] == mode]
        rows.sort(key=lambda row: rank("GOLD_BLIND_REPLAY_V1_PRESENT", mode, row["session_code"], row["session_date"]))
        for index, row in enumerate(rows, start=1):
            ordered.append({
                **row,
                "case_alias": f"{prefix}-{index:03d}",
                "mode_sequence": index,
                "global_sequence": index if mode == "PRACTICE" else 20 + index,
            })
    return ordered


def main() -> int:
    for path in (PRIVATE_REGISTRY, PUBLIC_REGISTRY, READINESS, FREEZE):
        if path.exists():
            raise RuntimeError(f"Append-only target already exists: {path.relative_to(ROOT)}")
    for path in (CONTRACT, PROTOCOL, CASEBOOK_MANIFEST, SESSIONS, PRICE_BARS, GC_PRIMARY, GC_REFERENCE):
        if not path.is_file():
            raise RuntimeError(f"Required source missing: {path.relative_to(ROOT)}")

    source_checks = verify_casebook()
    primary_sessions, reference_sessions = load_sessions_primary(), load_sessions_reference()
    if primary_sessions != reference_sessions:
        raise RuntimeError("Primary/reference session metadata differs")
    primary_boundaries, reference_boundaries = boundary_metadata_primary(), boundary_metadata_reference()
    if primary_boundaries != reference_boundaries:
        raise RuntimeError("Primary/reference M1 boundary metadata differs")
    candidates = candidate_rows(primary_sessions, primary_boundaries)
    population = select_population(candidates)
    counts = Counter((row["mode"], row["session_code"]) for row in population)
    scored_strata = Counter(row["stratum"] for row in population if row["mode"] == "SCORED")
    gates = {
        "casebook_hashes_verified": all(item["verified"] for item in source_checks),
        "session_metadata_reproduced": primary_sessions == reference_sessions,
        "m1_boundary_metadata_reproduced": primary_boundaries == reference_boundaries,
        "population_total_260": len(population) == 260,
        "practice_20_balanced": counts[("PRACTICE", "LONDON")] == 10 and counts[("PRACTICE", "NEW_YORK")] == 10,
        "scored_240_balanced": counts[("SCORED", "LONDON")] == 120 and counts[("SCORED", "NEW_YORK")] == 120,
        "scored_year_session_40": len(scored_strata) == 6 and all(value == 40 for value in scored_strata.values()),
        "unique_dates": len({row["session_date"] for row in population}) == 260,
        "all_checkpoints_have_complete_m1_boundary": all(row["checkpoint_at"] in primary_boundaries for row in population),
        "all_source_times_pre_2025": all(row["checkpoint_at"] < "2025-01-01T00:00:00Z" for row in population),
        "gc_primary_reference_byte_identical": sha256_file(GC_PRIMARY) == sha256_file(GC_REFERENCE),
        "no_market_outcome_used_for_selection": True,
        "no_acquisition_or_charge": True,
    }
    private_payload = {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_PRIVATE_POPULATION_1_0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selection_semantics": "TIMESTAMP_AND_SESSION_METADATA_ONLY",
        "case_count": len(population),
        "cases": population,
        "population_sha256": canonical_hash(population),
    }
    public_cases = [{
        "case_alias": row["case_alias"],
        "mode": row["mode"],
        "mode_sequence": row["mode_sequence"],
        "global_sequence": row["global_sequence"],
        "session_code": row["session_code"],
        "checkpoint_label": "SESSION_OPEN_PLUS_60_MINUTES",
    } for row in population]
    public_payload = {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_PUBLIC_POPULATION_1_0",
        "case_count": len(public_cases),
        "practice_count": 20,
        "scored_count": 240,
        "cases": public_cases,
        "public_population_sha256": canonical_hash(public_cases),
    }
    readiness = {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_POPULATION_READINESS_1_0",
        "performed_at": datetime.now(timezone.utc).isoformat(),
        "market_values_inspected_or_used": False,
        "outcomes_inspected_or_used": False,
        "price_metadata_records": len(primary_boundaries),
        "complete_session_dates": len([day for day, rows in primary_sessions.items() if len(rows) == 2]),
        "eligible_assigned_candidates": len(candidates),
        "counts": {f"{mode}|{session}": value for (mode, session), value in sorted(counts.items())},
        "scored_strata": dict(sorted(scored_strata.items())),
        "source_checks": source_checks,
        "gates": gates,
        "verdict": "PASS_POPULATION_READINESS" if all(gates.values()) else "FAIL_POPULATION_READINESS",
    }
    write_new_json(PRIVATE_REGISTRY, private_payload)
    write_new_json(PUBLIC_REGISTRY, public_payload)
    write_new_json(READINESS, readiness)
    if readiness["verdict"] != "PASS_POPULATION_READINESS":
        raise RuntimeError("Population readiness failed")

    seal_paths = [CONTRACT, PROTOCOL, Path(__file__), CASEBOOK_MANIFEST, PRIVATE_REGISTRY, PUBLIC_REGISTRY, READINESS, GC_PRIMARY, GC_REFERENCE]
    sealed_files = [{
        "path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)
    } for path in seal_paths]
    freeze = {
        "version": "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_POPULATION_FREEZE_1_0",
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "status": "SEALED_BEFORE_CASE_VALUE_MATERIALIZATION",
        "population_sha256": private_payload["population_sha256"],
        "public_population_sha256": public_payload["public_population_sha256"],
        "sealed_files": sealed_files,
        "sealed_files_sha256": canonical_hash(sealed_files),
        "market_values_opened": False,
        "outcomes_opened": False,
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    write_new_json(FREEZE, freeze)
    print(json.dumps({"verdict": readiness["verdict"], "population": len(population), "gates": gates}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
