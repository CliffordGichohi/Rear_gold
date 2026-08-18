"""Seal an externally confirmed OOM termination of the sole M2-R2 attempt.

This operational helper does not execute or resume materialization. It invokes
the failure-sealing function that was frozen before the attempt and then
verifies the resulting receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import materialize_gc_session_trigger_edge_m2 as m2  # noqa: E402
import run_gc_session_trigger_edge_m2r2 as r2  # noqa: E402


class KernelOOMKill(RuntimeError):
    """The operating system killed the process under global OOM pressure."""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-m2", required=True)
    parser.add_argument("--old-r1", required=True)
    parser.add_argument("--old-a1", required=True)
    parser.add_argument("--acquisition", required=True)
    parser.add_argument("--step5b2", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--xau", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--killed-at", required=True)
    parser.add_argument("--total-vm-kib", type=int, required=True)
    parser.add_argument("--anon-rss-kib", type=int, required=True)
    parser.add_argument("--last-checkpoint", type=int, required=True)
    parser.add_argument("--checkpoint-total", type=int, required=True)
    args = parser.parse_args()

    output = Path(args.output)
    required = ("pre_freeze_policy_proof.json", "preflight.json", "attempt_started.json")
    missing = [name for name in required if not (output / name).is_file()]
    if missing:
        raise RuntimeError(f"Cannot seal OOM failure; missing attempt artifacts: {missing}")
    forbidden = ("execution_failure.json", "verdict.json", "manifest.json", "final_seal.json")
    existing = [name for name in forbidden if (output / name).exists()]
    if existing:
        raise RuntimeError(f"Refusing to overwrite an existing disposition: {existing}")
    if Path(f"/proc/{args.pid}").exists():
        raise RuntimeError(f"Refusing to seal while worker PID {args.pid} is alive")
    attempt = r2.read_json(output / "attempt_started.json")
    if attempt.get("attempt") != 1 or attempt.get("maximum_attempts") != 1:
        raise RuntimeError("The sealed single-attempt marker is invalid")

    paths = m2.Paths(
        Path(args.acquisition),
        Path(args.step5b2),
        Path(args.context),
        Path(args.xau),
        output,
    )
    old_m2 = Path(args.old_m2)
    old_r1 = Path(args.old_r1)
    old_a1 = Path(args.old_a1)
    predecessor = r2.verify_freeze(old_m2, old_r1, old_a1, output)
    message = (
        "Kernel OOM killed the sole M2-R2 process; "
        f"pid={args.pid}; killed_at={args.killed_at}; "
        f"total_vm_kib={args.total_vm_kib}; anon_rss_kib={args.anon_rss_kib}; "
        f"last_completed_checkpoint={args.last_checkpoint}/{args.checkpoint_total}; "
        "no completed technical result or verdict was emitted"
    )
    error = KernelOOMKill(message)
    r2.seal_execution_failure(paths, predecessor, error)
    r2.verify_final(paths, old_m2, old_r1, old_a1)
    print(
        json.dumps(
            {
                "status": "SEALED_EXTERNAL_KERNEL_OOM_FAILURE",
                "error_type": type(error).__name__,
                "error_message": message,
                "error_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
                "attempts": 1,
                "rerun_performed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
