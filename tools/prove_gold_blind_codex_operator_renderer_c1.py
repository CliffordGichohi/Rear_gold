from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / ".codex_runs" / "codex_operator_replay_v1" / "renderer_c1_proof"
SYNTHETIC_LEDGER = RUN_ROOT / "synthetic_python_canonical.jsonl"
ENGINEERING_ARTIFACT = ROOT / ".codex_runs" / "codex_operator_replay_e2e" / "artifact"
REPORT_PATH = ROOT / "research_artifacts" / "gold_blind_codex_operator_replay_v1" / "renderer_correction_c1_proof.json"
VERSION = "GOLD_BLIND_CODEX_RENDERER_C1_SYNTHETIC_1_0"
GENESIS = "0" * 64


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def seal_synthetic() -> bytes:
    vectors = [
        {"diagnostic_counter": 1, "diagnostic_numeric": 1e-6, "nested": {"record_sha256": "nested-not-top-level"}},
        {"diagnostic_counter": 2, "diagnostic_numeric": 1e20, "escaped": "quote:\" slash:\\"},
        {"diagnostic_counter": 3, "diagnostic_numeric": -0.0, "unicode": "canonical-Δ"},
        {"diagnostic_counter": 4, "diagnostic_numeric": 1.2345678901234567, "nested": [1, {"ok": True}]},
    ]
    prior = GENESIS
    lines: list[bytes] = []
    for sequence, data in enumerate(vectors, start=1):
        body = {
            "data": data,
            "idempotency_key": f"synthetic-{sequence}",
            "ledger_sequence": sequence,
            "prior_record_sha256": prior,
            "version": VERSION,
        }
        record_hash = digest(canonical_bytes(body))
        row = {**body, "record_sha256": record_hash}
        lines.append(canonical_bytes(row))
        prior = record_hash
    return b"\n".join(lines) + b"\n"


def verify_python(path: Path, version: str) -> dict[str, Any]:
    prior = GENESIS
    seen: set[str] = set()
    rows = 0
    raw = path.read_bytes()
    for sequence, line in enumerate(raw.splitlines(), start=1):
        row = json.loads(line)
        submitted = row.pop("record_sha256")
        assert row["version"] == version
        assert row["ledger_sequence"] == sequence
        assert row["prior_record_sha256"] == prior
        assert digest(canonical_bytes(row)) == submitted
        assert row["idempotency_key"] not in seen
        seen.add(row["idempotency_key"])
        prior = submitted
        rows += 1
    return {"rows": rows, "source_sha256": digest(raw), "head_sha256": prior}


def node_proof() -> dict[str, Any]:
    command = [
        "node",
        str(ROOT / "frontend" / "tools" / "prove-codex-renderer-correction-c1.mjs"),
        "--synthetic",
        str(SYNTHETIC_LEDGER),
        "--engineering-visible",
        str(ENGINEERING_ARTIFACT / "ledgers" / "codex_blind_visible_ledger.jsonl"),
        "--engineering-hidden",
        str(ENGINEERING_ARTIFACT / "outcome_vault" / "codex_blind_outcome_ledger.jsonl"),
    ]
    completed = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def main() -> None:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    payload = seal_synthetic()
    SYNTHETIC_LEDGER.write_bytes(payload)

    python_checks = {
        "synthetic": verify_python(SYNTHETIC_LEDGER, VERSION),
        "engineering_visible": verify_python(
            ENGINEERING_ARTIFACT / "ledgers" / "codex_blind_visible_ledger.jsonl",
            "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_VISIBLE_EVENT_1_0",
        ),
        "engineering_hidden": verify_python(
            ENGINEERING_ARTIFACT / "outcome_vault" / "codex_blind_outcome_ledger.jsonl",
            "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_OUTCOME_EVENT_1_0",
        ),
    }
    first = node_proof()
    second = node_proof()
    agreement = first == second
    cross_implementation = (
        first["synthetic"]["rows"] == python_checks["synthetic"]["rows"]
        and first["synthetic"]["source_sha256"] == python_checks["synthetic"]["source_sha256"]
        and first["engineering"]["visible_rows"] == python_checks["engineering_visible"]["rows"]
        and first["engineering"]["hidden_rows"] == python_checks["engineering_hidden"]["rows"]
    )
    gates = {
        "all_node_gates_pass": all(first["gates"].values()),
        "independent_python_verification_pass": True,
        "node_runs_identical": agreement,
        "python_node_counts_and_source_hashes_identical": cross_implementation,
    }
    report = {
        "version": "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_RENDERER_CORRECTION_C1_CERTIFICATION_1_0",
        "verdict": "PASS_RENDERER_CORRECTION_C1_PROOF" if all(gates.values()) else "FAIL_RENDERER_CORRECTION_C1_PROOF",
        "gates": gates,
        "node_proof": first,
        "python_verification": python_checks,
        "second_node_proof_checksum": second["proof_checksum"],
    }
    report["certification_sha256"] = digest(canonical_bytes(report))
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_bytes(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n")
    print(json.dumps({"verdict": report["verdict"], "certification_sha256": report["certification_sha256"]}))
    if report["verdict"].startswith("FAIL"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
