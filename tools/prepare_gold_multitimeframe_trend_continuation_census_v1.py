from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
OUTPUT = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v01"
FREEZE = MANIFESTS / "gold_multitimeframe_trend_continuation_census_v1_design_freeze.json"
CONTRACT = ROOT / "GOLD_MULTITIMEFRAME_TREND_CONTINUATION_CENSUS_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_multitimeframe_trend_continuation_census_v1_protocol.json"
PRICE = ARTIFACTS / "gold_casebook_v01/price_bars.jsonl.gz"
CASEBOOK_MANIFEST = ARTIFACTS / "gold_casebook_v01/manifest.json"
PINNED_PRICE_SHA256 = "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20): digest.update(payload)
    return digest.hexdigest()


def record(path: Path, pinned: str | None = None) -> dict[str, object]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": pinned or sha(path), "verification": "INHERITED_FROM_SEALED_CASEBOOK" if pinned else "HASHED_NOW"}


def write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True); handle.write("\n")


def main() -> None:
    if FREEZE.exists() or OUTPUT.exists(): raise FileExistsError("Census already initialized")
    for path in (CONTRACT, PROTOCOL, PRICE, CASEBOOK_MANIFEST):
        if not path.is_file(): raise FileNotFoundError(path)
    manifest = json.loads(CASEBOOK_MANIFEST.read_text(encoding="utf-8"))
    price_entry = next(item for item in manifest["artifacts"] if item["name"] == "price_bars.jsonl.gz")
    if price_entry["sha256"] != PINNED_PRICE_SHA256 or price_entry["bytes"] != PRICE.stat().st_size:
        raise ValueError("Sealed casebook price binding failed")
    controls = {"contract": record(CONTRACT), "protocol": record(PROTOCOL)}
    sources = {"price_bars": record(PRICE, PINNED_PRICE_SHA256), "casebook_manifest": record(CASEBOOK_MANIFEST)}
    OUTPUT.mkdir(parents=True, exist_ok=False)
    preflight = {"version": "GOLD_MT_CENSUS_V1_PREFLIGHT_1_0", "status": "PASS_SOURCE_READINESS", "completed_at_utc": datetime.now(UTC).isoformat(), "controls": controls, "sources": sources, "outcomes_or_relationships_calculated": False, "forward_values_accessed": False}
    write(OUTPUT / "preflight.json", preflight)
    freeze = {"version": "GOLD_MT_CENSUS_V1_DESIGN_FREEZE_1_0", "status": "SEALED_BEFORE_CENSUS_MATERIALIZATION", "sealed_at_utc": datetime.now(UTC).isoformat(), "controls": controls, "sources": sources, "preflight": record(OUTPUT / "preflight.json"), "forward_values_accessed": False, "paid_acquisition_authorized": False}
    write(FREEZE, freeze)
    print(json.dumps({"status": freeze["status"], "source": sources["price_bars"]}, indent=2))


if __name__ == "__main__": main()
