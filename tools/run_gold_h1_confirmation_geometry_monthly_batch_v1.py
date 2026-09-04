#!/usr/bin/env python3
"""Restartable June-2022 through December-2024 H1 geometry batch."""

from __future__ import annotations

import csv
import gc
import gzip
import hashlib
import json
import os
import sys
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT / "tools")]

import materialize_gold_blind_discretionary_replay_v1 as replay_source  # noqa: E402
import run_gold_february_h1_confirmation_only_reclaim_v1 as feb  # noqa: E402
import run_gold_h1_confirmation_entry_stop_geometry_audit_v1 as audit  # noqa: E402
import run_gold_mar_apr_may_h1_confirmation_only_reclaim_v1 as mar  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import require, sha256_file  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    canonical_json,
    iso,
    parse_dt,
)
from gold_intel.analytics.h1_confirmation_geometry_audit_v1 import (  # noqa: E402
    CONTROL_ENTRY,
    CONTROL_STOP,
    ENTRY_POLICIES,
    RULESET,
    STOP_POLICIES,
    M1Path,
    build_structure_registry,
    evaluate_policy,
    stop_geometry,
    summarize,
    synthetic_proof,
)

BATCH_VERSION = "GOLD_H1_CONFIRMATION_GEOMETRY_MONTHLY_BATCH_V1"
SPEC = ROOT / "GOLD_H1_CONFIRMATION_GEOMETRY_MONTHLY_BATCH_V1.md"
IMPLEMENTATION = Path(__file__).resolve()
MODULE = ROOT / "backend/src/gold_intel/analytics/h1_confirmation_geometry_audit_v1.py"
AUDIT_RUNNER = ROOT / "tools/run_gold_h1_confirmation_entry_stop_geometry_audit_v1.py"
CASEBOOK = ROOT / "research_artifacts/gold_casebook_v01/price_bars.jsonl.gz"
CASEBOOK_MANIFEST = ROOT / "research_artifacts/gold_casebook_v01/manifest.json"
PREDECESSOR = ROOT / "research_artifacts/gold_h1_confirmation_entry_stop_geometry_audit_v1/manifest.json"
PREDECESSOR_CONTEXTS = ROOT / "research_artifacts/gold_h1_confirmation_entry_stop_geometry_audit_v1/case_contexts.json"
PREDECESSOR_LEDGER = ROOT / "research_artifacts/gold_h1_confirmation_entry_stop_geometry_audit_v1/case_geometry_ledger.csv"
SOURCE_TEMPLATE = ROOT / "research_artifacts/gold_february_h1_confirmation_only_reclaim_v1/february-h1-confirmation-only-continuous.template.html"
BROWSER_TOOL = ROOT / "frontend/tools/certify-gold-h1-confirmation-geometry-monthly-batch-v1.mjs"
SUPERVISOR = ROOT / "tools/supervise_gold_h1_confirmation_geometry_monthly_batch_v1.ps1"

OUT = ROOT / "research_artifacts/gold_h1_confirmation_geometry_monthly_batch_v1"
PRIMARY_DIR = OUT / "primary"
REFERENCE_DIR = OUT / "reference"
MONTHLY_DIR = OUT / "monthly"
PROTOCOL = OUT / "protocol_freeze.json"
STATUS = OUT / "status.json"
EVENT_LOG = OUT / "checkpoint_log.jsonl"
PRIMARY_SOURCE = OUT / "source_primary.json"
REFERENCE_SOURCE = OUT / "source_reference.json"
PRIMARY_REHEARSAL = OUT / "rehearsal_primary.json"
REFERENCE_REHEARSAL = OUT / "rehearsal_reference.json"
BATCH_RESULT = OUT / "batch_result.json"
SUMMARY_CSV = OUT / "monthly_policy_summary.csv"
REPORT = OUT / "report.md"
INDEX = OUT / "index.html"
FINAL_MANIFEST = OUT / "final_manifest.json"
SUPERVISOR_STATUS = OUT / "supervisor_status.json"
RUN_LOG = OUT / "unattended_run.log"

HISTORY_START = parse_dt("2021-07-23T00:00:00Z")
SOURCE_END = parse_dt("2025-01-01T00:00:00Z")
BATCH_START = parse_dt("2022-06-01T00:00:00Z")
REQUIRED_TIMEFRAMES = ("1m", "5m", "15m", "1h")


def next_month(value: datetime) -> datetime:
    return value.replace(year=value.year + (1 if value.month == 12 else 0), month=1 if value.month == 12 else value.month + 1)


def build_months(start: datetime, end: datetime) -> tuple[dict[str, Any], ...]:
    output = []
    point = start
    while point < end:
        endpoint = next_month(point)
        output.append(
            {
                "key": point.strftime("%Y_%m"),
                "label": point.strftime("%B %Y"),
                "slug": point.strftime("%Y-%m"),
                "start": point,
                "end": endpoint,
                "cutoff": min(endpoint + timedelta(days=2), SOURCE_END),
            }
        )
        point = endpoint
    return tuple(output)


