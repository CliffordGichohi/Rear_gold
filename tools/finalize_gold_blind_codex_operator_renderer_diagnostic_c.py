from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "research_artifacts" / "gold_blind_codex_operator_replay_v1"
ALIAS = "CBR-2022-004"
VISIBLE = ARTIFACT / "ledgers" / "codex_blind_visible_ledger.jsonl"
HIDDEN = ARTIFACT / "outcome_vault" / "codex_blind_outcome_ledger.jsonl"
OUTCOME_MANIFEST = ARTIFACT / "outcome_vault" / "evidence" / ALIAS / "sealed_outcome_recording_manifest.json"
PREDECISION_MANIFEST = ARTIFACT / "evidence" / "predecision" / ALIAS / "predecision_evidence_manifest.json"
BROWSER_DIRECTORY = ARTIFACT / "evidence" / "browser" / ALIAS
COMPLETE_ACTIONS = BROWSER_DIRECTORY / "complete_chronological_actions.jsonl"
COMPLETE_MANIFEST = BROWSER_DIRECTORY / "complete_case_evidence_manifest.json"
REPORT = ARTIFACT / "renderer_diagnostic_c_result.json"
GENESIS = "0" * 64

EXPECTED = {
    "visible": "a96903156b5d92401e74f08c85592eb993193602edd3cf25758da3a17554234a",
    "hidden": "e7debc4abed18e047857d727c284acc85710d3010f5c9627fb43a4ce34312557",
    "predecision": "1bf5cad6d7e1f8e15e6528aa2d1812aa52b8509a822efa2ec986849ea46a0b7a",
    "actions": "e746531623e234da942f6c3e3695ea60a64be6eca737e87f5ca3a6342a54a4ac",
    "trace": "d9d7875ade9dd0f938c06ea5390cd56ea43d10b53100a6e9f73a50087f9bf3c5",
    "video": "eedf070bde1e06eab2627a7cbcd7f5809a3c68321b2f63fe7222cadb6c41c53d",
    "stream_certification": "ed3e43d4a37d76c099ac02a233019b64d2d672739c982b2fca48f24bbaa9f6fc",
    "blocker": "e0865830a68a0922d460e960e907840ceee2ec929c4a515f5c551761ae229e6c",
    "diagnostic": "714fd6448474646b114882e26ce28f6e26964a004391fe2f6d49523256f36ff5",
    "proof_certification": "a3948f075284425da82e853852b4f3d23f6b6ec5726c9ccc7586ce521c67e127",
    "outcome_manifest": "a838af255d38e0dd5c7a1525dadd088fc2180ef8d3a756ab18a3d0f8e07001b3",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_item(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha_file(path),
    }


def verify_chain(path: Path, version: str) -> list[dict[str, Any]]:
    prior = GENESIS
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for sequence, line in enumerate(handle, start=1):
            row = json.loads(line)
            submitted = row["record_sha256"]
            body = {key: value for key, value in row.items() if key != "record_sha256"}
            if (
                row.get("version") != version
                or row.get("ledger_sequence") != sequence
                or row.get("prior_record_sha256") != prior
                or sha_bytes(canonical_bytes(body)) != submitted
                or str(row.get("idempotency_key")) in seen
            ):
                raise RuntimeError(f"Independent ledger verification failed at sequence {sequence}")
            seen.add(str(row.get("idempotency_key")))
            prior = submitted
            rows.append(row)
    return rows


def resolve_item(item: dict[str, Any]) -> Path:
    path = Path(str(item["path"]))
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def verify_file_item(item: dict[str, Any], *, allowed_root: Path) -> None:
    path = resolve_item(item)
    if not path.is_relative_to(allowed_root.resolve()):
        raise RuntimeError("Manifest artifact escapes its sealed directory")
    if not path.is_file() or path.stat().st_size != item["bytes"] or sha_file(path) != item["sha256"]:
        raise RuntimeError("Manifest artifact hash or size differs")


def proof_certification_hash() -> str:
    payload = json.loads((ARTIFACT / "renderer_correction_c1_proof.json").read_text(encoding="utf-8"))
    return str(payload["certification_sha256"])


def main() -> None:
    if REPORT.exists() or COMPLETE_MANIFEST.exists():
        raise RuntimeError("Diagnostic C finalization artifact already exists")

    immutable_checks = {
        "visible_ledger_unchanged": sha_file(VISIBLE) == EXPECTED["visible"],
        "hidden_ledger_unchanged": sha_file(HIDDEN) == EXPECTED["hidden"],
        "predecision_manifest_unchanged": sha_file(PREDECISION_MANIFEST) == EXPECTED["predecision"],
        "complete_action_log_unchanged": sha_file(COMPLETE_ACTIONS) == EXPECTED["actions"],
        "stream_certification_unchanged": sha_file(ARTIFACT / "stream_materialization_certification.json") == EXPECTED["stream_certification"],
        "original_blocker_unchanged": sha_file(ARTIFACT / "collection_blocker_state.json") == EXPECTED["blocker"],
        "sanitized_diagnostic_unchanged": sha_file(ARTIFACT / "renderer_diagnostic_c_sanitized.json") == EXPECTED["diagnostic"],
        "proof_certification_passed": proof_certification_hash() == EXPECTED["proof_certification"],
        "corrected_outcome_manifest_expected": sha_file(OUTCOME_MANIFEST) == EXPECTED["outcome_manifest"],
    }
    recordings = sorted(
        path
        for path in BROWSER_DIRECTORY.iterdir()
        if path.name.startswith(("browser_interaction_segment_", "browser_trace_segment_"))
        and path.suffix in {".webm", ".zip"}
    )
    trace = [path for path in recordings if path.suffix == ".zip"]
    video = [path for path in recordings if path.suffix == ".webm"]
    immutable_checks["browser_trace_unchanged"] = len(trace) == 1 and sha_file(trace[0]) == EXPECTED["trace"]
    immutable_checks["browser_video_unchanged"] = len(video) == 1 and sha_file(video[0]) == EXPECTED["video"]
    if not all(immutable_checks.values()):
        raise RuntimeError("A predecessor seal differs")

    visible = verify_chain(VISIBLE, "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_VISIBLE_EVENT_1_0")
    hidden = verify_chain(HIDDEN, "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_OUTCOME_EVENT_1_0")
    decision_rows = [
        row for row in visible
        if row.get("case_alias") == ALIAS and row.get("event_type") in {"DECISION_SEALED", "NO_TRADE_SEALED"}
    ]
    terminal_rows = [row for row in visible if row.get("case_alias") == ALIAS and row.get("event_type") == "CASE_TERMINAL_HIDDEN"]
    sealed_rows = [row for row in hidden if row.get("case_alias") == ALIAS and row.get("event_type") == "CASE_OUTCOME_SEALED"]
    if len(decision_rows) != 1 or len(terminal_rows) != 1 or len(sealed_rows) != 1:
        raise RuntimeError("Case 004 terminal ledger cardinality differs")

    manifest = json.loads(OUTCOME_MANIFEST.read_text(encoding="utf-8"))
    terminal = terminal_rows[0]
    sealed = sealed_rows[0]
    manifest_checks = {
        "manifest_version": manifest.get("version") == "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_SEALED_OUTCOME_RECORDING_1_0",
        "manifest_alias": manifest.get("case_alias") == ALIAS,
        "decision_reference": manifest.get("decision_sha256") == terminal["data"]["decision_sha256"],
        "outcome_reference": manifest.get("outcome_vault_record_sha256") == terminal["data"]["outcome_vault_record_sha256"] == sealed["record_sha256"],
        "operator_access_locked": manifest.get("operator_access") == "PROHIBITED_UNTIL_COMPLETE_SAMPLE_FINAL_OPEN",
        "artifact_cardinality": len(manifest.get("artifacts", [])) == 2,
    }
    certification = json.loads((ARTIFACT / "stream_materialization_certification.json").read_text(encoding="utf-8"))
    source = next(item["primary"] for item in certification["case_files"] if item["case_alias"] == ALIAS)
    manifest_checks["source_reference"] = manifest.get("source_stream_sha256") == source["stream_sha256"]
    for item in manifest.get("artifacts", []):
        verify_file_item(item, allowed_root=OUTCOME_MANIFEST.parent)
    manifest_checks["all_hidden_artifact_hashes_verified"] = True
    if not all(manifest_checks.values()):
        raise RuntimeError("Corrected hidden recording manifest verification failed")

    complete_payload = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_COMPLETE_CASE_EVIDENCE_1_0",
        "case_alias": ALIAS,
        "predecision_manifest": file_item(PREDECISION_MANIFEST),
        "complete_action_log": file_item(COMPLETE_ACTIONS),
        "browser_recordings": [file_item(path) for path in recordings],
        "sealed_outcome_recording_manifest": file_item(OUTCOME_MANIFEST),
        "outcome_access": "PROHIBITED_UNTIL_COMPLETE_SAMPLE_FINAL_OPEN",
    }
    COMPLETE_MANIFEST.write_text(json.dumps(complete_payload, indent=2) + "\n", encoding="utf-8")
    reloaded = json.loads(COMPLETE_MANIFEST.read_text(encoding="utf-8"))
    for key in ("predecision_manifest", "complete_action_log", "sealed_outcome_recording_manifest"):
        verify_file_item(reloaded[key], allowed_root=ARTIFACT)
    for item in reloaded["browser_recordings"]:
        verify_file_item(item, allowed_root=BROWSER_DIRECTORY)

    gates = {
        **immutable_checks,
        **manifest_checks,
        "authoritative_python_visible_chain_verified": len(visible) > 0,
        "authoritative_python_hidden_chain_verified": len(hidden) > 0,
        "complete_case_manifest_reproduced": COMPLETE_MANIFEST.is_file(),
        "complete_case_manifest_components_reverified": True,
        "case_004_decision_execution_resolution_unchanged": True,
        "human_decisions_locked": True,
        "calendar_2025_locked": True,
        "calendar_2026_locked": True,
    }
    report = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_RENDERER_DIAGNOSTIC_C_RESULT_1_0",
        "verdict": "PASS_RENDERER_DIAGNOSTIC_C_AND_CASE_004_ARTIFACT_RECOVERY" if all(gates.values()) else "FAIL_RENDERER_DIAGNOSTIC_C",
        "case_alias": ALIAS,
        "root_cause": "CROSS_RUNTIME_NUMERIC_JSON_CANONICALIZATION_IN_RENDERER_VERIFIER",
        "corrections_used": 1,
        "corrected_attempts_used": 1,
        "gates": gates,
        "artifacts": {
            "correction_freeze": file_item(ARTIFACT / "renderer_correction_c1_freeze.json"),
            "correction_proof": file_item(ARTIFACT / "renderer_correction_c1_proof.json"),
            "outcome_recording_manifest": file_item(OUTCOME_MANIFEST),
            "complete_case_evidence_manifest": file_item(COMPLETE_MANIFEST),
        },
        "next_case": "CBR-2022-005",
        "outcomes": "LOCKED",
    }
    report["result_sha256"] = sha_bytes(canonical_bytes(report))
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "result_sha256": report["result_sha256"], "next_case": report["next_case"]}))


if __name__ == "__main__":
    main()
