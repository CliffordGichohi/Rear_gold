from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audit_gold_session_behaviour_v3_m6a import (
    build_audit_report,
    collect_metadata_snapshot,
    validate_audit_report,
)
from sqlalchemy import text

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.session_behaviour_v3 import sha256_file
from gold_intel.analytics.session_behaviour_v3_m6a import (
    protocol_fingerprint,
)
from gold_intel.analytics.session_behaviour_v3_m6b import validate_m6b_freeze
from gold_intel.infrastructure.database import session_factory

SNAPSHOT_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M6B_SOURCE_SNAPSHOT_V0_1"
PREOPEN_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M6B_PREOPEN_MANIFEST_V0_1"
EXPECTED_V06A_STATE_HASH = (
    "fa8963661bb3a6e8eff1d95dac1c713015882019f6b2ba6937bc398d1ae85629"
)
EXPECTED_V06A_FILE_SHA256 = (
    "55aab7af7b3f08eb66a560697be7dc53497971ba9ec229ea8d49691dff048a66"
)
SOURCE_START = "2024-01-01T00:00:00+00:00"
SOURCE_END = "2026-07-30T00:00:00+00:00"

PRICE_SOURCE_SQL = """
SELECT
    id::text AS record_id,
    open_time,
    close_time,
    provider_code,
    instrument_code,
    timeframe,
    open::text AS open,
    high::text AS high,
    low::text AS low,
    close::text AS close,
    volume::text AS volume,
    volume_type,
    spread_points,
    spread_price::text AS spread_price,
    available_at,
    batch_id::text AS batch_id,
    source_record_key,
    is_complete,
    is_synthetic
FROM market.price_bars
WHERE provider_code = 'IC_MARKETS_MT5'
  AND instrument_code = 'XAUUSD'
  AND timeframe = '1m'
  AND open_time >= CAST(:price_start AS timestamptz)
  AND open_time < CAST(:source_end AS timestamptz)
ORDER BY open_time, available_at, id
"""

OBSERVATION_SOURCE_SQL = """
SELECT
    id::text AS record_id,
    observation_time,
    series_code,
    value::text AS value,
    unit,
    available_at,
    vintage,
    is_revision,
    supersedes_id::text AS supersedes_id,
    batch_id::text AS batch_id,
    source_record_key,
    is_synthetic
FROM market.observations
WHERE series_code IN ('US_VOLATILITY_INDEX', 'US_FINANCIAL_STRESS')
  AND observation_time >= CAST(:source_start AS timestamptz)
  AND available_at < CAST(:source_end AS timestamptz)
ORDER BY series_code, observation_time, available_at, vintage, id
"""

SOURCE_INTEGRITY_SQL = """
WITH price_duplicates AS (
    SELECT count(*) AS duplicate_groups
    FROM (
        SELECT
            provider_code,
            instrument_code,
            timeframe,
            open_time,
            available_at
        FROM market.price_bars
        WHERE provider_code = 'IC_MARKETS_MT5'
          AND instrument_code = 'XAUUSD'
          AND timeframe = '1m'
          AND open_time >= CAST(:price_start AS timestamptz)
          AND open_time < CAST(:source_end AS timestamptz)
        GROUP BY 1, 2, 3, 4, 5
        HAVING count(*) > 1
    ) duplicated
),
observation_duplicates AS (
    SELECT count(*) AS duplicate_groups
    FROM (
        SELECT series_code, observation_time, available_at, vintage
        FROM market.observations
        WHERE series_code IN (
            'US_VOLATILITY_INDEX',
            'US_FINANCIAL_STRESS'
        )
          AND observation_time >= CAST(:source_start AS timestamptz)
          AND available_at < CAST(:source_end AS timestamptz)
        GROUP BY 1, 2, 3, 4
        HAVING count(*) > 1
    ) duplicated
)
SELECT
    (SELECT duplicate_groups FROM price_duplicates)
        AS duplicate_price_natural_keys,
    (SELECT duplicate_groups FROM observation_duplicates)
        AS duplicate_observation_natural_keys
"""

