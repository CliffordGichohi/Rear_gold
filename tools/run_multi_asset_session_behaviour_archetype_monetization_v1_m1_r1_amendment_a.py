from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FROZEN_IMPLEMENTATION = ROOT / "tools/diagnose_multi_asset_session_behaviour_archetype_monetization_v1_m1_r1.py"
AMENDMENT = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1_preaccess_engineering_amendment_a.json"
INNER_SEAL = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1_seal.json"
OUTER_SEAL = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1_amendment_a_seal.json"
IMPLEMENTATION = Path(__file__).resolve()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(ROOT.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def import_frozen() -> Any:
    spec = importlib.util.spec_from_file_location("msbam_m1_r1_frozen", FROZEN_IMPLEMENTATION)
    if not spec or not spec.loader:
        raise RuntimeError("Cannot load frozen implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prove() -> dict[str, Any]:
    module = import_frozen()
    protocol = module.load(module.PROTOCOL)
    frozen = list(protocol["target_units"])
    semantic_membership_equal = set(frozen) == set(module.TARGET_UNITS)
    original_order_assertion_equal = frozen == sorted(module.TARGET_UNITS)
    result = {
        "proof": "TARGET_UNIT_ORDER_ONLY",
        "frozen_count": len(frozen),
        "implementation_count": len(module.TARGET_UNITS),
        "semantic_membership_equal": semantic_membership_equal,
        "original_order_assertion_equal": original_order_assertion_equal,
        "normalization": "SORT_BOTH_SIDES_FOR_GUARD_ONLY",
        "normalized_assertion_equal": sorted(frozen) == sorted(module.TARGET_UNITS),
    }
    if not semantic_membership_equal or original_order_assertion_equal or not result["normalized_assertion_equal"]:
        raise ValueError(result)
    return result


def execute() -> None:
    amendment = load(AMENDMENT)
    if amendment["status"] != "SEALED_PRE_TIMESTAMP_ACCESS_ENGINEERING_AMENDMENT_A":
        raise ValueError("Amendment not sealed")
    if record(FROZEN_IMPLEMENTATION) != amendment["frozen_implementation"]:
        raise ValueError("Frozen implementation changed")
    if record(IMPLEMENTATION) != amendment["amended_runner"]:
        raise ValueError("Amended runner changed")
    if amendment["proof"] != prove():
        raise ValueError("Order-only proof changed")
    if INNER_SEAL.exists() or OUTER_SEAL.exists():
        raise FileExistsError("R1 seal already exists")

    module = import_frozen()
    original_load = module.load

    def amended_load(path: Path) -> dict[str, Any]:
        value = original_load(path)
        if path.resolve() == module.PROTOCOL.resolve():
            value = dict(value)
            value["target_units"] = sorted(value["target_units"])
        return value

    module.load = amended_load
    module.main()

    inner = load(INNER_SEAL)
    for item in inner["artifacts"]:
        path = ROOT / item["path"]
        if record(path) != item:
            raise ValueError(f"Inner-seal artifact mismatch: {item['path']}")
    outer_core = {
        "version": "MSBAM_V1_M1_R1_AMENDMENT_A_SEAL_1_0",
        "status": "SEALED_MILESTONE_1_R1_COMPLETE_MANDATORY_STOP",
        "verdict": inner["verdict"],
        "preserved_m1_verdict": inner["preserved_m1_verdict"],
        "inner_result_seal": record(INNER_SEAL),
        "preaccess_engineering_amendment_a": record(AMENDMENT),
        "amended_runner": record(IMPLEMENTATION),
        "inner_artifact_set_verified": True,
        "research_definition_changed": False,
        "timestamp_rows_accessed_before_amendment_seal": False,
        "next_milestone_authorized": False,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    outer = {**outer_core, "outer_seal_hash": canonical_hash(outer_core), "sealed_at_utc": now()}
    write_exclusive(OUTER_SEAL, outer)
    print(json.dumps({"amendment_a_outer_seal": record(OUTER_SEAL)}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prove-only", action="store_true")
    args = parser.parse_args()
    if args.prove_only:
        print(json.dumps(prove(), indent=2))
    else:
        execute()


if __name__ == "__main__":
    main()
