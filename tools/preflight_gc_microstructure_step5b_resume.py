#!/usr/bin/env python3
"""Resume Step 5B through the last no-charge pre-submission gate.

This tool is deliberately limited to sealed-file verification, destination
capacity, Databento symbology, and historical metadata estimates. It contains
no batch submission, time-series retrieval, DBN decoding, or download path.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools import quote_gc_microstructure_step5a as quote_tool


ROOT = Path(__file__).resolve().parents[1]
STEP5A_MANIFEST = ROOT / "research_artifacts/gc_microstructure_step_5a_v01/manifest.json"
STEP5A_PRIMARY = ROOT / "research_artifacts/gc_microstructure_step_5a_v01/primary_quote.json"
STEP5A_FREEZE = ROOT / "research_manifests/gc_microstructure_step_5a_freeze_v01.json"
REQUEST_REGISTRY = ROOT / "research_manifests/gc_microstructure_step_5a_request_registry_v01.json"
AUTHORIZATION = ROOT / "research_manifests/gc_microstructure_step_5b_authorization_v01.json"
ATTEMPT1_MANIFEST = ROOT / "research_artifacts/gc_microstructure_step_5b_v01/manifest.json"
ATTEMPT1_VERDICT = ROOT / "research_artifacts/gc_microstructure_step_5b_v01/verdict.json"
AMENDMENT = ROOT / "research_manifests/gc_microstructure_step_5b_resume_amendment_a_v01.json"
RESUME_FREEZE = ROOT / "research_manifests/gc_microstructure_step_5b_resume_amendment_a_freeze_v01.json"

EXPECTED = {
    "step5a_manifest_sha256": "4fbc2b8365badb5c44f35201524629782873b43eb3b06861e4d289f8449b51c9",
    "step5a_manifest_hash": "ec869c52c223d460a086a2aeb19265777761a9b9296fbe012f96f62bdf174706",
    "step5a_freeze_sha256": "1c6528160551760391dc20909928c5e20d3d4a6a5203959b5c1ed3c9c47f5921",
    "step5a_freeze_hash": "cb67d1ba793a80e58d5439be2f3c07ac5fcac1b965440f2035bb48b86efde949",
    "request_registry_sha256": "f56467c32b5708bc1cb902e51f034243408b7a6f967f2ce2b652777cf2d00477",
    "authorization_sha256": "653c37f265ab055ff42928d1fb60853593a8556e0d744d6b671630a5e933e76a",
    "attempt1_manifest_sha256": "ac1418b0e8b5db020fa3c20319c6eec597dfa4898cffb51f6b6b0397520fddec",
    "attempt1_manifest_hash": "27f9826516160ef7e60a42d444158b5a62bf8d666acf7adde454783b9ec54402",
    "attempt1_verdict_sha256": "1b10fbf20c779999c98f6febf76bd7786f945e8e07440ef95c412eccf204febf",
    "attempt1_verdict_hash": "e40d073d23192b1a2a3091d97b3c11f90f05905ab5e56aeea3181d28e7ddb53c",
    "quote_tool_sha256": "1d84e69e44ded71e11dfc4648b93c39b86984bab20f4dac7aaef50beca851dbf",
}
EXPECTED_PACKAGES = {
    "databento": "0.82.0",
    "databento-dbn": "0.63.0",
    "numpy": "2.5.1",
    "pandas": "3.0.5",
    "pyarrow": "25.0.0",
    "zstandard": "0.25.0",
}
EXPECTED_DESTINATION = Path("/home/wapi/rear_gold_step5b_v01")
MINIMUM_FREE_BYTES = 375_809_638_400
MAXIMUM_COST_USD = 120.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(EXPECTED_DESTINATION / "artifacts/pre_submission_quote.json"),
    )
    parser.add_argument(
        "--env-file",
        default="/home/wapi/.config/rear_gold/databento.env",
    )
    parser.add_argument("--destination", default=str(EXPECTED_DESTINATION))
    args = parser.parse_args()
    run(Path(args.output), Path(args.env_file), Path(args.destination))


def run(output: Path, env_file: Path, destination: Path) -> None:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite a Step 5B quote: {output}")
    static = _verify_static_context()
    if destination.resolve() != EXPECTED_DESTINATION.resolve():
        raise ValueError("Destination differs from frozen resume amendment")
    free_bytes = int(shutil.disk_usage(destination).free)
    package_versions = {
        name: importlib.metadata.version(name) for name in EXPECTED_PACKAGES
    }
    client, sdk_version = quote_tool._client(quote_tool._api_key(env_file))
    registry = static["registry"]
    instrument = quote_tool._instrument_metadata(client, registry)
    estimates = quote_tool._interval_estimates(client, registry, "step_5b_resume")
    prior = _read_json(STEP5A_PRIMARY)

    request_rows_exact = all(
        fresh["request"] == frozen["request"]
        and fresh["request_id"] == frozen["request_id"]
        and fresh["interval_id"] == frozen["interval_id"]
        and fresh["schema"] == frozen["schema"]
        for fresh, frozen in zip(
            estimates["quotes"], registry["provider_quote_requests"], strict=True
        )
    )
    combined_cost = float(estimates["combined_totals"]["cost_usd"])
    gates = {
        "step5a_predecessor_seal_verified": static["step5a_verified"],
        "attempt1_stop_preserved_and_verified": static["attempt1_verified"],
        "resume_amendment_and_freeze_verified": static["resume_verified"],
        "destination_path_exact": destination.resolve() == EXPECTED_DESTINATION.resolve(),
        "destination_at_least_350_gib_free": free_bytes >= MINIMUM_FREE_BYTES,
        "databento_sdk_version_exact": sdk_version == EXPECTED_PACKAGES["databento"],
        "normalization_packages_exact": package_versions == EXPECTED_PACKAGES,
        "frozen_registry_has_86_requests": len(registry["provider_quote_requests"]) == 86,
        "all_86_estimates_returned": estimates["request_count"] == 86,
        "all_fresh_requests_exactly_frozen": request_rows_exact,
        "all_costs_finite_nonnegative": all(
            math.isfinite(float(row["cost_usd"])) and float(row["cost_usd"]) >= 0
            for row in estimates["quotes"]
        ),
        "all_record_counts_positive": all(
            int(row["record_count"]) > 0 for row in estimates["quotes"]
        ),
        "all_billable_sizes_positive": all(
            int(row["billable_size"]) > 0 for row in estimates["quotes"]
        ),
        "combined_estimate_at_or_below_120_usd": (
            math.isfinite(combined_cost) and combined_cost <= MAXIMUM_COST_USD
        ),
        "symbology_response_complete": instrument["response_complete"],
        "all_203_dates_map_exactly_once": instrument[
            "all_selected_dates_map_exactly_once"
        ],
        "selected_date_symbology_unchanged": (
            instrument["selected_date_mappings"]
            == prior["instrument_metadata"]["selected_date_mappings"]
            and instrument["selected_date_mapping_hash"]
            == prior["instrument_metadata"]["selected_date_mapping_hash"]
        ),
        "mapping_intervals_unchanged": (
            instrument["mapping_intervals"]
            == prior["instrument_metadata"]["mapping_intervals"]
        ),
        "metadata_endpoints_only_no_charge": True,
    }
    metadata_pass = all(gates.values())
    result = {
        "version": "GC_MICROSTRUCTURE_STEP_5B_RESUME_PREFLIGHT_QUOTE_V0_1",
        "status": (
            "PASS_NO_CHARGE_GATES_AWAITING_CREDIT_CONFIRMATION"
            if metadata_pass
            else "FAIL_RESUMED_PRE_SUBMISSION_GATE"
        ),
        "checked_at_utc": _now(),
        "classification": "METADATA_ONLY_NO_MARKET_VALUES_NO_CHARGE",
        "attempt": "STEP_5B_ATTEMPT_02_STORAGE_REMEDIATED",
        "preserved_attempt_01_status": "STOP_STEP_5B_PRE_SUBMISSION_STORAGE_GATE",
        "static_context": static["records"],
        "destination": {
            "path": str(destination.resolve()),
            "free_bytes": free_bytes,
            "free_gib": round(free_bytes / 2**30, 3),
            "minimum_free_bytes": MINIMUM_FREE_BYTES,
            "minimum_free_gib": 350,
        },
        "software": {
            "databento_sdk_version": sdk_version,
            "frozen_package_versions": package_versions,
        },
        "instrument_metadata": instrument,
        "fresh_estimates": estimates,
        "pre_submission_gates_except_credit": gates,
        "all_no_charge_gates_pass": metadata_pass,
        "credit_gate": {
            "status": "PENDING_HUMAN_PORTAL_EVIDENCE",
            "required_usable_credit_usd": combined_cost,
            "reason": "The Databento SDK exposes no account-credit balance endpoint; portal evidence is required before submission.",
        },
        "submission_ready": False,
        "batch_api_called": False,
        "timeseries_api_called": False,
        "jobs_submitted": 0,
        "data_downloaded": False,
        "charge_incurred": False,
        "market_values_or_outcomes_accessed": False,
        "relationships_signals_execution_trades_pnl_or_r_calculated": False,
    }
    result["preflight_hash"] = _canonical_hash(result)
    _write_json_atomic(output, result)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5B_RESUME_NO_CHARGE_PREFLIGHT",
                "status": result["status"],
                "free_gib": result["destination"]["free_gib"],
                "request_count": estimates["request_count"],
                "mbo_cost_usd": estimates["schema_totals"]["mbo"]["cost_usd"],
                "mbp10_cost_usd": estimates["schema_totals"]["mbp-10"]["cost_usd"],
                "combined_cost_usd": combined_cost,
                "authorized_cap_usd": MAXIMUM_COST_USD,
                "credit_gate": "PENDING_HUMAN_PORTAL_EVIDENCE",
                "jobs_submitted": 0,
                "charge_incurred": False,
            },
            sort_keys=True,
        )
    )


def _verify_static_context() -> dict[str, Any]:
    for path, expected in (
        (STEP5A_MANIFEST, EXPECTED["step5a_manifest_sha256"]),
        (STEP5A_FREEZE, EXPECTED["step5a_freeze_sha256"]),
        (REQUEST_REGISTRY, EXPECTED["request_registry_sha256"]),
        (AUTHORIZATION, EXPECTED["authorization_sha256"]),
        (ATTEMPT1_MANIFEST, EXPECTED["attempt1_manifest_sha256"]),
        (ATTEMPT1_VERDICT, EXPECTED["attempt1_verdict_sha256"]),
        (Path(quote_tool.__file__), EXPECTED["quote_tool_sha256"]),
    ):
        if _sha256(path) != expected:
            raise ValueError(f"Frozen file changed: {path}")

    step5a = _read_json(STEP5A_MANIFEST)
    if (
        step5a.get("manifest_hash") != EXPECTED["step5a_manifest_hash"]
        or _without_hash(step5a, "manifest_hash") != EXPECTED["step5a_manifest_hash"]
        or step5a.get("status") != "PASS_STEP_5A_METADATA_READINESS"
    ):
        raise ValueError("Step 5A manifest failed verification")
    for record in [*step5a["records"].values(), *step5a["artifacts"]]:
        _verify_relative_record(record)
    freeze = _read_json(STEP5A_FREEZE)
    if freeze.get("freeze_hash") != EXPECTED["step5a_freeze_hash"]:
        raise ValueError("Step 5A freeze hash changed")

    attempt1 = _read_json(ATTEMPT1_MANIFEST)
    attempt1_verdict = _read_json(ATTEMPT1_VERDICT)
    if (
        attempt1.get("manifest_hash") != EXPECTED["attempt1_manifest_hash"]
        or _without_hash(attempt1, "manifest_hash") != EXPECTED["attempt1_manifest_hash"]
        or attempt1.get("status") != "STOP_STEP_5B_PRE_SUBMISSION_STORAGE_GATE"
        or attempt1_verdict.get("verdict_hash") != EXPECTED["attempt1_verdict_hash"]
        or _without_hash(attempt1_verdict, "verdict_hash")
        != EXPECTED["attempt1_verdict_hash"]
    ):
        raise ValueError("Step 5B attempt-01 stop failed verification")
    for record in [
        *attempt1["predecessors"],
        attempt1["authorization"],
        *attempt1["artifacts"],
    ]:
        _verify_relative_record(record)

    registry = _read_json(REQUEST_REGISTRY)
    if (
        registry.get("registry_hash")
        != _canonical_hash({k: v for k, v in registry.items() if k != "registry_hash"})
        or registry["provider_quote_request_count"] != 86
        or registry["sample_counts"]["post_exclusion_dates"] != 203
    ):
        raise ValueError("Frozen request registry failed verification")

    resume_freeze = _read_json(RESUME_FREEZE)
    if resume_freeze.get("freeze_hash") != _canonical_hash(
        {k: v for k, v in resume_freeze.items() if k != "freeze_hash"}
    ):
        raise ValueError("Resume freeze canonical hash mismatch")
    for record in resume_freeze["records"].values():
        _verify_relative_record(record)

    return {
        "step5a_verified": True,
        "attempt1_verified": True,
        "resume_verified": True,
        "registry": registry,
        "records": {
            "step5a_manifest_hash": step5a["manifest_hash"],
            "step5a_freeze_hash": freeze["freeze_hash"],
            "attempt1_manifest_hash": attempt1["manifest_hash"],
            "attempt1_verdict_hash": attempt1_verdict["verdict_hash"],
            "request_registry_sha256": _sha256(REQUEST_REGISTRY),
            "resume_freeze_hash": resume_freeze["freeze_hash"],
            "preflight_tool_sha256": _sha256(Path(__file__)),
        },
    }


def _verify_relative_record(record: dict[str, Any]) -> None:
    path = ROOT / record["path"]
    if (
        not path.exists()
        or path.stat().st_size != int(record["bytes"])
        or _sha256(path) != record["sha256"]
    ):
        raise ValueError(f"Sealed relative record changed: {path}")


def _without_hash(value: dict[str, Any], key: str) -> str:
    return _canonical_hash({name: item for name, item in value.items() if name != key})


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
