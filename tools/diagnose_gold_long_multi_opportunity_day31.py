#!/usr/bin/env python3
"""Read-only exact-difference diagnostic for the sealed day-31 stop."""

from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_long_multi_opportunity_auction_v1 as study  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import (  # noqa: E402
    materialize_case,
    predict_class_probability,
    prepare_features,
    transform_rows,
)


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    output: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            output.update(flatten(child, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            output.update(flatten(child, f"{prefix}[{index}]"))
    else:
        output[prefix] = value
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("alias", nargs="?", default="CAM-2022-001")
    args = parser.parse_args()
    alias = str(args.alias)
    _, routers, corrected = study.source_rows()
    streams = study.baseline.load_all_streams("primary")
    stream = streams[alias]
    prepared = prepare_features(streams.values())
    translator = study.load_json(study.TRANSLATOR)
    checkpoints = materialize_case(
        alias=alias, stream=stream, prepared=prepared, end_at=None
    )
    probabilities = predict_class_probability(
        translator["semantic"]["tree"],
        transform_rows(checkpoints, translator["preprocessing"]),
        positive_class=1,
    ).astype(float).tolist()
    identities = study.m15_structure_identities(stream, checkpoints)
    episodes = study.signal_episodes(
        checkpoints, probabilities, structure_identities=identities
    )
    cache = study.build_structural_cache(stream)
    candidates = [
        study.candidate_from_episode(
            episode=episode,
            stream=stream,
            translator=translator,
            structural_cache=cache,
        )
        for episode in episodes
    ]
    signal = routers[alias]["control"]["signal_at"]
    rebuilt = next(row["corrected"] for row in candidates if row["signal_at"] == signal)
    sealed = corrected[alias]["corrected"]
    left = flatten(sealed)
    right = flatten(rebuilt)
    missing = object()
    differences = [
        {
            "path": key,
            "sealed": left.get(key, "<MISSING>"),
            "rebuilt": right.get(key, "<MISSING>"),
        }
        for key in sorted(set(left) | set(right))
        if left.get(key, missing) != right.get(key, missing)
    ]
    print(
        json.dumps(
            {
                "alias": alias,
                "signal_at": signal,
                "episodes": len(episodes),
                "difference_count": len(differences),
                "effective_result_equal": sealed.get("effective_result")
                == rebuilt.get("effective_result"),
                "differences": differences,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
