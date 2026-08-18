from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import discover_gold_trend_pullback_continuation_edge_v1 as discovery  # noqa: E402

MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
OUTPUT = ARTIFACTS / "gold_trend_pullback_continuation_economic_v1_v01"
PREDECESSOR = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"
CENSUS = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"

CONTRACT = ROOT / "GOLD_TREND_PULLBACK_CONTINUATION_ECONOMIC_EDGE_VALIDATION_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_trend_pullback_continuation_economic_v1_protocol.json"
DESIGN_FREEZE = MANIFESTS / "gold_trend_pullback_continuation_economic_v1_design_freeze.json"
TEST_REGISTRY = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_test_registry.json"
PREPATH_FREEZE = MANIFESTS / "gold_trend_pullback_continuation_economic_v1_prepath_freeze.json"

PRIMARY_SIGNALS = OUTPUT / "primary_development_signals.parquet"
REFERENCE_SIGNALS = OUTPUT / "reference_development_signals.parquet"
CERTIFICATION = OUTPUT / "signal_materialization_certification.json"
STATE = OUTPUT / "state_m2.json"

SIGNAL_SCHEMA = pa.schema([
    pa.field("signal_id", pa.string(), False),
    pa.field("candidate_id", pa.string(), False),
    pa.field("candidate_rank", pa.int64(), False),
    pa.field("pullback_id", pa.string(), False),
    pa.field("timeframe", pa.string(), False),
    pa.field("scale", pa.string(), False),
    pa.field("direction", pa.string(), False),
    pa.field("segment_id", pa.string(), False),
    pa.field("pivot_swing_id", pa.string(), False),
    pa.field("pivot_at_utc", pa.string(), False),
    pa.field("known_at_utc", pa.string(), False),
    pa.field("pivot_price_e8", pa.int64(), False),
    pa.field("atr14_e8", pa.float64(), False),
    pa.field("feature_lineage_hash", pa.string(), False),
    pa.field("signal_lineage_hash", pa.string(), False),
])


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(path)
    table = pa.Table.from_pylist(list(rows), schema=SIGNAL_SCHEMA)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6")
    temporary.replace(path)


