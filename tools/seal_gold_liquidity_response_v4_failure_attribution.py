from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research_artifacts/gold_liquidity_response_v4_failure_attribution"
SEAL = OUTPUT / "final_seal.json"
FILES = {
    "report": ROOT / "GOLD_LIQUIDITY_RESPONSE_V4_FAILURE_ATTRIBUTION_REPORT.md",
    "freeze": ROOT
    / "research_manifests/gold_liquidity_response_v4_failure_attribution_freeze.json",
    "result": OUTPUT / "result.json",
    "rows": OUTPUT / "rows.csv",
    "result_seal": OUTPUT / "seal.json",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    if SEAL.exists():
        raise FileExistsError(SEAL)
    missing = [name for name, path in FILES.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)
    result = json.loads(FILES["result"].read_text(encoding="utf-8"))
    expected = {
        "actual_v4_matches": 5,
        "diagnostic_natural_state_matches": 10,
        "diagnostic_natural_plus_htf_matches": 9,
        "control_natural_state_days": 11,
        "control_natural_plus_htf_days": 11,
    }
    if any(result["summary"].get(key) != value for key, value in expected.items()):
        raise RuntimeError("Attribution result changed")
    payload = {
        "version": "GOLD_LIQUIDITY_RESPONSE_V4_FAILURE_ATTRIBUTION_FINAL_SEAL_1_0",
        "status": "SEALED_NO_SUCCESSOR_AUTHORIZED_BY_CURRENT_ATTRIBUTION",
        "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "files": {
            name: {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
            for name, path in FILES.items()
        },
        "outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
    }
    descriptor = os.open(SEAL, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"status": payload["status"], "files": len(FILES)}, indent=2))


if __name__ == "__main__":
    main()
