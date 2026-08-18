#!/usr/bin/env python3
"""Run sealed Multi-Asset Session Behaviour V1 Milestones 2 and 3.

This runner may access only the frozen 2021-2024 development sources.  It
materializes a descriptive atlas first, independently reproduces it, then
applies the single non-optimized four-stage monetization-capacity framework.
It does not discover or select a trading rule and never reads 2025/2026.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from tools import msbam_v1_m2_m3_engine as engine
except ModuleNotFoundError:  # Direct ``python tools/<runner>.py`` invocation.
    import msbam_v1_m2_m3_engine as engine


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
R2_DIR = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1_r2"
M2_DIR = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m2"
M3_DIR = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m3"
R2_SEAL = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_m1_r2_seal.json"
R2_PRIMARY = R2_DIR / "recertification_primary.json"
R2_REFERENCE = R2_DIR / "recertification_reference.json"
SOURCE_CERT = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m2/certification.json"
M2_FREEZE = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_m2_preoutcome_freeze.json"
M3_FREEZE = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_m3_feasibility_freeze.json"
M2_REPORT = ROOT / "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_AND_MONETIZATION_V1_MILESTONE_2.md"
M3_REPORT = ROOT / "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_AND_MONETIZATION_V1_MILESTONE_3.md"
M2_SEAL = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_m2_seal.json"
M3_SEAL = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_m3_seal.json"
UTC = timezone.utc
SYMBOLS = tuple(engine.INSTRUMENTS)
EXPECTED_SELECTED_CASES = 10_388


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(ROOT.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_text_exclusive(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value.rstrip() + "\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def verify_record(record: Mapping[str, Any]) -> None:
    path = ROOT / str(record["path"])
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size != int(record["bytes"]) or sha256_file(path) != str(record["sha256"]):
        raise ValueError(f"Sealed artifact changed: {record['path']}")


def verify_predecessors_and_freezes() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    r2_seal = load(R2_SEAL)
    if r2_seal.get("verdict") != "PASS_M1_R2_BRANCH_READY" or not r2_seal.get("branch_ready"):
        raise ValueError("Coverage Amendment A branch gate is not intact")
    for item in r2_seal.get("artifacts", []):
        verify_record(item)
    for path, status in (
        (M2_FREEZE, "SEALED_BEFORE_M2_MARKET_VALUE_ACCESS"),
        (M3_FREEZE, "SEALED_BEFORE_M3_HYPOTHETICAL_CAPTURE_CALCULATION"),
    ):
        freeze = load(path)
        if freeze.get("status") != status:
            raise ValueError(f"Invalid freeze status: {path.name}")
        for item in freeze.get("bindings", {}).values():
            verify_record(item)
        for item in freeze.get("source_bindings", []):
            verify_record(item)
        controls = freeze.get("controls", {})
        if controls.get("calendar_2025_values_accessed") or controls.get("calendar_2026_values_accessed"):
            raise ValueError("Forward locks are not intact")
        if float(controls.get("charge_usd", 0.0)) != 0.0:
            raise ValueError("No-charge control failed")
    return r2_seal, load(M2_FREEZE), load(M3_FREEZE)


def source_inventory() -> dict[str, list[Path]]:
    certification = load(SOURCE_CERT)
    inventory: dict[str, list[Path]] = {}
    for item in certification.get("instrument_certifications", []):
        symbol = str(item.get("mt5_symbol"))
        if symbol not in SYMBOLS:
            continue
        if item.get("classification") != "PRESENT_AND_ADEQUATE":
            raise ValueError(f"Source no longer adequate: {symbol}")
        sources = item.get("coverage", {}).get("source_files", [])
        paths: list[Path] = []
        for source in sources:
            verify_record(source)
            path = ROOT / str(source["path"])
            if "2025" in path.name or "2026" in path.name:
                raise ValueError(f"Forward-period filename selected: {path.name}")
            paths.append(path)
        if not paths:
            raise ValueError(f"No frozen source files for {symbol}")
        inventory[symbol] = paths
    if set(inventory) != set(SYMBOLS):
        raise ValueError(f"Expected exactly six non-gold sources, got {sorted(inventory)}")
    return inventory


def select_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    primary = load(R2_PRIMARY)
    reference = load(R2_REFERENCE)
    result = load(R2_DIR / "recertification.json")
    if not primary.get("branch_pass") or not reference.get("branch_pass"):
        raise ValueError("R2 independent branch PASS is not intact")
    passing_units = set(result["passing_units"])

    def eligible(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        rows = [
            dict(row) for row in payload["case_rows"]
            if bool(row["eligible_for_milestone_2"])
            and f"{row['instrument']}|{row['session_code']}" in passing_units
        ]
        return sorted(rows, key=lambda row: (row["session_date_local"], row["instrument"], row["session_code"], row["case_id"]))

    primary_rows, reference_rows = eligible(primary), eligible(reference)
    if engine.canonical_hash(primary_rows) != engine.canonical_hash(reference_rows):
        raise ValueError("R2 primary/reference selected populations differ")
    if len(primary_rows) != EXPECTED_SELECTED_CASES:
        raise ValueError(f"Expected {EXPECTED_SELECTED_CASES} selected cases, found {len(primary_rows)}")
    if any(str(row["instrument"]) == "XAUUSD" for row in primary_rows):
        raise ValueError("Held gold branch leaked into multi-asset study")
    if any(str(row["session_date_local"]) >= "2025-01-01" for row in primary_rows):
        raise ValueError("Forward-period case leaked into development")
    counts = Counter(f"{row['instrument']}|{row['session_code']}" for row in primary_rows)
    if set(counts) != passing_units:
        raise ValueError("Selected unit set differs from Coverage Amendment A PASS units")
    return primary_rows, {"passing_units": sorted(passing_units), "unit_case_counts": dict(sorted(counts.items()))}


def materialize_m2(
    implementation: str,
    cases: Sequence[Mapping[str, Any]],
    inventory: Mapping[str, Sequence[Path]],
    output_path: Path,
    atlas_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    legacy = engine.load_legacy()
    engine.patch_sources(legacy, inventory)
    macro_book = legacy.MacroBook(implementation)
    previous = engine.prior_case_map(cases)
    rows: list[dict[str, Any]] = []
    source_diagnostics: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        series, diagnostic = legacy.load_price_series(symbol, implementation)
        bundle = legacy.build_technical_bundle(series, implementation)
        source_diagnostics.append({
            "symbol": symbol,
            "source_files": diagnostic["source_files"],
            "canonical_rows": diagnostic["canonical_rows"],
            "first_minute": diagnostic["first_minute"],
            "last_minute": diagnostic["last_minute"],
            "source_inventory_hash": diagnostic["source_inventory_hash"],
        })
        symbol_cases = [case for case in cases if str(case["instrument"]) == symbol]
        for case in symbol_cases:
            rows.append(engine.materialize_case(legacy, bundle, macro_book, case, previous[str(case["case_id"])]))
        del bundle, series
        gc.collect()
    rows.sort(key=lambda row: (row["session_date_local"], row["instrument"], row["session_code"], row["case_id"]))
    rows = engine.normalize_payload(rows)
    atlas = engine.normalize_payload(engine.atlas(rows))
    write_json_exclusive(output_path, {"rows": rows})
    write_json_exclusive(atlas_path, atlas)
    diagnostics = {
        "selected_case_count": len(cases), "materialized_case_count": len(rows),
        "valid_case_count": sum(row["materialization_status"] == "VALID" for row in rows),
        "unavailable_case_count": sum(row["materialization_status"] != "VALID" for row in rows),
        "source_diagnostics": source_diagnostics,
        "case_semantic_checksum": engine.canonical_hash(rows),
        "atlas_semantic_checksum": engine.canonical_hash(atlas),
    }
    return diagnostics, atlas


def annual_capacity(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    months = {2021: 5, 2022: 12, 2023: 12, 2024: 12}
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(str(row["session_date"])[:4])].append(row)
    output: list[dict[str, Any]] = []
    for year, values in sorted(grouped.items()):
        accepted = [row for row in values if row.get("portfolio_accepted")]
        output.append({
            "year": year, "case_count": len(values), "accepted_count": len(accepted),
            "stage1_r_per_month": engine.rounded(sum(float(row["stage1_full_path_ceiling_r"]) for row in values) / months[year]),
            "stage2_r_per_month": engine.rounded(sum(float(row["stage2_observable_ceiling_r"]) for row in values) / months[year]),
            "stage3_r_per_month": engine.rounded(sum(float(row["stage3_stop_feasible_gross_r"]) for row in values) / months[year]),
            "stage4_net_r_per_month": engine.rounded(sum(float(row["stage4_portfolio_net_r"]) for row in values) / months[year]),
            "stage4_dollars_per_month": engine.rounded(sum(float(row["net_pnl_usd"]) for row in accepted) / months[year]),
        })
    return output


def capacity_sources(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("portfolio_accepted"):
            grouped[(str(row["instrument"]), str(row["session"]), str(row["archetype"]))].append(row)
    output: list[dict[str, Any]] = []
    for key, values in grouped.items():
        net_r = sum(float(row["stage4_portfolio_net_r"]) for row in values)
        output.append({
            "instrument": key[0], "session": key[1], "archetype": key[2],
            "accepted_count": len(values), "net_r_per_month": engine.rounded(net_r / engine.MONTHS),
            "dollars_per_month": engine.rounded(sum(float(row["net_pnl_usd"]) for row in values) / engine.MONTHS),
        })
    return sorted(output, key=lambda row: (-float(row["net_r_per_month"]), row["instrument"], row["session"], row["archetype"]))


def calculate_m3(
    implementation: str,
    case_matrix_path: Path,
    inventory: Mapping[str, Sequence[Path]],
    output_path: Path,
) -> dict[str, Any]:
    case_rows = [row for row in load(case_matrix_path)["rows"] if row["materialization_status"] == "VALID"]
    legacy = engine.load_legacy()
    engine.patch_sources(legacy, inventory)
    raw_rows: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        series, _ = legacy.load_price_series(symbol, implementation)
        for case in (row for row in case_rows if str(row["instrument"]) == symbol):
            for timeframe in engine.TIMEFRAMES:
                raw_rows.append(engine.feasibility_row(series, case, timeframe))
        del series
        gc.collect()
    raw_rows = engine.normalize_payload(raw_rows)
    track_rows: list[dict[str, Any]] = []
    for timeframe in engine.TIMEFRAMES:
        subset = [row for row in raw_rows if row["timeframe"] == timeframe]
        track_rows.extend(engine.apply_portfolio(subset))
    track_rows.sort(key=lambda row: (row["session_date"], row["instrument"], row["session"], row["timeframe"], row["case_id"]))
    combined_rows = engine.apply_portfolio(engine.earliest_track_per_case(raw_rows))
    combined_rows.sort(key=lambda row: (row["session_date"], row["instrument"], row["session"], row["case_id"]))
    summaries = {
        timeframe: engine.summarize_feasibility([row for row in track_rows if row["timeframe"] == timeframe], timeframe)
        for timeframe in engine.TIMEFRAMES
    }
    summaries["COMBINED_EARLIEST"] = engine.summarize_feasibility(combined_rows, "COMBINED_EARLIEST")
    payload = engine.normalize_payload({
        "track_rows": track_rows,
        "combined_rows": combined_rows,
        "summaries": summaries,
        "strata": engine.strata_feasibility(track_rows) + engine.strata_feasibility(combined_rows),
        "annual_combined": annual_capacity(combined_rows),
        "capacity_sources": capacity_sources(combined_rows),
    })
    payload["semantic_checksum"] = engine.canonical_hash(payload)
    write_json_exclusive(output_path, payload)
    return payload


def m2_report(result: Mapping[str, Any], atlas: Mapping[str, Any]) -> str:
    counts = ", ".join(f"{name}: {count}" for name, count in atlas["archetype_counts"].items())
    return f"""# Multi-Asset Session Behaviour V1 — Milestone 2

