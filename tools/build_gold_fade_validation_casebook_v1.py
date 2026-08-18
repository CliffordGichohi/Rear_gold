from __future__ import annotations

import gzip
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import run_gold_triple_macro_acceptance_fade_validation_v1 as validation  # noqa: E402


OUT = ROOT / "research_artifacts" / "gold_triple_macro_acceptance_fade_validation_v01"
RESULT = OUT / "validation_result.json"
STATE = OUT / "execution_state.json"
ANCHORS = OUT / "validation_anchors.jsonl.gz"
DESTINATION = OUT / "forward_casebook.json"
REPORT = OUT / "forward_casebook.md"


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def verify_sealed_result() -> dict[str, Any]:
    result = load_json(RESULT)
    state = load_json(STATE)
    if canonical_hash({key: value for key, value in result.items() if key != "result_hash"}) != result["result_hash"]:
        raise RuntimeError("Validation result seal failed")
    if canonical_hash({key: value for key, value in state.items() if key != "state_hash"}) != state["state_hash"]:
        raise RuntimeError("Validation state seal failed")
    if sha256(ANCHORS) != result["artifacts"]["anchors_sha256"]:
        raise RuntimeError("Validation anchor hash failed")
    return result


def eligible_anchors() -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    with gzip.open(ANCHORS, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["eligible"]:
                output.append(row)
    return sorted(output, key=lambda row: row["released_at"])


def component_details(timestamps: set[str]) -> dict[str, list[dict[str, Any]]]:
    backend_src = ROOT / "backend" / "src"
    if str(backend_src) not in sys.path:
        sys.path.insert(0, str(backend_src))
    from gold_intel.analytics.events import SURPRISE_SPEC_BY_CODE

    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in (validation.EVENTS_2025, validation.EVENTS_2026):
        for event in load_json(path)["events"]:
            released_raw = event.get("released_at")
            if not released_raw:
                continue
            timestamp = validation.iso(validation.parse_ts(released_raw))
            if timestamp not in timestamps:
                continue
            forecasts: dict[str, list[dict[str, Any]]] = defaultdict(list)
            released_at = validation.parse_ts(released_raw)
            for forecast in event.get("forecasts", []):
                if validation.parse_ts(forecast["available_at"]) <= released_at:
                    forecasts[str(forecast["component_code"])].append(forecast)
            for release in event.get("releases", []):
                component = str(release["component_code"])
                candidates = forecasts.get(component, [])
                specification = SURPRISE_SPEC_BY_CODE.get(component)
                if not candidates or specification is None:
                    continue
                forecast = max(
                    candidates,
                    key=lambda item: (
                        validation.parse_ts(item["available_at"]),
                        validation.parse_ts(item["forecast_as_of"]),
                    ),
                )
                actual = float(release["actual_value"])
                expected = float(forecast["forecast_value"])
                raw = actual - expected
                impulse = validation.sign(float(specification.gold_sign) * raw)
                output[timestamp].append(
                    {
                        "event_code": event["event_code"],
                        "event_family": event["event_type"],
                        "component_code": component,
                        "actual": actual,
                        "forecast": expected,
                        "actual_minus_forecast": raw,
                        "unit": release["unit"],
                        "component_gold_impulse": impulse,
                    }
                )
    for rows in output.values():
        rows.sort(key=lambda row: (row["event_code"], row["component_code"]))
    return output


def delta(
    frame: pd.DataFrame,
    released: Any,
) -> tuple[float, float, float, int | None]:
    released_at = validation.parse_ts(str(released))
    reference = validation.lookup_frame(
        frame,
        validation.endpoint(released_at, 0),
        pd.Timestamp(released_at),
    )
    five = validation.lookup_frame(
        frame,
        validation.endpoint(released_at, 5),
        pd.Timestamp(released_at + validation.timedelta(minutes=5)),
    )
    if reference is None or five is None:
        raise RuntimeError(f"Sealed eligible case lost an endpoint at {released}")
    return reference[0], five[0], five[0] - reference[0], reference[1]


def main() -> None:
    if DESTINATION.exists() or REPORT.exists():
        raise FileExistsError("Forward casebook already exists")
    result = verify_sealed_result()
    anchors = eligible_anchors()
    components = component_details({row["released_at"] for row in anchors})

    xau2025, _ = validation.load_mt5("XAUUSD", validation.START_2025, validation.END_2025)
    xau2026, _ = validation.load_mt5("XAUUSD", validation.START_2026, validation.END_2026)
    eur2025, _ = validation.load_mt5("EURUSD", validation.START_2025, validation.END_2025)
    eur2026, _ = validation.load_mt5("EURUSD", validation.START_2026, validation.END_2026)
    sources = {
        "XAUUSD": pd.concat([xau2025, xau2026]).sort_index(),
        "EURUSD": pd.concat([eur2025, eur2026]).sort_index(),
        "ZT": validation.load_cme([validation.ZT_2025, validation.ZT_2026], "ZT.v.0"),
        "ZN": validation.load_cme([validation.ZN_2025, validation.ZN_2026], "ZN.v.0"),
    }

    cases: list[dict[str, Any]] = []
    for anchor in anchors:
        reactions: dict[str, Any] = {}
        for name, frame in sources.items():
            reference, five, change, instrument = delta(frame, anchor["released_at"])
            reactions[name] = {
                "reference_close": reference,
                "five_minute_close": five,
                "five_minute_change": change,
                "direction": validation.sign(change),
                "instrument_id": instrument,
            }
        case = {
            "case_id": anchor["anchor_id"],
            "released_at": anchor["released_at"],
            "year": anchor["year"],
            "event_families": anchor["event_families"],
            "event_codes": anchor["event_codes"],
            "macro_components": components[anchor["released_at"]],
            "F": anchor["F"],
            "M": anchor["M"],
            "G": anchor["G"],
            "five_minute_reactions": reactions,
            "frozen_prediction": anchor["prediction"],
            "prediction_label": "GOLD_UP_FADE" if anchor["prediction"] == 1 else "GOLD_DOWN_FADE",
            "gold_change_5_to_15_usd": anchor["outcome_15_displacement"],
            "gold_change_5_to_60_usd": anchor["outcome_60_displacement"],
            "hit_15_minute": anchor["prediction"] == anchor["outcome_15_sign"],
            "hit_60_minute": anchor["prediction"] == anchor["outcome_60_sign"],
        }
        case["case_hash"] = canonical_hash(case)
        cases.append(case)

    payload = {
        "version": "GOLD_TRIPLE_MACRO_ACCEPTANCE_FADE_FORWARD_CASEBOOK_V0_1",
        "status": "DESCRIPTIVE_PROJECTION_OF_SEALED_VALIDATION_ONLY",
        "candidate": result["candidate"],
        "validation_result_hash": result["result_hash"],
        "case_count": len(cases),
        "case_count_by_year": {
            str(year): sum(case["year"] == year for case in cases)
            for year in (2025, 2026)
        },
        "cases": cases,
        "restrictions": {
            "new_hypothesis_created": False,
            "candidate_retuned": False,
            "new_statistical_test_run": False,
            "execution_or_pnl_calculated": False,
        },
    }
    payload["casebook_hash"] = canonical_hash(payload)
    DESTINATION.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    REPORT.write_text(render_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": payload["status"],
                "case_count": payload["case_count"],
                "case_count_by_year": payload["case_count_by_year"],
                "casebook_hash": payload["casebook_hash"],
                "json_sha256": sha256(DESTINATION),
                "report_sha256": sha256(REPORT),
            },
            indent=2,
            sort_keys=True,
        )
    )


