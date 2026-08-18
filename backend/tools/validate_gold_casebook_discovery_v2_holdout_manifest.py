from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash
from gold_intel.backtesting.casebook_discovery_v2_holdout import (
    EXPECTED_EVALUATION_GATE_IDS,
    EXPECTED_READINESS_GATE_IDS,
    validate_holdout_manifest,
)
from gold_intel.backtesting.casebook_discovery_v2_relationships import (
    embedded_manifest_hash,
)


def main() -> None:
    args = _parser().parse_args()
    research = _load_json(Path(args.research_manifest))
    research_hash = validate_holdout_manifest(research)
    _verify_sources(research)

    contract = _load_json(Path("research_manifests/gold_casebook_discovery_contract_v02.json"))
    execution = _load_json(Path("research_manifests/gold_casebook_constant_execution_v01.json"))
    shortlist = _load_json(
        Path("research_artifacts/gold_casebook_discovery_v2_shortlist_v01/shortlist.json")
    )
    shortlist_validation = _load_json(
        Path("research_artifacts/gold_casebook_discovery_v2_shortlist_v01/semantic_validation.json")
    )
    quote = _load_json(
        Path("research_artifacts/gold_casebook_discovery_v2_m6_zn_quote_v01/quote.json")
    )
    quote_validation = _load_json(
        Path(
            "research_artifacts/gold_casebook_discovery_v2_m6_zn_quote_v01/semantic_validation.json"
        )
    )
    if embedded_manifest_hash(contract) != contract["manifest_hash"]:
        raise ValueError("V2 contract manifest hash mismatch")
    if embedded_manifest_hash(execution) != execution["manifest_hash"]:
        raise ValueError("Execution manifest hash mismatch")
    if shortlist["shortlist_hash"] != research["source"]["shortlist_hash"]:
        raise ValueError("M6 points to another shortlist")
    if shortlist_validation["result"] != "PASS_SEMANTIC_VALIDATION":
        raise ValueError("Shortlist semantic validation did not pass")
    if quote_validation["result"] != "PASS_SEMANTIC_VALIDATION":
        raise ValueError("Quote semantic validation did not pass")
    if quote["quote_hash"] != research["source"]["quote_hash"]:
        raise ValueError("M6 points to another quote")
    if float(quote["provider_observation"]["estimated_cost_usd"]) != float(
        research["source"]["quote_estimated_cost_usd"]
    ):
        raise ValueError("Quoted cost changed")
    if float(quote["provider_observation"]["estimated_cost_usd"]) > float(
        research["acquisition"]["maximum_cost_usd"]
    ):
        raise ValueError("Frozen quote exceeds the authorized cap")
    if any(
        quote["guardrails"][field] is not False
        for field in (
            "batch_job_submitted",
            "paid_download_started",
            "market_values_accessed",
            "holdout_features_calculated",
            "holdout_outcomes_accessed",
        )
    ):
        raise ValueError("Quote-stage guardrail failed")

    frozen_candidate = shortlist["candidates"][0]
    for field in ("candidate_code", "rule_table", "session", "threshold"):
        if research["candidate"][field] != frozen_candidate[field]:
            raise ValueError(f"M6 candidate changed: {field}")
    if research["candidate"]["tuning_permitted"] is not False:
        raise ValueError("Candidate tuning was enabled")
    if shortlist["summary"]["new_york_candidates"] != 0:
        raise ValueError("Unexpected New York shortlist candidate")
    if tuple(research["readiness"]["gate_ids"]) != EXPECTED_READINESS_GATE_IDS:
        raise ValueError("Readiness gate family changed")
    if tuple(research["evaluation"]["gate_ids"]) != EXPECTED_EVALUATION_GATE_IDS:
        raise ValueError("Evaluation gate family changed")

    if research["source"]["execution_manifest_hash"] != execution["manifest_hash"]:
        raise ValueError("M6 points to another execution manifest")
    expected_execution = {
        "decision_clock_local": execution["sessions"]["LONDON"]["decision_clock_local"],
        "entry_clock_local": execution["sessions"]["LONDON"]["entry_clock_local"],
        "exit_clock_local": execution["sessions"]["LONDON"]["fixed_exit_clock_local"],
        "commission_usd_per_lot_round_turn": execution["costs"][
            "commission_usd_per_lot_round_turn"
        ],
        "slippage_usd_per_ounce_per_side": execution["costs"][
            "slippage_price_usd_per_ounce_per_side"
        ],
        "notional_ounces": execution["notional"]["quantity_ounces"],
        "contract_size_ounces_per_lot": execution["notional"]["contract_size_ounces_per_lot"],
    }
    for field, value in expected_execution.items():
        if research["execution"][field] != value:
            raise ValueError(f"M6 execution changed: {field}")

    validation: dict[str, Any] = {
        "validation_version": ("GOLD_CASEBOOK_DISCOVERY_V2_M6_HOLDOUT_MANIFEST_VALIDATION_V0_1"),
        "result": "PASS_PREOPEN_MANIFEST_VALIDATION",
        "research_manifest_hash": research_hash,
        "assertions": {
            "authorization_and_cost_cap_frozen": True,
            "all_source_file_hashes_match": True,
            "contract_and_execution_manifest_hashes_match": True,
            "sole_london_candidate_unchanged": True,
            "new_york_candidate_absent": True,
            "all_five_readiness_gates_unchanged": True,
            "all_twelve_evaluation_gates_unchanged": True,
            "one_candidate_multiplicity_family_unchanged": True,
            "quote_below_cap_and_semantically_valid": True,
            "paid_job_not_yet_submitted": True,
            "market_values_not_accessed": True,
            "holdout_outcomes_not_accessed": True,
        },
    }
    validation["validation_hash"] = canonical_hash(validation)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite validation: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(output, validation)
    print(
        json.dumps(
            {
                "stage": "V2_M6_PREOPEN_MANIFEST_VALIDATED",
                "result": validation["result"],
                "research_manifest_hash": research_hash,
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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--research-manifest",
        default=("research_manifests/gold_casebook_discovery_v2_m6_holdout_v01.json"),
    )
    parser.add_argument(
        "--output",
        default=(
            "research_artifacts/gold_casebook_discovery_v2_m6_preopen_manifest_validation.json"
        ),
    )
    return parser


def _verify_sources(research: Mapping[str, Any]) -> None:
    for item in research["verified_sources"]:
        path = Path(str(item["path"]))
        if not path.is_file() or _sha256(path) != item["sha256"]:
            raise ValueError(f"M6 source file hash mismatch: {path}")


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
