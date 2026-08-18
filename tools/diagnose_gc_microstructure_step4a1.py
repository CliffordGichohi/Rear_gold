#!/usr/bin/env python3
"""Run the frozen Step 4A.1 engineering failure diagnostic.

Only technical flags, timestamp relations, native-event grouping, book-validity
classes, elapsed times, counts, and hashes are emitted. No market price, size,
feature value, outcome, signal, execution result, or PnL is reported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4a1_protocol_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4a1_freeze_v01.json"
)
STEP4A_MANIFEST_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_4a_v01"
    / "manifest.json"
)
MBO_PATH = (
    REPO_ROOT
    / "data"
    / "raw"
    / "databento_gc_mbo_engineering_pilot"
    / "GLBX-20260730-WB9AXCVFET"
    / "normalized"
    / "gc_v_0_2024_01_09_mbo.parquet"
)
MBP_PATH = (
    REPO_ROOT
    / "data"
    / "raw"
    / "databento_gc_mbp10_engineering_benchmark"
    / "GLBX-20260731-UJHWEDQUSX"
    / "normalized"
    / "gc_v_0_2024_01_09_mbp10.parquet"
)
MBO_QUALITY_PATH = MBO_PATH.parent / "data_quality_amendment_v02.json"
MBP_QUALITY_PATH = MBP_PATH.parent / "data_quality.json"
DEFAULT_OUTPUT = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_4a1_v01"
)
REPORT_PATH = REPO_ROOT / "GC_MICROSTRUCTURE_STEP_4A1_REPORT.md"

EXPECTED_PROTOCOL_SHA256 = (
    "8520f5d87d128131085075d61381425d680b2d0e6d1469c6e8b1c440263824e4"
)
EXPECTED_FREEZE_SHA256 = (
    "202e0305e02f2e98763f514e863206be7b68fe49e22d12e2186f75ffceb620be"
)
EXPECTED_STEP4A_MANIFEST_HASH = (
    "4960f1ee7f03e21cc490ea81b8e15554ed6c879527d8a02c3956b849cab2bf0f"
)
EXPECTED_STEP4A_VERDICT_HASH = (
    "853c99ea3c8655869ead48c15b09409952789cd8cb964df06c53aa84583c2c07"
)
EXPECTED_MBO_SHA256 = (
    "43a8a3bb2be9a4a36ab324e3fe0ca0e29ccb4529f445013a87156d3bad4c0ba3"
)
EXPECTED_MBP_SHA256 = (
    "4ead358f538d7c383a14f39bbde35b8ccfa21e38e58205edbc51bedfb2ed80d4"
)
EXPECTED_MBO_QUALITY_SHA256 = (
    "e9cec68c3d78e3f54638dad9e05e172ca44e1bac15bffee2329eb8aa29e37185"
)
EXPECTED_MBP_QUALITY_SHA256 = (
    "2782aeface4c16001195c4a7b4b4cf095f40e5e7adc5e28da4b46760baecb7ec"
)
EXPECTED_MBO_RECORDS = 2_322_905
EXPECTED_MBP_RECORDS = 1_924_786
EXPECTED_BAD_FLAG_ROWS = 2_745
EXPECTED_CROSSED_ROWS = 1
EXPECTED_CROSSED_BUCKETS = 60
EXPECTED_PUBLISHER_ID = 1
EXPECTED_INSTRUMENT_ID = 41_512

DAY_START_NS = 1_704_758_400_000_000_000
DAY_END_NS = 1_704_844_800_000_000_000
BUCKET_WIDTH_NS = 1_000_000_000
UNDEFINED_PRICE = 9_223_372_036_854_775_807
F_MAYBE_BAD_BOOK = 4
F_BAD_TS_RECV = 8
F_SNAPSHOT = 32
F_LAST = 128
BATCH_SIZE = 50_000
ALLOWED_SNAPSHOT_ACTIONS = {"A", "R"}

SEGMENTS = (
    (
        "CONTINUOUS_00_22",
        "CONTINUOUS_MATCHING",
        1_704_758_400_000_000_000,
        1_704_837_600_000_000_000,
    ),
    (
        "MAINTENANCE_22_2245",
        "MAINTENANCE",
        1_704_837_600_000_000_000,
        1_704_840_300_000_000_000,
    ),
    (
        "PRE_OPEN_2245_23",
        "PRE_OPEN",
        1_704_840_300_000_000_000,
        1_704_841_200_000_000_000,
    ),
    (
        "CONTINUOUS_23_24",
        "CONTINUOUS_MATCHING",
        1_704_841_200_000_000_000,
        1_704_844_800_000_000_000,
    ),
)

BASE_COLUMNS = (
    "source_row_ordinal",
    "ts_recv",
    "ts_event",
    "publisher_id",
    "instrument_id",
    "sequence",
    "action",
    "flags",
)
MBO_COLUMNS = BASE_COLUMNS
MBP_COLUMNS = (
    *BASE_COLUMNS,
    "bid_px_00",
    "bid_sz_00",
    "bid_ct_00",
    "ask_px_00",
    "ask_sz_00",
    "ask_ct_00",
)

TAXONOMY = (
    "CROSSED_AT_TERMINAL_F_LAST",
    "CROSSED_PRE_TERMINAL_F_LAST_COMPLETES_TWO_SIDED_UNCROSSED",
    "CROSSED_PRE_TERMINAL_F_LAST_COMPLETES_CROSSED",
    "CROSSED_PRE_TERMINAL_F_LAST_COMPLETES_ONE_SIDED",
    "CROSSED_GROUP_NO_UNIQUE_TERMINAL_F_LAST",
    "CROSSED_SNAPSHOT_OR_NONCONTIGUOUS_GROUP",
)
RECOMMENDATION_ID = "SNAPSHOT_EXCEPTION_AND_COMPLETED_MBP_STATE_V0_1"
RECOMMENDATION_TEXT = (
    "In a future separately authorized amendment only, permit BAD_TS_RECV "
    "rows solely when they satisfy the frozen snapshot semantics, and "
    "construct authoritative MBP state only from the valid snapshot baseline "
    "or unique terminal F_LAST native-event boundaries. Keep every other "
    "Step 4A definition and gate unchanged."
)

INT64 = struct.Struct(">q")
UINT32 = struct.Struct(">I")


@dataclass(slots=True)
class PrimaryRow:
    identity_hash: str
    recv: int
    action: str
    flags: int
    two_sided: bool
    crossed: bool
    state_class: str
    market_state: str
    next_recv: int | None = None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("primary", "reference", "seal", "verify")
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    run_stage(args.action, Path(args.output))


def run_stage(action: str, output: Path) -> None:
    context = _verified_context()
    _assert_protocol_matches_code(context["protocol"])
    output.mkdir(parents=True, exist_ok=True)

    if action in {"primary", "reference"}:
        destination = output / f"{action}_diagnostic.json"
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite {destination}")
        result = (
            _run_primary_diagnostic(context)
            if action == "primary"
            else _run_reference_diagnostic(context)
        )
        _write_json_atomic(destination, result)
        print(
            json.dumps(
                {
                    "stage": (
                        f"GC_MICROSTRUCTURE_STEP_4A1_{action.upper()}_COMPLETE"
                    ),
                    "implementation": action,
                    "mbo_records": result["audits"]["mbo"]["records"],
                    "mbp10_records": result["audits"]["mbp10"]["records"],
                    "bad_ts_recv_finding": result["findings"][
                        "bad_ts_recv_snapshot_semantics"
                    ],
                    "crossed_book_finding": result["findings"][
                        "crossed_unfinished_event"
                    ],
                    "recommendation": result["recommendation"]["id"],
                    "integrity_pass": result["formal_integrity_pass"],
                    "market_values_reported": False,
                    "outcomes_accessed": False,
                },
                sort_keys=True,
            )
        )
        return
    if action == "seal":
        _seal(output, context)
        return
    if action == "verify":
        _verify_seal(output)
        return
    raise AssertionError(action)


def _run_primary_diagnostic(context: dict[str, Any]) -> dict[str, Any]:
    mbo, mbo_input = _primary_scan_bad_source(
        MBO_PATH, "MBO", MBO_COLUMNS
    )
    mbp, crossed, mbp_input = _primary_scan_mbp()
    bad = _primary_combine_bad(mbo, mbp)
    findings = {
        "bad_ts_recv_snapshot_semantics": bad["finding"],
        "crossed_unfinished_event": crossed["finding"],
    }
    recommendation = (
        {"id": RECOMMENDATION_ID, "text": RECOMMENDATION_TEXT}
        if all(value == "CONFIRMED" for value in findings.values())
        else {"id": "NONE", "text": None}
    )
    audits = {
        "mbo": mbo["audit"],
        "mbp10": mbp["audit"],
        "native_event_groups": crossed["group_audit"],
    }
    integrity = _diagnostic_integrity(
        context, audits, bad, crossed, recommendation
    )
    return {
        "version": "GC_MICROSTRUCTURE_STEP_4A1_RUN_V0_1",
        "implementation": "primary",
        "classification": "ENGINEERING_FAILURE_DIAGNOSTIC_ONLY",
        "research_or_validation_credit": "NONE",
        "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "tool_sha256": _sha256(Path(__file__)),
        "source_input_checksums": {
            "mbo_complete_pass": mbo_input,
            "mbp10_complete_pass": mbp_input,
        },
        "audits": audits,
        "bad_ts_recv": bad,
        "crossed_book": crossed,
        "findings": findings,
        "recommendation": recommendation,
        "integrity_checks": integrity,
        "formal_integrity_pass": all(integrity.values()),
        **_scope_flags(),
    }


def _run_reference_diagnostic(context: dict[str, Any]) -> dict[str, Any]:
    mbo, mbo_input = _reference_scan_bad_source(
        MBO_PATH, "MBO", MBO_COLUMNS
    )
    mbp, crossed, mbp_input = _reference_scan_mbp()
    bad = _reference_combine_bad(mbo, mbp)
    bad_finding = bad["finding"]
    crossed_finding = crossed["finding"]
    if bad_finding == "CONFIRMED" and crossed_finding == "CONFIRMED":
        recommendation = {
            "id": RECOMMENDATION_ID,
            "text": RECOMMENDATION_TEXT,
        }
    else:
        recommendation = {"id": "NONE", "text": None}
    findings = {
        "bad_ts_recv_snapshot_semantics": bad_finding,
        "crossed_unfinished_event": crossed_finding,
    }
    audits = {
        "mbo": mbo["audit"],
        "mbp10": mbp["audit"],
        "native_event_groups": crossed["group_audit"],
    }
    integrity = _diagnostic_integrity(
        context, audits, bad, crossed, recommendation
    )
    return {
        "version": "GC_MICROSTRUCTURE_STEP_4A1_RUN_V0_1",
        "implementation": "reference",
        "classification": "ENGINEERING_FAILURE_DIAGNOSTIC_ONLY",
        "research_or_validation_credit": "NONE",
        "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "tool_sha256": _sha256(Path(__file__)),
        "source_input_checksums": {
            "mbo_complete_pass": mbo_input,
            "mbp10_complete_pass": mbp_input,
        },
        "audits": audits,
        "bad_ts_recv": bad,
        "crossed_book": crossed,
        "findings": findings,
        "recommendation": recommendation,
        "integrity_checks": integrity,
        "formal_integrity_pass": all(integrity.values()),
        **_scope_flags(),
    }


def _primary_scan_bad_source(
    path: Path, source: str, columns: tuple[str, ...]
) -> tuple[dict[str, Any], str]:
    audit: Counter[str] = Counter()
    bad: Counter[str] = Counter()
    bad_actions: Counter[str] = Counter()
    snapshot_actions: Counter[str] = Counter()
    bad_identity = hashlib.sha256()
    input_hash = hashlib.sha256()
    prior_recv: int | None = None
    prior_ordinal: int | None = None

    for batch in pq.ParquetFile(path).iter_batches(
        batch_size=BATCH_SIZE, columns=list(columns)
    ):
        _update_batch_checksum(input_hash, batch)
        arrays = _arrays(batch, columns)
        receives = arrays["ts_recv"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        events = arrays["ts_event"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        ordinals = arrays["source_row_ordinal"].to_numpy(
            zero_copy_only=False
        )
        publishers = arrays["publisher_id"].to_numpy(zero_copy_only=False)
        instruments = arrays["instrument_id"].to_numpy(zero_copy_only=False)
        sequences = arrays["sequence"].to_numpy(zero_copy_only=False)
        flags_values = arrays["flags"].to_numpy(zero_copy_only=False)
        actions = arrays["action"].to_pylist()
        for index in range(batch.num_rows):
            recv = int(receives[index])
            event = int(events[index])
            ordinal = int(ordinals[index])
            publisher = int(publishers[index])
            instrument = int(instruments[index])
            sequence = int(sequences[index])
            flags = int(flags_values[index])
            action = str(actions[index])
            audit["records"] += 1
            if prior_recv is not None and recv < prior_recv:
                audit["receive_timestamp_regressions"] += 1
            if prior_ordinal is not None and ordinal <= prior_ordinal:
                audit["source_ordinal_regressions"] += 1
            prior_recv = recv
            prior_ordinal = ordinal
            audit["outside_frozen_day"] += int(
                not (DAY_START_NS <= recv < DAY_END_NS)
            )
            audit["publisher_mismatches"] += int(
                publisher != EXPECTED_PUBLISHER_ID
            )
            audit["instrument_mismatches"] += int(
                instrument != EXPECTED_INSTRUMENT_ID
            )
            is_snapshot = bool(flags & F_SNAPSHOT)
            if is_snapshot:
                bad["snapshot_rows"] += 1
                snapshot_actions[action] += 1
                bad["pre_start_snapshot_rows"] += int(
                    recv == DAY_START_NS and event < DAY_START_NS
                )
            if not flags & F_BAD_TS_RECV:
                continue
            bad["bad_flag_rows"] += 1
            bad_actions[action] += 1
            bad["bad_snapshot_rows"] += int(is_snapshot)
            bad["bad_non_snapshot_rows"] += int(not is_snapshot)
            bad["bad_receive_at_day_start_rows"] += int(
                recv == DAY_START_NS
            )
            bad["bad_receive_not_at_day_start_rows"] += int(
                recv != DAY_START_NS
            )
            bad["bad_receive_inside_request_rows"] += int(
                DAY_START_NS <= recv < DAY_END_NS
            )
            bad["bad_receive_outside_request_rows"] += int(
                not (DAY_START_NS <= recv < DAY_END_NS)
            )
            bad["bad_event_pre_start_rows"] += int(event < DAY_START_NS)
            bad["bad_event_not_pre_start_rows"] += int(
                event >= DAY_START_NS
            )
            bad["bad_event_after_receive_rows"] += int(event > recv)
            bad["bad_action_allowed_rows"] += int(
                action in ALLOWED_SNAPSHOT_ACTIONS
            )
            bad["bad_action_not_allowed_rows"] += int(
                action not in ALLOWED_SNAPSHOT_ACTIONS
            )
            identity = _row_identity_hash(
                source,
                ordinal,
                publisher,
                instrument,
                sequence,
                event,
                recv,
            )
            bad_identity.update(bytes.fromhex(identity))

    return {
        "audit": _source_audit(audit),
        "counts": _bad_counts(bad),
        "bad_action_counts": _counter_dict(bad_actions),
        "snapshot_action_counts": _counter_dict(snapshot_actions),
        "bad_row_identity_checksum": bad_identity.hexdigest(),
    }, input_hash.hexdigest()


def _reference_scan_bad_source(
    path: Path, source: str, columns: tuple[str, ...]
) -> tuple[dict[str, Any], str]:
    source_audit: Counter[str] = Counter()
    measurements: Counter[str] = Counter()
    actions_on_bad: dict[str, int] = {}
    actions_on_snapshot: dict[str, int] = {}
    identity_digest = hashlib.sha256()
    complete_pass = hashlib.sha256()
    last_receive: int | None = None
    last_ordinal: int | None = None

    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(
        batch_size=BATCH_SIZE, columns=list(columns)
    ):
        _update_batch_checksum(complete_pass, batch)
        receive_values = batch.column(
            batch.schema.get_field_index("ts_recv")
        ).cast(pa.int64()).to_numpy(zero_copy_only=False)
        event_values = batch.column(
            batch.schema.get_field_index("ts_event")
        ).cast(pa.int64()).to_numpy(zero_copy_only=False)
        ordinal_values = batch.column(
            batch.schema.get_field_index("source_row_ordinal")
        ).to_numpy(zero_copy_only=False)
        publisher_values = batch.column(
            batch.schema.get_field_index("publisher_id")
        ).to_numpy(zero_copy_only=False)
        instrument_values = batch.column(
            batch.schema.get_field_index("instrument_id")
        ).to_numpy(zero_copy_only=False)
        sequence_values = batch.column(
            batch.schema.get_field_index("sequence")
        ).to_numpy(zero_copy_only=False)
        flag_values = batch.column(
            batch.schema.get_field_index("flags")
        ).to_numpy(zero_copy_only=False)
        action_values = batch.column(
            batch.schema.get_field_index("action")
        ).to_pylist()
        for row in range(batch.num_rows):
            receive = int(receive_values[row])
            event_time = int(event_values[row])
            ordinal = int(ordinal_values[row])
            publisher = int(publisher_values[row])
            instrument = int(instrument_values[row])
            sequence = int(sequence_values[row])
            flags = int(flag_values[row])
            action = str(action_values[row])
            source_audit["records"] += 1
            if last_receive is not None:
                source_audit["receive_timestamp_regressions"] += int(
                    receive < last_receive
                )
            if last_ordinal is not None:
                source_audit["source_ordinal_regressions"] += int(
                    ordinal <= last_ordinal
                )
            last_receive = receive
            last_ordinal = ordinal
            source_audit["outside_frozen_day"] += int(
                receive < DAY_START_NS or receive >= DAY_END_NS
            )
            source_audit["publisher_mismatches"] += int(
                publisher != EXPECTED_PUBLISHER_ID
            )
            source_audit["instrument_mismatches"] += int(
                instrument != EXPECTED_INSTRUMENT_ID
            )
            snapshot = (flags & F_SNAPSHOT) != 0
            if snapshot:
                measurements["snapshot_rows"] += 1
                actions_on_snapshot[action] = (
                    actions_on_snapshot.get(action, 0) + 1
                )
                if receive == DAY_START_NS and event_time < DAY_START_NS:
                    measurements["pre_start_snapshot_rows"] += 1
            if (flags & F_BAD_TS_RECV) == 0:
                continue
            measurements["bad_flag_rows"] += 1
            actions_on_bad[action] = actions_on_bad.get(action, 0) + 1
            measurements[
                "bad_snapshot_rows" if snapshot else "bad_non_snapshot_rows"
            ] += 1
            at_start = receive == DAY_START_NS
            measurements[
                "bad_receive_at_day_start_rows"
                if at_start
                else "bad_receive_not_at_day_start_rows"
            ] += 1
            in_request = DAY_START_NS <= receive < DAY_END_NS
            measurements[
                "bad_receive_inside_request_rows"
                if in_request
                else "bad_receive_outside_request_rows"
            ] += 1
            pre_start = event_time < DAY_START_NS
            measurements[
                "bad_event_pre_start_rows"
                if pre_start
                else "bad_event_not_pre_start_rows"
            ] += 1
            measurements["bad_event_after_receive_rows"] += int(
                event_time > receive
            )
            action_allowed = action in ALLOWED_SNAPSHOT_ACTIONS
            measurements[
                "bad_action_allowed_rows"
                if action_allowed
                else "bad_action_not_allowed_rows"
            ] += 1
            identity_digest.update(
                bytes.fromhex(
                    _row_identity_hash(
                        source,
                        ordinal,
                        publisher,
                        instrument,
                        sequence,
                        event_time,
                        receive,
                    )
                )
            )
    return {
        "audit": _source_audit(source_audit),
        "counts": _bad_counts(measurements),
        "bad_action_counts": dict(sorted(actions_on_bad.items())),
        "snapshot_action_counts": dict(
            sorted(actions_on_snapshot.items())
        ),
        "bad_row_identity_checksum": identity_digest.hexdigest(),
    }, complete_pass.hexdigest()


def _primary_scan_mbp() -> tuple[dict[str, Any], dict[str, Any], str]:
    audit: Counter[str] = Counter()
    bad: Counter[str] = Counter()
    bad_actions: Counter[str] = Counter()
    snapshot_actions: Counter[str] = Counter()
    bad_identity = hashlib.sha256()
    input_hash = hashlib.sha256()
    group_audit: Counter[str] = Counter()
    taxonomy: Counter[str] = Counter()
    observations: list[dict[str, Any]] = []
    current_key: tuple[int, int, int] | None = None
    current_rows: list[PrimaryRow] = []
    current_group_contiguous = True
    prior_recv: int | None = None
    prior_ordinal: int | None = None
    pending_crossed: PrimaryRow | None = None

    for batch in pq.ParquetFile(MBP_PATH).iter_batches(
        batch_size=BATCH_SIZE, columns=list(MBP_COLUMNS)
    ):
        _update_batch_checksum(input_hash, batch)
        arrays = _arrays(batch, MBP_COLUMNS)
        receives = arrays["ts_recv"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        events = arrays["ts_event"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        ordinals = arrays["source_row_ordinal"].to_numpy(
            zero_copy_only=False
        )
        publishers = arrays["publisher_id"].to_numpy(zero_copy_only=False)
        instruments = arrays["instrument_id"].to_numpy(zero_copy_only=False)
        sequences = arrays["sequence"].to_numpy(zero_copy_only=False)
        flags_values = arrays["flags"].to_numpy(zero_copy_only=False)
        actions = arrays["action"].to_pylist()
        bid_px_values = arrays["bid_px_00"].to_numpy(zero_copy_only=False)
        bid_sz_values = arrays["bid_sz_00"].to_numpy(zero_copy_only=False)
        bid_ct_values = arrays["bid_ct_00"].to_numpy(zero_copy_only=False)
        ask_px_values = arrays["ask_px_00"].to_numpy(zero_copy_only=False)
        ask_sz_values = arrays["ask_sz_00"].to_numpy(zero_copy_only=False)
        ask_ct_values = arrays["ask_ct_00"].to_numpy(zero_copy_only=False)

        for index in range(batch.num_rows):
            recv = int(receives[index])
            event = int(events[index])
            ordinal = int(ordinals[index])
            publisher = int(publishers[index])
            instrument = int(instruments[index])
            sequence = int(sequences[index])
            flags = int(flags_values[index])
            action = str(actions[index])
            if pending_crossed is not None:
                pending_crossed.next_recv = recv
                pending_crossed = None
            audit["records"] += 1
            if prior_recv is not None and recv < prior_recv:
                audit["receive_timestamp_regressions"] += 1
            if prior_ordinal is not None and ordinal <= prior_ordinal:
                audit["source_ordinal_regressions"] += 1
            prior_recv = recv
            prior_ordinal = ordinal
            audit["outside_frozen_day"] += int(
                not (DAY_START_NS <= recv < DAY_END_NS)
            )
            audit["publisher_mismatches"] += int(
                publisher != EXPECTED_PUBLISHER_ID
            )
            audit["instrument_mismatches"] += int(
                instrument != EXPECTED_INSTRUMENT_ID
            )
            key = (publisher, instrument, sequence)
            if current_key is not None and key != current_key:
                if key <= current_key:
                    group_audit["group_key_regressions"] += 1
                _primary_finalize_group(
                    current_key,
                    current_rows,
                    current_group_contiguous,
                    taxonomy,
                    observations,
                    group_audit,
                )
                current_rows = []
                current_group_contiguous = key > current_key
            current_key = key

            snapshot = bool(flags & F_SNAPSHOT)
            if snapshot:
                bad["snapshot_rows"] += 1
                snapshot_actions[action] += 1
                bad["pre_start_snapshot_rows"] += int(
                    recv == DAY_START_NS and event < DAY_START_NS
                )
            if flags & F_BAD_TS_RECV:
                bad["bad_flag_rows"] += 1
                bad_actions[action] += 1
                bad["bad_snapshot_rows"] += int(snapshot)
                bad["bad_non_snapshot_rows"] += int(not snapshot)
                bad["bad_receive_at_day_start_rows"] += int(
                    recv == DAY_START_NS
                )
                bad["bad_receive_not_at_day_start_rows"] += int(
                    recv != DAY_START_NS
                )
                bad["bad_receive_inside_request_rows"] += int(
                    DAY_START_NS <= recv < DAY_END_NS
                )
                bad["bad_receive_outside_request_rows"] += int(
                    not (DAY_START_NS <= recv < DAY_END_NS)
                )
                bad["bad_event_pre_start_rows"] += int(
                    event < DAY_START_NS
                )
                bad["bad_event_not_pre_start_rows"] += int(
                    event >= DAY_START_NS
                )
                bad["bad_event_after_receive_rows"] += int(event > recv)
                bad["bad_action_allowed_rows"] += int(
                    action in ALLOWED_SNAPSHOT_ACTIONS
                )
                bad["bad_action_not_allowed_rows"] += int(
                    action not in ALLOWED_SNAPSHOT_ACTIONS
                )
                bad_identity.update(
                    bytes.fromhex(
                        _row_identity_hash(
                            "MBP10",
                            ordinal,
                            publisher,
                            instrument,
                            sequence,
                            event,
                            recv,
                        )
                    )
                )

            bid_px = int(bid_px_values[index])
            bid_sz = int(bid_sz_values[index])
            bid_ct = int(bid_ct_values[index])
            ask_px = int(ask_px_values[index])
            ask_sz = int(ask_sz_values[index])
            ask_ct = int(ask_ct_values[index])
            two_sided = (
                bid_px != UNDEFINED_PRICE
                and ask_px != UNDEFINED_PRICE
                and bid_sz > 0
                and ask_sz > 0
                and bid_ct > 0
                and ask_ct > 0
            )
            crossed = two_sided and ask_px < bid_px
            state_class = (
                "CROSSED"
                if crossed
                else "TWO_SIDED_UNCROSSED"
                if two_sided
                else "ONE_SIDED"
            )
            market_state = _market_state(recv)
            identity = _row_identity_hash(
                "MBP10",
                ordinal,
                publisher,
                instrument,
                sequence,
                event,
                recv,
            )
            row = PrimaryRow(
                identity_hash=identity,
                recv=recv,
                action=action,
                flags=flags,
                two_sided=two_sided,
                crossed=crossed,
                state_class=state_class,
                market_state=market_state,
            )
            current_rows.append(row)
            if crossed and market_state == "CONTINUOUS_MATCHING":
                group_audit["continuous_crossed_rows"] += 1
                pending_crossed = row
            if (
                crossed
                and market_state == "CONTINUOUS_MATCHING"
                and flags & F_LAST
            ):
                group_audit["continuous_crossed_f_last_rows"] += 1

    if pending_crossed is not None:
        pending_crossed.next_recv = _segment_end(pending_crossed.recv)
    if current_key is not None:
        _primary_finalize_group(
            current_key,
            current_rows,
            current_group_contiguous,
            taxonomy,
            observations,
            group_audit,
        )
    group_audit["crossed_persistence_bucket_closes"] = sum(
        int(item["persistence_bucket_closes"]) for item in observations
    )
    crossed_result = _primary_crossed_result(
        taxonomy, observations, group_audit
    )
    return {
        "audit": _source_audit(audit),
        "counts": _bad_counts(bad),
        "bad_action_counts": _counter_dict(bad_actions),
        "snapshot_action_counts": _counter_dict(snapshot_actions),
        "bad_row_identity_checksum": bad_identity.hexdigest(),
    }, crossed_result, input_hash.hexdigest()


def _reference_scan_mbp() -> tuple[dict[str, Any], dict[str, Any], str]:
    source_audit: Counter[str] = Counter()
    bad_measurements: Counter[str] = Counter()
    bad_actions: dict[str, int] = {}
    snapshot_actions: dict[str, int] = {}
    bad_digest = hashlib.sha256()
    complete_pass = hashlib.sha256()
    group_stats: Counter[str] = Counter()
    taxonomy_counts: dict[str, int] = {name: 0 for name in TAXONOMY}
    classified: list[dict[str, Any]] = []
    active_key: tuple[int, int, int] | None = None
    active_rows: list[dict[str, Any]] = []
    active_contiguous = True
    last_receive: int | None = None
    last_ordinal: int | None = None
    unresolved_crossed_row: dict[str, Any] | None = None

    for batch in pq.ParquetFile(MBP_PATH).iter_batches(
        batch_size=BATCH_SIZE, columns=list(MBP_COLUMNS)
    ):
        _update_batch_checksum(complete_pass, batch)
        receives = batch.column(
            batch.schema.get_field_index("ts_recv")
        ).cast(pa.int64()).to_numpy(zero_copy_only=False)
        events = batch.column(
            batch.schema.get_field_index("ts_event")
        ).cast(pa.int64()).to_numpy(zero_copy_only=False)
        ordinals = batch.column(
            batch.schema.get_field_index("source_row_ordinal")
        ).to_numpy(zero_copy_only=False)
        publishers = batch.column(
            batch.schema.get_field_index("publisher_id")
        ).to_numpy(zero_copy_only=False)
        instruments = batch.column(
            batch.schema.get_field_index("instrument_id")
        ).to_numpy(zero_copy_only=False)
        sequences = batch.column(
            batch.schema.get_field_index("sequence")
        ).to_numpy(zero_copy_only=False)
        flags_values = batch.column(
            batch.schema.get_field_index("flags")
        ).to_numpy(zero_copy_only=False)
        actions = batch.column(
            batch.schema.get_field_index("action")
        ).to_pylist()
        bid_prices = batch.column(
            batch.schema.get_field_index("bid_px_00")
        ).to_numpy(zero_copy_only=False)
        bid_sizes = batch.column(
            batch.schema.get_field_index("bid_sz_00")
        ).to_numpy(zero_copy_only=False)
        bid_counts = batch.column(
            batch.schema.get_field_index("bid_ct_00")
        ).to_numpy(zero_copy_only=False)
        ask_prices = batch.column(
            batch.schema.get_field_index("ask_px_00")
        ).to_numpy(zero_copy_only=False)
        ask_sizes = batch.column(
            batch.schema.get_field_index("ask_sz_00")
        ).to_numpy(zero_copy_only=False)
        ask_counts = batch.column(
            batch.schema.get_field_index("ask_ct_00")
        ).to_numpy(zero_copy_only=False)

        for row_index in range(batch.num_rows):
            recv = int(receives[row_index])
            event = int(events[row_index])
            ordinal = int(ordinals[row_index])
            publisher = int(publishers[row_index])
            instrument = int(instruments[row_index])
            sequence = int(sequences[row_index])
            flags = int(flags_values[row_index])
            action = str(actions[row_index])
            if unresolved_crossed_row is not None:
                unresolved_crossed_row["next_recv"] = recv
                unresolved_crossed_row = None
            source_audit["records"] += 1
            if last_receive is not None:
                source_audit["receive_timestamp_regressions"] += int(
                    recv < last_receive
                )
            if last_ordinal is not None:
                source_audit["source_ordinal_regressions"] += int(
                    ordinal <= last_ordinal
                )
            last_receive = recv
            last_ordinal = ordinal
            source_audit["outside_frozen_day"] += int(
                recv < DAY_START_NS or recv >= DAY_END_NS
            )
            source_audit["publisher_mismatches"] += int(
                publisher != EXPECTED_PUBLISHER_ID
            )
            source_audit["instrument_mismatches"] += int(
                instrument != EXPECTED_INSTRUMENT_ID
            )
            key = (publisher, instrument, sequence)
            if active_key is not None and key != active_key:
                regression = key <= active_key
                group_stats["group_key_regressions"] += int(regression)
                _reference_finalize_group(
                    active_key,
                    active_rows,
                    active_contiguous,
                    taxonomy_counts,
                    classified,
                    group_stats,
                )
                active_rows = []
                active_contiguous = not regression
            active_key = key

            snapshot = (flags & F_SNAPSHOT) != 0
            if snapshot:
                bad_measurements["snapshot_rows"] += 1
                snapshot_actions[action] = snapshot_actions.get(action, 0) + 1
                if recv == DAY_START_NS and event < DAY_START_NS:
                    bad_measurements["pre_start_snapshot_rows"] += 1
            if flags & F_BAD_TS_RECV:
                bad_measurements["bad_flag_rows"] += 1
                bad_actions[action] = bad_actions.get(action, 0) + 1
                bad_measurements[
                    "bad_snapshot_rows" if snapshot else "bad_non_snapshot_rows"
                ] += 1
                bad_measurements[
                    "bad_receive_at_day_start_rows"
                    if recv == DAY_START_NS
                    else "bad_receive_not_at_day_start_rows"
                ] += 1
                bad_measurements[
                    "bad_receive_inside_request_rows"
                    if DAY_START_NS <= recv < DAY_END_NS
                    else "bad_receive_outside_request_rows"
                ] += 1
                bad_measurements[
                    "bad_event_pre_start_rows"
                    if event < DAY_START_NS
                    else "bad_event_not_pre_start_rows"
                ] += 1
                bad_measurements["bad_event_after_receive_rows"] += int(
                    event > recv
                )
                bad_measurements[
                    "bad_action_allowed_rows"
                    if action in ALLOWED_SNAPSHOT_ACTIONS
                    else "bad_action_not_allowed_rows"
                ] += 1
                bad_digest.update(
                    bytes.fromhex(
                        _row_identity_hash(
                            "MBP10",
                            ordinal,
                            publisher,
                            instrument,
                            sequence,
                            event,
                            recv,
                        )
                    )
                )

            bid_px = int(bid_prices[row_index])
            ask_px = int(ask_prices[row_index])
            two_sided = all(
                (
                    bid_px != UNDEFINED_PRICE,
                    ask_px != UNDEFINED_PRICE,
                    int(bid_sizes[row_index]) > 0,
                    int(ask_sizes[row_index]) > 0,
                    int(bid_counts[row_index]) > 0,
                    int(ask_counts[row_index]) > 0,
                )
            )
            crossed = two_sided and ask_px < bid_px
            state_class = (
                "CROSSED"
                if crossed
                else "TWO_SIDED_UNCROSSED"
                if two_sided
                else "ONE_SIDED"
            )
            market_state = _market_state(recv)
            technical_row = {
                "identity_hash": _row_identity_hash(
                    "MBP10",
                    ordinal,
                    publisher,
                    instrument,
                    sequence,
                    event,
                    recv,
                ),
                "recv": recv,
                "action": action,
                "flags": flags,
                "two_sided": two_sided,
                "crossed": crossed,
                "state_class": state_class,
                "market_state": market_state,
                "next_recv": None,
            }
            active_rows.append(technical_row)
            if crossed and market_state == "CONTINUOUS_MATCHING":
                group_stats["continuous_crossed_rows"] += 1
                unresolved_crossed_row = technical_row
            if crossed and market_state == "CONTINUOUS_MATCHING" and flags & F_LAST:
                group_stats["continuous_crossed_f_last_rows"] += 1

    if unresolved_crossed_row is not None:
        unresolved_crossed_row["next_recv"] = _segment_end(
            int(unresolved_crossed_row["recv"])
        )
    if active_key is not None:
        _reference_finalize_group(
            active_key,
            active_rows,
            active_contiguous,
            taxonomy_counts,
            classified,
            group_stats,
        )
    group_stats["crossed_persistence_bucket_closes"] = sum(
        int(row["persistence_bucket_closes"]) for row in classified
    )
    crossed_result = _reference_crossed_result(
        taxonomy_counts, classified, group_stats
    )
    return {
        "audit": _source_audit(source_audit),
        "counts": _bad_counts(bad_measurements),
        "bad_action_counts": dict(sorted(bad_actions.items())),
        "snapshot_action_counts": dict(sorted(snapshot_actions.items())),
        "bad_row_identity_checksum": bad_digest.hexdigest(),
    }, crossed_result, complete_pass.hexdigest()


def _primary_finalize_group(
    key: tuple[int, int, int],
    rows: list[PrimaryRow],
    contiguous: bool,
    taxonomy: Counter[str],
    observations: list[dict[str, Any]],
    group_audit: Counter[str],
) -> None:
    group_audit["groups"] += 1
    f_last_positions = [
        index for index, row in enumerate(rows) if row.flags & F_LAST
    ]
    terminal_valid = (
        len(f_last_positions) == 1 and f_last_positions[0] == len(rows) - 1
    )
    terminal_index = f_last_positions[0] if terminal_valid else None
    terminal = rows[terminal_index] if terminal_index is not None else None
    group_hash = _group_identity_hash(key)
    for position, row in enumerate(rows):
        if not row.crossed or row.market_state != "CONTINUOUS_MATCHING":
            continue
        if row.flags & F_SNAPSHOT or not contiguous:
            category = "CROSSED_SNAPSHOT_OR_NONCONTIGUOUS_GROUP"
        elif terminal is None or terminal_index is None:
            category = "CROSSED_GROUP_NO_UNIQUE_TERMINAL_F_LAST"
        elif position == terminal_index:
            category = "CROSSED_AT_TERMINAL_F_LAST"
        elif position < terminal_index:
            category = {
                "TWO_SIDED_UNCROSSED": "CROSSED_PRE_TERMINAL_F_LAST_COMPLETES_TWO_SIDED_UNCROSSED",
                "CROSSED": "CROSSED_PRE_TERMINAL_F_LAST_COMPLETES_CROSSED",
                "ONE_SIDED": "CROSSED_PRE_TERMINAL_F_LAST_COMPLETES_ONE_SIDED",
            }[terminal.state_class]
        else:
            category = "CROSSED_GROUP_NO_UNIQUE_TERMINAL_F_LAST"
        taxonomy[category] += 1
        next_recv = (
            row.next_recv
            if row.next_recv is not None
            else _segment_end(row.recv)
        )
        completion_delay = (
            terminal.recv - row.recv
            if terminal is not None and terminal_index is not None and position < terminal_index
            else 0
            if terminal is not None and position == terminal_index
            else None
        )
        observations.append(
            {
                "row_identity_hash": row.identity_hash,
                "group_identity_hash": group_hash,
                "action": row.action,
                "snapshot": bool(row.flags & F_SNAPSHOT),
                "f_last": bool(row.flags & F_LAST),
                "group_position_one_based": position + 1,
                "group_row_count": len(rows),
                "group_f_last_count": len(f_last_positions),
                "unique_terminal_f_last": terminal_valid,
                "terminal_after_crossed": bool(
                    terminal_index is not None and terminal_index > position
                ),
                "terminal_state_class": (
                    terminal.state_class if terminal is not None else None
                ),
                "completion_delay_ns": completion_delay,
                "completion_same_one_second_bucket": bool(
                    terminal is not None
                    and (terminal.recv - DAY_START_NS) // BUCKET_WIDTH_NS
                    == (row.recv - DAY_START_NS) // BUCKET_WIDTH_NS
                ),
                "persistence_bucket_closes": _primary_persistence(
                    row.recv, min(next_recv, _segment_end(row.recv))
                ),
                "taxonomy": category,
            }
        )


def _reference_finalize_group(
    key: tuple[int, int, int],
    rows: list[dict[str, Any]],
    contiguous: bool,
    taxonomy: dict[str, int],
    observations: list[dict[str, Any]],
    group_stats: Counter[str],
) -> None:
    group_stats["groups"] += 1
    final_markers = [
        index for index, row in enumerate(rows) if int(row["flags"]) & F_LAST
    ]
    valid_terminal = (
        len(final_markers) == 1 and final_markers[0] + 1 == len(rows)
    )
    terminal_position = final_markers[0] if valid_terminal else None
    terminal_row = (
        rows[terminal_position] if terminal_position is not None else None
    )
    group_identity = _group_identity_hash(key)
    for index, crossed_row in enumerate(rows):
        if not bool(crossed_row["crossed"]) or crossed_row[
            "market_state"
        ] != "CONTINUOUS_MATCHING":
            continue
        if bool(int(crossed_row["flags"]) & F_SNAPSHOT) or not contiguous:
            classification = "CROSSED_SNAPSHOT_OR_NONCONTIGUOUS_GROUP"
        elif terminal_row is None or terminal_position is None:
            classification = "CROSSED_GROUP_NO_UNIQUE_TERMINAL_F_LAST"
        elif index == terminal_position:
            classification = "CROSSED_AT_TERMINAL_F_LAST"
        elif index < terminal_position:
            terminal_class = str(terminal_row["state_class"])
            if terminal_class == "TWO_SIDED_UNCROSSED":
                classification = "CROSSED_PRE_TERMINAL_F_LAST_COMPLETES_TWO_SIDED_UNCROSSED"
            elif terminal_class == "CROSSED":
                classification = "CROSSED_PRE_TERMINAL_F_LAST_COMPLETES_CROSSED"
            else:
                classification = "CROSSED_PRE_TERMINAL_F_LAST_COMPLETES_ONE_SIDED"
        else:
            classification = "CROSSED_GROUP_NO_UNIQUE_TERMINAL_F_LAST"
        taxonomy[classification] += 1
        row_receive = int(crossed_row["recv"])
        next_receive = (
            int(crossed_row["next_recv"])
            if crossed_row["next_recv"] is not None
            else _segment_end(row_receive)
        )
        if terminal_row is None or terminal_position is None:
            delay: int | None = None
        elif index <= terminal_position:
            delay = int(terminal_row["recv"]) - row_receive
        else:
            delay = None
        observations.append(
            {
                "row_identity_hash": crossed_row["identity_hash"],
                "group_identity_hash": group_identity,
                "action": crossed_row["action"],
                "snapshot": bool(int(crossed_row["flags"]) & F_SNAPSHOT),
                "f_last": bool(int(crossed_row["flags"]) & F_LAST),
                "group_position_one_based": index + 1,
                "group_row_count": len(rows),
                "group_f_last_count": len(final_markers),
                "unique_terminal_f_last": valid_terminal,
                "terminal_after_crossed": bool(
                    terminal_position is not None and terminal_position > index
                ),
                "terminal_state_class": (
                    terminal_row["state_class"]
                    if terminal_row is not None
                    else None
                ),
                "completion_delay_ns": delay,
                "completion_same_one_second_bucket": bool(
                    terminal_row is not None
                    and (int(terminal_row["recv"]) - DAY_START_NS)
                    // BUCKET_WIDTH_NS
                    == (row_receive - DAY_START_NS) // BUCKET_WIDTH_NS
                ),
                "persistence_bucket_closes": _reference_persistence(
                    row_receive,
                    min(next_receive, _segment_end(row_receive)),
                ),
                "taxonomy": classification,
            }
        )


def _primary_crossed_result(
    taxonomy: Counter[str],
    observations: list[dict[str, Any]],
    audit: Counter[str],
) -> dict[str, Any]:
    complete_taxonomy = {name: int(taxonomy[name]) for name in TAXONOMY}
    confirmed = (
        audit["continuous_crossed_rows"] == EXPECTED_CROSSED_ROWS
        and audit["continuous_crossed_f_last_rows"] == 0
        and audit["group_key_regressions"] == 0
        and complete_taxonomy[
            "CROSSED_PRE_TERMINAL_F_LAST_COMPLETES_TWO_SIDED_UNCROSSED"
        ]
        == EXPECTED_CROSSED_ROWS
        and sum(complete_taxonomy.values()) == EXPECTED_CROSSED_ROWS
    )
    return {
        "continuous_crossed_rows": int(
            audit["continuous_crossed_rows"]
        ),
        "continuous_crossed_f_last_rows": int(
            audit["continuous_crossed_f_last_rows"]
        ),
        "persistence_bucket_closes": int(
            audit["crossed_persistence_bucket_closes"]
        ),
        "taxonomy": complete_taxonomy,
        "observations": sorted(
            observations, key=lambda item: item["row_identity_hash"]
        ),
        "group_audit": {
            "groups": int(audit["groups"]),
            "group_key_regressions": int(
                audit["group_key_regressions"]
            ),
        },
        "finding": "CONFIRMED" if confirmed else "NOT_CONFIRMED",
    }


def _reference_crossed_result(
    taxonomy: dict[str, int],
    observations: list[dict[str, Any]],
    audit: Counter[str],
) -> dict[str, Any]:
    total_classified = sum(int(taxonomy[name]) for name in TAXONOMY)
    target_class = int(
        taxonomy[
            "CROSSED_PRE_TERMINAL_F_LAST_COMPLETES_TWO_SIDED_UNCROSSED"
        ]
    )
    confirmed = all(
        (
            int(audit["continuous_crossed_rows"])
            == EXPECTED_CROSSED_ROWS,
            int(audit["continuous_crossed_f_last_rows"]) == 0,
            int(audit["group_key_regressions"]) == 0,
            target_class == EXPECTED_CROSSED_ROWS,
            total_classified == EXPECTED_CROSSED_ROWS,
        )
    )
    return {
        "continuous_crossed_rows": int(
            audit["continuous_crossed_rows"]
        ),
        "continuous_crossed_f_last_rows": int(
            audit["continuous_crossed_f_last_rows"]
        ),
        "persistence_bucket_closes": int(
            audit["crossed_persistence_bucket_closes"]
        ),
        "taxonomy": {name: int(taxonomy[name]) for name in TAXONOMY},
        "observations": sorted(
            observations, key=lambda item: item["row_identity_hash"]
        ),
        "group_audit": {
            "groups": int(audit["groups"]),
            "group_key_regressions": int(
                audit["group_key_regressions"]
            ),
        },
        "finding": "CONFIRMED" if confirmed else "NOT_CONFIRMED",
    }


def _primary_combine_bad(
    mbo: dict[str, Any], mbp: dict[str, Any]
) -> dict[str, Any]:
    combined = {
        name: int(mbo["counts"][name]) + int(mbp["counts"][name])
        for name in _bad_count_names()
    }
    conditions = {
        "bad_rows_exist": combined["bad_flag_rows"] > 0,
        "every_bad_row_is_snapshot": combined["bad_non_snapshot_rows"] == 0,
        "every_bad_row_received_at_day_start": (
            combined["bad_receive_not_at_day_start_rows"] == 0
        ),
        "every_bad_row_received_inside_request": (
            combined["bad_receive_outside_request_rows"] == 0
        ),
        "every_bad_row_event_pre_start": (
            combined["bad_event_not_pre_start_rows"] == 0
        ),
        "no_bad_row_event_after_receive": (
            combined["bad_event_after_receive_rows"] == 0
        ),
        "every_bad_row_action_allowed": (
            combined["bad_action_not_allowed_rows"] == 0
        ),
        "mbo_snapshot_coverage_reproduced": (
            mbo["counts"]["snapshot_rows"] == 2744
            and mbo["counts"]["pre_start_snapshot_rows"] == 2744
            and mbo["snapshot_action_counts"] == {"A": 2743, "R": 1}
        ),
        "mbp_snapshot_coverage_reproduced": (
            mbp["counts"]["snapshot_rows"] == 1
            and mbp["counts"]["pre_start_snapshot_rows"] == 1
            and set(mbp["snapshot_action_counts"]).issubset(
                ALLOWED_SNAPSHOT_ACTIONS
            )
        ),
    }
    identity_checksum = _canonical_hash(
        {
            "MBO": mbo["bad_row_identity_checksum"],
            "MBP10": mbp["bad_row_identity_checksum"],
        }
    )
    return {
        "combined_counts": combined,
        "by_source": {"MBO": _bad_public(mbo), "MBP10": _bad_public(mbp)},
        "condition_checks": conditions,
        "combined_bad_row_identity_checksum": identity_checksum,
        "finding": "CONFIRMED" if all(conditions.values()) else "NOT_CONFIRMED",
    }


def _reference_combine_bad(
    mbo: dict[str, Any], mbp: dict[str, Any]
) -> dict[str, Any]:
    totals: dict[str, int] = {}
    for name in _bad_count_names():
        totals[name] = int(mbo["counts"].get(name, 0)) + int(
            mbp["counts"].get(name, 0)
        )
    checks = {
        "bad_rows_exist": totals["bad_flag_rows"] > 0,
        "every_bad_row_is_snapshot": totals["bad_non_snapshot_rows"] == 0,
        "every_bad_row_received_at_day_start": totals[
            "bad_receive_not_at_day_start_rows"
        ]
        == 0,
        "every_bad_row_received_inside_request": totals[
            "bad_receive_outside_request_rows"
        ]
        == 0,
        "every_bad_row_event_pre_start": totals[
            "bad_event_not_pre_start_rows"
        ]
        == 0,
        "no_bad_row_event_after_receive": totals[
            "bad_event_after_receive_rows"
        ]
        == 0,
        "every_bad_row_action_allowed": totals[
            "bad_action_not_allowed_rows"
        ]
        == 0,
        "mbo_snapshot_coverage_reproduced": all(
            (
                int(mbo["counts"]["snapshot_rows"]) == 2744,
                int(mbo["counts"]["pre_start_snapshot_rows"]) == 2744,
                mbo["snapshot_action_counts"] == {"A": 2743, "R": 1},
            )
        ),
        "mbp_snapshot_coverage_reproduced": all(
            (
                int(mbp["counts"]["snapshot_rows"]) == 1,
                int(mbp["counts"]["pre_start_snapshot_rows"]) == 1,
                all(
                    action in ALLOWED_SNAPSHOT_ACTIONS
                    for action in mbp["snapshot_action_counts"]
                ),
            )
        ),
    }
    combined_identity = _canonical_hash(
        {
            "MBO": mbo["bad_row_identity_checksum"],
            "MBP10": mbp["bad_row_identity_checksum"],
        }
    )
    return {
        "combined_counts": totals,
        "by_source": {"MBO": _bad_public(mbo), "MBP10": _bad_public(mbp)},
        "condition_checks": checks,
        "combined_bad_row_identity_checksum": combined_identity,
        "finding": "CONFIRMED" if False not in checks.values() else "NOT_CONFIRMED",
    }


def _diagnostic_integrity(
    context: dict[str, Any],
    audits: dict[str, Any],
    bad: dict[str, Any],
    crossed: dict[str, Any],
    recommendation: dict[str, Any],
) -> dict[str, bool]:
    mbo = audits["mbo"]
    mbp = audits["mbp10"]
    groups = audits["native_event_groups"]
    return {
        "step_4a_and_all_source_seals_valid": bool(
            context["predecessor_and_source_seals_valid"]
        ),
        "required_columns_present": bool(
            context["required_columns_present"]
        ),
        "all_mbo_and_mbp10_rows_processed": (
            mbo["records"] == EXPECTED_MBO_RECORDS
            and mbp["records"] == EXPECTED_MBP_RECORDS
        ),
        "source_record_counts_exact": bool(context["record_counts_exact"]),
        "receive_order_valid": (
            mbo["receive_timestamp_regressions"] == 0
            and mbo["source_ordinal_regressions"] == 0
            and mbp["receive_timestamp_regressions"] == 0
            and mbp["source_ordinal_regressions"] == 0
        ),
        "publisher_instrument_and_day_exact": (
            mbo["publisher_mismatches"] == 0
            and mbo["instrument_mismatches"] == 0
            and mbo["outside_frozen_day"] == 0
            and mbp["publisher_mismatches"] == 0
            and mbp["instrument_mismatches"] == 0
            and mbp["outside_frozen_day"] == 0
        ),
        "native_event_groups_contiguous": groups[
            "group_key_regressions"
        ]
        == 0,
        "sealed_step_4a_bad_flag_count_reproduced": bad[
            "combined_counts"
        ]["bad_flag_rows"]
        == EXPECTED_BAD_FLAG_ROWS,
        "sealed_step_4a_crossed_counts_reproduced": (
            crossed["continuous_crossed_rows"] == EXPECTED_CROSSED_ROWS
            and crossed["persistence_bucket_closes"]
            == EXPECTED_CROSSED_BUCKETS
        ),
        "every_bad_flag_row_classified": (
            bad["combined_counts"]["bad_snapshot_rows"]
            + bad["combined_counts"]["bad_non_snapshot_rows"]
            == bad["combined_counts"]["bad_flag_rows"]
        ),
        "every_crossed_row_classified_exactly_once": (
            sum(crossed["taxonomy"].values())
            == crossed["continuous_crossed_rows"]
            == len(crossed["observations"])
        ),
        "no_market_values_emitted": True,
        "at_most_one_recommendation": recommendation["id"]
        in {"NONE", RECOMMENDATION_ID},
        "no_prohibited_work": True,
    }


def _primary_persistence(start: int, limit: int) -> int:
    first_end = (
        DAY_START_NS
        + ((start - DAY_START_NS) // BUCKET_WIDTH_NS + 1)
        * BUCKET_WIDTH_NS
    )
    if limit < first_end:
        return 0
    return (limit - first_end) // BUCKET_WIDTH_NS + 1


def _reference_persistence(start: int, limit: int) -> int:
    bucket_number = (start - DAY_START_NS) // BUCKET_WIDTH_NS
    next_close = DAY_START_NS + (bucket_number + 1) * BUCKET_WIDTH_NS
    count = 0
    while next_close <= limit:
        count += 1
        next_close += BUCKET_WIDTH_NS
    return count


def _market_state(timestamp: int) -> str:
    for _segment, state, start, end in SEGMENTS:
        if start <= timestamp < end:
            return state
    raise ValueError(f"Timestamp outside frozen state segments: {timestamp}")


def _segment_end(timestamp: int) -> int:
    for _segment, _state, start, end in SEGMENTS:
        if start <= timestamp < end:
            return end
    raise ValueError(f"Timestamp outside frozen state segments: {timestamp}")


def _row_identity_hash(
    source: str,
    ordinal: int,
    publisher: int,
    instrument: int,
    sequence: int,
    event: int,
    recv: int,
) -> str:
    digest = hashlib.sha256()
    encoded = source.encode("ascii")
    digest.update(UINT32.pack(len(encoded)))
    digest.update(encoded)
    for value in (
        ordinal,
        publisher,
        instrument,
        sequence,
        event,
        recv,
    ):
        digest.update(INT64.pack(value))
    return digest.hexdigest()


def _group_identity_hash(key: tuple[int, int, int]) -> str:
    digest = hashlib.sha256()
    for value in key:
        digest.update(INT64.pack(value))
    return digest.hexdigest()


def _arrays(
    batch: pa.RecordBatch, columns: tuple[str, ...]
) -> dict[str, pa.Array]:
    return {
        name: batch.column(batch.schema.get_field_index(name))
        for name in columns
    }


def _update_batch_checksum(digest: Any, batch: pa.RecordBatch) -> None:
    payload = batch.serialize().to_pybytes()
    digest.update(UINT32.pack(batch.num_rows))
    digest.update(UINT32.pack(len(payload)))
    digest.update(payload)


def _source_audit(counter: Counter[str]) -> dict[str, int]:
    return {
        name: int(counter[name])
        for name in (
            "records",
            "outside_frozen_day",
            "receive_timestamp_regressions",
            "source_ordinal_regressions",
            "publisher_mismatches",
            "instrument_mismatches",
        )
    }


def _bad_count_names() -> tuple[str, ...]:
    return (
        "snapshot_rows",
        "pre_start_snapshot_rows",
        "bad_flag_rows",
        "bad_snapshot_rows",
        "bad_non_snapshot_rows",
        "bad_receive_at_day_start_rows",
        "bad_receive_not_at_day_start_rows",
        "bad_receive_inside_request_rows",
        "bad_receive_outside_request_rows",
        "bad_event_pre_start_rows",
        "bad_event_not_pre_start_rows",
        "bad_event_after_receive_rows",
        "bad_action_allowed_rows",
        "bad_action_not_allowed_rows",
    )


def _bad_counts(counter: Counter[str]) -> dict[str, int]:
    return {name: int(counter[name]) for name in _bad_count_names()}


def _bad_public(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "counts": value["counts"],
        "bad_action_counts": value["bad_action_counts"],
        "snapshot_action_counts": value["snapshot_action_counts"],
        "bad_row_identity_checksum": value["bad_row_identity_checksum"],
    }


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: int(counter[key]) for key in sorted(counter)}


def _scope_flags() -> dict[str, bool]:
    return {
        "feature_pipeline_modified": False,
        "data_repaired_or_filtered": False,
        "mbo_mbp_alignment_attempted": False,
        "additional_data_acquired": False,
        "another_date_inspected": False,
        "market_values_reported": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
        "recommendation_implemented": False,
    }


def _seal(output: Path, context: dict[str, Any]) -> None:
    primary_path = output / "primary_diagnostic.json"
    reference_path = output / "reference_diagnostic.json"
    if not primary_path.exists() or not reference_path.exists():
        raise FileNotFoundError("Both Step 4A.1 diagnostics are required")
    primary = _read_json(primary_path)
    reference = _read_json(reference_path)
    current_tool_hash = _sha256(Path(__file__))
    for run in (primary, reference):
        if run["tool_sha256"] != current_tool_hash:
            raise ValueError("Diagnostic tool changed between runs and seal")

    compared = (
        "source_input_checksums",
        "audits",
        "bad_ts_recv",
        "crossed_book",
        "findings",
        "recommendation",
        "integrity_checks",
        "formal_integrity_pass",
    )
    matching = {name: primary[name] == reference[name] for name in compared}
    reproduction_pass = all(matching.values())
    source_pass = bool(context["predecessor_and_source_seals_valid"])
    integrity_pass = bool(
        primary["formal_integrity_pass"]
        and reference["formal_integrity_pass"]
    )
    if not source_pass:
        status = "FAIL_PREDECESSOR_OR_SOURCE_INTEGRITY"
    elif not integrity_pass:
        status = "FAIL_DIAGNOSTIC_INTEGRITY"
    elif not reproduction_pass:
        status = "FAIL_DIAGNOSTIC_REPRODUCTION"
    else:
        status = "PASS_DIAGNOSTIC_REPRODUCTION"

    formal_gates = {
        "step_4a_and_all_source_seals_valid": source_pass,
        "primary_diagnostic_integrity_pass": bool(
            primary["formal_integrity_pass"]
        ),
        "reference_diagnostic_integrity_pass": bool(
            reference["formal_integrity_pass"]
        ),
        "source_record_counts_and_checksums_reproduced": all(
            matching[name] for name in ("source_input_checksums", "audits")
        ),
        "bad_ts_recv_classification_reproduced": matching["bad_ts_recv"],
        "crossed_book_classification_reproduced": matching["crossed_book"],
        "findings_and_recommendation_reproduced": (
            matching["findings"] and matching["recommendation"]
        ),
        "at_most_one_recommendation": primary["recommendation"]["id"]
        in {"NONE", RECOMMENDATION_ID},
        "no_market_values_emitted": True,
        "no_feature_modification_repair_acquisition_other_date_outcome_signal_execution_or_pnl": all(
            not run[key]
            for run in (primary, reference)
            for key in (
                "feature_pipeline_modified",
                "data_repaired_or_filtered",
                "mbo_mbp_alignment_attempted",
                "additional_data_acquired",
                "another_date_inspected",
                "market_values_reported",
                "outcomes_accessed",
                "signals_calculated",
                "execution_optimized",
                "pnl_calculated",
                "recommendation_implemented",
            )
        ),
    }
    verdict: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_4A1_VERDICT_V0_1",
        "status": status,
        "formal_pass": status == "PASS_DIAGNOSTIC_REPRODUCTION",
        "classification": "ENGINEERING_FAILURE_DIAGNOSTIC_ONLY",
        "research_or_validation_credit": "NONE",
        "predecessor_step_4a_status": "FAIL_FEATURE_INTEGRITY",
        "predecessor_verdicts_preserved": True,
        "findings": primary["findings"],
        "bad_ts_recv": primary["bad_ts_recv"],
        "crossed_book": primary["crossed_book"],
        "recommendation": primary["recommendation"],
        "recommendation_count": int(
            primary["recommendation"]["id"] != "NONE"
        ),
        "reproduction": {
            "pass": reproduction_pass,
            "matching_sections": matching,
        },
        "formal_gates": formal_gates,
        "passed_formal_gates": sum(formal_gates.values()),
        "total_formal_gates": len(formal_gates),
        **_scope_flags(),
        "completion_policy": "Preserve the diagnostic and stop without implementing its recommendation.",
    }
    verdict["verdict_hash"] = _canonical_hash(verdict)
    verdict_path = output / "verdict.json"
    _write_json_atomic(verdict_path, verdict)
    _write_text_atomic(REPORT_PATH, _render_report(verdict))

    artifact_paths = (
        primary_path,
        reference_path,
        verdict_path,
        REPORT_PATH,
    )
    manifest: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_4A1_MANIFEST_V0_1",
        "status": status,
        "sealed_at_utc": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "classification": "ENGINEERING_FAILURE_DIAGNOSTIC_ONLY",
        "research_or_validation_credit": "NONE",
        "protocol": _file_record(PROTOCOL_PATH),
        "freeze_receipt": _file_record(FREEZE_PATH),
        "step4a_manifest": _file_record(STEP4A_MANIFEST_PATH),
        "mbo_source": _file_record(MBO_PATH),
        "mbp10_source": _file_record(MBP_PATH),
        "mbo_snapshot_quality": _file_record(MBO_QUALITY_PATH),
        "mbp10_quality": _file_record(MBP_QUALITY_PATH),
        "diagnostic_tool": _file_record(Path(__file__)),
        "artifacts": [_file_record(path) for path in artifact_paths],
        "verdict_hash": verdict["verdict_hash"],
        "predecessor_verdicts_preserved": True,
        **_scope_flags(),
    }
    manifest["manifest_hash"] = _canonical_hash(manifest)
    _write_json_atomic(output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_4A1_SEALED",
                "status": status,
                "formal_pass": verdict["formal_pass"],
                "bad_ts_recv_finding": verdict["findings"][
                    "bad_ts_recv_snapshot_semantics"
                ],
                "crossed_book_finding": verdict["findings"][
                    "crossed_unfinished_event"
                ],
                "recommendation": verdict["recommendation"]["id"],
                "reproduction_pass": reproduction_pass,
                "manifest_hash": manifest["manifest_hash"],
                "market_values_reported": False,
                "outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _render_report(verdict: dict[str, Any]) -> str:
    bad = verdict["bad_ts_recv"]["combined_counts"]
    crossed = verdict["crossed_book"]
    taxonomy = crossed["taxonomy"]
    observation = (
        crossed["observations"][0] if crossed["observations"] else None
    )
    lines = [
        "# GC Microstructure Step 4A.1 — Failure Diagnostic",
        "",
        "## Formal status",
        "",
        f"`{verdict['status']}`",
        "",
        "## BAD_TS_RECV snapshot semantics",
        "",
        f"- Finding: `{verdict['findings']['bad_ts_recv_snapshot_semantics']}`.",
        f"- BAD_TS_RECV rows: {bad['bad_flag_rows']:,}.",
        f"- Non-snapshot BAD_TS_RECV rows: {bad['bad_non_snapshot_rows']:,}.",
        f"- Rows violating day-start receive semantics: {bad['bad_receive_not_at_day_start_rows']:,}.",
        f"- Rows violating pre-start event semantics: {bad['bad_event_not_pre_start_rows']:,}.",
        f"- Rows with event time after receive time: {bad['bad_event_after_receive_rows']:,}.",
        f"- Rows with a disallowed snapshot action: {bad['bad_action_not_allowed_rows']:,}.",
        "",
        "## Continuous crossed-book row",
        "",
        f"- Finding: `{verdict['findings']['crossed_unfinished_event']}`.",
        f"- Continuous crossed rows: {crossed['continuous_crossed_rows']:,}.",
        f"- Continuous crossed F_LAST rows: {crossed['continuous_crossed_f_last_rows']:,}.",
        f"- Crossed rows completing two-sided uncrossed: {taxonomy['CROSSED_PRE_TERMINAL_F_LAST_COMPLETES_TWO_SIDED_UNCROSSED']:,}.",
        f"- Reproduced crossed-state bucket closes: {crossed['persistence_bucket_closes']:,}.",
    ]
    if observation is not None:
        lines.extend(
            [
                f"- Crossed row was F_LAST: `{str(observation['f_last']).lower()}`.",
                f"- Unique terminal F_LAST existed later: `{str(observation['terminal_after_crossed']).lower()}`.",
                f"- Terminal state class: `{observation['terminal_state_class']}`.",
                f"- Completion delay in nanoseconds: {observation['completion_delay_ns']}.",
                f"- Completion in the same one-second bucket: `{str(observation['completion_same_one_second_bucket']).lower()}`.",
            ]
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"`{verdict['recommendation']['id']}`",
            "",
            (
                verdict["recommendation"]["text"]
                if verdict["recommendation"]["text"] is not None
                else "No correction is recommended under the frozen rule."
            ),
            "",
            "The recommendation was not implemented.",
            "",
            "## Restrictions honored",
            "",
            "No market values were emitted. No feature pipeline modification, data repair, acquisition, other date, outcome, signal, execution optimization, trade, or PnL calculation occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def _verify_seal(output: Path) -> None:
    context = _verified_context()
    _assert_protocol_matches_code(context["protocol"])
    manifest = _read_json(output / "manifest.json")
    verdict = _read_json(output / "verdict.json")
    if manifest["manifest_hash"] != _canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    ):
        raise ValueError("Step 4A.1 manifest hash mismatch")
    if verdict["verdict_hash"] != _canonical_hash(
        {key: value for key, value in verdict.items() if key != "verdict_hash"}
    ):
        raise ValueError("Step 4A.1 verdict hash mismatch")
    for record in manifest["artifacts"]:
        _verify_file_record(record)
    for key, expected in (
        ("protocol", EXPECTED_PROTOCOL_SHA256),
        ("freeze_receipt", EXPECTED_FREEZE_SHA256),
        ("mbo_source", EXPECTED_MBO_SHA256),
        ("mbp10_source", EXPECTED_MBP_SHA256),
        ("mbo_snapshot_quality", EXPECTED_MBO_QUALITY_SHA256),
        ("mbp10_quality", EXPECTED_MBP_QUALITY_SHA256),
    ):
        if manifest[key]["sha256"] != expected:
            raise ValueError(f"Step 4A.1 {key} declaration mismatch")
        _verify_file_record(manifest[key])
    if manifest["diagnostic_tool"]["sha256"] != _sha256(Path(__file__)):
        raise ValueError("Step 4A.1 diagnostic tool changed")
    if manifest["status"] != verdict["status"]:
        raise ValueError("Step 4A.1 status differs between verdict and manifest")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_4A1_SEAL_VERIFIED",
                "status": manifest["status"],
                "manifest_hash": manifest["manifest_hash"],
                "sealed_artifacts_verified": len(manifest["artifacts"]),
                "predecessor_verdicts_preserved": manifest[
                    "predecessor_verdicts_preserved"
                ],
                "feature_pipeline_modified": manifest[
                    "feature_pipeline_modified"
                ],
                "additional_data_acquired": manifest[
                    "additional_data_acquired"
                ],
                "another_date_inspected": manifest["another_date_inspected"],
                "market_values_reported": manifest["market_values_reported"],
                "outcomes_accessed": manifest["outcomes_accessed"],
                "signals_calculated": manifest["signals_calculated"],
                "pnl_calculated": manifest["pnl_calculated"],
                "recommendation_implemented": manifest[
                    "recommendation_implemented"
                ],
                "research_or_validation_credit": manifest[
                    "research_or_validation_credit"
                ],
            },
            sort_keys=True,
        )
    )


def _verified_context() -> dict[str, Any]:
    if _sha256(PROTOCOL_PATH) != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Step 4A.1 protocol changed")
    if _sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 4A.1 freeze receipt changed")
    protocol = _read_json(PROTOCOL_PATH)
    freeze = _read_json(FREEZE_PATH)
    if freeze["protocol"]["sha256"] != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Freeze receipt does not bind Step 4A.1 protocol")

    step4a = _read_json(STEP4A_MANIFEST_PATH)
    computed = _canonical_hash(
        {key: value for key, value in step4a.items() if key != "manifest_hash"}
    )
    if (
        step4a.get("manifest_hash") != EXPECTED_STEP4A_MANIFEST_HASH
        or computed != EXPECTED_STEP4A_MANIFEST_HASH
        or step4a.get("status") != "FAIL_FEATURE_INTEGRITY"
        or step4a.get("verdict_hash") != EXPECTED_STEP4A_VERDICT_HASH
    ):
        raise ValueError("Step 4A predecessor seal changed")
    for record in step4a["artifacts"]:
        _verify_file_record(record)
    for name in (
        "protocol",
        "freeze_receipt",
        "step3f_manifest",
        "mbo_source",
        "mbp10_source",
        "feature_tool",
    ):
        _verify_file_record(step4a[name])
    for path, expected in (
        (MBO_PATH, EXPECTED_MBO_SHA256),
        (MBP_PATH, EXPECTED_MBP_SHA256),
        (MBO_QUALITY_PATH, EXPECTED_MBO_QUALITY_SHA256),
        (MBP_QUALITY_PATH, EXPECTED_MBP_QUALITY_SHA256),
    ):
        if _sha256(path) != expected:
            raise ValueError(f"Sealed Step 4A.1 dependency changed: {path}")
    mbo_parquet = pq.ParquetFile(MBO_PATH)
    mbp_parquet = pq.ParquetFile(MBP_PATH)
    required = (
        set(MBO_COLUMNS).issubset(mbo_parquet.schema_arrow.names)
        and set(MBP_COLUMNS).issubset(mbp_parquet.schema_arrow.names)
    )
    counts = (
        mbo_parquet.metadata.num_rows == EXPECTED_MBO_RECORDS
        and mbp_parquet.metadata.num_rows == EXPECTED_MBP_RECORDS
    )
    if not required or not counts:
        raise ValueError("Step 4A.1 source schema or count changed")
    return {
        "protocol": protocol,
        "freeze": freeze,
        "predecessor_and_source_seals_valid": True,
        "required_columns_present": required,
        "record_counts_exact": counts,
    }


def _assert_protocol_matches_code(protocol: dict[str, Any]) -> None:
    constants = protocol["constants"]
    if (
        constants["day_start_inclusive_ns"] != DAY_START_NS
        or constants["day_end_exclusive_ns"] != DAY_END_NS
        or constants["bucket_width_ns"] != BUCKET_WIDTH_NS
        or constants["undefined_price_fixed_1e9"] != UNDEFINED_PRICE
        or constants["flag_bad_ts_recv"] != F_BAD_TS_RECV
        or constants["flag_snapshot"] != F_SNAPSHOT
        or constants["flag_last"] != F_LAST
    ):
        raise ValueError("Step 4A.1 code constants differ from protocol")
    frozen_segments = tuple(
        (
            item["segment_id"],
            item["state"],
            item["start_inclusive_ns"],
            item["end_exclusive_ns"],
        )
        for item in protocol["market_state_policy"]["segments"]
    )
    if frozen_segments != SEGMENTS:
        raise ValueError("Step 4A.1 market-state segments differ")
    if tuple(protocol["crossed_book_diagnostic"]["exclusive_taxonomy"]) != TAXONOMY:
        raise ValueError("Step 4A.1 taxonomy differs")
    recommendation = protocol["recommendation_rule"][
        "both_findings_confirmed"
    ]
    if (
        recommendation["recommendation_id"] != RECOMMENDATION_ID
        or recommendation["bounded_text"] != RECOMMENDATION_TEXT
    ):
        raise ValueError("Step 4A.1 recommendation rule differs")


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _verify_file_record(record: dict[str, Any]) -> None:
    path = Path(record["path"])
    if not path.exists():
        raise FileNotFoundError(path)
    if path.stat().st_size != record["bytes"]:
        raise ValueError(f"File size changed: {path}")
    if _sha256(path) != record["sha256"]:
        raise ValueError(f"File hash changed: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_text_atomic(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