BATCH_LINEAGE_SQL = """
WITH selected_batch_ids AS (
    SELECT DISTINCT batch_id
    FROM market.price_bars
    WHERE provider_code = 'IC_MARKETS_MT5'
      AND instrument_code = 'XAUUSD'
      AND timeframe = '1m'
      AND open_time >= CAST(:price_start AS timestamptz)
      AND open_time < CAST(:source_end AS timestamptz)
    UNION
    SELECT DISTINCT batch_id
    FROM market.observations
    WHERE series_code IN (
        'US_VOLATILITY_INDEX',
        'US_FINANCIAL_STRESS'
    )
      AND observation_time >= CAST(:source_start AS timestamptz)
      AND available_at < CAST(:source_end AS timestamptz)
)
SELECT
    batch.id::text AS batch_id,
    batch.provider_code,
    batch.dataset_code,
    batch.schema_version,
    batch.content_hash,
    batch.raw_object_path,
    batch.status,
    batch.record_count,
    batch.is_synthetic,
    batch.source_published_at,
    batch.ingested_at
FROM raw.ingestion_batches batch
JOIN selected_batch_ids selected ON selected.batch_id = batch.id
ORDER BY batch.provider_code, batch.dataset_code, batch.ingested_at, batch.id
"""

IMPLEMENTATION_PATHS = (
    "backend/src/gold_intel/analytics/session_behaviour_v3_m6b.py",
    "backend/tools/refresh_gold_session_behaviour_v3_m6b_sources.py",
    "backend/tools/seal_gold_session_behaviour_v3_m6b_sources.py",
    "backend/tools/run_gold_session_behaviour_v3_m6b.py",
    "backend/tools/validate_gold_session_behaviour_v3_m6b.py",
    "backend/tests/unit/test_session_behaviour_v3_m6b.py",
)


async def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    output_dir = (root / args.output_dir).resolve()
    state_path = (root / args.state).resolve()
    preopen_manifest_path = (root / args.preopen_manifest).resolve()
    for path in (output_dir, state_path, preopen_manifest_path):
        _assert_within(root, path)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("M6B source snapshot directory is not empty")
    if preopen_manifest_path.exists():
        raise FileExistsError("M6B pre-open manifest already exists")
    for relative in IMPLEMENTATION_PATHS:
        if not (root / relative).is_file():
            raise FileNotFoundError(f"Missing frozen M6B implementation: {relative}")

    predecessor = _verify_v06a(root=root, state_path=state_path)
    if validate_m6b_freeze():
        raise ValueError(f"M6B frozen design failed: {validate_m6b_freeze()}")

    m6a_manifest_path = (
        root
        / "research_manifests"
        / "gold_session_behaviour_v3_m6a_amendment_b_v01.json"
    )
    m6a_manifest = _load_json(m6a_manifest_path)
    metadata = await collect_metadata_snapshot()
    readiness = build_audit_report(
        metadata_snapshot=metadata,
        pre_manifest=m6a_manifest,
        pre_manifest_path=m6a_manifest_path,
        generated_at=datetime.now(UTC).isoformat(),
    )
    readiness_checks = validate_audit_report(
        readiness,
        pre_manifest=m6a_manifest,
    )
    failed_readiness_checks = [
        item for item in readiness_checks if item["status"] != "PASS"
    ]
    if failed_readiness_checks:
        raise ValueError(
            f"Repeated metadata audit failed: {failed_readiness_checks}"
        )
    if not readiness["readiness_decision"][
        "all_historical_candidate_partition_metadata_gates_pass"
    ]:
        raise ValueError("Repeated M6B metadata readiness gates did not pass")

    source_snapshot = await _source_snapshot()
    if source_snapshot["source_integrity"][
        "duplicate_price_natural_keys"
    ]:
        raise ValueError("Duplicate price natural keys in final source snapshot")
    if source_snapshot["source_integrity"][
        "duplicate_observation_natural_keys"
    ]:
        raise ValueError(
            "Duplicate observation natural keys in final source snapshot"
        )
    if set(source_snapshot["lineage"]["provider_codes"]) != {
        "FRED_PUBLIC",
        "IC_MARKETS_MT5",
    }:
        raise ValueError("Final source lineage contains an unauthorized provider")
    if source_snapshot["lineage"]["synthetic_batch_count"] != 0:
        raise ValueError("Final source lineage includes synthetic batches")

    output_dir.mkdir(parents=True, exist_ok=True)
    readiness_path = output_dir / "metadata_readiness_audit.json"
    source_path = output_dir / "source_snapshot.json"
    manifest_path = output_dir / "manifest.json"
    _write_json(readiness_path, readiness)
    _write_json(source_path, source_snapshot)

    implementation = {
        relative: sha256_file(root / relative)
        for relative in IMPLEMENTATION_PATHS
    }
    preopen: dict[str, Any] = {
        "manifest_version": PREOPEN_VERSION,
        "milestone": "V3_M6B_ONE_TIME_FORWARD_VALUE_EVALUATION",
        "created_at": datetime.now(UTC).isoformat(),
        "authorization": {
            "source_refresh_permitted": [
                "IC_MARKETS_MT5_XAUUSD",
                "US_VOLATILITY_INDEX",
                "US_FINANCIAL_STRESS",
            ],
            "paid_acquisition_permitted": False,
            "calendar_2025_open_once_permitted_after_this_seal": True,
            "calendar_2026_ytd_open_once_after_2025_seal_permitted": True,
            "prospective_ledger_initialization_permitted": True,
        },
        "predecessor": predecessor,
        "protocol_fingerprint": protocol_fingerprint(),
        "implementation_freeze": implementation,
        "source_snapshot": {
            "path": _portable(source_path),
            "source_snapshot_hash": source_snapshot["source_snapshot_hash"],
            "file_sha256": sha256_file(source_path),
            "machine_hashed_without_human_value_inspection": True,
        },
        "metadata_readiness": {
            "path": _portable(readiness_path),
            "readiness_audit_hash": readiness["readiness_audit_hash"],
            "file_sha256": sha256_file(readiness_path),
            "all_historical_candidate_partition_metadata_gates_pass": True,
        },
        "research_boundary": {
            "candidate_codes": [
                "LONDON_VOLATILITY_DIRECTION_V0_1",
                "NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1",
            ],
            "candidate_definitions_changed": False,
            "new_variables_or_candidates": 0,
            "execution_variants": 0,
            "trades_or_returns": 0,
            "cot_used_as_pass_gate": False,
            "paid_acquisition": False,
            "forward_candidate_states_outcomes_or_relationships_calculated": False,
            "source_payloads_machine_hashed": True,
            "source_values_printed_or_human_inspected": False,
        },
        "verdict": "PASS_M6B_PREOPEN_SOURCE_AND_IMPLEMENTATION_SEAL",
        "manifest_hash": "",
    }
    preopen["manifest_hash"] = _embedded_hash(preopen, "manifest_hash")
    _write_json(preopen_manifest_path, preopen)

    manifest: dict[str, Any] = {
        "manifest_version": SNAPSHOT_VERSION,
        "milestone": "V3_M6B_FINAL_SOURCE_SNAPSHOT_PRE_OPEN",
        "created_at": preopen["created_at"],
        "artifacts": [
            _artifact(readiness_path),
            _artifact(source_path),
            _artifact(preopen_manifest_path),
        ],
        "source_snapshot_hash": source_snapshot["source_snapshot_hash"],
        "preopen_manifest_hash": preopen["manifest_hash"],
        "values_printed_or_human_inspected": False,
        "candidate_states_outcomes_or_relationships_calculated": False,
        "verdict": "PASS_M6B_FINAL_SOURCE_SNAPSHOT_SEALED",
        "manifest_hash": "",
    }
    manifest["manifest_hash"] = _embedded_hash(manifest, "manifest_hash")
    _write_json(manifest_path, manifest)
    print(
        json.dumps(
            {
                "metadata_readiness_verdict": readiness[
                    "readiness_decision"
                ]["verdict"],
                "source_snapshot_hash": source_snapshot[
                    "source_snapshot_hash"
                ],
                "preopen_manifest_hash": preopen["manifest_hash"],
                "manifest_hash": manifest["manifest_hash"],
                "paid_acquisition": False,
                "source_values_printed_or_human_inspected": False,
                "forward_results_calculated": False,
                "verdict": manifest["verdict"],
            },
            indent=2,
            sort_keys=True,
        )
    )


