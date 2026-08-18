from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash
from gold_intel.backtesting.casebook_discovery_v2_holdout import (
    EXPECTED_ZN_QUOTE_REQUEST,
    M6_QUOTE_SCHEMA_VERSION,
    M6_QUOTE_VERSION,
    quote_request_fingerprint,
    validate_quote_manifest,
)


def main() -> None:
    args = _parser().parse_args()
    research_path = Path(args.research_manifest)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite immutable M6 quote bundle: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    research = _load_json(research_path)
    research_hash = validate_quote_manifest(research)
    _verify_source_hashes(research)
    key = _api_key(Path(args.env_file))
    client, sdk_version = _databento_client(key)
    estimated_cost = _metadata_cost(client, EXPECTED_ZN_QUOTE_REQUEST)

    observed_at = datetime.now(UTC).isoformat()
    quote: dict[str, Any] = {
        "quote_version": M6_QUOTE_VERSION,
        "schema_version": M6_QUOTE_SCHEMA_VERSION,
        "milestone": "V2_M6_PREOPEN_ZN_COST_ESTIMATE",
        "status": "QUOTED_AWAITING_PAID_DOWNLOAD_AUTHORIZATION",
        "research_manifest_hash": research_hash,
        "request": EXPECTED_ZN_QUOTE_REQUEST,
        "request_fingerprint": quote_request_fingerprint(),
        "provider_observation": {
            "provider": "DATABENTO",
            "endpoint": "Historical.metadata.get_cost",
            "classification": "OBSERVED",
            "estimated_cost_usd": estimated_cost,
            "observed_at": observed_at,
            "sdk_version": sdk_version,
            "quote_expiry": "NOT_PROVIDED_BY_ENDPOINT",
        },
        "guardrails": {
            "api_key_recorded": False,
            "batch_job_submitted": False,
            "paid_download_started": False,
            "market_values_accessed": False,
            "holdout_features_calculated": False,
            "holdout_outcomes_accessed": False,
            "calendar_2026_values_accessed": False,
        },
        "next_action": {
            "authorized": False,
            "requires_user_approval": True,
            "action": "SUBMIT_PAID_DATABENTO_BATCH_JOB_WITH_EXPLICIT_COST_CAP",
        },
    }
    quote["quote_hash"] = canonical_hash(quote)

    with tempfile.TemporaryDirectory(
        dir=output.parent,
        prefix=f".{output.name}.staging-",
    ) as temporary:
        staging = Path(temporary)
        quote_path = staging / "quote.json"
        _write_json(quote_path, quote)
        bundle: dict[str, Any] = {
            "quote_version": M6_QUOTE_VERSION,
            "schema_version": M6_QUOTE_SCHEMA_VERSION,
            "milestone": "V2_M6_PREOPEN_ZN_COST_ESTIMATE",
            "status": quote["status"],
            "source": {
                "research_manifest_hash": research_hash,
                "shortlist_bundle_hash": research["source"]["shortlist_bundle_hash"],
                "shortlist_hash": research["source"]["shortlist_hash"],
            },
            "artifacts": [
                {
                    "path": "quote.json",
                    "sha256": _sha256(quote_path),
                    "bytes": quote_path.stat().st_size,
                    "document_hash": quote["quote_hash"],
                }
            ],
            "integrity": {
                "metadata_endpoint_calls": 1,
                "batch_job_submitted": False,
                "paid_download_started": False,
                "market_values_accessed": False,
                "holdout_outcomes_accessed": False,
            },
        }
        bundle["manifest_hash"] = canonical_hash(bundle)
        _write_json(staging / "manifest.json", bundle)
        staging.rename(output)

    print(
        json.dumps(
            {
                "stage": "V2_M6_ZN_COST_ESTIMATE_COMPLETE",
                "estimated_cost_usd": estimated_cost,
                "quote_hash": quote["quote_hash"],
                "bundle_manifest_hash": bundle["manifest_hash"],
                "paid_submission_authorized": False,
                "batch_job_submitted": False,
                "market_values_accessed": False,
                "holdout_outcomes_accessed": False,
                "output": str(output),
            },
            sort_keys=True,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Obtain a cost-only Databento metadata quote for the frozen "
            "calendar-2025 ZN source. This utility cannot submit or download a job."
        )
    )
    parser.add_argument(
        "--research-manifest",
        default="research_manifests/gold_casebook_discovery_v2_m6_zn_quote_v01.json",
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument(
        "--output",
        default="research_artifacts/gold_casebook_discovery_v2_m6_zn_quote_v01",
    )
    return parser


def _api_key(env_file: Path) -> str:
    existing = os.getenv("DATABENTO_API_KEY", "").strip()
    if existing:
        return existing
    if env_file.exists():
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "DATABENTO_API_KEY":
                key = value.strip().strip("\"'")
                if key:
                    return key
    raise RuntimeError("DATABENTO_API_KEY is missing")


def _databento_client(key: str) -> tuple[Any, str]:
    try:
        import databento as db
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "The Databento SDK is required for the cost-only metadata request"
        ) from exc
    return db.Historical(key), str(getattr(db, "__version__", "UNKNOWN"))


def _metadata_cost(client: Any, request: Mapping[str, Any]) -> float:
    value = float(
        client.metadata.get_cost(
            dataset=request["dataset"],
            symbols=list(request["symbols"]),
            schema=request["schema"],
            stype_in=request["stype_in"],
            start=request["start"],
            end=request["end"],
        )
    )
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Databento returned an invalid cost estimate: {value!r}")
    return value


def _verify_source_hashes(research: Mapping[str, Any]) -> None:
    for source in research["verified_sources"]:
        path = Path(source["path"])
        if not path.is_file():
            raise FileNotFoundError(path)
        if _sha256(path) != source["sha256"]:
            raise ValueError(f"Source hash mismatch: {path}")


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
