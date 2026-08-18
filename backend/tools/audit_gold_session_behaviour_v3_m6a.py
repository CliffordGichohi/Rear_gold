from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.casebook_discovery_v3 import (
    EXPOSED_2025_END,
    EXPOSED_2025_START,
    LOCKED_2026_YTD_END,
    LOCKED_2026_YTD_START,
    assert_metadata_only_sql,
    audit_timestamp_only_session_coverage,
)
from gold_intel.analytics.session_behaviour_v3 import sha256_file
from gold_intel.analytics.session_behaviour_v3_m6a import (
    M5_SHORTLIST_CODES,
    M6A_AUDIT_VERSION,
    M6A_PROTOCOL_VERSION,
    assess_candidate_partition_metadata,
    forward_candidate_registry,
    forward_protocol,
    prospective_metadata_plan,
    protocol_fingerprint,
    validate_forward_protocol,
)
from gold_intel.infrastructure.database import session_factory

RESULT_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M6A_READINESS_RESULT_V0_1"
BUILD_VALIDATION_VERSION = (
    "GOLD_SESSION_BEHAVIOUR_V3_M6A_BUILD_VALIDATION_V0_1"
)

PRICE_METADATA_SQL = """
SELECT
    provider_code,
    instrument_code,
    timeframe,
    count(*) AS rows,
    count(DISTINCT open_time) AS distinct_open_times,
    min(open_time) AS first_open_time,
    max(open_time) AS last_open_time,
    min(available_at) AS first_available_at,
    max(available_at) AS last_available_at,
    count(*) FILTER (WHERE available_at <= close_time) AS valid_availability_rows,
    count(*) FILTER (WHERE NOT is_complete) AS incomplete_rows,
    count(*) FILTER (WHERE is_synthetic) AS synthetic_rows
FROM market.price_bars
WHERE provider_code = 'IC_MARKETS_MT5'
  AND instrument_code = 'XAUUSD'
  AND timeframe = '1m'
  AND open_time >= :start
  AND open_time < :end
GROUP BY provider_code, instrument_code, timeframe
ORDER BY provider_code, instrument_code, timeframe
"""

XAU_FIVE_MINUTE_TIMESTAMPS_SQL = """
WITH canonical_timestamps AS (
    SELECT DISTINCT open_time
    FROM market.price_bars
    WHERE provider_code = 'IC_MARKETS_MT5'
      AND instrument_code = 'XAUUSD'
      AND timeframe = '1m'
      AND is_complete
      AND NOT is_synthetic
      AND open_time >= :start
      AND open_time < :end
      AND available_at <= close_time
)
SELECT time_bucket('5 minutes', open_time) AS bucket_open_time
FROM canonical_timestamps
GROUP BY 1
HAVING count(*) = 5
ORDER BY 1
"""

CANDIDATE_SERIES_METADATA_SQL = """
SELECT
    series_code,
    count(*) FILTER (
        WHERE available_at >= :start
          AND available_at < :end
    ) AS rows_available_in_interval,
    count(DISTINCT observation_time) FILTER (
        WHERE available_at >= :start
          AND available_at < :end
    ) AS observation_periods_in_interval,
    min(observation_time) FILTER (
        WHERE available_at >= :start
          AND available_at < :end
    ) AS first_observation_time_in_interval,
    max(observation_time) FILTER (
        WHERE available_at >= :start
          AND available_at < :end
    ) AS last_observation_time_in_interval,
    min(available_at) FILTER (
        WHERE available_at >= :start
          AND available_at < :end
    ) AS first_available_at_in_interval,
    max(available_at) FILTER (
        WHERE available_at >= :start
          AND available_at < :end
    ) AS last_available_at_in_interval,
    count(DISTINCT observation_time) FILTER (
        WHERE available_at < :start
    ) AS pre_segment_observation_periods,
    max(available_at) FILTER (
        WHERE available_at < :start
    ) AS last_pre_segment_available_at,
    count(*) FILTER (
        WHERE available_at >= :start
          AND available_at < :end
          AND available_at >= observation_time
    ) AS valid_availability_rows_in_interval,
    count(*) FILTER (
        WHERE available_at >= :start
          AND available_at < :end
          AND is_synthetic
    ) AS synthetic_rows_in_interval,
    count(*) FILTER (
        WHERE available_at >= :start
          AND available_at < :end
          AND is_revision
    ) AS revision_rows_in_interval
FROM market.observations
WHERE series_code IN ('US_VOLATILITY_INDEX', 'US_FINANCIAL_STRESS')
  AND available_at < :end
GROUP BY series_code
ORDER BY series_code
"""

