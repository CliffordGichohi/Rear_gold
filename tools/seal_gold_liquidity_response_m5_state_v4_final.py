from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research_artifacts" / "gold_liquidity_response_m5_structure_state_edge_v4"
STATE = OUTPUT / "final_state.json"
SEAL = OUTPUT / "final_seal.json"
FILES = {
    "report": ROOT / "GOLD_LIQUIDITY_RESPONSE_M5_STRUCTURE_STATE_EDGE_V4_REPORT.md",
    "freeze": ROOT
    / "research_manifests"
    / "gold_liquidity_response_m5_structure_state_edge_v4_preoutcome_freeze.json",
    "result": OUTPUT / "semantic_calibration.json",
    "rows": OUTPUT / "semantic_rows.csv",
    "semantic_seal": OUTPUT / "semantic_seal.json",
    "implementation": ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "liquidity_shift_v4.py",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": digest(path),
    }


def write(path: Path, payload: dict[str, object]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> None:
    if STATE.exists() or SEAL.exists():
        raise FileExistsError("V4 final artifacts already exist")
    missing = [name for name, path in FILES.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    result = json.loads(FILES["result"].read_text(encoding="utf-8"))
    metrics = result["metrics"]
    if metrics["semantic_verdict"] != "FAIL_SEMANTIC_REPRESENTATION":
        raise RuntimeError("V4 failure was not preserved")
    if metrics["trade_matches"] != 5 or metrics["false_positive_days"] != 11:
        raise RuntimeError("V4 support changed")
    payload: dict[str, object] = {
        "version": "GOLD_LIQUIDITY_RESPONSE_M5_STRUCTURE_STATE_EDGE_V4_FINAL_STATE_1_0",
        "status": "TERMINATED_FAIL_SEMANTIC_REPRESENTATION",
        "finalized_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "trade_matches": 5,
        "false_positive_days": 11,
        "development_outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "files": {name: record(path) for name, path in FILES.items()},
    }
    write(STATE, payload)
    write(
        SEAL,
        {
            "version": "GOLD_LIQUIDITY_RESPONSE_M5_STRUCTURE_STATE_EDGE_V4_FINAL_SEAL_1_0",
            "verdict": payload["status"],
            "final_state": record(STATE),
        },
    )
    print(json.dumps({"status": payload["status"], "files": len(FILES)}, indent=2))


if __name__ == "__main__":
    main()
