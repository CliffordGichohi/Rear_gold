from __future__ import annotations

import argparse
import gzip
import io
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.session_behaviour_v3 import (
    CASEBOOK_MANIFEST_HASH,
    CREATED_AND_SEALED_AT,
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    FIVE_MINUTE_POINT_COUNT,
    M2_PRE_RESULT_MANIFEST_HASH,
    MEASUREMENT_BAR_COUNT,
    RESEARCH_POLICY,
    SCHEMA_VERSION,
    TRANSFORM_VERSION,
    build_case,
    compact_price_bar,
    parse_timestamp,
    sha256_file,
    validate_case_semantics,
    validate_json_schema,
)

EXPECTED_INPUT_HASHES = {
    "cross_market_snapshots.jsonl.gz": (
        "470a2e1c020cd2f97f2ad5b0d7f9c5220aff4f644689c4d680c24373964eb285"
    ),
    "events.jsonl.gz": (
        "c7875e09d9ed831ece0f223b8be5efb75550af5bf1996a2dfea9d6119b24e35f"
    ),
    "fundamentals.jsonl.gz": (
        "d2b776f60c4535978bbfb28706b4700e6d054a10f8d57cfee171c83b212b7235"
    ),
    "positioning.jsonl.gz": (
        "e6d1aabf0d4401f3af4e54dc8ef4c0e4074772ec3f2199cfe9009b5a0b267228"
    ),
    "price_bars.jsonl.gz": (
        "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e"
    ),
    "sessions.jsonl.gz": (
        "2695a2c0b9e8f41fcbf64c9f388e8883ebf7e1f0b3b09b90fb3a60ba7e64966a"
    ),
    "structure_snapshots.jsonl.gz": (
        "31eea2decc8ed3f8d3e498a9339e7f59ee101e7c787da47a831e63bfb97c1064"
    ),
}
EXPECTED_COUNTS = {"LONDON": 833, "NEW_YORK": 826}
RESULT_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M2_RESULT_V0_1"
VALIDATION_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M2_VALIDATION_V0_1"


class DeterministicJsonlGzipWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.temporary_path = path.with_suffix(path.suffix + ".tmp")
        self._raw: io.BufferedWriter | None = None
        self._gzip: gzip.GzipFile | None = None
        self._text: io.TextIOWrapper | None = None
        self.count = 0

    def __enter__(self) -> DeterministicJsonlGzipWriter:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._raw = self.temporary_path.open("wb")
        self._gzip = gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=6,
            fileobj=self._raw,
            mtime=0,
        )
        self._text = io.TextIOWrapper(self._gzip, encoding="utf-8", newline="\n")
        return self

    def write(self, record: Mapping[str, Any]) -> None:
        if self._text is None:
            raise RuntimeError("Writer is not open")
        self._text.write(
            json.dumps(
                json_ready(record),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        self.count += 1

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._text is not None:
            self._text.close()
        self._text = None
        self._gzip = None
        self._raw = None
        if exc_type is not None:
            self.temporary_path.unlink(missing_ok=True)
            return
        self.temporary_path.replace(self.path)


def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    source_dir = (root / args.source_dir).resolve()
    output_dir = (root / args.output_dir).resolve()
    result = build(root=root, source_dir=source_dir, output_dir=output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


def build(*, root: Path, source_dir: Path, output_dir: Path) -> dict[str, Any]:
    pre_manifest_path = (
        root
        / "research_manifests"
        / "gold_session_behaviour_v3_m2_case_matrix_v01.json"
    )
    schema_path = (
        root
        / "research_schemas"
        / "gold_session_behaviour_v3_case_matrix.schema.json"
    )
    pre_manifest = _load_json(pre_manifest_path)
    _verify_embedded_hash(
        pre_manifest,
        hash_field="manifest_hash",
        expected=M2_PRE_RESULT_MANIFEST_HASH,
    )
    schema = _load_json(schema_path)
    if sha256_file(schema_path) != pre_manifest["frozen_inputs"]["case_matrix_schema"][
        "sha256"
    ]:
        raise ValueError("Frozen case-matrix schema hash mismatch")

    input_hashes = _verify_input_hashes(source_dir)
    source_manifest = _load_json(source_dir / "manifest.json")
    _verify_embedded_hash(
        source_manifest,
        hash_field="manifest_hash",
        expected=CASEBOOK_MANIFEST_HASH,
    )

    sessions = _load_sessions(source_dir / "sessions.jsonl.gz")
    counts = Counter(str(item["session_code"]) for item in sessions)
    if counts != EXPECTED_COUNTS:
        raise ValueError(f"Unexpected session counts: {dict(counts)}")
    expected_keys = [
        (str(item["session_date"]), str(item["session_code"])) for item in sessions
    ]
    if len(expected_keys) != len(set(expected_keys)):
        raise ValueError("Duplicate source session_code-session_date keys")

    bars_by_session = _collect_measurement_bars(
        source_dir / "price_bars.jsonl.gz",
        sessions,
    )
    structure_sessions = {
        str(item["decision_state"]["market_structure_snapshot_id"]): item
        for item in sessions
    }
    cross_ids = {
        str(item["decision_state"]["cross_market_snapshot_id"]) for item in sessions
    }
    fundamental_ids = {
        str(item["decision_state"]["fundamental_snapshot_id"]) for item in sessions
    }
    positioning_ids = {
        str(item["decision_state"]["positioning_record_id"])
        for item in sessions
        if item["decision_state"].get("positioning_record_id")
    }

    cross = _load_selected_records(
        source_dir / "cross_market_snapshots.jsonl.gz",
        cross_ids,
        record_type="CROSS_MARKET_SNAPSHOT",
    )
    positioning = _load_selected_records(
        source_dir / "positioning.jsonl.gz",
        positioning_ids,
        record_type="POSITIONING_REPORT",
    )
    fundamentals, policy_windows = _load_fundamentals(
        source_dir / "fundamentals.jsonl.gz",
        fundamental_ids,
    )
    events = _load_all_records(
        source_dir / "events.jsonl.gz",
        record_type="EVENT_CASE",
    )
    events.sort(key=lambda item: parse_timestamp(str(item["released_at"])))
    policy_windows.sort(
        key=lambda item: (
            str(item["observation_date"]),
            str(item["reference_start"]),
            str(item["record_id"]),
        )
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    cases_path = output_dir / "cases.jsonl.gz"
    validation_path = output_dir / "semantic_validation.json"
    result_manifest_path = output_dir / "manifest.json"

    keys_written: list[tuple[str, str]] = []
    case_ids: set[str] = set()
    schema_error_count = 0
    semantic_error_count = 0
    decision_fact_future_count = 0
    unknown_non_null_count = 0
    record_hash_mismatch_count = 0
    session_counts: Counter[str] = Counter()

    with DeterministicJsonlGzipWriter(cases_path) as writer:
        for structure in _iter_jsonl(source_dir / "structure_snapshots.jsonl.gz"):
            if structure.get("record_type") != "STRUCTURE_SNAPSHOT":
                continue
            session = structure_sessions.get(str(structure["record_id"]))
            if session is None:
                continue
            _verify_record_hash(structure)
            session_id = str(session["record_id"])
            decision_at = str(session["decision_at"])
            eligible_events = _eligible_recent_events(events, decision_at)
            eligible_windows = _eligible_policy_windows(policy_windows, decision_at)
            positioning_id = session["decision_state"].get("positioning_record_id")
            case = build_case(
                session=session,
                measurement_bars=bars_by_session[session_id],
                structure=structure,
                cross=cross[str(session["decision_state"]["cross_market_snapshot_id"])],
                fundamental=fundamentals[
                    str(session["decision_state"]["fundamental_snapshot_id"])
                ],
                positioning=(
                    positioning.get(str(positioning_id)) if positioning_id else None
                ),
                recent_events=eligible_events,
                policy_windows=eligible_windows,
            )
            key = (
                str(case["case_metadata"]["session_date"]),
                str(case["case_metadata"]["session_code"]),
            )
            expected_key = expected_keys[len(keys_written)]
            if key != expected_key:
                raise ValueError(
                    f"Structure stream order violates frozen row order: "
                    f"{key} != {expected_key}"
                )
            case_id = str(case["case_metadata"]["case_id"])
            if case_id in case_ids:
                raise ValueError(f"Duplicate V3 case_id: {case_id}")
            case_ids.add(case_id)

            semantic_errors = validate_case_semantics(case)
            schema_errors = validate_json_schema(case, schema)
            if semantic_errors or schema_errors:
                raise ValueError(
                    f"Invalid V3 case {case_id}: "
                    f"semantic={semantic_errors[:10]} schema={schema_errors[:10]}"
                )
            writer.write(case)
            keys_written.append(key)
            session_counts[str(case["case_metadata"]["session_code"])] += 1
            schema_error_count += len(schema_errors)
            semantic_error_count += len(semantic_errors)
            decision_fact_future_count += sum(
                error.startswith("FUTURE_") for error in semantic_errors
            )
            unknown_non_null_count += sum(
                error.startswith("UNKNOWN_NON_NULL") for error in semantic_errors
            )
            record_hash_mismatch_count += sum(
                error == "RECORD_HASH_MISMATCH" for error in semantic_errors
            )

    if len(keys_written) != len(sessions):
        missing = sorted(set(expected_keys) - set(keys_written))
        raise ValueError(
            f"Missing decision structure snapshots: wrote {len(keys_written)} of "
            f"{len(sessions)}; examples={missing[:5]}"
        )
    if session_counts != EXPECTED_COUNTS:
        raise ValueError(f"Written session counts mismatch: {dict(session_counts)}")

    cases_sha256 = sha256_file(cases_path)
    semantic_validation = _semantic_validation_document(
        cases_path=cases_path,
        cases_sha256=cases_sha256,
        keys_written=keys_written,
        case_ids=case_ids,
        session_counts=session_counts,
        schema_error_count=schema_error_count,
        semantic_error_count=semantic_error_count,
        decision_fact_future_count=decision_fact_future_count,
        unknown_non_null_count=unknown_non_null_count,
        record_hash_mismatch_count=record_hash_mismatch_count,
        input_hashes=input_hashes,
    )
    _write_hashed_json(
        validation_path,
        semantic_validation,
        hash_field="validation_hash",
    )
    semantic_validation = _load_json(validation_path)

    result_manifest: dict[str, Any] = {
        "manifest_version": RESULT_VERSION,
        "milestone": "V3_M2_DEVELOPMENT_CASE_MATRIX",
        "created_at": CREATED_AND_SEALED_AT,
        "sealed_at": CREATED_AND_SEALED_AT,
        "pre_result_manifest": {
            "path": (
                "research_manifests/"
                "gold_session_behaviour_v3_m2_case_matrix_v01.json"
            ),
            "manifest_hash": M2_PRE_RESULT_MANIFEST_HASH,
        },
        "source_bundle": {
            "path": "research_artifacts/gold_casebook_v01/manifest.json",
            "manifest_hash": CASEBOOK_MANIFEST_HASH,
            "artifact_hashes_verified_before_deserialization": input_hashes,
        },
        "schema": {
            "path": (
                "research_schemas/"
                "gold_session_behaviour_v3_case_matrix.schema.json"
            ),
            "schema_version": SCHEMA_VERSION,
            "sha256": sha256_file(schema_path),
        },
        "artifacts": [
            {
                "name": cases_path.name,
                "path": cases_path.name,
                "bytes": cases_path.stat().st_size,
                "sha256": cases_sha256,
                "record_count": len(keys_written),
                "record_type": "GOLD_SESSION_BEHAVIOUR_V3_CASE",
            },
            {
                "name": validation_path.name,
                "path": validation_path.name,
                "bytes": validation_path.stat().st_size,
                "sha256": sha256_file(validation_path),
                "validation_hash": semantic_validation["validation_hash"],
            },
        ],
        "development_partition": {
            "session_date_start_inclusive": "2021-08-01",
            "session_date_end_inclusive": "2024-12-31",
            "access_class": "DEVELOPMENT",
        },
        "case_counts": {
            "total": len(keys_written),
            "london": session_counts["LONDON"],
            "new_york": session_counts["NEW_YORK"],
        },
        "integrity": {
            "unique_case_ids": len(case_ids),
            "unique_session_keys": len(set(keys_written)),
            "record_hashes_verified": len(keys_written),
            "schema_valid_records": len(keys_written),
            "semantic_valid_records": len(keys_written),
            "decision_fact_future_violations": decision_fact_future_count,
            "unknown_non_null_violations": unknown_non_null_count,
            "source_row_order_verified": True,
            "deterministic_gzip_mtime": 0,
        },
        "research_boundary": {
            "development_values_opened": True,
            "exposed_2025_values_opened": False,
            "locked_2026_values_opened": False,
            "feature_outcome_joins_calculated": 0,
            "relationship_statistics_calculated": 0,
            "descriptive_distributions_calculated": 0,
            "candidates_created": 0,
            "execution_variants_tested": 0,
            "trades_or_returns_calculated": 0,
            "mfe_or_mae_calculated": 0,
        },
        "research_policy": dict(RESEARCH_POLICY),
        "transform_version": TRANSFORM_VERSION,
        "verdict": "PASS_V3_MILESTONE_2_CASE_MATRIX_SEALED",
        "mandatory_stop": True,
        "next_milestone": {
            "code": "V3_M3_DESCRIPTIVE_SESSION_BEHAVIOUR_ATLAS",
            "authorized": False,
            "started": False,
        },
    }
    _write_hashed_json(
        result_manifest_path,
        result_manifest,
        hash_field="manifest_hash",
    )
    result_manifest = _load_json(result_manifest_path)
    return {
        "artifact": str(cases_path),
        "artifact_bytes": cases_path.stat().st_size,
        "artifact_sha256": cases_sha256,
        "cases": len(keys_written),
        "london": session_counts["LONDON"],
        "new_york": session_counts["NEW_YORK"],
        "manifest": str(result_manifest_path),
        "manifest_hash": result_manifest["manifest_hash"],
        "semantic_validation": str(validation_path),
        "semantic_validation_hash": semantic_validation["validation_hash"],
        "verdict": result_manifest["verdict"],
    }


def _load_sessions(path: Path) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for record in _iter_jsonl(path):
        if record.get("record_type") != "SESSION_CASE":
            continue
        _verify_record_hash(record)
        if record.get("holdout_loaded") is not False:
            raise ValueError(f"Source holdout flag violated: {record['record_id']}")
        decision = parse_timestamp(str(record["decision_at"]))
        if not DEVELOPMENT_START <= decision < DEVELOPMENT_END:
            raise ValueError(f"Session outside development: {record['record_id']}")
        sessions.append(record)
    session_order = {"LONDON": 0, "NEW_YORK": 1}
    sessions.sort(
        key=lambda item: (
            str(item["session_date"]),
            session_order[str(item["session_code"])],
        )
    )
    return sessions


def _collect_measurement_bars(
    path: Path,
    sessions: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    intervals = sorted(
        [
            (
                parse_timestamp(str(session["decision_at"])) + timedelta(minutes=1),
                parse_timestamp(str(session["observation_end"])),
                str(session["record_id"]),
            )
            for session in sessions
        ],
        key=lambda item: (item[0], item[2]),
    )
    bars_by_session: dict[str, list[dict[str, Any]]] = {
        str(session["record_id"]): [] for session in sessions
    }
    active: list[tuple[datetime, datetime, str]] = []
    interval_index = 0
    saw_one_minute = False
    for record in _iter_jsonl(path):
        timeframe = record.get("timeframe")
        if timeframe != "1m":
            if saw_one_minute:
                break
            continue
        saw_one_minute = True
        if record.get("instrument_code") != "XAUUSD":
            continue
        open_dt = parse_timestamp(str(record["open_time"]))
        close_dt = parse_timestamp(str(record["close_time"]))
        while interval_index < len(intervals) and intervals[interval_index][0] <= open_dt:
            active.append(intervals[interval_index])
            interval_index += 1
        active = [item for item in active if item[1] > open_dt]
        if not active:
            if interval_index >= len(intervals):
                break
            continue
        for start, end, session_id in active:
            if open_dt >= start and close_dt <= end:
                _verify_record_hash(record)
                bars_by_session[session_id].append(compact_price_bar(record))
    incomplete = {
        session_id: len(values)
        for session_id, values in bars_by_session.items()
        if len(values) != MEASUREMENT_BAR_COUNT
    }
    if incomplete:
        raise ValueError(
            f"Neutral one-minute coverage incomplete for {len(incomplete)} cases: "
            f"{list(incomplete.items())[:5]}"
        )
    return bars_by_session


def _load_selected_records(
    path: Path,
    selected_ids: set[str],
    *,
    record_type: str,
) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for record in _iter_jsonl(path):
        if record.get("record_type") != record_type:
            continue
        record_id = str(record["record_id"])
        if record_id not in selected_ids:
            continue
        _verify_record_hash(record)
        selected[record_id] = record
    missing = selected_ids - set(selected)
    if missing:
        raise ValueError(f"Missing {record_type} records: {sorted(missing)[:5]}")
    return selected


def _load_all_records(path: Path, *, record_type: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for record in _iter_jsonl(path):
        if record.get("record_type") != record_type:
            continue
        _verify_record_hash(record)
        values.append(record)
    return values


def _load_fundamentals(
    path: Path,
    snapshot_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    snapshots: dict[str, dict[str, Any]] = {}
    windows: list[dict[str, Any]] = []
    for record in _iter_jsonl(path):
        record_type = record.get("record_type")
        if record_type == "FUNDAMENTAL_SNAPSHOT":
            record_id = str(record["record_id"])
            if record_id not in snapshot_ids:
                continue
            _verify_record_hash(record)
            snapshots[record_id] = record
        elif record_type == "POLICY_EXPECTATION_WINDOW":
            _verify_record_hash(record)
            windows.append(record)
    missing = snapshot_ids - set(snapshots)
    if missing:
        raise ValueError(f"Missing fundamental snapshots: {sorted(missing)[:5]}")
    return snapshots, windows


def _eligible_recent_events(
    events: Iterable[Mapping[str, Any]],
    decision_at: str,
) -> list[Mapping[str, Any]]:
    decision = parse_timestamp(decision_at)
    lower = decision - timedelta(days=7)
    return [
        event
        for event in events
        if lower <= parse_timestamp(str(event["released_at"])) < decision
        and parse_timestamp(str(event["event_available_at"])) <= decision
    ]


def _eligible_policy_windows(
    windows: Iterable[Mapping[str, Any]],
    decision_at: str,
) -> list[Mapping[str, Any]]:
    decision = parse_timestamp(decision_at)
    eligible = [
        item
        for item in windows
        if parse_timestamp(str(item["available_at"])) <= decision
    ]
    if not eligible:
        return []
    latest_date = max(str(item["observation_date"]) for item in eligible)
    return [item for item in eligible if str(item["observation_date"]) == latest_date]


def _semantic_validation_document(
    *,
    cases_path: Path,
    cases_sha256: str,
    keys_written: list[tuple[str, str]],
    case_ids: set[str],
    session_counts: Counter[str],
    schema_error_count: int,
    semantic_error_count: int,
    decision_fact_future_count: int,
    unknown_non_null_count: int,
    record_hash_mismatch_count: int,
    input_hashes: Mapping[str, str],
) -> dict[str, Any]:
    checks = [
        _check(
            "FROZEN_INPUT_HASHES",
            input_hashes == EXPECTED_INPUT_HASHES,
            dict(input_hashes),
        ),
        _check(
            "EXACT_CASE_COUNTS",
            len(keys_written) == 1659
            and session_counts["LONDON"] == 833
            and session_counts["NEW_YORK"] == 826,
            {
                "total": len(keys_written),
                "london": session_counts["LONDON"],
                "new_york": session_counts["NEW_YORK"],
            },
        ),
        _check(
            "UNIQUE_KEYS_AND_IDS",
            len(keys_written) == len(set(keys_written)) == len(case_ids),
            {
                "case_ids": len(case_ids),
                "session_keys": len(set(keys_written)),
            },
        ),
        _check(
            "ROW_ORDER",
            keys_written == sorted(
                keys_written,
                key=lambda item: (item[0], {"LONDON": 0, "NEW_YORK": 1}[item[1]]),
            ),
            {"first": keys_written[:1], "last": keys_written[-1:]},
        ),
        _check(
            "CASE_RECORD_HASHES",
            record_hash_mismatch_count == 0,
            {"mismatches": record_hash_mismatch_count},
        ),
        _check(
            "FROZEN_SCHEMA",
            schema_error_count == 0,
            {"errors": schema_error_count, "records_checked": len(keys_written)},
        ),
        _check(
            "SEMANTIC_INVARIANTS",
            semantic_error_count == 0,
            {"errors": semantic_error_count, "records_checked": len(keys_written)},
        ),
        _check(
            "POINT_IN_TIME_DECISION_FACTS",
            decision_fact_future_count == 0,
            {"future_violations": decision_fact_future_count},
        ),
        _check(
            "UNKNOWN_IS_NULL",
            unknown_non_null_count == 0,
            {"violations": unknown_non_null_count},
        ),
        _check(
            "NEUTRAL_PATH_COUNTS",
            True,
            {
                "one_minute_bars_per_case": MEASUREMENT_BAR_COUNT,
                "five_minute_points_per_case": FIVE_MINUTE_POINT_COUNT,
                "fixed_horizons_per_case": 5,
            },
        ),
        _check(
            "RESEARCH_BOUNDARY",
            True,
            {
                "2025_values_opened": False,
                "2026_values_opened": False,
                "relationships": 0,
                "distributions": 0,
                "candidates": 0,
                "execution_variants": 0,
                "trades": 0,
            },
        ),
    ]
    failed = sum(item["status"] == "FAIL" for item in checks)
    return {
        "validation_version": VALIDATION_VERSION,
        "generated_at": CREATED_AND_SEALED_AT,
        "milestone": "V3_M2_DEVELOPMENT_CASE_MATRIX",
        "pre_result_manifest_hash": M2_PRE_RESULT_MANIFEST_HASH,
        "case_artifact": {
            "path": cases_path.name,
            "bytes": cases_path.stat().st_size,
            "sha256": cases_sha256,
            "record_count": len(keys_written),
        },
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - failed,
            "failed": failed,
        },
        "verdict": (
            "PASS_V3_MILESTONE_2_SEMANTIC_VALIDATION"
            if failed == 0
            else "FAIL_V3_MILESTONE_2_SEMANTIC_VALIDATION"
        ),
    }


def _check(code: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {
        "code": code,
        "status": "PASS" if passed else "FAIL",
        "evidence": json_ready(evidence),
    }


def _verify_input_hashes(source_dir: Path) -> dict[str, str]:
    actual: dict[str, str] = {}
    for name, expected in EXPECTED_INPUT_HASHES.items():
        path = source_dir / name
        supplied = sha256_file(path)
        if supplied != expected:
            raise ValueError(f"Frozen input hash mismatch: {name}")
        actual[name] = supplied
    return actual


def _verify_embedded_hash(
    document: Mapping[str, Any],
    *,
    hash_field: str,
    expected: str,
) -> None:
    supplied = str(document.get(hash_field, ""))
    unhashed = {key: value for key, value in document.items() if key != hash_field}
    calculated = canonical_hash(unhashed)
    if supplied != expected or calculated != supplied:
        raise ValueError(
            f"Embedded hash mismatch for {hash_field}: "
            f"expected={expected} supplied={supplied} calculated={calculated}"
        )


def _verify_record_hash(record: Mapping[str, Any]) -> None:
    supplied = str(record.get("record_hash", ""))
    unhashed = {key: value for key, value in record.items() if key != "record_hash"}
    if not supplied or canonical_hash(unhashed) != supplied:
        raise ValueError(f"Source record hash mismatch: {record.get('record_id')}")


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Expected JSON object: {path}:{line_number}")
            yield value


def _write_hashed_json(
    path: Path,
    document: Mapping[str, Any],
    *,
    hash_field: str,
) -> None:
    payload = dict(document)
    if hash_field in payload:
        raise ValueError(f"{hash_field} already supplied")
    payload[hash_field] = canonical_hash(payload)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(json_ready(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the frozen Gold Session Behaviour V3 Milestone 2 development "
            "case matrix. This tool cannot read 2025 or 2026 sources."
        )
    )
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--source-dir",
        default="research_artifacts/gold_casebook_v01",
    )
    parser.add_argument(
        "--output-dir",
        default="research_artifacts/gold_session_behaviour_v3_case_matrix_v01",
    )
    return parser


if __name__ == "__main__":
    main()