SQL_STATEMENTS = {
    "candidate_series_metadata": CANDIDATE_SERIES_METADATA_SQL,
    "price_metadata": PRICE_METADATA_SQL,
    "xau_five_minute_timestamps": XAU_FIVE_MINUTE_TIMESTAMPS_SQL,
}

PARTITIONS = (
    {
        "partition_code": "EXPOSED_CALENDAR_2025",
        "start": EXPOSED_2025_START,
        "end": EXPOSED_2025_END,
        "session_date_start": date(2025, 1, 1),
        "session_date_end": date(2025, 12, 31),
        "classification": "EXPOSED_HISTORICAL_FORWARD_NO_INDEPENDENT_CREDIT",
    },
    {
        "partition_code": "LOCKED_2026_YTD",
        "start": LOCKED_2026_YTD_START,
        "end": LOCKED_2026_YTD_END,
        "session_date_start": date(2026, 1, 1),
        "session_date_end": date(2026, 7, 29),
        "classification": "LOCKED_INDEPENDENT_HOLDOUT",
    },
)


async def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    output_dir = (root / args.output_dir).resolve()
    pre_manifest_path = (root / args.pre_result_manifest).resolve()
    _assert_within(root, output_dir)
    _assert_within(root, pre_manifest_path)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            "M6A output directory is not empty; refusing to overwrite a seal"
        )
    result = await build(
        root=root,
        pre_manifest_path=pre_manifest_path,
        output_dir=output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


async def build(
    *,
    root: Path,
    pre_manifest_path: Path,
    output_dir: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    assert_metadata_only_sql(SQL_STATEMENTS)
    pre_manifest = _verify_pre_result_manifest(
        root=root,
        pre_manifest_path=pre_manifest_path,
    )
    snapshot = await collect_metadata_snapshot()
    report = build_audit_report(
        metadata_snapshot=snapshot,
        pre_manifest=pre_manifest,
        pre_manifest_path=pre_manifest_path,
        generated_at=generated_at or datetime.now(UTC).isoformat(),
    )
    semantic_checks = validate_audit_report(
        report,
        pre_manifest=pre_manifest,
    )
    failed = [item for item in semantic_checks if item["status"] != "PASS"]
    if failed:
        raise ValueError(f"M6A semantic validation failed: {failed}")

    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "readiness_audit.json"
    validation_path = output_dir / "semantic_validation.json"
    manifest_path = output_dir / "manifest.json"
    _write_json(result_path, report)

    validation: dict[str, Any] = {
        "validation_version": BUILD_VALIDATION_VERSION,
        "milestone": "V3_M6A_FORWARD_PROTOCOL_AND_METADATA_READINESS",
        "generated_at": report["generated_at"],
        "pre_result_manifest_hash": pre_manifest["manifest_hash"],
        "readiness_audit_hash": report["readiness_audit_hash"],
        "readiness_audit_file_sha256": sha256_file(result_path),
        "checks": semantic_checks,
        "summary": {
            "total": len(semantic_checks),
            "passed": len(semantic_checks) - len(failed),
            "failed": len(failed),
        },
        "verdict": "PASS_V3_MILESTONE_6A_BUILD_SEMANTIC_VALIDATION",
        "validation_hash": "",
    }
    validation["validation_hash"] = _embedded_hash(
        validation,
        "validation_hash",
    )
    _write_json(validation_path, validation)

    manifest: dict[str, Any] = {
        "manifest_version": RESULT_VERSION,
        "milestone": "V3_M6A_FORWARD_PROTOCOL_AND_METADATA_READINESS",
        "created_at": report["generated_at"],
        "pre_result_manifest": {
            "path": _portable_path(pre_manifest_path),
            "manifest_hash": pre_manifest["manifest_hash"],
            "file_sha256": sha256_file(pre_manifest_path),
            "sealed_before_metadata_audit": True,
            "sealed_before_forward_value_access": True,
        },
        "implementation_seals": dict(
            pre_manifest["implementation_freeze"]
        ),
        "artifacts": [
            {
                "name": "readiness_audit.json",
                "bytes": result_path.stat().st_size,
                "sha256": sha256_file(result_path),
                "readiness_audit_hash": report["readiness_audit_hash"],
            },
            {
                "name": "semantic_validation.json",
                "bytes": validation_path.stat().st_size,
                "sha256": sha256_file(validation_path),
                "validation_hash": validation["validation_hash"],
            },
        ],
        "candidate_inventory": {
            "authorized": 2,
            "metadata_ready_exposed_2025": sum(
                bool(item["metadata_ready"])
                for item in report["partitions"]["EXPOSED_CALENDAR_2025"][
                    "candidate_assessments"
                ]
            ),
            "metadata_ready_locked_2026_ytd": sum(
                bool(item["metadata_ready"])
                for item in report["partitions"]["LOCKED_2026_YTD"][
                    "candidate_assessments"
                ]
            ),
        },
        "research_boundary": dict(report["audit_boundary"]),
        "readiness_verdict": report["readiness_decision"]["verdict"],
        "verdict": "PASS_V3_MILESTONE_6A_METADATA_AUDIT_SEALED",
        "mandatory_stop": True,
        "next_milestone": {
            "code": "V3_M6B_ONE_TIME_FORWARD_VALUE_EVALUATION",
            "authorized": False,
            "started": False,
        },
        "manifest_hash": "",
    }
    manifest["manifest_hash"] = _embedded_hash(manifest, "manifest_hash")
    _write_json(manifest_path, manifest)
    return {
        "manifest": str(manifest_path),
        "manifest_hash": manifest["manifest_hash"],
        "readiness_audit": str(result_path),
        "readiness_audit_hash": report["readiness_audit_hash"],
        "readiness_audit_file_sha256": sha256_file(result_path),
        "semantic_validation": str(validation_path),
        "semantic_validation_hash": validation["validation_hash"],
        "verdict": manifest["verdict"],
    }


async def collect_metadata_snapshot() -> dict[str, Any]:
    assert_metadata_only_sql(SQL_STATEMENTS)
    output: dict[str, Any] = {}
    async with session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        for definition in PARTITIONS:
            parameters = {
                "start": definition["start"],
                "end": definition["end"],
            }
            price_rows = _rows(
                (
                    await session.execute(
                        text(PRICE_METADATA_SQL),
                        parameters,
                    )
                )
                .mappings()
                .all()
            )
            timestamp_rows = (
                await session.execute(
                    text(XAU_FIVE_MINUTE_TIMESTAMPS_SQL),
                    parameters,
                )
            ).mappings().all()
            candidate_series_rows = _rows(
                (
                    await session.execute(
                        text(CANDIDATE_SERIES_METADATA_SQL),
                        parameters,
                    )
                )
                .mappings()
                .all()
            )
            timestamp_coverage = audit_timestamp_only_session_coverage(
                [
                    row["bucket_open_time"]
                    for row in timestamp_rows
                ],
                session_date_start=definition["session_date_start"],
                session_date_end_inclusive=definition["session_date_end"],
            )
            output[str(definition["partition_code"])] = {
                "partition_code": definition["partition_code"],
                "classification": definition["classification"],
                "database_interval": {
                    "start_inclusive": definition["start"].isoformat(),
                    "end_exclusive": definition["end"].isoformat(),
                },
                "session_date_start_inclusive": definition[
                    "session_date_start"
                ].isoformat(),
                "session_date_end_inclusive": definition[
                    "session_date_end"
                ].isoformat(),
                "xau_price_metadata": (
                    price_rows[0] if len(price_rows) == 1 else {}
                ),
                "session_timestamp_coverage": timestamp_coverage,
                "candidate_series_metadata": candidate_series_rows,
            }
        await session.rollback()
    return output


def build_audit_report(
    *,
    metadata_snapshot: Mapping[str, Any],
    pre_manifest: Mapping[str, Any],
    pre_manifest_path: Path,
    generated_at: str,
) -> dict[str, Any]:
    candidates = forward_candidate_registry()
    protocol = forward_protocol()
    partitions: dict[str, Any] = {}
    all_assessments: list[dict[str, Any]] = []
    for code in ("EXPOSED_CALENDAR_2025", "LOCKED_2026_YTD"):
        partition = _mapping(metadata_snapshot[code])
        assessments = [
            assess_candidate_partition_metadata(
                candidate=candidate,
                partition=partition,
                protocol=protocol,
            )
            for candidate in candidates
        ]
        all_assessments.extend(assessments)
        partitions[code] = {
            **partition,
            "candidate_assessments": assessments,
            "market_or_macro_values_read": False,
            "candidate_states_calculated": False,
            "session_outcomes_calculated": False,
            "relationships_calculated": False,
        }

    metadata_ready = all(
        bool(item["metadata_ready"]) for item in all_assessments
    )
    low_power_count = sum(
        item["readiness_status"] == "READY_WITH_LOW_POWER_EXPECTED"
        for item in all_assessments
    )
    locked = partitions["LOCKED_2026_YTD"]
    locked_missing = _mapping(
        locked["session_timestamp_coverage"]
    ).get("missing_dates", {})
    terminal_missing_dates = sorted(
        {
            item
            for dates in _mapping(locked_missing).values()
            for item in _sequence(dates)
            if str(item) >= "2026-07-27"
        }
    )
    if metadata_ready:
        verdict = (
            "READY_WITH_LOW_POWER_EXPECTED_AND_RECORDED_COVERAGE_GAPS"
            if low_power_count
            else "READY_FOR_SEPARATELY_AUTHORIZED_M6B"
        )
    else:
        verdict = "NOT_READY_METADATA_GATE_FAILURE"

    report: dict[str, Any] = {
        "audit_version": M6A_AUDIT_VERSION,
        "milestone": "V3_M6A_FORWARD_PROTOCOL_AND_METADATA_READINESS",
        "generated_at": generated_at,
        "pre_result_manifest": {
            "path": _portable_path(pre_manifest_path),
            "manifest_hash": pre_manifest["manifest_hash"],
            "file_sha256": sha256_file(pre_manifest_path),
            "protocol_fingerprint": pre_manifest["protocol_fingerprint"],
            "sealed_before_metadata_audit": True,
            "sealed_before_forward_value_access": True,
        },
        "predecessor": {
            "v05_state_hash": pre_manifest["frozen_inputs"][
                "v05_state"
            ]["state_hash"],
            "m5_result_hash": pre_manifest["frozen_inputs"][
                "m5_result"
            ]["m5_hash"],
            "m5_shortlist_codes": list(M5_SHORTLIST_CODES),
        },
        "audit_boundary": {
            "access_class": "METADATA_ONLY",
            "database_transaction_read_only": True,
            "sql_guard_passed": True,
            "sql_statement_count": len(SQL_STATEMENTS),
            "sql_statement_sha256": {
                name: hashlib.sha256(statement.encode()).hexdigest()
                for name, statement in sorted(SQL_STATEMENTS.items())
            },
            "permitted_data": [
                "provider instrument timeframe and series identifiers",
                "bar observation availability and file timestamps",
                "row distinct timestamp completeness synthetic revision and ordering counts",
                "sealed hashes and metadata manifests",
            ],
            "development_values_read": False,
            "calendar_2025_market_or_macro_values_read": False,
            "calendar_2025_candidate_states_or_outcomes_calculated": False,
            "calendar_2026_market_or_macro_values_read": False,
            "calendar_2026_candidate_states_or_outcomes_calculated": False,
            "forward_relationships_effects_p_values_or_verdicts_calculated": False,
            "charts_or_row_payloads_inspected": False,
            "execution_variants": 0,
            "trades_or_returns": 0,
            "cot_used_as_pass_gate": False,
            "rejected_candidates_or_zn_rules_reopened": False,
        },
        "frozen_forward_design": {
            "protocol_version": M6A_PROTOCOL_VERSION,
            "protocol_fingerprint": protocol_fingerprint(),
            "candidate_count": len(candidates),
            "candidate_codes": [
                item["candidate_code"] for item in candidates
            ],
            "protocol": protocol,
        },
        "partitions": partitions,
        "prospective_tracking": prospective_metadata_plan(protocol),
        "power_interpretation": {
            "candidate_partition_assessments": len(all_assessments),
            "best_case_below_80pct_power_count": low_power_count,
            "forward_values_or_candidate_state_prevalence_used": False,
            "gate_changed_due_to_power": False,
            "conclusion": (
                "FINITE_FORWARD_SEGMENTS_EXPECTED_TO_HAVE_LOW_POWER_FOR_THE_STRICT_PASS_GATE"
                if low_power_count
                else "AT_LEAST_ONE_FINITE_SEGMENT_REACHES_PLANNING_POWER"
            ),
        },
        "readiness_decision": {
            "all_historical_candidate_partition_metadata_gates_pass": (
                metadata_ready
            ),
            "verdict": verdict,
            "m6b_authorized": False,
            "holdout_values_opened": False,
            "source_refresh_before_m6b_recommended": bool(
                terminal_missing_dates
            ),
            "locked_2026_terminal_missing_session_dates_metadata": (
                terminal_missing_dates
            ),
            "refresh_policy": (
                "Only observed IC Markets and public-source records may be "
                "acquired under separate M6B authority; missing cases remain "
                "missing and are never synthesized."
            ),
            "paid_api_required_for_frozen_candidates": False,
            "cme_or_zn_data_required_for_frozen_candidates": False,
            "next_step": (
                "SEPARATE_M6B_AUTHORIZATION_AFTER_REVIEW_OF_SEALED_M6A"
            ),
        },
        "mandatory_stop": {
            "stop_after_m6a": True,
            "calendar_2025_values_remain_locked_for_v3_m6": True,
            "calendar_2026_values_remain_locked_for_v3_m6": True,
            "next_milestone_authorized": False,
        },
        "readiness_audit_hash": "",
    }
    report["readiness_audit_hash"] = _embedded_hash(
        report,
        "readiness_audit_hash",
        excluded=("generated_at",),
    )
    return report


def validate_audit_report(
    report: Mapping[str, Any],
    *,
    pre_manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    boundary = _mapping(report["audit_boundary"])
    design = _mapping(report["frozen_forward_design"])
    partitions = _mapping(report["partitions"])
    assessments = [
        item
        for code in ("EXPOSED_CALENDAR_2025", "LOCKED_2026_YTD")
        for item in _sequence(_mapping(partitions[code])["candidate_assessments"])
    ]
    checks = [
        _check(
            "PRE_RESULT_MANIFEST_HASH_MATCH",
            report["pre_result_manifest"]["manifest_hash"]
            == pre_manifest["manifest_hash"],
        ),
        _check(
            "PROTOCOL_FINGERPRINT_MATCH",
            design["protocol_fingerprint"] == protocol_fingerprint()
            == pre_manifest["protocol_fingerprint"],
        ),
        _check(
            "EXACT_TWO_CANDIDATES_UNCHANGED",
            design["candidate_codes"] == list(M5_SHORTLIST_CODES)
            and int(design["candidate_count"]) == 2,
        ),
        _check(
            "SQL_GUARD_AND_READ_ONLY_TRANSACTION",
            boundary["sql_guard_passed"]
            and boundary["database_transaction_read_only"],
        ),
        _check(
            "NO_2025_VALUE_STATE_OR_OUTCOME_ACCESS",
            not boundary["calendar_2025_market_or_macro_values_read"]
            and not boundary[
                "calendar_2025_candidate_states_or_outcomes_calculated"
            ],
        ),
        _check(
            "NO_2026_VALUE_STATE_OR_OUTCOME_ACCESS",
            not boundary["calendar_2026_market_or_macro_values_read"]
            and not boundary[
                "calendar_2026_candidate_states_or_outcomes_calculated"
            ],
        ),
        _check(
            "NO_FORWARD_RELATIONSHIP_OR_INFERENCE",
            not boundary[
                "forward_relationships_effects_p_values_or_verdicts_calculated"
            ],
        ),
        _check(
            "NO_EXECUTION_COT_OR_ZN_REOPEN",
            int(boundary["execution_variants"]) == 0
            and int(boundary["trades_or_returns"]) == 0
            and not boundary["cot_used_as_pass_gate"]
            and not boundary["rejected_candidates_or_zn_rules_reopened"],
        ),
        _check(
            "BOTH_PARTITIONS_AND_CANDIDATES_RECORDED",
            set(partitions) == {
                "EXPOSED_CALENDAR_2025",
                "LOCKED_2026_YTD",
            }
            and len(assessments) == 4,
        ),
        _check(
            "NO_CANDIDATE_STATE_OR_OUTCOME_COUNTS",
            all(
                not item["exact_condition_cases_known"]
                and not item["exact_complement_cases_known"]
                and not item["candidate_states_calculated"]
                and not item["outcomes_calculated"]
                for item in assessments
            ),
        ),
        _check(
            "POWER_AUDIT_USES_NO_FORWARD_VALUES",
            all(
                not item["power_audit"][
                    "forward_values_or_candidate_states_used"
                ]
                for item in assessments
            ),
        ),
        _check(
            "PROSPECTIVE_LEDGER_EMPTY",
            report["prospective_tracking"][
                "decision_records_created_by_m6a"
            ]
            == 0
            and not report["prospective_tracking"][
                "market_values_or_outcomes_read"
            ],
        ),
        _check(
            "MANDATORY_STOP_AND_M6B_UNAUTHORIZED",
            report["mandatory_stop"]["stop_after_m6a"]
            and not report["mandatory_stop"]["next_milestone_authorized"]
            and not report["readiness_decision"]["m6b_authorized"],
        ),
        _check(
            "READINESS_HASH_VALID",
            _embedded_hash(
                report,
                "readiness_audit_hash",
                excluded=("generated_at",),
            )
            == report["readiness_audit_hash"],
        ),
    ]
    return checks


def _verify_pre_result_manifest(
    *,
    root: Path,
    pre_manifest_path: Path,
) -> dict[str, Any]:
    manifest = _load_json(pre_manifest_path)
    actual_hash = _embedded_hash(manifest, "manifest_hash")
    if actual_hash != manifest.get("manifest_hash"):
        raise ValueError("M6A pre-result manifest embedded hash mismatch")
    if manifest.get("milestone") != (
        "V3_M6A_FORWARD_PROTOCOL_AND_METADATA_READINESS"
    ):
        raise ValueError("Unexpected M6A pre-result milestone")
    if manifest.get("protocol_fingerprint") != protocol_fingerprint():
        raise ValueError("M6A protocol fingerprint mismatch")
    if validate_forward_protocol():
        raise ValueError("M6A forward protocol implementation is invalid")

    implementation = _mapping(manifest["implementation_freeze"])
    expected = {
        "m6a_module_path": "m6a_module_sha256",
        "m6a_audit_tool_path": "m6a_audit_tool_sha256",
        "m6a_test_path": "m6a_test_sha256",
        "amendment_b_path": "amendment_b_sha256",
    }
    for path_key, hash_key in expected.items():
        path = (root / str(implementation[path_key])).resolve()
        _assert_within(root, path)
        if sha256_file(path) != implementation[hash_key]:
            raise ValueError(f"M6A implementation seal mismatch: {path_key}")
    return manifest


def _check(code: str, passed: bool) -> dict[str, Any]:
    return {
        "code": code,
        "status": "PASS" if passed else "FAIL",
    }


def _row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): json_ready(value) for key, value in row.items()}


def _rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [_row(row) for row in rows]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return list(value)
    return []


def _embedded_hash(
    document: Mapping[str, Any],
    hash_field: str,
    *,
    excluded: Sequence[str] = (),
) -> str:
    payload = {
        key: value
        for key, value in document.items()
        if key != hash_field and key not in set(excluded)
    }
    return canonical_hash(payload)


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


def _portable_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _assert_within(root: Path, path: Path) -> None:
    if path != root and root not in path.parents:
        raise ValueError(f"Path must remain inside repository root: {path}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the V3 M6A candidate-specific metadata-only readiness "
            "and power audit."
        )
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--pre-result-manifest",
        default=(
            "research_manifests/"
            "gold_session_behaviour_v3_m6a_amendment_b_v01.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=(
            "research_artifacts/"
            "gold_session_behaviour_v3_m6a_readiness_v01"
        ),
    )
    return parser


if __name__ == "__main__":
    asyncio.run(main())
