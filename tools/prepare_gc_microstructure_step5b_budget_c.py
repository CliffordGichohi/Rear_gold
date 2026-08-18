#!/usr/bin/env python3
"""Prepare and freeze the outcome-blind Step 5B Budget Amendment C."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_REGISTRY = ROOT / "research_manifests/gc_microstructure_step_5a_request_registry_v01.json"
ORIGINAL_AUTHORIZATION = ROOT / "research_manifests/gc_microstructure_step_5b_authorization_v01.json"
STEP5A_MANIFEST = ROOT / "research_artifacts/gc_microstructure_step_5a_v01/manifest.json"
ATTEMPT1_MANIFEST = ROOT / "research_artifacts/gc_microstructure_step_5b_v01/manifest.json"
RESUME_MANIFEST = ROOT / "research_artifacts/gc_microstructure_step_5b_resume_v01/manifest.json"
RESUME_PREFLIGHT = ROOT / "research_artifacts/gc_microstructure_step_5b_resume_v01/pre_submission_quote.json"
AMENDMENT = ROOT / "research_manifests/gc_microstructure_step_5b_budget_amendment_c_v01.json"
AMENDED_REGISTRY = ROOT / "research_manifests/gc_microstructure_step_5b_budget_c_request_registry_v01.json"
FREEZE = ROOT / "research_manifests/gc_microstructure_step_5b_budget_c_freeze_v01.json"
ACQUISITION_TOOL = ROOT / "tools/acquire_gc_microstructure_step5b_budget_c.py"
MBO_NORMALIZER = ROOT / "tools/databento_gc_mbo_engineering_pilot.py"
MBP10_NORMALIZER = ROOT / "tools/databento_gc_mbp10_step3b2.py"
QUOTE_TOOL = ROOT / "tools/quote_gc_microstructure_step5a.py"

DROP_MONTHS = ("2021-08", "2021-09", "2021-10")
EXPECTED = {
    ORIGINAL_REGISTRY: "f56467c32b5708bc1cb902e51f034243408b7a6f967f2ce2b652777cf2d00477",
    ORIGINAL_AUTHORIZATION: "653c37f265ab055ff42928d1fb60853593a8556e0d744d6b671630a5e933e76a",
    STEP5A_MANIFEST: "4fbc2b8365badb5c44f35201524629782873b43eb3b06861e4d289f8449b51c9",
    ATTEMPT1_MANIFEST: "ac1418b0e8b5db020fa3c20319c6eec597dfa4898cffb51f6b6b0397520fddec",
    RESUME_MANIFEST: "b635c6cd0d195e1bd21c50417bcd1396c7c2f0f4993c40ae0f20d91fbd8bd711",
    RESUME_PREFLIGHT: "9c4a83c9502d8915a12a526fcaa3784ad348af98eaa42700b1283560fb77a701",
    MBO_NORMALIZER: "ddb4225576c2b37370712cf7b1d20707f1aa0b91bcdbb4acf6a369bd51bc590c",
    MBP10_NORMALIZER: "551fc9a76036739f3dc24adbe8b754e63971953614279de93bd162590e3486c5",
    QUOTE_TOOL: "1d84e69e44ded71e11dfc4648b93c39b86984bab20f4dac7aaef50beca851dbf",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "freeze", "verify"))
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    elif args.action == "freeze":
        freeze()
    else:
        verify()


def prepare() -> None:
    _verify_predecessors()
    if AMENDMENT.exists() or AMENDED_REGISTRY.exists():
        raise FileExistsError("Refusing to overwrite Budget Amendment C")
    original = _read_json(ORIGINAL_REGISTRY)
    quote = _read_json(RESUME_PREFLIGHT)
    if not quote["all_no_charge_gates_pass"]:
        raise ValueError("The storage-remediated preflight did not pass")
    dropped_week_ids = {
        f"{month}:SECOND_COMPLETE_CME_WEEK" for month in DROP_MONTHS
    }
    kept_weeks = [
        row
        for row in original["weeks"]
        if row["selected_month_week_id"] not in dropped_week_ids
    ]
    removed_weeks = [
        row
        for row in original["weeks"]
        if row["selected_month_week_id"] in dropped_week_ids
    ]
    kept_dates = [
        row
        for row in original["selected_dates"]
        if row["selected_month_week_id"] not in dropped_week_ids
    ]
    removed_dates = [
        row
        for row in original["selected_dates"]
        if row["selected_month_week_id"] in dropped_week_ids
    ]
    kept_intervals = [
        row
        for row in original["request_intervals"]
        if row["selected_month_week_id"] not in dropped_week_ids
    ]
    removed_intervals = [
        row
        for row in original["request_intervals"]
        if row["selected_month_week_id"] in dropped_week_ids
    ]
    kept_requests = [
        row
        for row in original["provider_quote_requests"]
        if row["selected_month_week_id"] not in dropped_week_ids
    ]
    removed_requests = [
        row
        for row in original["provider_quote_requests"]
        if row["selected_month_week_id"] in dropped_week_ids
    ]
    kept_daily = [
        row
        for row in original["daily_coverage_checks"]
        if row["trade_date"] >= "2021-11-08"
    ]
    fresh_by_id = {
        row["request_id"]: row for row in quote["fresh_estimates"]["quotes"]
    }
    retained_quote_rows = [fresh_by_id[row["request_id"]] for row in kept_requests]
    schema_totals = {
        schema: {
            "request_count": sum(row["schema"] == schema for row in retained_quote_rows),
            "cost_usd": sum(
                row["cost_usd"] for row in retained_quote_rows if row["schema"] == schema
            ),
            "record_count": sum(
                row["record_count"] for row in retained_quote_rows if row["schema"] == schema
            ),
            "billable_size": sum(
                row["billable_size"] for row in retained_quote_rows if row["schema"] == schema
            ),
        }
        for schema in ("mbo", "mbp-10")
    }
    estimate = {
        "schema_totals": schema_totals,
        "combined": {
            "request_count": len(retained_quote_rows),
            "cost_usd": sum(row["cost_usd"] for row in retained_quote_rows),
            "record_count": sum(row["record_count"] for row in retained_quote_rows),
            "billable_size": sum(row["billable_size"] for row in retained_quote_rows),
        },
        "source": _record(RESUME_PREFLIGHT),
        "classification": "PRE_AMENDMENT_METADATA_ONLY_REFERENCE_NOT_SUBMISSION_QUOTE",
    }
    if (
        len(kept_weeks) != 38
        or len(kept_dates) != 188
        or len(kept_intervals) != 40
        or len(kept_requests) != 80
        or len(kept_daily) != 376
        or len(removed_dates) != 15
        or len(removed_requests) != 6
        or kept_dates[0]["trade_date"] != "2021-11-08"
        or kept_dates[-1]["trade_date"] != "2024-12-13"
        or abs(estimate["combined"]["cost_usd"] - 106.20845379531302) > 1e-9
    ):
        raise ValueError("Budget C deterministic reduction failed its frozen counts")

    registry = {
        "version": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_REQUEST_REGISTRY_V0_1",
        "status": "FROZEN_OUTCOME_BLIND_BEFORE_AMENDED_PROVIDER_QUOTE_OR_SUBMISSION",
        "classification": "BUDGET_CONSTRAINED_DEVELOPMENT_ACQUISITION",
        "source_registry": _record(ORIGINAL_REGISTRY),
        "selection_amendment": {
            "rule": "Remove only the complete first three selected monthly blocks in ascending calendar order.",
            "removed_months": list(DROP_MONTHS),
            "removed_week_ids": sorted(dropped_week_ids),
            "reason": "Fit the development acquisition within existing USD 108.78 credits with no card charge and retain a safety buffer.",
            "market_values_outcomes_or_performance_used": False,
            "cost_used_only_as_global_budget_constraint": True,
        },
        "permanent_engineering_exclusions": original["permanent_engineering_exclusions"],
        "sample_counts": {
            "selected_monthly_weeks": len(kept_weeks),
            "selected_dates": len(kept_dates),
            "request_intervals": len(kept_intervals),
            "provider_requests": len(kept_requests),
            "daily_coverage_checks": len(kept_daily),
            "removed_monthly_weeks": len(removed_weeks),
            "removed_dates": len(removed_dates),
            "removed_provider_requests": len(removed_requests),
        },
        "development_period": {
            "start_inclusive": "2021-11-08",
            "end_inclusive": "2024-12-13",
            "month_blocks": 38,
        },
        "weeks": kept_weeks,
        "removed_weeks": removed_weeks,
        "selected_dates": kept_dates,
        "removed_dates": removed_dates,
        "request_intervals": kept_intervals,
        "removed_request_intervals": removed_intervals,
        "provider_quote_requests": kept_requests,
        "removed_provider_quote_requests": removed_requests,
        "provider_quote_request_count": len(kept_requests),
        "daily_coverage_checks": kept_daily,
        "daily_coverage_check_count": len(kept_daily),
        "symbology_request": {
            **original["symbology_request"],
            "start_date": "2021-11-08",
        },
        "pre_amendment_reference_estimate": estimate,
        "maximum_total_cost_usd": 108.78,
        "card_charge_permitted": False,
        "market_values_or_outcomes_used": False,
        "registry_hash": "",
    }
    registry["registry_hash"] = _canonical_hash(
        {key: value for key, value in registry.items() if key != "registry_hash"}
    )
    _write_json(AMENDED_REGISTRY, registry)

    amendment = {
        "version": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_AMENDMENT_C_V0_1",
        "status": "FROZEN_USER_AUTHORIZATION_BEFORE_AMENDED_PROVIDER_QUOTE_OR_SUBMISSION",
        "authorized_at_utc": _now(),
        "classification": "OUTCOME_BLIND_BUDGET_REDUCTION_ONLY",
        "user_instruction": "Remove the complete August, September, and October 2021 monthly blocks, producing 188 dates and 80 requests from 2021-11-08 through 2024-12-13; retain both schemas and prohibit any card charge.",
        "preserved_verdicts": {
            "attempt_01": "STOP_STEP_5B_PRE_SUBMISSION_STORAGE_GATE",
            "attempt_02": "STOP_STEP_5B_PRE_SUBMISSION_CREDIT_GATE",
            "all_prior_research_and_engineering_verdicts": "PRESERVED_UNCHANGED",
        },
        "changes_only": {
            "removed_months": list(DROP_MONTHS),
            "original_dates": 203,
            "amended_dates": 188,
            "original_requests": 86,
            "amended_requests": 80,
            "original_start": "2021-08-09",
            "amended_start": "2021-11-08",
            "end_unchanged": "2024-12-13",
        },
        "unchanged": [
            "GLBX.MDP3",
            "GC.v.0 continuous symbology",
            "MBO and MBP-10 schemas",
            "all 85 feature definitions",
            "London and New York DST-aware cutoffs",
            "fundamental and price/session context definitions",
            "missing-data policy",
            "no execution, trade, PnL, or outcome access in Step 5B",
        ],
        "budget": {
            "available_credits_usd": 108.78,
            "maximum_amended_estimate_usd": 108.78,
            "card_charge_permitted": False,
            "pre_amendment_reference_estimate_usd": estimate["combined"]["cost_usd"],
            "pre_amendment_reference_headroom_usd": 108.78 - estimate["combined"]["cost_usd"],
        },
        "fail_fast_gates": [
            "all predecessor and Amendment C seals verify",
            "destination remains at least 350 GiB free",
            "all 80 amended estimates are freshly rerun",
            "fresh combined estimate does not exceed USD 108.78",
            "all amended requests and symbology match the frozen amended registry",
            "no card charge is required or permitted",
        ],
        "request_registry": _record(AMENDED_REGISTRY),
        "batch_jobs_submitted": 0,
        "data_acquired": False,
        "charge_incurred": False,
        "market_values_or_outcomes_accessed": False,
        "amendment_hash": "",
    }
    amendment["amendment_hash"] = _canonical_hash(
        {key: value for key, value in amendment.items() if key != "amendment_hash"}
    )
    _write_json(AMENDMENT, amendment)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_PREPARED",
                "amendment_hash": amendment["amendment_hash"],
                "registry_hash": registry["registry_hash"],
                "selected_dates": len(kept_dates),
                "requests": len(kept_requests),
                "reference_estimate_usd": estimate["combined"]["cost_usd"],
                "card_charge_permitted": False,
            },
            sort_keys=True,
        )
    )


def freeze() -> None:
    _verify_predecessors()
    if FREEZE.exists():
        raise FileExistsError("Refusing to overwrite Budget C freeze")
    if not AMENDMENT.exists() or not AMENDED_REGISTRY.exists() or not ACQUISITION_TOOL.exists():
        raise FileNotFoundError("Prepare the amendment, registry, and acquisition tool first")
    amendment = _read_json(AMENDMENT)
    registry = _read_json(AMENDED_REGISTRY)
    if amendment["amendment_hash"] != _canonical_hash(
        {key: value for key, value in amendment.items() if key != "amendment_hash"}
    ):
        raise ValueError("Amendment hash mismatch")
    if registry["registry_hash"] != _canonical_hash(
        {key: value for key, value in registry.items() if key != "registry_hash"}
    ):
        raise ValueError("Amended registry hash mismatch")
    value = {
        "version": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_FREEZE_V0_1",
        "status": "FROZEN_BEFORE_FRESH_AMENDED_PROVIDER_QUOTE_OR_BATCH_SUBMISSION",
        "frozen_at_utc": _now(),
        "classification": "PAID_ACQUISITION_CONTROL_FREEZE_NO_CARD_CHARGE",
        "records": {
            "amendment_c": _record(AMENDMENT),
            "amended_request_registry": _record(AMENDED_REGISTRY),
            "original_authorization": _record(ORIGINAL_AUTHORIZATION),
            "step5a_manifest": _record(STEP5A_MANIFEST),
            "attempt1_manifest": _record(ATTEMPT1_MANIFEST),
            "attempt2_manifest": _record(RESUME_MANIFEST),
            "attempt2_preflight": _record(RESUME_PREFLIGHT),
            "prepare_tool": _record(Path(__file__)),
            "acquisition_tool": _record(ACQUISITION_TOOL),
            "mbo_normalizer": _record(MBO_NORMALIZER),
            "mbp10_normalizer": _record(MBP10_NORMALIZER),
            "quote_tool": _record(QUOTE_TOOL),
        },
        "amendment_hash": amendment["amendment_hash"],
        "registry_hash": registry["registry_hash"],
        "selected_dates": 188,
        "request_intervals": 40,
        "provider_requests": 80,
        "available_credits_usd": 108.78,
        "maximum_combined_estimate_usd": 108.78,
        "minimum_destination_free_bytes": 375_809_638_400,
        "card_charge_permitted": False,
        "provider_metadata_called_after_amendment": False,
        "batch_jobs_submitted": 0,
        "data_acquired": False,
        "market_values_or_outcomes_accessed": False,
        "freeze_hash": "",
    }
    value["freeze_hash"] = _canonical_hash(
        {key: item for key, item in value.items() if key != "freeze_hash"}
    )
    _write_json(FREEZE, value)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_FROZEN",
                "freeze_hash": value["freeze_hash"],
                "requests": value["provider_requests"],
                "card_charge_permitted": False,
            },
            sort_keys=True,
        )
    )


def verify() -> None:
    _verify_predecessors()
    for path in (AMENDMENT, AMENDED_REGISTRY, FREEZE):
        if not path.exists():
            raise FileNotFoundError(path)
    amendment = _read_json(AMENDMENT)
    registry = _read_json(AMENDED_REGISTRY)
    frozen = _read_json(FREEZE)
    if amendment["amendment_hash"] != _canonical_hash(
        {key: value for key, value in amendment.items() if key != "amendment_hash"}
    ):
        raise ValueError("Amendment hash mismatch")
    if registry["registry_hash"] != _canonical_hash(
        {key: value for key, value in registry.items() if key != "registry_hash"}
    ):
        raise ValueError("Registry hash mismatch")
    if frozen["freeze_hash"] != _canonical_hash(
        {key: value for key, value in frozen.items() if key != "freeze_hash"}
    ):
        raise ValueError("Freeze hash mismatch")
    for record in frozen["records"].values():
        _verify_record(record)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5B_BUDGET_C_FREEZE_VERIFIED",
                "freeze_hash": frozen["freeze_hash"],
                "records_verified": len(frozen["records"]),
                "requests": registry["provider_quote_request_count"],
                "card_charge_permitted": False,
            },
            sort_keys=True,
        )
    )


def _verify_predecessors() -> None:
    for path, expected in EXPECTED.items():
        if not path.exists() or _sha256(path) != expected:
            raise ValueError(f"Predecessor changed: {path}")
    step5a = _read_json(STEP5A_MANIFEST)
    attempt1 = _read_json(ATTEMPT1_MANIFEST)
    resume = _read_json(RESUME_MANIFEST)
    preflight = _read_json(RESUME_PREFLIGHT)
    if (
        step5a["manifest_hash"] != "ec869c52c223d460a086a2aeb19265777761a9b9296fbe012f96f62bdf174706"
        or attempt1["manifest_hash"] != "27f9826516160ef7e60a42d444158b5a62bf8d666acf7adde454783b9ec54402"
        or resume["manifest_hash"] != "1c6eb28ab2e02dfe3c840244edea1af1c9fec0a92537a8e13879c1f6ef503648"
        or resume["status"] != "STOP_STEP_5B_PRE_SUBMISSION_CREDIT_GATE"
        or preflight["preflight_hash"] != "a52a66ac24e5fd1d9682e2f35e016454b3e915ccb114027f05046297576302ec"
    ):
        raise ValueError("Predecessor internal seal changed")


def _record(path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(ROOT.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _verify_record(record: dict[str, Any]) -> None:
    path = ROOT / record["path"]
    if (
        not path.exists()
        or path.stat().st_size != int(record["bytes"])
        or _sha256(path) != record["sha256"]
    ):
        raise ValueError(f"Frozen record changed: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
