#!/usr/bin/env python3
"""Freeze Step 5D-R1 before any row-level source metadata is read."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
PROTOCOL_PATH = MANIFESTS / "gc_microstructure_step_5dr1_protocol_v01.json"
FREEZE_PATH = MANIFESTS / "gc_microstructure_step_5dr1_freeze_v01.json"

BOUND = {
    "step5d_final_seal": (
        ARTIFACTS / "gc_microstructure_step5d_v01" / "final_seal.json",
        "17f2a97487c72cf447eed34b6dabda558af7f88671fc845316139c2a1c71c2db",
    ),
    "step5d_manifest": (
        ARTIFACTS / "gc_microstructure_step5d_v01" / "manifest.json",
        "3bf05208cd89dc7ec8743d8daaa40799134521faac2ea5cc620a719ba50a8eda",
    ),
    "step5d_failure": (
        ARTIFACTS / "gc_microstructure_step5d_v01" / "outcome_opening_failure.json",
        "44f32d8da4e58d19f1f4e2d2a9fccace63457f75fa58370e119d0b5273090805",
    ),
    "step5d_verdict": (
        ARTIFACTS / "gc_microstructure_step5d_v01" / "verdict.json",
        "3ec082a95bd48cb412b9771eaae8cffd1641593c7ad60b033da3c9a95a6994ef",
    ),
    "step5d_protocol": (
        MANIFESTS / "gc_microstructure_step_5d_protocol_v01.json",
        "835361070b3955912938b5519ec0b7b32542d6774c895f43bde11a93fb268b64",
    ),
    "step5d_test_registry": (
        MANIFESTS / "gc_microstructure_step_5d_test_registry_v01.json",
        "e3b7a132f03cebaff4c05cc646e00f0b1867881d0109c65b71f1076e74ab2d4a",
    ),
    "casebook_manifest": (
        ARTIFACTS / "gold_casebook_v01" / "manifest.json",
        "38e4aadc43917a5b91d04d47ab18542d7514fe257cc030f959d34080865314d6",
    ),
    "price_bar_source": (
        ARTIFACTS / "gold_casebook_v01" / "price_bars.jsonl.gz",
        "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e",
    ),
    "session_source": (
        ARTIFACTS / "gold_casebook_v01" / "sessions.jsonl.gz",
        "2695a2c0b9e8f41fcbf64c9f388e8883ebf7e1f0b3b09b90fb3a60ba7e64966a",
    ),
    "casebook_builder_rules": (
        ROOT / "backend" / "src" / "gold_intel" / "analytics" / "casebook.py",
        "fa4370052d4ffdc9ec144009373d427c13477a4b4bbfc31bf72eaeb737f381e3",
    ),
    "v3_outcome_rules": (
        ROOT / "backend" / "src" / "gold_intel" / "analytics" / "session_behaviour_v3.py",
        "33d53780a2db17f5cb8940bf3251797ddf273531f8b64ed330b7cb892c5115be",
    ),
    "v3_case_builder": (
        ROOT / "backend" / "tools" / "build_gold_session_behaviour_v3_case_matrix.py",
        "1e24762f388e4e8cf5a20c64544995079a831f0d4d7d4b5ca01c6aa0641ada68",
    ),
}


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


def main() -> None:
    if PROTOCOL_PATH.exists() or FREEZE_PATH.exists():
        raise FileExistsError("Step 5D-R1 was already frozen")
    for name, (path, expected) in BOUND.items():
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"Predecessor seal failed: {name} {actual}")
    failure = load_json(BOUND["step5d_failure"][0])
    if failure.get("status") != "FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE":
        raise ValueError("Step 5D failure is not preserved")
    if failure.get("source_stream_open_count") != 1:
        raise ValueError("Step 5D single-opening record changed")
    missing = sorted(
        (
            {"session_date": str(item["session_date"]), "session_code": str(item["session_code"])}
            for item in failure["missing_keys"]
        ),
        key=lambda item: (item["session_date"], item["session_code"]),
    )
    if len(missing) != 16:
        raise ValueError("Frozen missing-key count changed")

    frozen_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    protocol: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R1_PROTOCOL_V0_1",
        "status": "FROZEN_BEFORE_ROW_LEVEL_SOURCE_METADATA_ACCESS",
        "classification": "METADATA_ONLY_OUTCOME_COVERAGE_DIAGNOSTIC",
        "frozen_at_utc": frozen_at,
        "authority": {
            "authorized_step": "STEP_5D_R1",
            "authorized_keys": missing,
            "authorized_sources": ["sealed gold_casebook_v01 price_bars metadata", "sealed gold_casebook_v01 sessions metadata"],
            "mandatory_stop": "Stop after independently reproduced classifications and one-or-zero bounded recovery recommendation are sealed.",
        },
        "preserved_history": {
            "step5d_status": "FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE",
            "source_stream_open_count": 1,
            "tests_and_seeds_unchanged": 148,
            "stage_1_tests_executed": 0,
            "stage_2_tests_executed": 0,
            "all_prior_artifacts_immutable": True,
        },
        "source_bindings": {
            name: {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": expected}
            for name, (path, expected) in BOUND.items()
        },
        "allowed_metadata_fields": {
            "price_bar": [
                "record_type",
                "record_id",
                "record_hash",
                "provider_code",
                "instrument_code",
                "timeframe",
                "open_time",
                "close_time",
                "available_at",
                "ingested_at",
                "complete",
                "missing_source_minutes",
                "epistemic_status",
                "calculation_version",
                "source.batch_id",
                "source.source_record_key",
                "source.source_count",
                "source.source_hash",
                "source.first_source_open",
                "source.last_source_open",
                "source.source_batch_count"
            ],
            "session": [
                "record_type",
                "record_id",
                "record_hash",
                "session_date",
                "session_code",
                "session_timezone",
                "decision_at",
                "observation_end",
                "availability_at",
                "data_quality.status",
                "data_quality.five_minute_bar_count",
                "data_quality.one_minute_bar_count_implied"
            ],
            "forbidden": [
                "ohlc",
                "open high low close price values",
                "volume",
                "spread_points",
                "spread_price",
                "signed displacement",
                "direction",
                "return",
                "excursion",
                "subsequent behaviour values"
            ]
        },
        "time_rules": {
            "timezone_conversion": "Python IANA zoneinfo independently for Europe/London, America/New_York, and Asia/Tokyo; no hard-coded DST offsets.",
            "neutral_outcome_window": {
                "start_open_local": "08:01:00",
                "final_close_local": "12:00:00",
                "timeframe": "1m",
                "expected_open_timestamps": 239,
                "expected_first_open": "decision_at plus one minute",
                "expected_last_open": "observation_end minus one minute"
            },
            "case_builder_5m_windows": {
                "ASIA": {"timezone": "Asia/Tokyo", "start": "10:05:00", "end": "16:00:00", "expected": 71},
                "LONDON": {"timezone": "Europe/London", "start": "08:00:00", "end": "12:00:00", "expected": 48},
                "NEW_YORK": {"timezone": "America/New_York", "start": "08:00:00", "end": "12:00:00", "expected": 48}
            }
        },
        "exact_tests": {
            "session_record": [
                "exact session_date plus session_code presence/absence",
                "timezone decision_at and observation_end equal IANA-derived clocks",
                "record identity and hash fields are structurally present"
            ],
            "one_minute_recoverability": [
                "exactly one XAUUSD IC_MARKETS_MT5 1m record for every one of 239 expected open timestamps",
                "no duplicate expected timestamp",
                "complete is true",
                "close_time equals open_time plus one minute",
                "available_at is no later than close_time",
                "missing_source_minutes equals zero",
                "record_id record_hash batch_id source_record_key and source_hash are structurally present",
                "no unexpected 1m record is counted as support"
            ],
            "case_builder_exclusion": [
                "derive exact expected 5m timestamps for Asia London and New York",
                "test unique complete contiguous records close_time and available_at metadata",
                "London emission requires complete Asia and London windows",
                "New York emission requires complete Asia London and New York windows",
                "compare deterministic predicted emission against sealed session-record presence"
            ],
            "holiday": [
                "weekday classification",
                "presence of any sealed XAUUSD timestamp metadata during the required day",
                "only a previously sealed official full-closure classification may produce DOCUMENTED_UNAVAILABLE",
                "absence of a sealed holiday classification is reported as NO_DOCUMENTED_FULL_CLOSURE, not proof of a normal schedule"
            ],
            "lineage": [
                "whole-artifact SHA-256 already sealed",
                "per-record record_id record_hash and source hash fields must be syntactically valid",
                "hash contents are not recomputed because doing so would require forbidden OHLC values"
            ]
        },
        "classification_rules": {
            "RECOVERABLE_EXISTING_SEALED_SOURCE": "All 239 exact one-minute timestamps pass every metadata and lineage-structure gate, regardless of why the five-minute session builder excluded the key.",
            "RECOVERABLE_TARGETED_MT5_REFRESH": "The key is not a documented closure and one or more required one-minute records are absent or metadata-ineligible, with no sealed corruption declaration preventing a targeted source refresh.",
            "DOCUMENTED_UNAVAILABLE": "A pre-existing sealed official calendar classification declares the complete required outcome window unavailable.",
            "GENUINE_SOURCE_GAP": "Sealed metadata explicitly declares a malformed/corrupt source interval or irrecoverable lineage failure.",
            "UNRESOLVED": "Metadata conflicts, parsers disagree, or none of the other rules resolves the key.",
            "precedence": ["UNRESOLVED", "DOCUMENTED_UNAVAILABLE", "GENUINE_SOURCE_GAP", "RECOVERABLE_EXISTING_SEALED_SOURCE", "RECOVERABLE_TARGETED_MT5_REFRESH"]
        },
        "independent_reproduction": {
            "primary": "Byte-regex metadata projection; forbidden value fields are never deserialized.",
            "reference": "Independent byte-level JSON scalar scanner; forbidden value fields are skipped and never deserialized.",
            "required_exact": [
                "all 16 key identities",
                "IANA-derived window timestamps",
                "session presence",
                "1m and 5m counts gaps duplicates validity and lineage-structure counts",
                "builder exclusion reasons",
                "holiday dispositions",
                "classifications",
                "complete-result checksum"
            ]
        },
        "recommendation_rule": {
            "maximum": 1,
            "all_existing": "Recommend a new separately authorized pre-value recovery amendment using only sealed one-minute records and the unchanged neutral-outcome formula.",
            "any_refresh": "Recommend a targeted IC Markets MT5 metadata-and-bar refresh only for deficient keys, followed by a new seal and coverage audit.",
            "any_unresolved_or_genuine_gap": "Recommend no research restart until a separate source-resolution protocol is approved.",
            "implementation_in_r1": False
        },
        "prohibited": [
            "opening or reporting OHLC volume spread direction displacement return excursion or outcome values",
            "reopening the 358 found Step 5D outcomes",
            "repair reconstruction refresh substitution acquisition or charge",
            "Stage 1 or Stage 2 relationship testing",
            "candidate creation or alteration of the 148-test registry",
            "2025 or 2026 value access",
            "execution trade PnL R multiple or return calculation"
        ]
    }
    protocol["protocol_hash"] = canonical_hash(protocol)
    write_json_exclusive(PROTOCOL_PATH, protocol)

    freeze: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R1_FREEZE_V0_1",
        "status": "SEALED_BEFORE_ROW_LEVEL_SOURCE_METADATA_ACCESS",
        "frozen_at_utc": frozen_at,
        "protocol": {
            "path": str(PROTOCOL_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(PROTOCOL_PATH),
            "protocol_hash": protocol["protocol_hash"]
        },
        "bound_predecessors": {name: expected for name, (_, expected) in BOUND.items()},
        "authorized_key_hash": canonical_hash(missing),
        "authorized_key_count": len(missing),
        "row_level_metadata_accessed_before_freeze": False,
        "market_or_outcome_values_accessed_before_freeze": False,
        "year_2025_or_2026_values_accessed": False,
        "next_action": "Run only the two frozen metadata projections, compare, classify, recommend at most one recovery path, seal, and stop."
    }
    freeze["freeze_receipt"] = canonical_hash(freeze)
    write_json_exclusive(FREEZE_PATH, freeze)
    print(json.dumps({
        "status": freeze["status"],
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "freeze_sha256": sha256_file(FREEZE_PATH),
        "freeze_receipt": freeze["freeze_receipt"],
        "authorized_keys": len(missing),
        "row_level_metadata_accessed": False
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
