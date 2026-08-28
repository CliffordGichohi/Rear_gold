"""Value-blind field-path diagnosis for the exposed-policy reproduction mismatch."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import regress_gold_coherent_auction_frozen_policy_exposed_v1 as subject  # noqa: E402


def differences(left: Any, right: Any, path: str = "$") -> list[str]:
    if type(left) is not type(right):
        return [f"{path}:TYPE"]
    if isinstance(left, dict):
        output: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}"
            if key not in left or key not in right:
                output.append(f"{child}:PRESENCE")
            else:
                output.extend(differences(left[key], right[key], child))
        return output
    if isinstance(left, list):
        if len(left) != len(right):
            return [f"{path}:LENGTH"]
        output = []
        for index, (first, second) in enumerate(zip(left, right, strict=True)):
            output.extend(differences(first, second, f"{path}[{index}]"))
        return output
    return [] if left == right else [f"{path}:VALUE"]


def main() -> int:
    primary = subject.add_attribution(
        subject.analyze(subject.simulate_track_b, subject.primary_completed_metadata)
    )
    reference = subject.add_attribution(
        subject.analyze(
            subject.simulate_track_b_reference, subject.reference_completed_metadata
        )
    )
    paths = differences(primary, reference)
    redacted = {
        "status": "FIELD_PATH_DIAGNOSIS_ONLY",
        "primary_payload_sha256": subject.canonical_hash(primary),
        "reference_payload_sha256": subject.canonical_hash(reference),
        "difference_count": len(paths),
        "difference_paths": paths,
        "control_reproduction_failure_aliases": [
            row["case_alias"]
            for row in primary["cases"]
            if not row["control_reproduction_exact"]
        ],
        "market_or_economic_values_printed": False,
    }
    print(json.dumps(redacted, indent=2))
    return 0 if paths else 1


if __name__ == "__main__":
    raise SystemExit(main())