def fmt(value: float) -> str:
    return f"{value:+.6g}"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Gold Triple Macro-Acceptance Fade Forward Casebook V1",
        "",
        "This is a descriptive projection of the already sealed validation. It does not change the candidate or add a test.",
        "",
        "| Release UTC | Events | Macro actual vs forecast | First 5m: ZT / ZN / EURUSD / Gold | Frozen fade | Gold +5→+15 | Result | Gold +5→+60 |",
        "|---|---|---|---|---|---:|---|---:|",
    ]
    for case in payload["cases"]:
        macro = "; ".join(
            f"{item['component_code']} {item['actual']:g} vs {item['forecast']:g} ({fmt(item['actual_minus_forecast'])})"
            for item in case["macro_components"]
        )
        reaction = case["five_minute_reactions"]
        first = " / ".join(
            [
                f"{fmt(reaction['ZT']['five_minute_change'])}",
                f"{fmt(reaction['ZN']['five_minute_change'])}",
                f"{fmt(10000 * reaction['EURUSD']['five_minute_change'])} pips",
                f"{fmt(reaction['XAUUSD']['five_minute_change'])} USD",
            ]
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    case["released_at"],
                    ", ".join(case["event_families"]),
                    macro,
                    first,
                    case["prediction_label"],
                    fmt(case["gold_change_5_to_15_usd"]),
                    "HIT" if case["hit_15_minute"] else "MISS",
                    fmt(case["gold_change_5_to_60_usd"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            f"Casebook hash: `{payload['casebook_hash']}`.",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
