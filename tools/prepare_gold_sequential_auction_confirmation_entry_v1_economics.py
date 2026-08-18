from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
MATERIALIZATION = ARTIFACTS / "gold_sequential_auction_confirmation_entry_v1_materialization"
PROTOCOL = MANIFESTS / "gold_sequential_auction_confirmation_entry_v1_protocol.json"
MATERIALIZATION_SEAL = MATERIALIZATION / "materialization_seal.json"
RUNNER = ROOT / "tools" / "run_gold_sequential_auction_confirmation_entry_v1_development.py"
ECONOMIC_FREEZE = MANIFESTS / "gold_sequential_auction_confirmation_entry_v1_pre_economic_freeze.json"
IMPLEMENTATION_FREEZE = MANIFESTS / "gold_sequential_auction_confirmation_entry_v1_economic_implementation_freeze.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    if ECONOMIC_FREEZE.exists() or IMPLEMENTATION_FREEZE.exists():
        raise FileExistsError(ECONOMIC_FREEZE if ECONOMIC_FREEZE.exists() else IMPLEMENTATION_FREEZE)
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    seal = json.loads(MATERIALIZATION_SEAL.read_text(encoding="utf-8"))
    if seal.get("status") != "PASS_OUTCOME_BLIND_SEQUENCE_MATERIALIZATION":
        raise ValueError("Outcome-blind materialization did not pass")
    for item in [*seal["controls"].values(), *seal["artifacts"].values()]:
        path = ROOT / item["path"]
        if not path.is_file() or record(path) != item:
            raise ValueError(f"Materialization artifact changed: {item['path']}")
    proof_process = subprocess.run([sys.executable, str(RUNNER), "--self-test"], cwd=ROOT, check=True, capture_output=True, text=True)
    proof = json.loads(proof_process.stdout.strip())
    if proof.get("status") != "PASS_SYNTHETIC_ECONOMIC_PROOF":
        raise ValueError("Synthetic economic proof failed")

    rows = pq.read_table(MATERIALIZATION / "primary_sequences.parquet", columns=["candidate_id", "variant", "status", "cluster_date"]).to_pylist()
    counts: dict[str, dict[str, Any]] = defaultdict(lambda: {"setup_rows": 0, "entry_eligible": 0, "dates": set(), "statuses": Counter()})
    for row in rows:
        identity = f"{row['variant']}::{row['candidate_id']}"
        counts[identity]["setup_rows"] += 1
        counts[identity]["statuses"][str(row["status"])] += 1
        if row["status"] == "ENTRY_ELIGIBLE":
            counts[identity]["entry_eligible"] += 1; counts[identity]["dates"].add(str(row["cluster_date"]))
    registry = []
    for identity in sorted(counts):
        value = counts[identity]
        registry.append({"identity": identity, "setup_rows": value["setup_rows"], "entry_eligible_pre_overlap": value["entry_eligible"], "entry_eligible_dates_pre_overlap": len(value["dates"]), "status_counts": dict(sorted(value["statuses"].items()))})
    primary_candidates = sorted({str(row["candidate_id"]) for row in rows if row["variant"] == "PRIMARY"})
    if len(primary_candidates) != 36 or len(registry) != 108:
        raise ValueError(f"Frozen registry cardinality changed: {len(primary_candidates)}:{len(registry)}")

    implementation_payload = {
        "version": "GOLD_SEQUENTIAL_AUCTION_CONFIRMATION_ENTRY_V1_ECONOMIC_IMPLEMENTATION_FREEZE_1_0",
        "status": "FROZEN_BEFORE_DEVELOPMENT_OUTCOME_PATHS",
        "frozen_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "implementation": record(RUNNER), "synthetic_proof": proof,
        "path": {
            "interval": "DELAYED_ENTRY_INCLUSIVE_ORIGINAL_DEADLINE_EXCLUSIVE",
            "requires_complete_contiguous_m1": True, "same_bar": "STOP_FIRST", "gap_stop": True,
            "target_fill": "FROZEN_ABSOLUTE_TARGET", "time_fill": "LAST_M1_CLOSE_BEFORE_DEADLINE",
            "mfe_mae": "FROM_DELAYED_ENTRY_THROUGH_REALIZED_EXIT_AND_COMPLETE_DEADLINE_PATH",
            "stopped_then_later_target": "STRICTLY_LATER_M1_OFFSET_WITHIN_ORIGINAL_DEADLINE",
        },
        "economics": {
            "gross_r_denominator": "ABS_ENTRY_MINUS_STOP_PRICE", "net_r": "GROSS_R_MINUS_ROUNDTRIP_COST_DIVIDED_BY_STOP_DISTANCE",
            "normalized_pnl_usd": "50_TIMES_NET_R_FOR_PRIOR_STUDY_COMPARABILITY",
            "whole_ounce_pnl_usd": "FLOORED_OUNCES_TIMES_SIGNED_PRICE_CHANGE_MINUS_ROUNDTRIP_COST",
            "actual_stop_plus_cost_risk_cap_usd": 50.0, "compounding": False,
        },
        "independence": {"primary": "NUMPY_SEARCH_AND_VECTOR_SCAN", "reference": "BISECT_AND_RECORD_LOOP_SCAN", "required": "ALL_ROWS_AND_BYTE_IDENTICAL_PARQUET"},
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    economic_payload = {
        "version": "GOLD_SEQUENTIAL_AUCTION_CONFIRMATION_ENTRY_V1_PRE_ECONOMIC_FREEZE_1_0",
        "status": "FROZEN_BEFORE_DEVELOPMENT_OUTCOME_PATHS",
        "frozen_at_utc": implementation_payload["frozen_at_utc"],
        "controls": {"protocol": record(PROTOCOL), "materialization_seal": record(MATERIALIZATION_SEAL), "primary_sequences": record(MATERIALIZATION / "primary_sequences.parquet"), "reference_sequences": record(MATERIALIZATION / "reference_sequences.parquet")},
        "primary_candidate_ids": primary_candidates, "support_registry_pre_outcome": registry,
        "outcome_join": {"entry_key": "EXACT_DELAYED_ENTRY_AT_UTC", "end_key": "EXACT_ORIGINAL_DEADLINE_AT_UTC", "source": "SEALED_DEVELOPMENT_XAUUSD_M1", "opening_count_before_freeze": 0},
        "overlap": {"scope": "VARIANT_X_CANDIDATE", "sort": ["DELAYED_ENTRY_AT_UTC", "TRADE_ID"], "accept": "ENTRY_GTE_CURRENT_EXIT", "same_timestamp": "LOWEST_TRADE_ID"},
        "formal_population": "BLOCKED_OOF_VALIDATION_UNION_ONLY_AFTER_PER_CANDIDATE_OVERLAP",
        "statistics": {"bootstrap_clusters": "TRADING_DATE", "bootstrap_resamples": 5000, "base_seed": 970331, "multiplicity": "BH_BY_TIMEFRAME_ACROSS_12_PRIMARY_CANDIDATES", "daily_sharpe_sortino": "STATIC_10000_ACCOUNT_DAILY_NORMALIZED_PNL_SQRT252"},
        "candidate_limit": protocol["maximum_candidates_per_timeframe"], "pass_gates": protocol["pass_gates"], "ranking": protocol["ranking"],
        "outcomes_accessed_before_freeze": False, "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    write_exclusive(IMPLEMENTATION_FREEZE, implementation_payload)
    try:
        write_exclusive(ECONOMIC_FREEZE, economic_payload)
    except Exception:
        IMPLEMENTATION_FREEZE.unlink(missing_ok=True)
        raise
    print(json.dumps({"status": economic_payload["status"], "primary_candidates": len(primary_candidates), "registry_rows": len(registry), "implementation": implementation_payload["implementation"]}, sort_keys=True))


if __name__ == "__main__":
    main()