async def _source_snapshot() -> dict[str, Any]:
    parameters = {
        "price_start": datetime(2025, 1, 1, tzinfo=UTC),
        "source_start": datetime.fromisoformat(SOURCE_START),
        "source_end": datetime.fromisoformat(SOURCE_END),
    }
    async with session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        price_hash, price_count = await _hash_stream(
            session,
            PRICE_SOURCE_SQL,
            parameters,
        )
        observation_hash, observation_count = await _hash_stream(
            session,
            OBSERVATION_SOURCE_SQL,
            parameters,
        )
        integrity_row = (
            await session.execute(text(SOURCE_INTEGRITY_SQL), parameters)
        ).mappings().one()
        lineage_rows = (
            await session.execute(text(BATCH_LINEAGE_SQL), parameters)
        ).mappings().all()
        await session.rollback()
    lineage = [
        {str(key): json_ready(value) for key, value in row.items()}
        for row in lineage_rows
    ]
    snapshot: dict[str, Any] = {
        "snapshot_version": SNAPSHOT_VERSION,
        "sealed_range": {
            "price_start_inclusive": "2025-01-01T00:00:00+00:00",
            "observation_start_inclusive": SOURCE_START,
            "all_sources_end_exclusive": SOURCE_END,
            "historical_session_end_inclusive": "2026-07-29",
        },
        "source_payload_digests": {
            "ic_markets_mt5_xauusd_1m": {
                "row_count": price_count,
                "stream_sha256": price_hash,
                "query_sha256": hashlib.sha256(
                    PRICE_SOURCE_SQL.encode()
                ).hexdigest(),
            },
            "fred_candidate_observations": {
                "row_count": observation_count,
                "stream_sha256": observation_hash,
                "query_sha256": hashlib.sha256(
                    OBSERVATION_SOURCE_SQL.encode()
                ).hexdigest(),
                "series_codes": [
                    "US_VOLATILITY_INDEX",
                    "US_FINANCIAL_STRESS",
                ],
            },
        },
        "source_integrity": {
            str(key): int(value)
            for key, value in integrity_row.items()
        },
        "lineage": {
            "batch_count": len(lineage),
            "provider_codes": sorted(
                {str(item["provider_code"]) for item in lineage}
            ),
            "dataset_codes": sorted(
                {str(item["dataset_code"]) for item in lineage}
            ),
            "synthetic_batch_count": sum(
                bool(item["is_synthetic"]) for item in lineage
            ),
            "noncompleted_batch_count": sum(
                not str(item["status"]).startswith("COMPLETED")
                for item in lineage
            ),
            "batch_records": lineage,
            "batch_records_hash": canonical_hash(lineage),
        },
        "seal_method": {
            "row_payload_values_machine_read_for_hashing": True,
            "row_payload_values_printed_or_human_inspected": False,
            "candidate_states_calculated": False,
            "session_outcomes_calculated": False,
            "relationships_or_verdicts_calculated": False,
            "stream_format": "CANONICAL_SORTED_COMPACT_JSON_PER_ROW_PLUS_LF",
        },
        "paid_acquisition": False,
        "source_snapshot_hash": "",
    }
    snapshot["source_snapshot_hash"] = _embedded_hash(
        snapshot,
        "source_snapshot_hash",
    )
    return snapshot


