from __future__ import annotations

import json
import math
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUESTS = (
    {
        "request_id": "ZT_2025",
        "dataset": "GLBX.MDP3",
        "symbols": ["ZT.v.0"],
        "schema": "ohlcv-1m",
        "stype_in": "continuous",
        "start": "2025-01-01T00:00:00Z",
        "end": "2026-01-01T00:00:00Z",
    },
    {
        "request_id": "ZT_ZN_2026_YTD",
        "dataset": "GLBX.MDP3",
        "symbols": ["ZT.v.0", "ZN.v.0"],
        "schema": "ohlcv-1m",
        "stype_in": "continuous",
        "start": "2026-01-01T00:00:00Z",
        "end": "2026-07-30T00:00:00Z",
    },
)


def api_key() -> str:
    existing = os.getenv("DATABENTO_API_KEY", "").strip()
    if existing:
        return existing
    path = ROOT / ".env"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABENTO_API_KEY="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value:
                return value
    raise RuntimeError("DATABENTO_API_KEY is unavailable")


def main() -> None:
    import databento as db

    client = db.Historical(api_key())
    estimates = []
    for request in REQUESTS:
        kwargs = {key: value for key, value in request.items() if key != "request_id"}
        cost = float(client.metadata.get_cost(**kwargs))
        count = int(client.metadata.get_record_count(**kwargs))
        size = int(client.metadata.get_billable_size(**kwargs))
        if not math.isfinite(cost) or cost < 0 or count <= 0 or size <= 0:
            raise RuntimeError(f"Invalid metadata response for {request['request_id']}")
        estimates.append(
            {
                "request_id": request["request_id"],
                "request": kwargs,
                "estimated_cost_usd": cost,
                "estimated_record_count": count,
                "estimated_billable_size": size,
            }
        )
    print(
        json.dumps(
            {
                "version": "GOLD_FADE_VALIDATION_SOURCE_QUOTE_V0_1",
                "sdk_version": str(db.__version__),
                "metadata_only": True,
                "jobs_submitted": 0,
                "downloads": 0,
                "charge_incurred_usd": 0.0,
                "requests": estimates,
                "combined_estimated_cost_usd": sum(row["estimated_cost_usd"] for row in estimates),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