MONTHS = build_months(BATCH_START, SOURCE_END)
REHEARSAL_MONTHS = audit.MONTHS
require(len(MONTHS) == 31, f"Frozen month count differs: {len(MONTHS)}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def append_event(stage: str, state: str, *, month: str | None = None, detail: str = "") -> None:
    payload = {
        "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "stage": stage,
        "state": state,
        "month": month,
        "detail": detail,
        "process_id": os.getpid(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    with EVENT_LOG.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(payload) + "\n")
    print(canonical_json(payload), flush=True)


def update_status(
    stage: str,
    state: str,
    *,
    month: str | None = None,
    completed: int = 0,
    total: int = len(MONTHS),
    detail: str = "",
) -> None:
    write_json(
        STATUS,
        {
            "version": f"{BATCH_VERSION}_STATUS",
            "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "stage": stage,
            "state": state,
            "month": month,
            "completed_months": completed,
            "total_months": total,
            "detail": detail,
            "process_id": os.getpid(),
        },
    )
    append_event(stage, state, month=month, detail=detail)


def verified_json(path: Path, hash_field: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    claimed = str(payload.pop(hash_field))
    require(canonical_hash(payload) == claimed, f"Internal hash mismatch: {path}")
    payload[hash_field] = claimed
    return payload


def verify_predecessors() -> dict[str, Any]:
    for path in (
        SPEC,
        IMPLEMENTATION,
        MODULE,
        AUDIT_RUNNER,
        CASEBOOK,
        CASEBOOK_MANIFEST,
        PREDECESSOR,
        PREDECESSOR_CONTEXTS,
        PREDECESSOR_LEDGER,
        SOURCE_TEMPLATE,
        BROWSER_TOOL,
        SUPERVISOR,
    ):
        require(path.is_file(), f"Required source absent: {path}")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    require(predecessor["verdict"] == "PASS_EXPOSED_MATCHED_CASE_GEOMETRY_AUDIT_REPRODUCTION", "Predecessor verdict differs")
    for row in predecessor["files"]:
        path = ROOT / str(row["path"])
        require(path.is_file() and sha256_file(path) == str(row["sha256"]), f"Predecessor file seal differs: {path}")
    casebook_manifest = json.loads(CASEBOOK_MANIFEST.read_text(encoding="utf-8"))
    source = [row for row in casebook_manifest["artifacts"] if row["name"] == CASEBOOK.name]
    require(len(source) == 1, "Casebook source binding differs")
    require(sha256_file(CASEBOOK) == str(source[0]["sha256"]), "Casebook source hash differs")
    require(casebook_manifest["contract"]["case_end_exclusive"] == "2025-01-01T00:00:00+00:00", "Casebook boundary differs")
    return {
        "casebook_sha256": sha256_file(CASEBOOK),
        "casebook_manifest_sha256": sha256_file(CASEBOOK_MANIFEST),
        "predecessor_manifest_sha256": sha256_file(PREDECESSOR),
        "predecessor_manifest_internal_sha256": predecessor["manifest_sha256"],
        "source_template_sha256": sha256_file(SOURCE_TEMPLATE),
    }


def protocol_payload(bindings: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "version": f"{BATCH_VERSION}_PROTOCOL_FREEZE",
        "evidence_status": "EXPOSED_HISTORICAL_EXTENSION_ZERO_VALIDATION_CREDIT",
        "period": {"start": iso(BATCH_START), "end_exclusive": iso(SOURCE_END)},
        "months": [
            {
                "key": month["key"],
                "label": month["label"],
                "start": iso(month["start"]),
                "end_exclusive": iso(month["end"]),
                "source_cutoff": iso(month["cutoff"]),
            }
            for month in MONTHS
        ],
        "rehearsal": {
            "period": "2022-01-01 through 2022-05-31",
            "required_contexts": 326,
            "required_matrix_rows": 3912,
            "exact_hash_equality_required": True,
        },
        "entry_policies": list(ENTRY_POLICIES),
        "stop_policies": list(STOP_POLICIES),
        "default_chart_policy": {"entry": CONTROL_ENTRY, "stop": CONTROL_STOP},
        "accounting": {
            "risk_per_case_usd": 50.0,
            "costs": "excluded unchanged from predecessor",
            "overlap": "unconstrained unchanged from predecessor",
            "ambiguity": "stop first",
            "deadline": "calendar month end",
        },
        "guards": {
            "primary_reference_required": True,
            "one_month_atomic_checkpoints": True,
            "no_2025_or_2026": True,
            "no_paid_or_free_acquisition": True,
            "no_month_specific_policy_selection": True,
        },
        "bindings": dict(bindings),
        "implementation": {
            "spec_sha256": sha256_file(SPEC),
            "runner_sha256": sha256_file(IMPLEMENTATION),
            "analytics_module_sha256": sha256_file(MODULE),
            "predecessor_runner_sha256": sha256_file(AUDIT_RUNNER),
            "browser_tool_sha256": sha256_file(BROWSER_TOOL),
            "supervisor_sha256": sha256_file(SUPERVISOR),
        },
    }
    payload["protocol_sha256"] = canonical_hash(payload)
    return payload


def prepare() -> dict[str, Any]:
    bindings = verify_predecessors()
    expected = protocol_payload(bindings)
    if PROTOCOL.is_file():
        existing = verified_json(PROTOCOL, "protocol_sha256")
        require(existing == expected, "Existing batch protocol differs from current frozen implementation")
    else:
        write_json(PROTOCOL, expected)
    proof = synthetic_proof()
    require(proof["verdict"] == "PASS", "Frozen analytics synthetic proof failed")
    return expected


def load_casebook(
    parser: Callable[[str], dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    rows: dict[str, list[dict[str, Any]]] = {timeframe: [] for timeframe in REQUIRED_TIMEFRAMES}
    with gzip.open(CASEBOOK, "rt", encoding="utf-8") as handle:
        for line in handle:
            parsed = parser(line)
            timeframe = str(parsed["timeframe"])
            if timeframe not in rows or not bool(parsed["complete"]):
                continue
            opened = parse_dt(str(parsed["open_time"]))
            available = parse_dt(str(parsed["available_at"]))
            if opened >= HISTORY_START and available <= SOURCE_END:
                rows[timeframe].append(feb.canonical_bar(parsed))
    diagnostics: dict[str, Any] = {}
    for timeframe, values in rows.items():
        values.sort(key=lambda row: (parse_dt(str(row["open_at"])), parse_dt(str(row["available_at"]))))
        require(values, f"No source rows for {timeframe}")
        identities = [(str(row["open_at"]), str(row["available_at"])) for row in values]
        require(len(identities) == len(set(identities)), f"Duplicate {timeframe} source bars")
        digest = hashlib.sha256()
        for row in values:
            digest.update(canonical_json(row).encode("utf-8"))
            digest.update(b"\n")
        diagnostics[timeframe] = {
            "rows": len(values),
            "first_open_at": str(values[0]["open_at"]),
            "last_available_at": str(values[-1]["available_at"]),
            "stream_sha256": digest.hexdigest(),
        }
    diagnostics["diagnostics_sha256"] = canonical_hash(diagnostics)
    return rows, diagnostics


class RowIndex:
    def __init__(self, rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
        self.rows = rows
        self.open_times = {
            key: [parse_dt(str(row["open_at"])) for row in values] for key, values in rows.items()
        }
        self.available_times = {
            key: [parse_dt(str(row["available_at"])) for row in values] for key, values in rows.items()
        }

    def opens(self, timeframe: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        values = self.rows[timeframe]
        times = self.open_times[timeframe]
        left = bisect_left(times, start)
        right = bisect_left(times, end)
        return [dict(row) for row in values[left:right] if parse_dt(str(row["available_at"])) <= end]

    def known(self, timeframe: str, cutoff: datetime) -> list[dict[str, Any]]:
        values = self.rows[timeframe]
        times = self.available_times[timeframe]
        right = bisect_right(times, cutoff)
        return [dict(row) for row in values[:right] if parse_dt(str(row["available_at"])) <= cutoff]


def month_rows(index: RowIndex, month: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        "1m": index.opens("1m", month["start"], month["end"]),
        "5m": index.known("5m", month["cutoff"]),
        "15m": index.known("15m", month["cutoff"]),
        "1h": index.known("1h", month["cutoff"]),
    }


def compact_bars(index: RowIndex, month: Mapping[str, Any]) -> dict[str, list[list[float | int]]]:
    output: dict[str, list[list[float | int]]] = {}
    for timeframe, label in (("1h", "H1"), ("15m", "M15"), ("5m", "M5")):
        output[label] = [
            [
                int(parse_dt(str(row["open_at"])).timestamp()),
                round(float(row["open"]), 4),
                round(float(row["high"]), 4),
                round(float(row["low"]), 4),
                round(float(row["close"]), 4),
            ]
            for row in index.opens(timeframe, month["start"], month["end"])
        ]
    return output


def compute_month(
    index: RowIndex,
    registry: Mapping[str, Any],
    month: Mapping[str, Any],
    protocol_sha256: str,
) -> dict[str, Any]:
    selected = month_rows(index, month)
    require(selected["1m"], f"No M1 rows for {month['label']}")
    population = feb.build_population(
        selected,
        start=month["start"],
        end=month["end"],
        cutoff=month["cutoff"],
    )
    control_ledger = mar.apply_policy(population["trades"], selected, end=month["end"])
    executed = [row for row in control_ledger if bool(row["executed"])]
    trades_by_id = {str(row["trade_identity"]): row for row in population["trades"]}
    contexts: list[dict[str, Any]] = []
    originals: dict[str, dict[str, Any]] = {}
    for row in executed:
        identity = str(row["trade_identity"])
        require(identity in trades_by_id, f"Executed identity absent from population: {identity}")
        context = audit.reconstruct_executed_context(
            trades_by_id[identity], row, selected, registry["5m"]["swings"], month=month
        )
        context["context_sha256"] = canonical_hash(
            {key: value for key, value in context.items() if key != "context_sha256"}
        )
        contexts.append(context)
        originals[identity] = {
            "entry_at": str(row["entry_at"]),
            "stop": float(row["stop"]),
            "target": float(row["target"]),
            "outcome": str(row["outcome"]),
            "resolution_at": str(row["resolution_at"]),
            "net_r": float(row["net_r"]),
        }
    contexts.sort(key=lambda row: (row["control_entry_at"], row["trade_identity"]))
    path = M1Path(selected["1m"])
    matrix: list[dict[str, Any]] = []
    for case in contexts:
        for entry_policy in ENTRY_POLICIES:
            for stop_policy in STOP_POLICIES:
                geometry = stop_geometry(case, registry, stop_policy)
                lifecycle = evaluate_policy(case, geometry, path, entry_policy)
                matrix.append(audit.flatten_policy_row(case, geometry, lifecycle))
    matrix.sort(
        key=lambda row: (
            row["control_entry_at"],
            row["trade_identity"],
            ENTRY_POLICIES.index(str(row["entry_policy"])),
            STOP_POLICIES.index(str(row["stop_policy"])),
        )
    )
    require(len(matrix) == 12 * len(executed), f"Matrix cardinality differs for {month['label']}")
    control_equivalence = audit.control_equivalence(matrix, originals)
    summary: dict[str, Any] = {}
    for entry_policy in ENTRY_POLICIES:
        summary[entry_policy] = {}
        for stop_policy in STOP_POLICIES:
            relevant = [
                row
                for row in matrix
                if row["entry_policy"] == entry_policy and row["stop_policy"] == stop_policy
            ]
            summary[entry_policy][stop_policy] = summarize(relevant, originals)
    control_r = float(summary[CONTROL_ENTRY][CONTROL_STOP]["net_r"])
    for entry_policy in ENTRY_POLICIES:
        for stop_policy in STOP_POLICIES:
            summary[entry_policy][stop_policy]["delta_vs_control_r"] = (
                float(summary[entry_policy][stop_policy]["net_r"]) - control_r
            )
    payload = {
        "version": f"{BATCH_VERSION}_MONTH",
        "protocol_sha256": protocol_sha256,
        "month": str(month["key"]),
        "label": str(month["label"]),
        "period": {"start": iso(month["start"]), "end_exclusive": iso(month["end"])},
        "population": {key: value for key, value in population.items() if key != "trades"},
        "control_setup_count": len(control_ledger),
        "executed_count": len(executed),
        "control_equivalence": control_equivalence,
        "contexts_sha256": canonical_hash(contexts),
        "matrix_sha256": canonical_hash(matrix),
        "summary_sha256": canonical_hash(summary),
        "control_ledger": control_ledger,
        "contexts": contexts,
        "matrix": matrix,
        "summary": summary,
        "bars": compact_bars(index, month),
        "guards": {
            "gross_before_costs": True,
            "overlap_unconstrained": True,
            "exposed_historical_extension": True,
            "policy_retuned": False,
            "source_end_exclusive": iso(SOURCE_END),
        },
    }
    payload["month_payload_sha256"] = canonical_hash(payload)
    return payload


def load_predecessor_hashes() -> tuple[list[str], list[str]]:
    contexts = json.loads(PREDECESSOR_CONTEXTS.read_text(encoding="utf-8"))
    context_hashes = [str(row["context_sha256"]) for row in contexts["rows"]]
    with PREDECESSOR_LEDGER.open("r", encoding="utf-8", newline="") as handle:
        matrix_hashes = [str(row["row_sha256"]) for row in csv.DictReader(handle)]
    return context_hashes, matrix_hashes


def run_rehearsal(
    side: str,
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    index: RowIndex,
    registry: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    destination = PRIMARY_REHEARSAL if side == "primary" else REFERENCE_REHEARSAL
    if destination.is_file():
        existing = verified_json(destination, "rehearsal_sha256")
        require(existing["protocol_sha256"] == protocol["protocol_sha256"], "Rehearsal protocol differs")
        return existing
    expected_contexts, expected_matrix = load_predecessor_hashes()
    observed_contexts: list[str] = []
    observed_matrix: list[str] = []
    for month in REHEARSAL_MONTHS:
        payload = compute_month(index, registry, month, str(protocol["protocol_sha256"]))
        observed_contexts.extend(str(row["context_sha256"]) for row in payload["contexts"])
        observed_matrix.extend(str(row["row_sha256"]) for row in payload["matrix"])
    require(observed_contexts == expected_contexts, f"{side} rehearsal context hashes differ")
    require(observed_matrix == expected_matrix, f"{side} rehearsal matrix hashes differ")
    result = {
        "version": f"{BATCH_VERSION}_{side.upper()}_REHEARSAL",
        "verdict": "PASS_EXACT_JANUARY_MAY_REPRODUCTION",
        "protocol_sha256": protocol["protocol_sha256"],
        "contexts": len(observed_contexts),
        "matrix_rows": len(observed_matrix),
        "contexts_sha256": canonical_hash(observed_contexts),
        "matrix_rows_sha256": canonical_hash(observed_matrix),
    }
    result["rehearsal_sha256"] = canonical_hash(result)
    write_json(destination, result)
    return result


def checkpoint_path(side: str, month: Mapping[str, Any]) -> Path:
    return (PRIMARY_DIR if side == "primary" else REFERENCE_DIR) / f"{month['key']}.json"


def verify_month_payload(path: Path, protocol: Mapping[str, Any]) -> dict[str, Any]:
    payload = verified_json(path, "month_payload_sha256")
    require(payload["protocol_sha256"] == protocol["protocol_sha256"], "Checkpoint protocol differs")
    require(payload["guards"]["source_end_exclusive"] == iso(SOURCE_END), "Checkpoint source boundary differs")
    return payload


def run_pass(side: str, protocol: Mapping[str, Any]) -> None:
    parser = replay_source.parse_price_primary if side == "primary" else replay_source.parse_price_reference
    source_path = PRIMARY_SOURCE if side == "primary" else REFERENCE_SOURCE
    update_status(f"{side.upper()}_SOURCE", "RUNNING", completed=0)
    rows, diagnostics = load_casebook(parser)
    source_payload = {
        "version": f"{BATCH_VERSION}_{side.upper()}_SOURCE",
        "protocol_sha256": protocol["protocol_sha256"],
        "casebook_sha256": protocol["bindings"]["casebook_sha256"],
        "diagnostics": diagnostics,
    }
    source_payload["source_payload_sha256"] = canonical_hash(source_payload)
    write_json(source_path, source_payload)
    index = RowIndex(rows)
    registry = build_structure_registry(rows, cutoff=SOURCE_END)
    update_status(f"{side.upper()}_REHEARSAL", "RUNNING", completed=0)
    run_rehearsal(side, rows, index, registry, protocol)
    update_status(f"{side.upper()}_REHEARSAL", "PASS", completed=0)

    completed = 0
    for month in MONTHS:
        destination = checkpoint_path(side, month)
        if side == "reference":
            primary_path = checkpoint_path("primary", month)
            require(primary_path.is_file(), f"Primary checkpoint absent: {month['label']}")
        if destination.is_file():
            if side == "primary":
                verify_month_payload(destination, protocol)
            else:
                existing = verified_json(destination, "month_payload_sha256")
                require(existing["protocol_sha256"] == protocol["protocol_sha256"], "Reference checkpoint protocol differs")
                require(existing["verdict"] == "PASS_PRIMARY_REFERENCE_EXACT", "Reference checkpoint verdict differs")
            completed += 1
            update_status(f"{side.upper()}_MONTHS", "SKIP_VERIFIED", month=month["label"], completed=completed)
            continue
        update_status(f"{side.upper()}_MONTHS", "RUNNING", month=month["label"], completed=completed)
        payload = compute_month(index, registry, month, str(protocol["protocol_sha256"]))
        if side == "primary":
            write_json(destination, payload)
        else:
            primary = verify_month_payload(checkpoint_path("primary", month), protocol)
            require(payload == primary, f"Primary/reference month payload differs: {month['label']}")
            certificate = {
                "version": f"{BATCH_VERSION}_REFERENCE_CERTIFICATE",
                "month": month["key"],
                "label": month["label"],
                "verdict": "PASS_PRIMARY_REFERENCE_EXACT",
                "protocol_sha256": protocol["protocol_sha256"],
                "primary_month_payload_sha256": primary["month_payload_sha256"],
                "reference_month_payload_sha256": payload["month_payload_sha256"],
                "context_count": len(payload["contexts"]),
                "matrix_rows": len(payload["matrix"]),
            }
            certificate["month_payload_sha256"] = canonical_hash(certificate)
            write_json(destination, certificate)
        completed += 1
        update_status(f"{side.upper()}_MONTHS", "PASS", month=month["label"], completed=completed)
    del registry, index, rows
    gc.collect()


def compact_plan(row: Mapping[str, Any], number: int) -> dict[str, Any]:
    entry = float(row["entry_price"])
    stop = float(row["stop"])
    target = float(row["target"])
    outcome = str(row["outcome"])
    route = str(row["route"])
    return {
        "number": number,
        "planIdentity": str(row["trade_identity"]),
        "sampleId": str(row["trade_identity"]),
        "decision": int(parse_dt(str(row["entry_at"])).timestamp()),
        "resolution": int(parse_dt(str(row["resolution_at"])).timestamp()),
        "resolutionKnown": int(parse_dt(str(row["resolution_at"])).timestamp()),
        "direction": str(row["direction"]),
        "family": "Reclaim" if route.startswith("RECLAIM") else "Initial confirmation",
        "h1State": "EXPOSED_HISTORICAL_EXTENSION",
        "setupFamily": route,
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "target": round(target, 4),
        "targetTimeframe": "H1",
        "targetRole": "PRE_EXISTING_OPPOSING_H1_SWING",
        "disposition": "MONTH_END_MARK" if outcome == "TIME_EXIT" else outcome,
        "grossR": round(float(row["net_r"]), 6),
        "targetR": round(abs(target - entry) / abs(entry - stop), 6),
        "durationMinutes": max(0, round((parse_dt(str(row["resolution_at"])) - parse_dt(str(row["entry_at"]))).total_seconds() / 60)),
        "ambiguous": outcome == "STOP_FIRST_AMBIGUOUS",
        "route": route,
    }


def chart_template(source: str, month: Mapping[str, Any]) -> str:
    key = str(month["key"])
    label = str(month["label"])
    name = label.split()[0]
    return (
        source
        .replace("gold-february-h1-confirmation-only-v1", f"gold-{key.replace('_', '-')}-h1-confirmation-only-v1")
        .replace("February 2022", label)
        .replace("Full February", f"Full {name}")
        .replace("February trade ledger", f"{label} trade ledger")
        .replace("continuous February chart", f"continuous {name} chart")
        .replace("February chart", f"{name} chart")
        .replace("February timeline", f"{name} timeline")
        .replace("February 2022 continuous", f"{label} continuous")
    )


def render_month_outputs(month: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    out = MONTHLY_DIR / str(month["key"])
    out.mkdir(parents=True, exist_ok=True)
    matrix_path = out / "case_geometry_ledger.csv"
    control_path = out / "control_case_ledger.csv"
    report_path = out / "report.md"
    template_path = out / "chart.template.html"
    html_path = out / "continuous_chart.html"
    audit.write_csv(matrix_path, payload["matrix"])
    audit.write_csv(control_path, payload["control_ledger"])
    lines = [
        f"# {month['label']} H1 confirmation geometry extension",
        "",
        "Exposed historical extension only; gross before costs and overlap controls.",
        "",
        *audit.render_scope_table(payload["summary"]),
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    control_rows = [
        row
        for row in payload["matrix"]
        if row["entry_policy"] == CONTROL_ENTRY and row["stop_policy"] == CONTROL_STOP
    ]
    plans = [compact_plan(row, number) for number, row in enumerate(control_rows, start=1)]
    metrics = payload["summary"][CONTROL_ENTRY][CONTROL_STOP]
    dataset = {
        "version": f"{BATCH_VERSION}_{str(month['key']).upper()}_CHART",
        "period": payload["period"],
        "summary": {
            "plans": len(plans),
            "target_hits": sum(plan["disposition"] == "TARGET" for plan in plans),
            "stops": sum(plan["disposition"] == "STOP" for plan in plans),
            "stop_first_ambiguous": sum(plan["disposition"] == "STOP_FIRST_AMBIGUOUS" for plan in plans),
            "month_end_marks": sum(plan["disposition"] == "MONTH_END_MARK" for plan in plans),
            "resolved_hit_rate": metrics["win_rate_filled"],
            "gross_r_sum": metrics["net_r"],
            "profit_factor": metrics["profit_factor"],
            "max_drawdown_r": metrics["maximum_drawdown_r"],
        },
        "bars": payload["bars"],
        "plans": plans,
        "guards": {
            "continuous_month_not_cases": True,
            "unchanged_control_overlay": True,
            "white_chart": True,
            "local_trade_lines": True,
            "exposed_historical_extension": True,
        },
        "source_hashes": {
            "month_payload": payload["month_payload_sha256"],
            "source_template": sha256_file(SOURCE_TEMPLATE),
            "renderer": sha256_file(IMPLEMENTATION),
        },
    }
    dataset["dataSha256"] = canonical_hash(dataset)
    template = chart_template(SOURCE_TEMPLATE.read_text(encoding="utf-8"), month)
    marker = "__FEBRUARY_CONFIRMATION_ONLY_DATA__"
    require(template.count(marker) == 1, f"Chart marker differs: {month['label']}")
    template_path.write_text(template, encoding="utf-8", newline="\n")
    encoded = json.dumps(dataset, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    html_path.write_text(template.replace(marker, encoded), encoding="utf-8", newline="\n")
    return {
        "month": month["key"],
        "label": month["label"],
        "executed": len(plans),
        "control_net_r": metrics["net_r"],
        "report": report_path.relative_to(ROOT).as_posix(),
        "chart": html_path.relative_to(ROOT).as_posix(),
        "chart_sha256": sha256_file(html_path),
    }


def finalize(protocol: Mapping[str, Any]) -> None:
    primary_source = verified_json(PRIMARY_SOURCE, "source_payload_sha256")
    reference_source = verified_json(REFERENCE_SOURCE, "source_payload_sha256")
    require(primary_source["diagnostics"] == reference_source["diagnostics"], "Primary/reference source diagnostics differ")
    all_matrix: list[dict[str, Any]] = []
    all_originals: dict[str, dict[str, Any]] = {}
    monthly_payloads: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    chart_rows: list[dict[str, Any]] = []
    flat_summary: list[dict[str, Any]] = []
    for month in MONTHS:
        payload = verify_month_payload(checkpoint_path("primary", month), protocol)
        cert = verified_json(checkpoint_path("reference", month), "month_payload_sha256")
        require(cert["verdict"] == "PASS_PRIMARY_REFERENCE_EXACT", f"Reference certificate failed: {month['label']}")
        require(cert["primary_month_payload_sha256"] == payload["month_payload_sha256"], f"Certificate binding differs: {month['label']}")
        monthly_payloads.append((month, payload))
        all_matrix.extend(payload["matrix"])
        for context in payload["contexts"]:
            all_originals[str(context["trade_identity"])] = {
                "net_r": float(context["original_net_r"])
            }
        for entry_policy in ENTRY_POLICIES:
            for stop_policy in STOP_POLICIES:
                metrics = payload["summary"][entry_policy][stop_policy]
                flat_summary.append(
                    {
                        "month": month["key"],
                        "label": month["label"],
                        "entry_policy": entry_policy,
                        "stop_policy": stop_policy,
                        **{key: value for key, value in metrics.items() if key != "outcome_counts"},
                        "outcome_counts_json": canonical_json(metrics["outcome_counts"]),
                    }
                )
        chart_rows.append(render_month_outputs(month, payload))

    combined: dict[str, Any] = {}
    for entry_policy in ENTRY_POLICIES:
        combined[entry_policy] = {}
        for stop_policy in STOP_POLICIES:
            selected = [
                row
                for row in all_matrix
                if row["entry_policy"] == entry_policy and row["stop_policy"] == stop_policy
            ]
            combined[entry_policy][stop_policy] = summarize(selected, all_originals)
    control_r = float(combined[CONTROL_ENTRY][CONTROL_STOP]["net_r"])
    for entry_policy in ENTRY_POLICIES:
        for stop_policy in STOP_POLICIES:
            combined[entry_policy][stop_policy]["delta_vs_control_r"] = float(combined[entry_policy][stop_policy]["net_r"]) - control_r
    running_equity = 10_000.0
    for row in chart_rows:
        row["opening_equity_usd"] = running_equity
        row["control_pnl_usd"] = 50.0 * float(row["control_net_r"])
        running_equity += float(row["control_pnl_usd"])
        row["closing_equity_usd"] = running_equity
    audit.write_csv(SUMMARY_CSV, flat_summary)
    batch = {
        "version": BATCH_VERSION,
        "verdict": "PASS_31_MONTH_EXPOSED_EXTENSION_PRIMARY_REFERENCE_EXACT",
        "evidence_status": "EXPOSED_HISTORICAL_EXTENSION_ZERO_VALIDATION_CREDIT",
        "protocol_sha256": protocol["protocol_sha256"],
        "months": chart_rows,
        "month_count": len(chart_rows),
        "executed_count": len(all_originals),
        "matrix_rows": len(all_matrix),
        "combined": combined,
        "source_diagnostics_sha256": primary_source["diagnostics"]["diagnostics_sha256"],
        "primary_reference_exact": True,
        "costs_included": False,
        "overlap_policy_applied": False,
        "validation_credit": False,
    }
    batch["batch_result_sha256"] = canonical_hash(batch)
    write_json(BATCH_RESULT, batch)
    report_lines = [
        "# Gold H1 Confirmation Geometry Monthly Batch V1",
        "",
        f"**Verdict:** `{batch['verdict']}`",
        "",
        "June 2022 through December 2024 exposed extension. Gross before costs and overlap controls; no policy was selected month by month.",
        "",
        "## Frozen control by month",
        "",
        "| Month | Trades | Net R | $ at $50/case | Closing illustrative equity |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in chart_rows:
        report_lines.append(
            f"| {row['label']} | {row['executed']} | {float(row['control_net_r']):+.3f} | "
            f"${float(row['control_pnl_usd']):+,.2f} | ${float(row['closing_equity_usd']):,.2f} |"
        )
    control = combined[CONTROL_ENTRY][CONTROL_STOP]
    control_pf = "n/a" if control["profit_factor"] is None else f"{float(control['profit_factor']):.3f}"
    report_lines.extend(
        [
            "",
            f"Combined unchanged control: {float(control['net_r']):+.3f}R across {control['population']} trades; "
            f"win rate {100*float(control['win_rate_filled']):.1f}%; PF "
            f"{control_pf}; "
            f"maximum drawdown {float(control['maximum_drawdown_r']):.3f}R.",
            "",
            "The complete monthly 3 x 4 matrices are stored in each monthly report and in `monthly_policy_summary.csv`.",
        ]
    )
    REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8", newline="\n")
    index_lines = [
        "<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
        "<title>Gold H1 Monthly Batch</title><style>body{font-family:Arial,sans-serif;margin:28px;color:#111827;background:#fff}table{border-collapse:collapse;width:100%;max-width:900px}th,td{padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:left}a{color:#1746c7}</style></head><body>",
        "<h1>Gold H1 confirmation monthly charts</h1><p>June 2022 through December 2024. Exposed diagnostic evidence; default overlay is the unchanged control.</p>",
        "<table><thead><tr><th>Month</th><th>Trades</th><th>Control R</th><th>Chart</th><th>Report</th></tr></thead><tbody>",
    ]
    for row in chart_rows:
        rel_chart = Path(row["chart"]).relative_to(OUT.relative_to(ROOT)).as_posix()
        rel_report = Path(row["report"]).relative_to(OUT.relative_to(ROOT)).as_posix()
        index_lines.append(f"<tr><td>{row['label']}</td><td>{row['executed']}</td><td>{float(row['control_net_r']):+.3f}R</td><td><a href=\"{rel_chart}\">Open chart</a></td><td><a href=\"{rel_report}\">Report</a></td></tr>")
    index_lines.append("</tbody></table></body></html>")
    INDEX.write_text("".join(index_lines), encoding="utf-8", newline="\n")


def seal_browser(protocol: Mapping[str, Any]) -> None:
    browser_summary = OUT / "browser_certification_summary.json"
    require(browser_summary.is_file(), "Browser certification summary absent")
    browser = verified_json(browser_summary, "summary_sha256")
    require(browser["verdict"] == "PASS_ALL_31_MONTHLY_CHARTS", "Browser certification failed")
    excluded = {
        STATUS.resolve(),
        EVENT_LOG.resolve(),
        FINAL_MANIFEST.resolve(),
        SUPERVISOR_STATUS.resolve(),
        RUN_LOG.resolve(),
    }
    files = [
        path
        for path in OUT.rglob("*")
        if path.is_file() and path.resolve() not in excluded and not path.name.endswith(".tmp")
    ]
    external = [
        SPEC,
        IMPLEMENTATION,
        MODULE,
        AUDIT_RUNNER,
        PREDECESSOR,
        SOURCE_TEMPLATE,
        BROWSER_TOOL,
        SUPERVISOR,
    ]
    manifest = {
        "version": f"{BATCH_VERSION}_FINAL_MANIFEST",
        "verdict": "PASS_UNATTENDED_BATCH_AND_BROWSER_CERTIFICATION",
        "protocol_sha256": protocol["protocol_sha256"],
        "batch_result_sha256": verified_json(BATCH_RESULT, "batch_result_sha256")["batch_result_sha256"],
        "browser_summary_sha256": browser["summary_sha256"],
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted((*files, *external), key=lambda item: item.as_posix())
        ],
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    write_json(FINAL_MANIFEST, manifest)
    update_status("ALL", "COMPLETE", completed=len(MONTHS), detail="Results, reports, charts and browser certification sealed.")


def run_all() -> None:
    protocol = prepare()
    update_status("PREPARE", "PASS", completed=0, detail="Predecessor seals and frozen protocol verified.")
    run_pass("primary", protocol)
    run_pass("reference", protocol)
    update_status("FINALIZE", "RUNNING", completed=len(MONTHS))
    finalize(protocol)
    update_status("BROWSER_PENDING", "READY", completed=len(MONTHS), detail="Run browser certification, then seal-browser.")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "all"
    try:
        protocol = prepare()
        if command == "all":
            run_all()
        elif command == "seal-browser":
            seal_browser(protocol)
        elif command == "prepare":
            update_status("PREPARE", "PASS", detail="Protocol frozen and sources verified.")
        else:
            raise ValueError(f"Unknown command: {command}")
    except Exception as exc:
        update_status("BATCH", "FAILED", detail=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
