from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research_artifacts" / "gold_h4_half_retrace_final_falsification_v1"
MODEL_SEAL = OUTPUT / "pre_forward_model_seal.json"
RAW = OUTPUT / "cftc_gold_cot_forward_source.json"
SEAL = OUTPUT / "cftc_gold_cot_forward_source_seal.json"
URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
CONTRACT_CODE = "088691"
START = "2024-12-25T00:00:00"
END = "2026-07-29T23:59:59"
FIELDS = (
    "id,market_and_exchange_names,report_date_as_yyyy_mm_dd,"
    "cftc_contract_market_code,open_interest_all,"
    "prod_merc_positions_long,prod_merc_positions_short,"
    "swap_positions_long_all,swap__positions_short_all,"
    "swap__positions_spread_all,m_money_positions_long_all,"
    "m_money_positions_short_all,m_money_positions_spread,"
    "other_rept_positions_long,other_rept_positions_short,"
    "other_rept_positions_spread,pct_of_oi_prod_merc_long,"
    "pct_of_oi_prod_merc_short,pct_of_oi_swap_long_all,"
    "pct_of_oi_swap_short_all,pct_of_oi_m_money_long_all,"
    "pct_of_oi_m_money_short_all,pct_of_oi_other_rept_long,"
    "pct_of_oi_other_rept_short,traders_prod_merc_long_all,"
    "traders_prod_merc_short_all,traders_swap_long_all,"
    "traders_swap_short_all,traders_m_money_long_all,"
    "traders_m_money_short_all,traders_other_rept_long_all,"
    "traders_other_rept_short"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    if RAW.exists() or SEAL.exists():
        raise FileExistsError("Forward COT source already acquired")
    model_seal = json.loads(MODEL_SEAL.read_text(encoding="utf-8"))
    if model_seal["status"] != "FROZEN_FULL_DEVELOPMENT_MODEL_BEFORE_FORWARD_VALUES" or model_seal["forward_values_accessed"] is not False:
        raise ValueError("Model was not sealed before forward predictor access")
    query = {
        "$select": FIELDS,
        "$where": (
            f"cftc_contract_market_code='{CONTRACT_CODE}' AND "
            f"report_date_as_yyyy_mm_dd between '{START}' and '{END}'"
        ),
        "$order": "report_date_as_yyyy_mm_dd asc",
        "$limit": "5000",
    }
    request_url = URL + "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(
        request_url,
        headers={"Accept": "application/json", "User-Agent": "Gold-Market-Intelligence-Engine/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
        status = response.status
        content_type = response.headers.get("Content-Type")
    if status != 200:
        raise RuntimeError(f"CFTC returned HTTP {status}")
    rows = json.loads(payload)
    if not isinstance(rows, list) or not rows:
        raise ValueError("CFTC returned no forward gold reports")
    if any(str(row.get("cftc_contract_market_code")) != CONTRACT_CODE for row in rows):
        raise ValueError("CFTC response contains another contract")
    dates = [str(row["report_date_as_yyyy_mm_dd"])[:10] for row in rows]
    if dates != sorted(dates) or len(dates) != len(set(dates)):
        raise ValueError("CFTC report dates are unordered or duplicated")
    write_exclusive(RAW, payload)
    seal = {
        "version": "GOLD_H4_HALF_RETRACE_FORWARD_COT_SOURCE_1_0",
        "status": "SEALED_OFFICIAL_PUBLIC_SOURCE",
        "sealed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "provider": "CFTC_PUBLIC",
        "dataset": "Disaggregated Futures Only",
        "endpoint": URL,
        "contract_market_code": CONTRACT_CODE,
        "query": query,
        "http_status": status,
        "content_type": content_type,
        "reports": len(rows),
        "first_observation_date": dates[0],
        "last_observation_date": dates[-1],
        "raw_source": record(RAW),
        "model_seal": record(MODEL_SEAL),
        "charge_usd": 0.0,
        "feature_or_threshold_changed": False,
        "outcomes_accessed": False,
    }
    write_exclusive(SEAL, (json.dumps(seal, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(json.dumps({"status": seal["status"], "reports": len(rows), "coverage": [dates[0], dates[-1]], "source": record(RAW), "charge_usd": 0.0}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