def verify_design() -> tuple[dict[str, Any], list[str]]:
    freeze = json.loads(DESIGN_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_POST_DECISION_PRICE_PATH_ACCESS":
        raise ValueError("Economic design freeze invalid")
    for name, path in {"contract": CONTRACT, "protocol": PROTOCOL}.items():
        if sha256_file(path) != freeze["controls"][name]["sha256"]:
            raise ValueError(f"Economic control changed: {name}")
    predecessor_auth = json.loads((PREDECESSOR / "outcome_opening_authorization.json").read_text(encoding="utf-8"))
    if sha256_file(Path(discovery.__file__).resolve()) != predecessor_auth["implementation"]["sha256"]:
        raise ValueError("Frozen candidate implementation changed")
    candidates = json.loads((PREDECESSOR / "frozen_provisional_candidates.json").read_text(encoding="utf-8"))
    if candidates.get("candidate_ids") != freeze["predecessor"]["candidate_ids"]:
        raise ValueError("Candidate order changed")
    for name, item in freeze["sources"].items():
        path = ROOT / item["path"]
        if path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Frozen source changed: {name}")
    return freeze, list(candidates["candidate_ids"])


def load_pullbacks(path: Path) -> dict[str, dict[str, Any]]:
    columns = [
        "pullback_id", "timeframe", "scale", "direction", "segment_id",
        "pivot_swing_id", "pivot_at_utc", "known_at_utc", "pivot_price_e8",
        "actionable_at_known", "research_eligible", "decision_facts_hash",
    ]
    rows = pq.read_table(path, columns=columns).to_pylist()
    return {str(row["pullback_id"]): row for row in rows}


def materialize_impl(feature_path: Path, pullback_path: Path, candidate_ids: Sequence[str]) -> list[dict[str, Any]]:
    features = pq.read_table(feature_path).to_pylist()
    pullbacks = load_pullbacks(pullback_path)
    registry = json.loads(TEST_REGISTRY.read_text(encoding="utf-8"))
    stage1, stage2 = discovery.conditions(registry)
    predicates = {**stage1, **stage2}
    rows: list[dict[str, Any]] = []
    for feature in features:
        if not (
            feature["feature_available"]
            and feature["actionable_at_known"]
            and feature["research_eligible"]
            and feature["scale"] == "STANDARD"
            and str(feature["known_at_utc"]) < "2025-01-01T00:00:00Z"
        ):
            continue
        pullback = pullbacks.get(str(feature["pullback_id"]))
        if pullback is None:
            raise ValueError(f"Missing pullback facts: {feature['pullback_id']}")
        if not pullback["actionable_at_known"] or not pullback["research_eligible"]:
            raise ValueError("Feature/pullback eligibility mismatch")
        for rank, candidate_id in enumerate(candidate_ids):
            timeframe, stage_text, condition = candidate_id.split("|", 2)
            if timeframe != feature["timeframe"]:
                continue
            predicate = predicates.get(condition)
            if predicate is None:
                raise ValueError(f"Missing frozen predicate: {condition}")
            state = predicate(feature)
            if state is not True:
                continue
            identity = [candidate_id, feature["pullback_id"], feature["known_at_utc"]]
            rows.append({
                "signal_id": f"TPCE-ECON-SIGNAL::{canonical_hash(identity)[:24]}",
                "candidate_id": candidate_id,
                "candidate_rank": rank,
                "pullback_id": str(feature["pullback_id"]),
                "timeframe": str(feature["timeframe"]),
                "scale": str(feature["scale"]),
                "direction": str(feature["direction"]),
                "segment_id": str(feature["segment_id"]),
                "pivot_swing_id": str(feature["pivot_swing_id"]),
                "pivot_at_utc": str(feature["pivot_at_utc"]),
                "known_at_utc": str(feature["known_at_utc"]),
                "pivot_price_e8": int(pullback["pivot_price_e8"]),
                "atr14_e8": float(feature["atr14_e8"]),
                "feature_lineage_hash": str(feature["feature_lineage_hash"]),
                "signal_lineage_hash": canonical_hash([identity, feature["feature_lineage_hash"], pullback["decision_facts_hash"]]),
            })
    rows.sort(key=lambda row: (row["known_at_utc"], row["candidate_rank"], row["pullback_id"], row["signal_id"]))
    return rows


def main() -> None:
    if any(path.exists() for path in (PRIMARY_SIGNALS, REFERENCE_SIGNALS, CERTIFICATION, PREPATH_FREEZE, STATE)):
        raise FileExistsError("Economic signal artifact already exists")
    freeze, candidate_ids = verify_design()
    primary = materialize_impl(PREDECESSOR / "primary_features.parquet", CENSUS / "primary_pullback_cases.parquet", candidate_ids)
    reference = materialize_impl(PREDECESSOR / "reference_features.parquet", CENSUS / "reference_pullback_cases.parquet", candidate_ids)
    if primary != reference:
        raise ValueError("Primary/reference economic signals differ")
    write_parquet_exclusive(PRIMARY_SIGNALS, primary)
    write_parquet_exclusive(REFERENCE_SIGNALS, reference)
    if sha256_file(PRIMARY_SIGNALS) != sha256_file(REFERENCE_SIGNALS):
        raise ValueError("Signal Parquet bytes differ")
    counts = {candidate: sum(row["candidate_id"] == candidate for row in primary) for candidate in candidate_ids}
    certification = {
        "version": "GOLD_TPCE_ECONOMIC_V1_SIGNAL_CERTIFICATION_1_0",
        "status": "PASS_EXACT_SIGNAL_MATERIALIZATION",
        "certified_at_utc": utc_now(),
        "candidate_ids": candidate_ids,
        "candidate_signal_counts": counts,
        "signal_rows": len(primary),
        "unique_signal_ids": len({row["signal_id"] for row in primary}),
        "unique_pullback_ids": len({row["pullback_id"] for row in primary}),
        "signals_hash": canonical_hash(primary),
        "primary": file_record(PRIMARY_SIGNALS),
        "reference": file_record(REFERENCE_SIGNALS),
        "byte_identical": True,
        "post_decision_price_paths_accessed": False,
        "forward_values_accessed": False,
    }
    if certification["unique_signal_ids"] != len(primary):
        raise ValueError("Duplicate economic signal identity")
    write_json_exclusive(CERTIFICATION, certification)
    prepath = {
        "version": "GOLD_TPCE_ECONOMIC_V1_PREPATH_FREEZE_1_0",
        "status": "SEALED_EXACT_SIGNAL_POPULATION_BEFORE_PRICE_PATHS",
        "sealed_at_utc": utc_now(),
        "design_freeze": file_record(DESIGN_FREEZE),
        "implementation": file_record(Path(__file__).resolve()),
        "primary_signals": file_record(PRIMARY_SIGNALS),
        "reference_signals": file_record(REFERENCE_SIGNALS),
        "certification": file_record(CERTIFICATION),
        "signals_hash": certification["signals_hash"],
        "candidate_signal_counts": counts,
        "post_decision_price_paths_accessed": False,
        "forward_values_accessed": False,
    }
    write_json_exclusive(PREPATH_FREEZE, prepath)
    write_json_exclusive(STATE, {
        "version": "GOLD_TPCE_ECONOMIC_V1_STATE_M2_1_0",
        "status": certification["status"],
        "recorded_at_utc": utc_now(),
        "prepath_freeze": file_record(PREPATH_FREEZE),
        "next_step": "ONE_CONTROLLED_DEVELOPMENT_PRICE_PATH_OPENING",
    })
    print(json.dumps({
        "status": certification["status"],
        "signal_rows": len(primary),
        "unique_pullbacks": certification["unique_pullback_ids"],
        "counts": counts,
        "prepath_freeze": file_record(PREPATH_FREEZE),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
