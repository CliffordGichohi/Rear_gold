"""Technical-only diagnosis of fixed-H1 control reproduction tolerance."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import regress_gold_coherent_auction_frozen_policy_exposed_v1 as subject  # noqa: E402


def main() -> int:
    base = json.loads(subject.BASE_RESULT.read_text(encoding="utf-8"))
    comparison = json.loads(subject.COMPARISON.read_text(encoding="utf-8"))
    humans = {
        row["case_alias"]: row["human"]
        for row in comparison["cases"]
        if row["human"]["is_trade"]
    }
    failures = []
    for case in base["cases"]:
        stream = subject.load_stream(case["source"])
        recomputed = subject.round_floats(
            subject.recompute_control(case, stream, humans[case["case_alias"]])
        )
        sealed = case["h1_fixed_control"]
        r_delta = abs(float(recomputed["net_r50"]) - float(sealed["net_r50"]))
        usd_delta = abs(float(recomputed["net_usd"]) - float(sealed["net_usd"]))
        if (
            recomputed["resolution"] != sealed["resolution"]
            or r_delta > 1e-8
            or usd_delta > 1e-8
        ):
            failures.append(
                {
                    "case_alias": case["case_alias"],
                    "resolution_equal": recomputed["resolution"] == sealed["resolution"],
                    "absolute_r_delta": r_delta,
                    "absolute_usd_delta": usd_delta,
                    "within_1e_minus_6": r_delta <= 1e-6 and usd_delta <= 1e-6,
                }
            )
    print(
        json.dumps(
            {
                "status": "CONTROL_TOLERANCE_DIAGNOSIS",
                "failure_count_at_1e_minus_8": len(failures),
                "failures": failures,
                "market_prices_printed": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

