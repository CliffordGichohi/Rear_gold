from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research_artifacts" / "gold_trend_pullback_movement_anatomy_edge_v1_v01"
CONTRACT = ROOT / "GOLD_CONDITIONAL_MOVEMENT_POLICY_EDGE_CONTRACT_V1.md"
PROTOCOL = ROOT / "research_manifests" / "gold_conditional_movement_policy_edge_v1_protocol.json"
FREEZE = ROOT / "research_manifests" / "gold_conditional_movement_policy_edge_v1_design_freeze.json"
STATE = OUTPUT / "conditional_policy_state_m1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20): digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False); handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True); raise


def main() -> None:
    if FREEZE.exists() or STATE.exists(): raise FileExistsError("Conditional policy already frozen")
    development_seal = OUTPUT / "development_discovery_seal.json"
    seal = json.loads(development_seal.read_text(encoding="utf-8"))
    if seal["status"] != "REJECT_NO_OOF_ECONOMIC_EDGE" or seal["forward_values_accessed"]:
        raise ValueError("Movement Anatomy predecessor state invalid")
    for item in seal["artifacts"].values():
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Predecessor seal failure: {item['path']}")
    sources = {
        "contract": CONTRACT, "protocol": PROTOCOL, "development_seal": development_seal,
        "features_primary": ROOT / "research_artifacts" / "gold_trend_pullback_continuation_edge_v1_v01" / "primary_features.parquet",
        "features_reference": ROOT / "research_artifacts" / "gold_trend_pullback_continuation_edge_v1_v01" / "reference_features.parquet",
        "matrix_m15": OUTPUT / "trade_matrix_checkpoint_m15.npz", "matrix_h1": OUTPUT / "trade_matrix_checkpoint_h1.npz", "matrix_h4": OUTPUT / "trade_matrix_checkpoint_h4.npz",
    }
    if sha256_file(sources["features_primary"]) != sha256_file(sources["features_reference"]): raise ValueError("Feature payloads differ")
    freeze = {
        "version": "GOLD_CMP_EDGE_V1_DESIGN_FREEZE_1_0", "status": "FROZEN_BEFORE_CONDITIONAL_MODEL_OUTCOMES",
        "frozen_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "sources": {name: record(path) for name, path in sources.items()},
        "registered_policy_count": 12, "forward_values_accessed": False, "paid_acquisition_authorized": False, "retuning_permitted": False,
    }
    write_json_exclusive(FREEZE, freeze)
    write_json_exclusive(STATE, {"version": "GOLD_CMP_EDGE_V1_STATE_M1_1_0", "status": "PASS_POLICY_DESIGN_FROZEN", "design_freeze": record(FREEZE), "next_step": "RUN_TRANSPARENT_WALK_FORWARD_POLICIES"})
    print(json.dumps({"status": "PASS_POLICY_DESIGN_FROZEN", "policies": 12, "design_freeze": record(FREEZE)}, indent=2, sort_keys=True))


if __name__ == "__main__": main()
