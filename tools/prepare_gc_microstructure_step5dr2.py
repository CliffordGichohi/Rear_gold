#!/usr/bin/env python3
"""Freeze Step 5D-R2 before initializing or querying MetaTrader 5."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
PROTOCOL_PATH = MANIFESTS / "gc_microstructure_step_5dr2_recovery_protocol_v01.json"
FREEZE_PATH = MANIFESTS / "gc_microstructure_step_5dr2_recovery_freeze_v01.json"
IMPLEMENTATION_PATH = ROOT / "tools" / "recover_gc_microstructure_step5dr2.py"
TERMINAL_PATH = Path(r"C:\Program Files\MetaTrader 5\terminal64.exe")

BOUND = {
    "step5d_failure": (
        ARTIFACTS / "gc_microstructure_step5d_v01" / "outcome_opening_failure.json",
        "44f32d8da4e58d19f1f4e2d2a9fccace63457f75fa58370e119d0b5273090805",
    ),
    "step5d_verdict": (
        ARTIFACTS / "gc_microstructure_step5d_v01" / "verdict.json",
        "3ec082a95bd48cb412b9771eaae8cffd1641593c7ad60b033da3c9a95a6994ef",
    ),
    "step5dr1_protocol": (
        MANIFESTS / "gc_microstructure_step_5dr1_protocol_v01.json",
        "18c4637970505d6b2f58e74e7cc4f8bb862bf50e1336aa6fd62057eaac3536ac",
    ),
    "step5dr1_freeze": (
        MANIFESTS / "gc_microstructure_step_5dr1_freeze_v01.json",
        "3d2602f6c2efb8c2146835c8b877727d7a0a4bc82aa66d5617e08be18fc5b34d",
    ),
    "step5dr1_original_final_seal": (
        ARTIFACTS / "gc_microstructure_step5dr1_v01" / "final_seal.json",
        "d163c989e9c1008163c36732db026955c0a325ee57d2096adeaa5053e4848bf9",
    ),
    "step5dr1_corrected_manifest": (
        ARTIFACTS / "gc_microstructure_step5dr1_corrected_v01" / "manifest.json",
        "fe53160bd36f3d073b4250d65a23fbafb8f2beb48a580681f84c21049498af85",
    ),
    "step5dr1_corrected_final_seal": (
        ARTIFACTS / "gc_microstructure_step5dr1_corrected_v01" / "final_seal.json",
        "885d292f604669011a76b28bb649baf8389d7a2ecd59ff43d42abce08e9ae578",
    ),
    "step5dr1_corrected_verdict": (
        ARTIFACTS / "gc_microstructure_step5dr1_corrected_v01" / "verdict.json",
        "7737aeac938bb26d33391409d72c25c56f230582a9483c95e614c13e28145686",
    ),
    "step5dr1_corrected_primary": (
        ARTIFACTS / "gc_microstructure_step5dr1_corrected_v01" / "primary_corrected_diagnostic.json",
        "f7e3460e32df145a15b24696bd5db8d78c15069b85e002310c6685c47b37421c",
    ),
    "step5dr1_corrected_reference": (
        ARTIFACTS / "gc_microstructure_step5dr1_corrected_v01" / "reference_corrected_diagnostic.json",
        "3e81ae8e8d925f266c2a98c18061368ef534055ea0f52bfe5bd806776cbf7cb9",
    ),
    "existing_casebook_price_source": (
        ARTIFACTS / "gold_casebook_v01" / "price_bars.jsonl.gz",
        "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e",
    ),
}

REQUESTS = [
    {
        "request_id": "R2-20211213-NEW_YORK",
        "session_date": "2021-12-13",
        "session_code": "NEW_YORK",
        "session_timezone": "America/New_York",
        "start_utc_inclusive": "2021-12-13T13:01:00Z",
        "end_utc_exclusive": "2021-12-13T17:00:00Z",
    },
    {
        "request_id": "R2-20230315-NEW_YORK",
        "session_date": "2023-03-15",
        "session_code": "NEW_YORK",
        "session_timezone": "America/New_York",
        "start_utc_inclusive": "2023-03-15T12:01:00Z",
        "end_utc_exclusive": "2023-03-15T16:00:00Z",
    },
    {
        "request_id": "R2-20230815-LONDON",
        "session_date": "2023-08-15",
        "session_code": "LONDON",
        "session_timezone": "Europe/London",
        "start_utc_inclusive": "2023-08-15T07:01:00Z",
        "end_utc_exclusive": "2023-08-15T11:00:00Z",
    },
    {
        "request_id": "R2-20230913-NEW_YORK",
        "session_date": "2023-09-13",
        "session_code": "NEW_YORK",
        "session_timezone": "America/New_York",
        "start_utc_inclusive": "2023-09-13T12:01:00Z",
        "end_utc_exclusive": "2023-09-13T16:00:00Z",
    },
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed.astimezone(UTC)


def expected_timestamps(request: Mapping[str, str]) -> list[str]:
    cursor = parse_timestamp(request["start_utc_inclusive"])
    end = parse_timestamp(request["end_utc_exclusive"])
    output: list[str] = []
    while cursor < end:
        output.append(cursor.isoformat().replace("+00:00", "Z"))
        cursor += timedelta(minutes=1)
    if len(output) != 239:
        raise ValueError(f"Frozen request is not 239 minutes: {request['request_id']}")
    return output


def main() -> None:
    if PROTOCOL_PATH.exists() or FREEZE_PATH.exists():
        raise FileExistsError("Step 5D-R2 was already frozen")
    for name, (path, expected) in BOUND.items():
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"Predecessor seal failed: {name} {actual}")
    if not IMPLEMENTATION_PATH.is_file():
        raise FileNotFoundError(IMPLEMENTATION_PATH)
    if not TERMINAL_PATH.is_file():
        raise FileNotFoundError(TERMINAL_PATH)
    failure = load_json(BOUND["step5d_failure"][0])
    if failure.get("status") != "FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE":
        raise ValueError("Step 5D failure changed")
    if failure.get("source_stream_open_count") != 1:
        raise ValueError("Step 5D single source-opening record changed")
    primary = load_json(BOUND["step5dr1_corrected_primary"][0])
    reference = load_json(BOUND["step5dr1_corrected_reference"][0])
    if primary["result_checksum"] != reference["result_checksum"]:
        raise ValueError("Corrected R1 reproductions disagree")
    if primary["result_checksum"] != "461dd90a7c9e37547cce4b2c515122ecef2896b1d24729c306284080f0382348":
        raise ValueError("Corrected R1 result changed")
    all_keys = [
        {"session_date": str(item["session_date"]), "session_code": str(item["session_code"])}
        for item in primary["result"]["keys"]
    ]
    all_keys.sort(key=lambda item: (item["session_date"], item["session_code"]))
    if len(all_keys) != 16:
        raise ValueError("R1 missing-key population changed")
    refresh_keys = {(item["session_date"], item["session_code"]) for item in REQUESTS}
    r1_refresh_keys = {
        (str(item["session_date"]), str(item["session_code"]))
        for item in primary["result"]["keys"]
        if item["classification"] == "RECOVERABLE_TARGETED_MT5_REFRESH"
    }
    if refresh_keys != r1_refresh_keys:
        raise ValueError("Authorized refresh keys differ from corrected R1")
    existing_keys = [item for item in all_keys if (item["session_date"], item["session_code"]) not in refresh_keys]
    if len(existing_keys) != 12:
        raise ValueError("Expected exactly twelve existing-source keys")

    requests: list[dict[str, Any]] = []
    for request in REQUESTS:
        timestamps = expected_timestamps(request)
        requests.append({
            **request,
            "expected_open_timestamp_count": len(timestamps),
            "expected_first_open": timestamps[0],
            "expected_last_open": timestamps[-1],
            "expected_open_timestamp_hash": canonical_hash(timestamps),
            "mt5_copy_rates_date_to_inclusive": timestamps[-1],
        })
    frozen_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    protocol: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R2_RECOVERY_PROTOCOL_V0_1",
        "status": "SEALED_BEFORE_MT5_ACCESS",
        "classification": "BOUNDED_OUTCOME_COVERAGE_RECOVERY_AND_METADATA_CERTIFICATION",
        "frozen_at_utc": frozen_at,
        "authority": {
            "authorized_step": "STEP_5D_R2",
            "authorized_provider": "IC_MARKETS_MT5",
            "authorized_instrument": "XAUUSD",
            "authorized_timeframe": "1m",
            "authorized_request_count": 4,
            "charge_authorized": False,
            "mandatory_stop": "Stop after recovery, sixteen-key metadata certification, documentation, and sealing. Do not calculate outcomes or resume research.",
        },
        "preserved_history": {
            "step5d_status": "FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE",
            "step5d_source_stream_open_count": 1,
            "step5dr1_corrected_status": "PASS_STEP_5D_R1_DIAGNOSTIC_REPRODUCTION_AFTER_IMPLEMENTATION_CORRECTION",
            "step5dr1_result_checksum": primary["result_checksum"],
            "previously_found_outcomes": 358,
            "existing_casebook_immutable": True,
            "all_prior_verdicts_and_artifacts_immutable": True,
        },
        "predecessor_bindings": {
            name: {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": expected}
            for name, (path, expected) in BOUND.items()
        },
        "implementation": {
            "path": str(IMPLEMENTATION_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(IMPLEMENTATION_PATH),
            "synthetic_self_test_required_before_freeze": True,
            "modification_after_freeze_prohibited": True,
        },
        "mt5_source": {
            "terminal_path": str(TERMINAL_PATH),
            "terminal_executable_sha256": sha256_file(TERMINAL_PATH),
            "account_session": "Reuse only the already logged-in local terminal session; do not store an account identifier or credential.",
            "broker_identity_gate": "Connected account company or server metadata must identify IC Markets.",
            "symbol_gate": "XAUUSD must be selectable from the connected terminal.",
            "operation": "Read-only copy_rates_range; order_send is forbidden.",
            "provider_availability_semantics": "Historical one-minute bar is market-known at close_time; capture ingested_at records the later recovery timestamp separately.",
        },
        "recovery_requests": requests,
        "source_capture": {
            "request_policy": "Exactly four copy_rates_range calls, one per frozen request, with inclusive start and inclusive expected last-open timestamp.",
            "row_policy": "Retain only rows whose open timestamp is one of the 239 authorized timestamps for that request.",
            "raw_policy": "Serialize provider rows without modification into a deterministic gzip JSONL capture; values remain sealed and unreported.",
            "normalized_policy": "Create a separate deterministic versioned PRICE_BAR JSONL bundle with observed OHLC/volume/spread retained, source lineage, close_time, market available_at, recovery ingested_at, source hash, and record hash.",
            "versioning_policy": "Never update, append to, or overwrite gold_casebook_v01. The complete refreshed four-window source is a new immutable Step 5D-R2 version.",
            "selection_policy": "For each of the four refresh keys, use the complete versioned refresh window as one source; never cherry-pick or splice only missing minutes. The other twelve keys remain bound to gold_casebook_v01.",
            "human_value_inspection": False,
        },
        "metadata_integrity_gates": [
            "exactly 239 unique open timestamps per refreshed request",
            "first and last opens equal the frozen endpoints",
            "one-minute contiguous timestamp grid with no duplicates",
            "provider IC_MARKETS_MT5 instrument XAUUSD timeframe 1m",
            "complete=true and missing_source_minutes=0",
            "close_time equals open_time plus one minute",
            "available_at is no later than close_time",
            "record_id record_hash batch_id source_record_key and source_hash are structurally valid",
            "raw and normalized row counts both equal 956",
            "raw normalized manifests and complete lineage are hashed and sealed",
            "no existing casebook artifact changes",
        ],
        "coverage_audit": {
            "all_16_keys": all_keys,
            "existing_source_keys": existing_keys,
            "refreshed_source_keys": [
                {"session_date": item["session_date"], "session_code": item["session_code"]}
                for item in requests
            ],
            "neutral_window": "08:01 through the 11:59 bar closing at 12:00 in the session IANA timezone; exactly 239 one-minute records.",
            "dst_method": "Python IANA zoneinfo using Europe/London or America/New_York; UTC endpoints and complete expected timestamp hashes are frozen before MT5 access.",
            "reproduction": "Primary byte-regex and independent structural byte-scanner projections must produce identical sixteen-key results and checksums without deserializing OHLC values.",
            "existing_358_outcomes_reopened": False,
            "pass_rule": "PASS only if all four refresh requests are exact and all sixteen missing keys are metadata-constructible, yielding 374 of 374 required non-holiday outcomes under the unchanged neutral definition.",
        },
        "failure_rules": {
            "mt5_preflight": "Seal FAIL_STEP_5D_R2_MT5_PREFLIGHT if terminal, account lineage, or XAUUSD is unavailable.",
            "coverage_or_integrity": "Seal FAIL_STEP_5D_R2_RECOVERY_OR_METADATA_CERTIFICATION if any timestamp, lineage, source-count, reproduction, or 374/374 gate fails.",
            "no_repair_or_substitution": True,
        },
        "prohibited": [
            "human inspection or reporting of OHLC volume spread displacement direction return or outcome values",
            "modification of gold_casebook_v01 or any predecessor artifact",
            "substitution of another provider symbol instrument or timeframe",
            "construction or joining of outcomes",
            "opening the 358 previously found outcomes",
            "Stage 1 or Stage 2 tests relationships candidates signals or retuning",
            "2025 or 2026 value access",
            "execution optimization trades PnL R multiples or returns",
            "orders payments charges or paid acquisition",
        ],
    }
    protocol["protocol_hash"] = canonical_hash(protocol)
    write_json_exclusive(PROTOCOL_PATH, protocol)
    freeze: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R2_RECOVERY_FREEZE_V0_1",
        "status": "SEALED_BEFORE_MT5_ACCESS",
        "frozen_at_utc": frozen_at,
        "protocol": {
            "path": str(PROTOCOL_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(PROTOCOL_PATH),
            "protocol_hash": protocol["protocol_hash"],
        },
        "implementation": protocol["implementation"],
        "terminal_executable_sha256": protocol["mt5_source"]["terminal_executable_sha256"],
        "request_registry_hash": canonical_hash(requests),
        "all_16_key_hash": canonical_hash(all_keys),
        "predecessor_hashes": {name: expected for name, (_, expected) in BOUND.items()},
        "mt5_initialized_or_queried_before_freeze": False,
        "row_level_market_data_accessed_before_freeze": False,
        "outcome_values_accessed": False,
        "next_action": "Run the frozen implementation once, seal PASS or FAIL, and stop.",
    }
    freeze["freeze_receipt"] = canonical_hash(freeze)
    write_json_exclusive(FREEZE_PATH, freeze)
    print(json.dumps({
        "status": freeze["status"],
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "freeze_sha256": sha256_file(FREEZE_PATH),
        "freeze_receipt": freeze["freeze_receipt"],
        "implementation_sha256": protocol["implementation"]["sha256"],
        "authorized_requests": len(requests),
        "authorized_timestamps": sum(item["expected_open_timestamp_count"] for item in requests),
        "mt5_accessed": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