async def _hash_stream(
    session: Any,
    statement: str,
    parameters: Mapping[str, Any],
) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    result = await session.stream(
        text(statement).execution_options(yield_per=5000),
        dict(parameters),
    )
    async for row in result.mappings():
        encoded = json.dumps(
            json_ready(dict(row)),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        digest.update(encoded)
        digest.update(b"\n")
        count += 1
    return digest.hexdigest(), count


def _verify_v06a(*, root: Path, state_path: Path) -> dict[str, Any]:
    if sha256_file(state_path) != EXPECTED_V06A_FILE_SHA256:
        raise ValueError("V06A state file seal mismatch")
    state = _load_json(state_path)
    actual_state_hash = canonical_hash(
        {
            key: value
            for key, value in state.items()
            if key not in {"generated_at", "state_hash"}
        }
    )
    if (
        actual_state_hash != EXPECTED_V06A_STATE_HASH
        or state.get("state_hash") != EXPECTED_V06A_STATE_HASH
    ):
        raise ValueError("V06A embedded state hash mismatch")
    failures = []
    for output in state["milestone_6a_outputs"]:
        path = (root / str(output["path"])).resolve()
        _assert_within(root, path)
        if not path.is_file() or sha256_file(path) != output["sha256"]:
            failures.append(str(output["path"]))
    if failures:
        raise ValueError(f"V06A predecessor output seal mismatch: {failures}")
    if state["contract"]["protocol_fingerprint"] != protocol_fingerprint():
        raise ValueError("V06A protocol fingerprint mismatch")
    return {
        "path": _portable(state_path),
        "file_sha256": sha256_file(state_path),
        "state_hash": state["state_hash"],
        "output_seals_verified": len(state["milestone_6a_outputs"]),
        "output_seal_failures": 0,
    }


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": _portable(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _embedded_hash(document: Mapping[str, Any], field: str) -> str:
    return canonical_hash(
        {key: value for key, value in document.items() if key != field}
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_ready(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _portable(path: Path) -> str:
    return str(path).replace("\\", "/")


def _assert_within(root: Path, path: Path) -> None:
    if path != root and root not in path.parents:
        raise ValueError(f"Path must remain inside repository root: {path}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Repeat M6B metadata readiness, hash the final permitted source "
            "snapshot without human value inspection, and seal the evaluator."
        )
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--state",
        default="research_artifacts/gold_session_behaviour_v3_state_v06a.json",
    )
    parser.add_argument(
        "--output-dir",
        default=(
            "research_artifacts/"
            "gold_session_behaviour_v3_m6b_source_snapshot_v01"
        ),
    )
    parser.add_argument(
        "--preopen-manifest",
        default=(
            "research_manifests/"
            "gold_session_behaviour_v3_m6b_preopen_v01.json"
        ),
    )
    return parser


if __name__ == "__main__":
    asyncio.run(main())
