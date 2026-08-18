from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash
from gold_intel.backtesting.casebook_discovery_v2_holdout import (
    EXPECTED_ZN_QUOTE_REQUEST,
    M6_QUOTE_VERSION,
    quote_request_fingerprint,
    validate_quote_manifest,
)


def main() -> None:
    args = _parser().parse_args()
    bundle_root = Path(args.bundle)
    research = _load_json(Path(args.research_manifest))
    research_hash = validate_quote_manifest(research)
    quote_path = bundle_root / "quote.json"
    bundle_path = bundle_root / "manifest.json"
    quote = _load_json(quote_path)
    bundle = _load_json(bundle_path)

    _verify_embedded_hash(quote, field="quote_hash")
    _verify_embedded_hash(bundle, field="manifest_hash")
    if quote["quote_version"] != M6_QUOTE_VERSION:
        raise ValueError("Unexpected quote version")
    if quote["research_manifest_hash"] != research_hash:
        raise ValueError("Quote points to another research manifest")
    if quote["request"] != EXPECTED_ZN_QUOTE_REQUEST:
        raise ValueError("Quote request changed")
    if quote["request_fingerprint"] != quote_request_fingerprint():
        raise ValueError("Quote request fingerprint mismatch")

    observation = quote["provider_observation"]
    estimated_cost = float(observation["estimated_cost_usd"])
    if not math.isfinite(estimated_cost) or estimated_cost < 0:
        raise ValueError("Invalid quoted cost")
    if observation["endpoint"] != "Historical.metadata.get_cost":
        raise ValueError("A non-metadata endpoint was recorded")
    if observation["classification"] != "OBSERVED":
        raise ValueError("Provider quote must be classified as OBSERVED")

    expected_false = (
        "api_key_recorded",
        "batch_job_submitted",
        "calendar_2026_values_accessed",
        "holdout_features_calculated",
        "holdout_outcomes_accessed",
        "market_values_accessed",
        "paid_download_started",
    )
    for field in expected_false:
        if quote["guardrails"][field] is not False:
            raise ValueError(f"Quote guardrail failed: {field}")
    if quote["next_action"]["authorized"] is not False:
        raise ValueError("Paid submission was unexpectedly authorized")

    artifact = bundle["artifacts"]
    if len(artifact) != 1 or artifact[0]["path"] != "quote.json":
        raise ValueError("Unexpected quote artifact inventory")
    if artifact[0]["sha256"] != _sha256(quote_path):
        raise ValueError("Quote file hash mismatch")
    if artifact[0]["bytes"] != quote_path.stat().st_size:
        raise ValueError("Quote byte count mismatch")
    if artifact[0]["document_hash"] != quote["quote_hash"]:
        raise ValueError("Quote document hash mismatch")
    for field in (
        "batch_job_submitted",
        "holdout_outcomes_accessed",
        "market_values_accessed",
        "paid_download_started",
    ):
        if bundle["integrity"][field] is not False:
            raise ValueError(f"Bundle integrity guard failed: {field}")

    validation: dict[str, Any] = {
        "validation_version": "GOLD_CASEBOOK_DISCOVERY_V2_M6_ZN_QUOTE_VALIDATION_V0_1",
        "result": "PASS_SEMANTIC_VALIDATION",
        "research_manifest_hash": research_hash,
        "bundle_manifest_hash": bundle["manifest_hash"],
        "quote_hash": quote["quote_hash"],
        "estimated_cost_usd": estimated_cost,
        "assertions": {
            "exact_2025_zn_only_request": True,
            "metadata_cost_endpoint_only": True,
            "provider_quote_classified_observed": True,
            "artifact_hashes_and_lengths_match": True,
            "paid_job_not_submitted": True,
            "market_values_not_accessed": True,
            "holdout_features_not_calculated": True,
            "holdout_outcomes_not_accessed": True,
            "api_key_not_recorded": True,
            "additional_user_authorization_required": True,
        },
    }
    validation["validation_hash"] = canonical_hash(validation)
    output = bundle_root / "semantic_validation.json"
    _write_json(output, validation)
    print(
        json.dumps(
            {
                "stage": "V2_M6_ZN_COST_ESTIMATE_VALIDATED",
                "result": validation["result"],
                "estimated_cost_usd": estimated_cost,
                "validation_hash": validation["validation_hash"],
                "paid_job_submitted": False,
                "market_values_accessed": False,
                "holdout_outcomes_accessed": False,
                "output": str(output),
            },
            sort_keys=True,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the metadata-only calendar-2025 ZN cost quote."
    )
    parser.add_argument(
        "--bundle",
        default="research_artifacts/gold_casebook_discovery_v2_m6_zn_quote_v01",
    )
    parser.add_argument(
        "--research-manifest",
        default="research_manifests/gold_casebook_discovery_v2_m6_zn_quote_v01.json",
    )
    return parser


def _verify_embedded_hash(document: Mapping[str, Any], *, field: str) -> None:
    supplied = str(document[field])
    content = {key: value for key, value in document.items() if key != field}
    if canonical_hash(content) != supplied:
        raise ValueError(f"{field} mismatch")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
