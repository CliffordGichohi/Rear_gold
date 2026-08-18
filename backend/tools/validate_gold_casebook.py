from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import (
    CASEBOOK_SCHEMA_VERSION,
    CASEBOOK_VERSION,
    HOLDOUT_START,
    canonical_hash,
)

VALIDATION_VERSION = "GOLD_CASEBOOK_SEMANTIC_VALIDATION_V0_1"
FORBIDDEN_RESEARCH_FIELDS = {
    "entry_price",
    "exit_price",
    "stop_price",
    "target_price",
    "gross_pnl",
    "net_pnl",
    "r_multiple",
    "mfe",
    "mae",
    "directional_outcome",
    "trade_direction",
}
COMMON_REQUIRED = {
    "record_type",
    "record_id",
    "record_hash",
    "casebook_version",
    "schema_version",
    "epistemic_status",
    "holdout_loaded",
}


def main() -> None:
    args = _parser().parse_args()
    root = Path(args.bundle)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _verify_manifest(manifest)

    ids: set[str] = set()
    structure_times: dict[str, datetime] = {}
    cross_times: dict[str, datetime] = {}
    positioning_times: dict[str, datetime] = {}
    fundamental_times: dict[str, datetime] = {}
    counts: Counter[str] = Counter()
    price_timeframes: Counter[str] = Counter()
    price_incomplete: Counter[str] = Counter()
    structure_detection_count = 0
    stale_us500_count = 0
    event_unknown_pre_event_count = 0
    verified_record_hashes = 0

    expected_files = {
        item["path"]: item for item in manifest["artifacts"]
    }
    for relative_path, artifact in expected_files.items():
        path = root / relative_path
        if _sha256(path) != artifact["sha256"]:
            raise ValueError(f"Artifact SHA-256 mismatch: {relative_path}")
        file_count = 0
        for record in _records(path):
            _verify_common(record, ids)
            _assert_no_forbidden_fields(record)
            record_type = record["record_type"]
            counts[record_type] += 1
            file_count += 1
            verified_record_hashes += 1

            if record_type == "PRICE_BAR":
                _verify_price(record)
                timeframe = record["timeframe"]
                price_timeframes[timeframe] += 1
                if not record["complete"]:
                    price_incomplete[timeframe] += 1
            elif record_type == "STRUCTURE_SNAPSHOT":
                structure_times[record["record_id"]] = _timestamp(record["as_of"])
                structure_detection_count += _verify_structure(record)
            elif record_type == "CROSS_MARKET_SNAPSHOT":
                cross_times[record["record_id"]] = _timestamp(record["as_of"])
                stale_us500_count += _verify_cross_market(record)
            elif record_type == "POSITIONING_REPORT":
                positioning_times[record["record_id"]] = _timestamp(
                    record["publication_at"]
                )
                _verify_positioning(record)
            elif record_type == "EVENT_CASE":
                event_unknown_pre_event_count += _verify_event(record)
            elif record_type == "FUNDAMENTAL_SNAPSHOT":
                fundamental_times[record["record_id"]] = _timestamp(record["as_of"])
                _verify_fundamental_snapshot(record)
            elif record_type == "FUNDAMENTAL_OBSERVATION":
                _verify_fundamental_observation(record)
            elif record_type in {
                "POLICY_PATH_POINT",
                "POLICY_EXPECTATION_WINDOW",
            }:
                _verify_policy_record(record)
            elif record_type != "SESSION_CASE":
                raise ValueError(f"Unsupported record type: {record_type}")
        if file_count != artifact["record_count"]:
            raise ValueError(
                f"Record-count mismatch in {relative_path}: "
                f"{file_count} != {artifact['record_count']}"
            )
        print(
            json.dumps(
                {
                    "validation_stage": "ARTIFACT_VERIFIED",
                    "artifact": relative_path,
                    "records": file_count,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    london, new_york = _verify_sessions(
        root / "sessions.jsonl.gz",
        structure_times=structure_times,
        cross_times=cross_times,
        positioning_times=positioning_times,
        fundamental_times=fundamental_times,
    )
    expected_counts = manifest["record_counts"]
    if london != expected_counts["london_cases"]:
        raise ValueError("London case count does not match manifest")
    if new_york != expected_counts["new_york_cases"]:
        raise ValueError("New York case count does not match manifest")
    if verified_record_hashes != manifest["integrity"]["record_hashes_verified"]:
        raise ValueError("Verified record total does not match manifest")
    if len(ids) != verified_record_hashes:
        raise ValueError("Global record IDs are not unique")
    print(
        json.dumps(
            {
                "validation_stage": "SEMANTIC_JOINS_VERIFIED",
                "london_cases": london,
                "new_york_cases": new_york,
            },
            sort_keys=True,
        ),
        flush=True,
    )

    report: dict[str, Any] = {
        "validation_version": VALIDATION_VERSION,
        "casebook_version": CASEBOOK_VERSION,
        "schema_version": CASEBOOK_SCHEMA_VERSION,
        "manifest_hash": manifest["manifest_hash"],
        "holdout_loaded": False,
        "profitability_calculated": False,
        "directional_outcome_calculated": False,
        "verified": {
            "artifact_hashes": len(expected_files),
            "record_hashes": verified_record_hashes,
            "unique_record_ids": len(ids),
            "record_type_counts": dict(sorted(counts.items())),
            "price_timeframe_counts": dict(sorted(price_timeframes.items())),
            "incomplete_price_buckets": dict(sorted(price_incomplete.items())),
            "structure_detections": structure_detection_count,
            "stale_us500_snapshots": stale_us500_count,
            "events_with_unknown_pre_event_state": event_unknown_pre_event_count,
            "london_cases": london,
            "new_york_cases": new_york,
        },
        "semantic_assertions": {
            "all_market_times_before_or_at_exclusive_boundary": True,
            "session_decision_and_subsequent_observation_separated": True,
            "all_decision_joins_available_by_decision": True,
            "all_structure_detections_available_by_snapshot": True,
            "cot_publication_respected": True,
            "historical_pre_event_state_not_backfilled": True,
            "stale_cross_market_values_not_neutralized": True,
            "forbidden_execution_and_outcome_fields_absent": True,
        },
    }
    report["validation_hash"] = canonical_hash(report)
    output = Path(args.output)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


def _verify_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest["casebook_version"] != CASEBOOK_VERSION:
        raise ValueError("Casebook version mismatch")
    if manifest["schema_version"] != CASEBOOK_SCHEMA_VERSION:
        raise ValueError("Schema version mismatch")
    if manifest["contract"]["holdout_loaded"] is not False:
        raise ValueError("Manifest says the holdout was loaded")
    if manifest["contract"]["case_end_exclusive"] != HOLDOUT_START.isoformat():
        raise ValueError("Unexpected holdout boundary")
    supplied_hash = manifest["manifest_hash"]
    unhashed = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    if canonical_hash(unhashed) != supplied_hash:
        raise ValueError("Manifest hash mismatch")


def _verify_common(record: dict[str, Any], ids: set[str]) -> None:
    missing = COMMON_REQUIRED - record.keys()
    if missing:
        raise ValueError(f"Missing common fields: {sorted(missing)}")
    if record["casebook_version"] != CASEBOOK_VERSION:
        raise ValueError(f"Casebook version mismatch: {record['record_id']}")
    if record["schema_version"] != CASEBOOK_SCHEMA_VERSION:
        raise ValueError(f"Schema version mismatch: {record['record_id']}")
    if record["epistemic_status"] not in {
        "OBSERVED",
        "CALCULATED",
        "INFERRED",
        "UNKNOWN",
    }:
        raise ValueError(f"Invalid epistemic status: {record['record_id']}")
    if record["holdout_loaded"] is not False:
        raise ValueError(f"Holdout flag violated: {record['record_id']}")
    record_id = record["record_id"]
    if record_id in ids:
        raise ValueError(f"Duplicate record ID: {record_id}")
    ids.add(record_id)
    supplied_hash = record["record_hash"]
    unhashed = {key: value for key, value in record.items() if key != "record_hash"}
    if canonical_hash(unhashed) != supplied_hash:
        raise ValueError(f"Record hash mismatch: {record_id}")


def _verify_price(record: Mapping[str, Any]) -> None:
    open_time = _timestamp(record["open_time"])
    close_time = _timestamp(record["close_time"])
    available_at = _timestamp(record["available_at"])
    if open_time >= HOLDOUT_START:
        raise ValueError(f"Price opens in holdout: {record['record_id']}")
    if close_time > HOLDOUT_START:
        raise ValueError(f"Price closes beyond holdout boundary: {record['record_id']}")
    if not open_time < close_time:
        raise ValueError(f"Price time order invalid: {record['record_id']}")
    if available_at > close_time or available_at >= HOLDOUT_START:
        raise ValueError(f"Price availability invalid: {record['record_id']}")
    ohlc = record["ohlc"]
    if not (
        ohlc["high"] >= ohlc["open"]
        and ohlc["high"] >= ohlc["close"]
        and ohlc["high"] >= ohlc["low"]
        and ohlc["low"] <= ohlc["open"]
        and ohlc["low"] <= ohlc["close"]
    ):
        raise ValueError(f"OHLC geometry invalid: {record['record_id']}")
    expected_status = "OBSERVED" if record["timeframe"] == "1m" else "CALCULATED"
    if record["epistemic_status"] != expected_status:
        raise ValueError(f"Price epistemic status invalid: {record['record_id']}")


def _verify_structure(record: Mapping[str, Any]) -> int:
    as_of = _timestamp(record["as_of"])
    if as_of >= HOLDOUT_START:
        raise ValueError(f"Structure snapshot enters holdout: {record['record_id']}")
    timeframes = record["timeframes"]
    if [item["timeframe"] for item in timeframes] != [
        "1m",
        "5m",
        "15m",
        "1h",
        "4h",
        "1d",
    ]:
        raise ValueError(f"Structure timeframe set invalid: {record['record_id']}")
    count = 0
    for timeframe in timeframes:
        for detection in timeframe["detections"]:
            timestamp = _timestamp(detection["timestamp"])
            detected_at = _timestamp(detection["detected_at"])
            if timestamp > detected_at or detected_at > as_of:
                raise ValueError(
                    f"Look-ahead structure detection: {record['record_id']}"
                )
            if not detection["detection_method"]:
                raise ValueError(f"Missing structure method: {record['record_id']}")
            if not detection["invalidation_condition"]:
                raise ValueError(
                    f"Missing structure invalidation: {record['record_id']}"
                )
            count += 1
    return count


def _verify_cross_market(record: Mapping[str, Any]) -> int:
    as_of = _timestamp(record["as_of"])
    stale_us500 = 0
    for code, fact in record["instruments"].items():
        if fact is None:
            continue
        if _timestamp(fact["available_at"]) > as_of:
            raise ValueError(f"Future cross-market fact: {record['record_id']} {code}")
        if fact["status"] not in {"READY", "STALE"}:
            raise ValueError(f"Invalid cross-market status: {record['record_id']}")
        if code == "US500" and fact["status"] == "STALE":
            stale_us500 += 1
        for change in fact["changes"].values():
            if change["status"] == "READY":
                if _timestamp(change["reference_available_at"]) > as_of:
                    raise ValueError(
                        f"Future cross-market reference: {record['record_id']} {code}"
                    )
                if change["epistemic_status"] != "CALCULATED":
                    raise ValueError(
                        f"Cross-market change not calculated: {record['record_id']}"
                    )
            elif change["epistemic_status"] != "UNKNOWN":
                raise ValueError(
                    f"Unavailable cross-market change is not UNKNOWN: "
                    f"{record['record_id']}"
                )
    return stale_us500


def _verify_positioning(record: Mapping[str, Any]) -> None:
    publication = _timestamp(record["publication_at"])
    observation = datetime.fromisoformat(record["observation_date"]).date()
    if publication >= HOLDOUT_START:
        raise ValueError(f"COT publication enters holdout: {record['record_id']}")
    if observation >= publication.date():
        raise ValueError(f"COT observation/publication order invalid: {record['record_id']}")
    if set(record["categories"]) != {
        "MANAGED_MONEY",
        "OTHER_REPORTABLE",
        "PRODUCER_MERCHANT",
        "SWAP_DEALER",
    }:
        raise ValueError(f"COT category set invalid: {record['record_id']}")
    if record["calculated"]["epistemic_status"] != "CALCULATED":
        raise ValueError(f"COT calculations not classified: {record['record_id']}")
    if record["inferred"]["epistemic_status"] != "INFERRED":
        raise ValueError(f"COT inferences not classified: {record['record_id']}")


def _verify_event(record: Mapping[str, Any]) -> int:
    scheduled = _timestamp(record["scheduled_at"])
    if scheduled >= HOLDOUT_START:
        raise ValueError(f"Event enters holdout: {record['record_id']}")
    pre_event = record["pre_event_state"]
    if not record["schedule_verified_for_pre_event_use"]:
        if pre_event["schedule"] != "UNKNOWN":
            raise ValueError(f"Historical schedule backfilled: {record['record_id']}")
        if pre_event["consensus"] != "UNKNOWN":
            raise ValueError(f"Historical consensus backfilled: {record['record_id']}")
    for forecast in record["forecasts"]:
        if (
            forecast["pre_event_use_allowed"]
            and _timestamp(forecast["available_at"]) > scheduled
        ):
            raise ValueError(
                f"Late forecast marked pre-event eligible: {record['record_id']}"
            )
    for code, reaction in record["reaction_snapshots"].items():
        if code != "REFERENCE" and reaction["decision_eligible_at_release"]:
            raise ValueError(f"Post-event fact leaked to release: {record['record_id']}")
    return int(
        pre_event["schedule"] == "UNKNOWN"
        and pre_event["consensus"] == "UNKNOWN"
    )


def _verify_fundamental_observation(record: Mapping[str, Any]) -> None:
    observation_time = _timestamp(record["observation_time"])
    available_at = _timestamp(record["available_at"])
    if observation_time >= HOLDOUT_START or available_at >= HOLDOUT_START:
        raise ValueError(f"Fundamental observation enters holdout: {record['record_id']}")


def _verify_policy_record(record: Mapping[str, Any]) -> None:
    if _timestamp(record["available_at"]) >= HOLDOUT_START:
        raise ValueError(f"Policy record enters holdout: {record['record_id']}")
    if _timestamp(record["snapshot_as_of"]) >= HOLDOUT_START:
        raise ValueError(f"Policy snapshot enters holdout: {record['record_id']}")


def _verify_fundamental_snapshot(record: Mapping[str, Any]) -> None:
    as_of = _timestamp(record["as_of"])
    for series in record["series_state"].values():
        if series["status"] == "READY" and _timestamp(series["available_at"]) > as_of:
            raise ValueError(
                f"Future fundamental series state: {record['record_id']}"
            )
    if record["engine_state"]["reasoning"]["score_is_not_trade_signal"] is not True:
        raise ValueError(f"Fundamental score warning absent: {record['record_id']}")


def _verify_sessions(
    path: Path,
    *,
    structure_times: Mapping[str, datetime],
    cross_times: Mapping[str, datetime],
    positioning_times: Mapping[str, datetime],
    fundamental_times: Mapping[str, datetime],
) -> tuple[int, int]:
    london = 0
    new_york = 0
    for record in _records(path):
        decision = _timestamp(record["decision_at"])
        observation_end = _timestamp(record["observation_end"])
        if not decision < observation_end < HOLDOUT_START:
            raise ValueError(f"Session clock order invalid: {record['record_id']}")
        state = record["decision_state"]
        subsequent = record["subsequent_observation"]
        if subsequent["decision_eligible"] is not False:
            raise ValueError(f"Session outcome leaked to decision: {record['record_id']}")
        if _timestamp(subsequent["available_at"]) < observation_end:
            raise ValueError(f"Session observation available too early: {record['record_id']}")
        if state["windows"]["asia"]["status"] != "COMPLETE":
            raise ValueError(f"Asia prerequisite incomplete: {record['record_id']}")
        if record["session_code"] == "LONDON":
            london += 1
            if state["windows"]["london"]["status"] != "NOT_STARTED":
                raise ValueError(
                    f"London session leaked into London decision: {record['record_id']}"
                )
        elif record["session_code"] == "NEW_YORK":
            new_york += 1
            if state["windows"]["london"]["status"] != "COMPLETE":
                raise ValueError(
                    f"London prerequisite incomplete at New York: {record['record_id']}"
                )
            if state["windows"]["new_york"]["status"] != "NOT_STARTED":
                raise ValueError(
                    f"New York session leaked into decision: {record['record_id']}"
                )
        else:
            raise ValueError(f"Unknown session code: {record['record_id']}")
        for level in state["known_levels"]:
            if _timestamp(level["known_at"]) > decision:
                raise ValueError(f"Future level at decision: {record['record_id']}")
        _assert_join_time(
            state["market_structure_snapshot_id"],
            structure_times,
            decision,
            exact=True,
        )
        _assert_join_time(
            state["cross_market_snapshot_id"],
            cross_times,
            decision,
            exact=True,
        )
        _assert_join_time(
            state["fundamental_snapshot_id"],
            fundamental_times,
            decision,
            exact=True,
        )
        positioning_id = state["positioning_record_id"]
        if positioning_id is not None:
            _assert_join_time(
                positioning_id,
                positioning_times,
                decision,
                exact=False,
            )
        _assert_join_time(
            subsequent["market_structure_snapshot_id"],
            structure_times,
            observation_end,
            exact=True,
        )
        if len(subsequent["five_minute_path"]) != 48:
            raise ValueError(f"Session 5-minute path incomplete: {record['record_id']}")
        if (
            subsequent["one_minute_source_reference"][
                "expected_complete_bar_count"
            ]
            != 240
        ):
            raise ValueError(f"Session 1-minute path invalid: {record['record_id']}")
        policy = record["research_policy"]
        if any(policy.values()):
            raise ValueError(
                f"Session contains prohibited research outcome: {record['record_id']}"
            )
    return london, new_york


def _assert_join_time(
    record_id: str,
    available: Mapping[str, datetime],
    decision: datetime,
    *,
    exact: bool,
) -> None:
    if record_id not in available:
        raise ValueError(f"Missing joined record: {record_id}")
    timestamp = available[record_id]
    if (exact and timestamp != decision) or (not exact and timestamp > decision):
        raise ValueError(f"Point-in-time join violation: {record_id}")


def _assert_no_forbidden_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        forbidden = FORBIDDEN_RESEARCH_FIELDS & value.keys()
        if forbidden:
            raise ValueError(f"Forbidden research fields found: {sorted(forbidden)}")
        for item in value.values():
            _assert_no_forbidden_fields(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_forbidden_fields(item)


def _records(path: Path) -> Iterable[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Naive timestamp in casebook: {value}")
    return parsed.astimezone(UTC)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Independently verify the immutable Gold Casebook bundle."
    )
    parser.add_argument(
        "--bundle",
        default="/workspace/research_artifacts/gold_casebook_v01",
    )
    parser.add_argument(
        "--output",
        default=(
            "/workspace/research_artifacts/gold_casebook_v01/"
            "semantic_validation.json"
        ),
    )
    return parser


if __name__ == "__main__":
    main()
