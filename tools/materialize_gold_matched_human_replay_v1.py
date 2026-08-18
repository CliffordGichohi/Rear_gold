from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "research_artifacts" / "gold_blind_codex_operator_replay_v1"
DESTINATION = ROOT / "research_artifacts" / "gold_matched_human_replay_v1"
CASE_COUNT = 30


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    if (DESTINATION / "ledgers" / "matched_human_visible_ledger.jsonl").exists():
        raise RuntimeError("Matched human collection already started; materialization is immutable")
    source_registry = read_json(SOURCE / "population_registry.private.json")
    source_certification = read_json(SOURCE / "stream_materialization_certification.json")
    expected = [f"CBR-2022-{index:03d}" for index in range(1, CASE_COUNT + 1)]
    cases = source_registry["cases"][:CASE_COUNT]
    case_files = source_certification["case_files"][:CASE_COUNT]
    if [row["case_alias"] for row in cases] != expected:
        raise RuntimeError("The frozen source case order differs")
    if [row["case_alias"] for row in case_files] != expected:
        raise RuntimeError("The frozen source-file order differs")
    if not all(source_certification.get("gates", {}).values()):
        raise RuntimeError("The source certification has a failed gate")

    population_sha256 = sha256_bytes(canonical_bytes(cases))
    registry = {
        "version": "GOLD_MATCHED_HUMAN_REPLAY_V1_PRIVATE_REGISTRY_1_0",
        "case_count": CASE_COUNT,
        "population_sha256": population_sha256,
        "outcomes": "LOCKED_UNTIL_COMPLETE_POPULATION",
        "research_credit": "ZERO_CREDIT_MATCHED_METHOD_DIAGNOSTIC",
        "source_population_sha256": source_registry["population_sha256"],
        "cases": cases,
    }
    public_registry = {
        "version": "GOLD_MATCHED_HUMAN_REPLAY_V1_PUBLIC_REGISTRY_1_0",
        "case_count": CASE_COUNT,
        "population_sha256": population_sha256,
        "research_credit": "ZERO_CREDIT_MATCHED_METHOD_DIAGNOSTIC",
        "codex_decisions": "HIDDEN_DURING_COLLECTION",
        "outcomes": "HIDDEN_DURING_COLLECTION",
        "cases": [
            {
                "case_alias": row["case_alias"],
                "mode_sequence": row["mode_sequence"],
                "trading_date_utc": row["trading_date_utc"],
            }
            for row in cases
        ],
    }
    certification = {
        "version": "GOLD_MATCHED_HUMAN_REPLAY_V1_SOURCE_CERTIFICATION_1_0",
        "verdict": "PASS_CODEX_OPERATOR_PRIVATE_STREAM_MATERIALIZATION",
        "case_count": CASE_COUNT,
        "population_sha256": population_sha256,
        "source_certification_sha256": sha256_file(
            SOURCE / "stream_materialization_certification.json"
        ),
        "source_artifact": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "gates": source_certification["gates"],
        "case_files": case_files,
    }
    write_json(DESTINATION / "population_registry.private.json", registry)
    write_json(DESTINATION / "population_registry.public.json", public_registry)
    write_json(DESTINATION / "stream_materialization_certification.json", certification)

    for filename in ("decision_policy.json", "execution_policy.json", "ledger_policy.json"):
        payload = (SOURCE / filename).read_bytes()
        target = DESTINATION / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    state = {
        "version": "GOLD_MATCHED_HUMAN_REPLAY_V1_STATE_1_0",
        "state": "READY_FOR_MATCHED_HUMAN_COLLECTION",
        "case_count": CASE_COUNT,
        "first_date": cases[0]["trading_date_utc"],
        "last_date": cases[-1]["trading_date_utc"],
        "population_sha256": population_sha256,
        "source_values_reused_without_reacquisition": True,
        "codex_ledgers_unchanged": True,
        "human_visible_ledger": "NOT_STARTED",
        "human_outcome_ledger": "NOT_STARTED",
        "files": {
            filename: sha256_file(DESTINATION / filename)
            for filename in (
                "population_registry.private.json",
                "population_registry.public.json",
                "stream_materialization_certification.json",
                "decision_policy.json",
                "execution_policy.json",
                "ledger_policy.json",
            )
        },
    }
    write_json(DESTINATION / "state.json", state)
    print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
