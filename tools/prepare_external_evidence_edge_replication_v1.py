#!/usr/bin/env python3
"""Outcome-blind source-readiness audit and pre-outcome seal for EER V1."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")
SYMBOLS = ("US500", "USTEC", "XTIUSD")
REQUIRED_CLOCKS = ("09:59", "14:59", "15:29", "15:59")
CERTIFICATION = Path("research_artifacts/multi_asset_macro_session_portfolio_v1_m2/certification.json")
CATALOG = Path("research_manifests/external_evidence_edge_replication_v1_evidence_catalog.json")
DEDUP = Path("research_manifests/external_evidence_edge_replication_v1_deduplication_matrix.json")
PROTOCOL = Path("research_manifests/external_evidence_edge_replication_v1_protocol.json")
INVENTORY = Path("research_manifests/external_evidence_edge_replication_v1_repository_strategy_artifact_inventory.json")
READINESS = Path("research_artifacts/external_evidence_edge_replication_v1_preoutcome/readiness.json")
FREEZE = Path("research_manifests/external_evidence_edge_replication_v1_preoutcome_freeze.json")
STATIC_SEAL_FILES = (
    Path("EXTERNAL_EVIDENCE_EDGE_REPLICATION_AND_TRANSFER_CONTRACT_V1.md"),
    Path("tools/external_evidence_replication_v1_engine.py"),
    Path("tools/prepare_external_evidence_edge_replication_v1.py"),
    Path("tools/run_external_evidence_edge_replication_v1.py"),
    Path("tests/test_external_evidence_replication_v1_engine.py"),
    CATALOG,
    DEDUP,
    PROTOCOL,
    CERTIFICATION,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_new_json(relative: Path, value: Any) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)


def source_registry() -> dict[str, list[dict[str, Any]]]:
    certification = json.loads((ROOT / CERTIFICATION).read_text(encoding="utf-8"))
    if certification.get("verdict") != "PASS_MILESTONE_2_ALL_SEVEN_INSTRUMENTS_SOURCE_CERTIFIED":
        raise RuntimeError("Required predecessor source certification is not PASS")
    output: dict[str, list[dict[str, Any]]] = {}
    for item in certification["instrument_certifications"]:
        symbol = item.get("mt5_symbol")
        if symbol in SYMBOLS:
            if item.get("classification") != "PRESENT_AND_ADEQUATE":
                raise RuntimeError(f"{symbol} predecessor source is not adequate")
            output[symbol] = list(item["coverage"]["source_files"])
    if set(output) != set(SYMBOLS):
        raise RuntimeError(f"Missing source registry symbol: {set(SYMBOLS) - set(output)}")
    return output


def verify_sources(registry: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        for item in registry[symbol]:
            relative = Path(item["path"])
            path = ROOT / relative
            actual_size = path.stat().st_size
            actual_hash = sha256_file(path)
            verified = actual_size == int(item["bytes"]) and actual_hash == item["sha256"]
            checks.append(
                {
                    "symbol": symbol,
                    "path": relative.as_posix(),
                    "expected_bytes": int(item["bytes"]),
                    "actual_bytes": actual_size,
                    "expected_sha256": item["sha256"],
                    "actual_sha256": actual_hash,
                    "verified": verified,
                }
            )
    if not all(item["verified"] for item in checks):
        raise RuntimeError("At least one sealed MT5 source differs from its predecessor certification")
    return checks


def _primary_metadata(paths: Iterable[str]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for relative in sorted(paths):
        frame = pd.read_csv(ROOT / relative, usecols=["open_time"])
        stamps = pd.to_datetime(frame["open_time"], utc=True, errors="raise")
        local = stamps.dt.tz_convert("America/New_York")
        clocks = local.dt.strftime("%H:%M")
        mask = clocks.isin(REQUIRED_CLOCKS)
        for index in frame.index[mask]:
            stamp = stamps.iloc[index].isoformat().replace("+00:00", "Z")
            if stamp not in selected:
                selected[stamp] = {
                    "timestamp": stamp,
                    "session_date": local.iloc[index].strftime("%Y-%m-%d"),
                    "clock": clocks.iloc[index],
                    "source_path": relative,
                    "source_row": int(index) + 1,
                }
    return [selected[key] for key in sorted(selected)]


def _reference_metadata(paths: Iterable[str]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for relative in sorted(paths):
        with (ROOT / relative).open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row_number, row in enumerate(reader, start=1):
                stamp = datetime.fromisoformat(str(row["open_time"]).replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                stamp = stamp.astimezone(timezone.utc)
                local = stamp.astimezone(NY)
                clock = local.strftime("%H:%M")
                if clock not in REQUIRED_CLOCKS:
                    continue
                key = stamp.isoformat().replace("+00:00", "Z")
                if key not in selected:
                    selected[key] = {
                        "timestamp": key,
                        "session_date": local.strftime("%Y-%m-%d"),
                        "clock": clock,
                        "source_path": relative,
                        "source_row": row_number,
                    }
    return [selected[key] for key in sorted(selected)]


def _potential_cases(rows: list[dict[str, Any]]) -> list[str]:
    by_day: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        by_day[row["session_date"]].add(row["clock"])
    p13_days = [day for day in sorted(by_day) if "15:59" in by_day[day]]
    has_prior = set(p13_days[1:])
    prelim = [day for day in sorted(by_day) if set(REQUIRED_CLOCKS).issubset(by_day[day]) and day in has_prior]
    return prelim[20:]


def _support(days: list[str]) -> dict[str, Any]:
    years = {str(year): sum(day.startswith(str(year)) for day in days) for year in (2022, 2023, 2024)}
    folds = {
        "2022_H1": sum("2022-01-01" <= day < "2022-07-01" for day in days),
        "2022_H2": sum("2022-07-01" <= day < "2023-01-01" for day in days),
        "2023_H1": sum("2023-01-01" <= day < "2023-07-01" for day in days),
        "2023_H2": sum("2023-07-01" <= day < "2024-01-01" for day in days),
        "2024_H1": sum("2024-01-01" <= day < "2024-07-01" for day in days),
        "2024_H2": sum("2024-07-01" <= day < "2025-01-01" for day in days),
    }
    gate_days = [day for day in days if "2022-01-01" <= day <= "2024-12-31"]
    return {
        "potential_dates_all": len(days),
        "potential_gate_dates": len(gate_days),
        "years": years,
        "folds": folds,
        "potential_support_gate": len(gate_days) >= 300 and all(value >= 80 for value in years.values()) and all(value >= 40 for value in folds.values()),
        "note": "Outcome-blind upper support: exact C02 executed support and zero-volatility exclusions are evaluated only after the sealed value opening.",
    }


def repository_inventory() -> dict[str, Any]:
    keywords = ("CONTRACT", "REPORT", "RESULT", "FINAL", "VERDICT", "MILESTONE")
    records: list[dict[str, Any]] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".json"}:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith("research_artifacts/external_evidence_edge_replication_v1"):
            continue
        if relative in {INVENTORY.as_posix(), FREEZE.as_posix()}:
            continue
        if any(keyword in path.name.upper() for keyword in keywords):
            records.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return {
        "version": "EXTERNAL_EVIDENCE_EDGE_REPLICATION_V1_REPOSITORY_STRATEGY_ARTIFACT_INVENTORY_1_0",
        "selection": "All Markdown/JSON files whose filename contains CONTRACT, REPORT, RESULT, FINAL, VERDICT, or MILESTONE, excluding this new branch's generated artifacts.",
        "artifact_count": len(records),
        "inventory_sha256": canonical_hash(records),
        "artifacts": records,
    }


def main() -> int:
    for relative in (INVENTORY, READINESS, FREEZE):
        if (ROOT / relative).exists():
            raise RuntimeError(f"Append-only target already exists: {relative}")
    for relative in STATIC_SEAL_FILES:
        if not (ROOT / relative).is_file():
            raise RuntimeError(f"Required freeze file missing: {relative}")

    registry = source_registry()
    source_checks = verify_sources(registry)
    symbol_audits: dict[str, Any] = {}
    primary_cases: dict[str, list[str]] = {}
    for symbol in SYMBOLS:
        paths = [item["path"].replace("\\", "/") for item in registry[symbol]]
        primary = _primary_metadata(paths)
        reference = _reference_metadata(paths)
        if primary != reference:
            raise RuntimeError(f"Primary/reference timestamp metadata mismatch for {symbol}")
        cases = _potential_cases(primary)
        primary_cases[symbol] = cases
        symbol_audits[symbol] = {
            "source_files": len(paths),
            "required_anchor_rows": len(primary),
            "first_required_anchor": primary[0]["timestamp"] if primary else None,
            "last_required_anchor": primary[-1]["timestamp"] if primary else None,
            "anchor_metadata_sha256": canonical_hash(primary),
            "primary_reference_exact": True,
            "potential_case_support": _support(cases),
        }

    equity_union = sorted(set(primary_cases["US500"]) | set(primary_cases["USTEC"]))
    candidate_readiness = {
        "EER_C01_EQUITY_MIM_R1": _support(equity_union),
        "EER_C02_EQUITY_MIM_R1_R12": _support(equity_union),
        "EER_C03_WTI_MIM_R1": _support(primary_cases["XTIUSD"]),
    }
    readiness = {
        "version": "EXTERNAL_EVIDENCE_EDGE_REPLICATION_V1_SOURCE_READINESS_1_0",
        "performed_at": datetime.now(timezone.utc).isoformat(),
        "semantic_market_values_accessed": False,
        "paid_acquisition": False,
        "charge_usd": 0.0,
        "predecessor_verdict": "PASS_MILESTONE_2_ALL_SEVEN_INSTRUMENTS_SOURCE_CERTIFIED",
        "source_checks": source_checks,
        "symbols": symbol_audits,
        "candidate_readiness": candidate_readiness,
        "gates": {
            "all_63_source_files_hash_verified": len(source_checks) == 63 and all(item["verified"] for item in source_checks),
            "primary_reference_timestamp_metadata_exact": all(item["primary_reference_exact"] for item in symbol_audits.values()),
            "all_candidates_have_potential_support": all(item["potential_support_gate"] for item in candidate_readiness.values()),
            "no_paid_data_required": True,
        },
    }
    readiness["verdict"] = "PASS_OUTCOME_BLIND_SOURCE_READINESS" if all(readiness["gates"].values()) else "FAIL_OUTCOME_BLIND_SOURCE_READINESS"
    write_new_json(READINESS, readiness)

    inventory = repository_inventory()
    write_new_json(INVENTORY, inventory)
    if readiness["verdict"] != "PASS_OUTCOME_BLIND_SOURCE_READINESS":
        raise RuntimeError("Outcome-blind source readiness failed; no freeze or outcome access permitted")

    seal_paths = list(STATIC_SEAL_FILES) + [INVENTORY, READINESS]
    sealed_files = []
    for relative in seal_paths:
        path = ROOT / relative
        sealed_files.append({"path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    for item in source_checks:
        sealed_files.append({"path": item["path"], "bytes": item["actual_bytes"], "sha256": item["actual_sha256"]})
    sealed_files = sorted(sealed_files, key=lambda item: item["path"])
    freeze = {
        "version": "EXTERNAL_EVIDENCE_EDGE_REPLICATION_V1_PREOUTCOME_FREEZE_1_0",
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "status": "SEALED_AND_AUTHORIZED_FOR_ONE_DEVELOPMENT_OPENING",
        "selected_candidate_count": 3,
        "selected_candidates": ["EER_C01_EQUITY_MIM_R1", "EER_C02_EQUITY_MIM_R1_R12", "EER_C03_WTI_MIM_R1"],
        "market_values_accessed_before_freeze": False,
        "development_outcomes_opened": False,
        "forward_2025_opened": False,
        "forward_2026_opened": False,
        "paid_acquisition": False,
        "charge_usd": 0.0,
        "sealed_files": sealed_files,
        "sealed_files_sha256": canonical_hash(sealed_files),
        "controls": {
            "one_development_opening": True,
            "no_rule_reinterpretation": True,
            "no_rejected_rule_reopened": True,
            "forward_only_after_pass": True,
        },
    }
    write_new_json(FREEZE, freeze)
    print(json.dumps({"verdict": readiness["verdict"], "freeze": FREEZE.as_posix(), "candidate_readiness": candidate_readiness}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