## Verdict

**{result['verdict']}**

- Frozen eligible population: **{result['selected_case_count']:,}** session identities across 12 passing units.
- Valid materialized paths: **{result['valid_case_count']:,}**.
- Retained technical unavailability: **{result['unavailable_case_count']:,}**.
- Independent reproduction: **{str(result['independent_reproduction']).lower()}**.
- XAUUSD: excluded; held policy unchanged.
- 2025/2026 accessed: no. Charge: $0.

Archetype counts: {counts}.

The atlas is descriptive. It contains no entry rule, candidate, edge claim, or PnL calculation.
"""


def m3_report(result: Mapping[str, Any]) -> str:
    combined = result["summaries"]["COMBINED_EARLIEST"]
    lines = [
        "# Multi-Asset Session Behaviour V1 — Milestone 3",
        "", "## Target-feasibility verdict", "",
        f"**{result['verdict']}**", "",
        f"- Full-path hindsight ceiling: **{combined['stage1_r_per_month']:.3f} R/month**.",
        f"- First-observable ceiling: **{combined['stage2_r_per_month']:.3f} R/month**.",
        f"- Stop-feasible gross result: **{combined['stage3_r_per_month']:.3f} R/month**.",
        f"- Non-overlapping, cost-adjusted portfolio result: **{combined['stage4_net_r_per_month']:.3f} R/month**.",
        f"- Frozen $10,000-account result: **${combined['stage4_dollars_per_month']:.2f}/month**.",
        f"- Accepted opportunities: **{combined['accepted_trades_per_month']:.2f}/month**; maximum drawdown **{combined['max_drawdown_r']:.2f} R**.",
        "", "## Retention waterfall", "",
        f"- Hindsight → observable loss: {combined['stage1_to_stage2_loss_r_per_month']:.3f} R/month.",
        f"- Observable → stop-feasible loss: {combined['stage2_to_stage3_loss_r_per_month']:.3f} R/month.",
        f"- Stop-feasible → portfolio/cost loss: {combined['stage3_to_stage4_loss_r_per_month']:.3f} R/month.",
        "", "This is a capacity falsification result, not a strategy or edge claim. XAUUSD remained excluded, no paid data were acquired, and 2025/2026 remained locked.",
    ]
    return "\n".join(lines)


def seal(path: Path, version: str, verdict: str, artifacts: Sequence[Path], extra: Mapping[str, Any]) -> None:
    records = [file_record(item) for item in artifacts]
    payload = {
        "version": version, "status": "SEALED_COMPLETE", "verdict": verdict,
        "sealed_at_utc": utc_now(), "artifacts": records,
        "artifact_set_hash": engine.canonical_hash(records),
        "controls": {"calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "charge_usd": 0.0},
        **extra,
    }
    write_json_exclusive(path, payload)


def main() -> int:
    r2_seal, _, _ = verify_predecessors_and_freezes()
    inventory = source_inventory()
    cases, population = select_cases()

    m2_primary = M2_DIR / "primary_case_matrix.json"
    m2_reference = M2_DIR / "reference_case_matrix.json"
    atlas_primary = M2_DIR / "primary_atlas.json"
    atlas_reference = M2_DIR / "reference_atlas.json"
    primary_diag, primary_atlas = materialize_m2("primary", cases, inventory, m2_primary, atlas_primary)
    reference_diag, reference_atlas = materialize_m2("reference", cases, inventory, m2_reference, atlas_reference)
    reproduced = (
        sha256_file(m2_primary) == sha256_file(m2_reference)
        and sha256_file(atlas_primary) == sha256_file(atlas_reference)
        and primary_diag == reference_diag
        and primary_atlas == reference_atlas
    )
    m2_verdict = "PASS_M2_BEHAVIOURAL_ATLAS_REPRODUCED" if reproduced else "FAIL_M2_INDEPENDENT_REPRODUCTION"
    m2_result = {
        "version": "MSBAM_V1_M2_RESULT_1_0", "verdict": m2_verdict,
        "completed_at_utc": utc_now(), "selected_case_count": len(cases),
        "valid_case_count": primary_diag["valid_case_count"],
        "unavailable_case_count": primary_diag["unavailable_case_count"],
        "population": population, "independent_reproduction": reproduced,
        "primary_case_checksum": primary_diag["case_semantic_checksum"],
        "reference_case_checksum": reference_diag["case_semantic_checksum"],
        "atlas_checksum": primary_diag["atlas_semantic_checksum"],
        "controls": {"2025_values_accessed": False, "2026_values_accessed": False, "charge_usd": 0.0, "strategy_or_candidate_created": False},
    }
    m2_result_path = M2_DIR / "result.json"
    m2_validation_path = M2_DIR / "validation.json"
    write_json_exclusive(m2_result_path, m2_result)
    write_json_exclusive(m2_validation_path, {"primary": primary_diag, "reference": reference_diag, "exact_reproduction": reproduced})
    write_text_exclusive(M2_REPORT, m2_report(m2_result, primary_atlas))
    seal(
        M2_SEAL, "MSBAM_V1_M2_SEAL_1_0", m2_verdict,
        [M2_FREEZE, m2_primary, m2_reference, atlas_primary, atlas_reference, m2_result_path, m2_validation_path, M2_REPORT, Path(__file__).resolve(), ROOT / "tools/msbam_v1_m2_m3_engine.py"],
        {"coverage_r2_seal_sha256": sha256_file(R2_SEAL), "independent_reproduction": reproduced},
    )
    if not reproduced:
        print(json.dumps({"milestone_2": m2_verdict, "milestone_3": "NOT_RUN"}, indent=2))
        return 2

    m3_primary = M3_DIR / "primary_feasibility.json"
    m3_reference = M3_DIR / "reference_feasibility.json"
    primary_m3 = calculate_m3("primary", m2_primary, inventory, m3_primary)
    del primary_m3
    gc.collect()
    reference_m3 = calculate_m3("reference", m2_reference, inventory, m3_reference)
    reproduced_m3 = sha256_file(m3_primary) == sha256_file(m3_reference)
    if not reproduced_m3:
        m3_verdict = "FAIL_M3_INDEPENDENT_REPRODUCTION"
        result_payload: dict[str, Any] = {"summaries": reference_m3["summaries"], "capacity_sources": reference_m3["capacity_sources"]}
    else:
        combined = reference_m3["summaries"]["COMBINED_EARLIEST"]
        capacity = float(combined["stage4_net_r_per_month"])
        m3_verdict = "PASS_M3_TARGET_CAPACITY_ABOVE_10R_NO_EDGE_CLAIM" if capacity >= 10.0 else "FAIL_M3_CURRENT_UNIVERSE_BELOW_10R_CAPACITY"
        result_payload = {
            "summaries": reference_m3["summaries"], "strata": reference_m3["strata"],
            "annual_combined": reference_m3["annual_combined"],
            "capacity_sources": reference_m3["capacity_sources"] if capacity >= 10.0 else [],
        }
    m3_result = {
        "version": "MSBAM_V1_M3_RESULT_1_0", "verdict": m3_verdict,
        "completed_at_utc": utc_now(), "independent_reproduction": reproduced_m3,
        "target_r_per_month": 10.0, "edge_claim": False,
        "framework_is_constant_nonoptimized": True,
        "held_gold_policy_status": "EXCLUDED_UNCHANGED",
        "controls": {"2025_values_accessed": False, "2026_values_accessed": False, "charge_usd": 0.0, "candidate_created": False, "entry_optimization": False},
        **result_payload,
    }
    m3_result_path = M3_DIR / "result.json"
    m3_validation_path = M3_DIR / "validation.json"
    write_json_exclusive(m3_result_path, m3_result)
    write_json_exclusive(m3_validation_path, {
        "primary_sha256": sha256_file(m3_primary), "reference_sha256": sha256_file(m3_reference),
        "exact_byte_reproduction": reproduced_m3, "predecessor_m2_verdict": m2_verdict,
    })
    write_text_exclusive(M3_REPORT, m3_report(m3_result))
    seal(
        M3_SEAL, "MSBAM_V1_M3_SEAL_1_0", m3_verdict,
        [M3_FREEZE, M2_SEAL, m3_primary, m3_reference, m3_result_path, m3_validation_path, M3_REPORT, Path(__file__).resolve(), ROOT / "tools/msbam_v1_m2_m3_engine.py"],
        {"independent_reproduction": reproduced_m3, "edge_claim": False, "gold_excluded": True},
    )
    print(json.dumps({
        "milestone_2": m2_verdict, "milestone_3": m3_verdict,
        "selected_cases": len(cases), "valid_cases": primary_diag["valid_case_count"],
        "combined": m3_result["summaries"]["COMBINED_EARLIEST"],
        "m3_seal_sha256": sha256_file(M3_SEAL),
    }, indent=2, sort_keys=True))
    return 0 if reproduced_m3 else 3


if __name__ == "__main__":
    raise SystemExit(main())
