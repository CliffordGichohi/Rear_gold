#!/usr/bin/env python3
"""Apply the sealed confirmation-only H1 policy separately to Mar-May 2022."""

from __future__ import annotations

import csv
import gzip
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT / "tools")]

import materialize_gold_blind_discretionary_replay_v1 as replay_source  # noqa: E402
import run_gold_february_h1_confirmation_only_reclaim_v1 as feb  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import require, sha256_file  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    confirmed_swings,
    iso,
    parse_dt,
)

SPEC = ROOT / "GOLD_MARCH_APRIL_MAY_2022_H1_CONFIRMATION_ONLY_RECLAIM_APPLICATION_V1.md"
CASEBOOK = ROOT / "research_artifacts/gold_casebook_v01/price_bars.jsonl.gz"
CASEBOOK_MANIFEST = ROOT / "research_artifacts/gold_casebook_v01/manifest.json"
JAN_RESULT = ROOT / "research_artifacts/gold_january_h1_confirmation_only_reclaim_v2/result.json"
JAN_MANIFEST = ROOT / "research_artifacts/gold_january_h1_confirmation_only_reclaim_v2/manifest.json"
FEB_RESULT = ROOT / "research_artifacts/gold_february_h1_confirmation_only_reclaim_v1/result.json"
FEB_MANIFEST = ROOT / "research_artifacts/gold_february_h1_confirmation_only_reclaim_v1/manifest.json"
OUT = ROOT / "research_artifacts/gold_mar_apr_may_h1_confirmation_only_reclaim_v1"
SOURCE_CERT = OUT / "source_and_predecessor_certification.json"
ROOT_MANIFEST = OUT / "manifest.json"

HISTORY_START = parse_dt("2021-07-23T00:00:00Z")
JAN_START = parse_dt("2022-01-01T00:00:00Z")
FEB_START = parse_dt("2022-02-01T00:00:00Z")
MAR_START = parse_dt("2022-03-01T00:00:00Z")
APR_START = parse_dt("2022-04-01T00:00:00Z")
MAY_START = parse_dt("2022-05-01T00:00:00Z")
JUN_START = parse_dt("2022-06-01T00:00:00Z")
FINAL_CUTOFF = parse_dt("2022-06-03T00:00:00Z")
GOOD_FRIDAY = date(2022, 4, 15)
REQUIRED_TIMEFRAMES = ("1m", "5m", "15m", "1h")
DISPLAY_TIMEFRAMES = ("1h", "15m", "5m")

MONTHS = (
    {"key": "march_2022", "label": "March 2022", "start": MAR_START, "end": APR_START, "cutoff": parse_dt("2022-04-03T00:00:00Z")},
    {"key": "april_2022", "label": "April 2022", "start": APR_START, "end": MAY_START, "cutoff": parse_dt("2022-05-03T00:00:00Z")},
    {"key": "may_2022", "label": "May 2022", "start": MAY_START, "end": JUN_START, "cutoff": FINAL_CUTOFF},
)


def verify_manifest_file(manifest_path: Path, required: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [
        row for row in manifest["files"]
        if (ROOT / str(row["path"])).resolve() == required.resolve()
    ]
    require(len(matches) == 1, f"Manifest binding absent or ambiguous: {required}")
    actual = sha256_file(required)
    require(actual == str(matches[0]["sha256"]), f"Manifest hash differs: {required}")
    return actual


def verify_sources() -> dict[str, str]:
    for path in (SPEC, CASEBOOK, CASEBOOK_MANIFEST, JAN_RESULT, JAN_MANIFEST, FEB_RESULT, FEB_MANIFEST):
        require(path.is_file(), f"Required source absent: {path}")
    casebook_manifest = json.loads(CASEBOOK_MANIFEST.read_text(encoding="utf-8"))
    matches = [row for row in casebook_manifest["artifacts"] if row["name"] == CASEBOOK.name]
    require(len(matches) == 1, "Casebook price source binding is ambiguous")
    casebook_sha = sha256_file(CASEBOOK)
    require(casebook_sha == str(matches[0]["sha256"]), "Casebook price source seal mismatch")
    jan_sha = verify_manifest_file(JAN_MANIFEST, JAN_RESULT)
    feb_sha = verify_manifest_file(FEB_MANIFEST, FEB_RESULT)
    jan = json.loads(JAN_RESULT.read_text(encoding="utf-8"))
    prior = json.loads(FEB_RESULT.read_text(encoding="utf-8"))
    require(jan["primary_reference_exact"] is True, "January predecessor did not reproduce")
    require(prior["primary_reference_exact"] is True, "February predecessor did not reproduce")
    require(prior["january_semantic_equivalence_exact"] is True, "February predecessor did not reproduce January")
    return {
        "casebook_sha256": casebook_sha,
        "casebook_manifest_sha256": sha256_file(CASEBOOK_MANIFEST),
        "january_result_sha256": jan_sha,
        "january_manifest_sha256": sha256_file(JAN_MANIFEST),
        "february_result_sha256": feb_sha,
        "february_manifest_sha256": sha256_file(FEB_MANIFEST),
    }


def expected_trading_dates(start, end) -> set[date]:
    current = start.date()
    expected: set[date] = set()
    while current < end.date():
        if current.weekday() < 5 and current != GOOD_FRIDAY:
            expected.add(current)
        current += timedelta(days=1)
    return expected


def load_casebook(
    parser: Callable[[str], dict[str, Any]]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    rows: dict[str, list[dict[str, Any]]] = {timeframe: [] for timeframe in REQUIRED_TIMEFRAMES}
    with gzip.open(CASEBOOK, "rt", encoding="utf-8") as handle:
        for line in handle:
            parsed = parser(line)
            timeframe = str(parsed["timeframe"])
            if timeframe not in rows or not bool(parsed["complete"]):
                continue
            opened = parse_dt(str(parsed["open_time"]))
            available = parse_dt(str(parsed["available_at"]))
            if timeframe in {"5m", "1h"}:
                include = opened >= HISTORY_START and available <= FINAL_CUTOFF
            elif timeframe == "1m":
                include = opened >= JAN_START and available <= JUN_START
            else:
                include = opened >= MAR_START and available <= JUN_START
            if include:
                rows[timeframe].append(feb.canonical_bar(parsed))

    diagnostics: dict[str, Any] = {"timeframes": {}, "months": {}}
    for timeframe, values in rows.items():
        values.sort(key=lambda row: (parse_dt(str(row["open_at"])), parse_dt(str(row["available_at"]))))
        require(values, f"No selected casebook rows for {timeframe}")
        identities = [(str(row["open_at"]), str(row["available_at"])) for row in values]
        require(len(identities) == len(set(identities)), f"Duplicate selected {timeframe} bars")
        diagnostics["timeframes"][timeframe] = {
            "rows": len(values),
            "first_open_at": str(values[0]["open_at"]),
            "last_available_at": str(values[-1]["available_at"]),
            "rows_sha256": canonical_hash(values),
        }

    for month in MONTHS:
        selected = [
            row for row in rows["1m"]
            if month["start"] <= parse_dt(str(row["open_at"])) < month["end"]
            and parse_dt(str(row["available_at"])) <= month["end"]
        ]
        require(selected, f"No M1 rows for {month['label']}")
        observed = {parse_dt(str(row["open_at"])).date() for row in selected}
        expected = expected_trading_dates(month["start"], month["end"])
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        require(not missing, f"Missing expected trading dates for {month['label']}: {missing}")
        require(not unexpected, f"Unexpected trading dates for {month['label']}: {unexpected}")
        daily_counts = Counter(parse_dt(str(row["open_at"])).date().isoformat() for row in selected)
        require(min(daily_counts.values()) >= 1_000, f"Insufficient observed quote path for {month['label']}")
        diagnostics["months"][month["key"]] = {
            "m1_rows": len(selected),
            "trading_dates": len(observed),
            "expected_dates": len(expected),
            "first_open_at": str(selected[0]["open_at"]),
            "last_open_at": str(selected[-1]["open_at"]),
            "minimum_daily_rows": min(daily_counts.values()),
            "closed_intervals_imputed": False,
            "rows_sha256": canonical_hash(selected),
        }
    return rows, diagnostics


def apply_policy(
    trades: Sequence[Mapping[str, Any]],
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    end,
) -> list[dict[str, Any]]:
    m1_rows = list(rows["1m"])
    h1_rows = list(rows["1h"])
    m5_rows = list(rows["5m"])
    cutoff = end + timedelta(days=2)
    _, m5_swings = confirmed_swings(
        [row for row in m5_rows if parse_dt(str(row["open_at"])) < cutoff], cutoff, "M5"
    )
    ledger: list[dict[str, Any]] = []
    for trade in sorted(trades, key=lambda row: (parse_dt(str(row["decision_at"])), str(row["trade_identity"]))):
        direction = str(trade["direction"])
        decision = parse_dt(str(trade["decision_at"]))
        boundary_at = parse_dt(str(trade["resolution_at"]))
        swing = float(trade["stop"])
        target = float(trade["target"])
        control = feb.latest_control(m5_swings, decision, direction)
        confirmation = (
            feb.first_confirmation(
                m5_rows,
                after=decision,
                through=boundary_at,
                direction=direction,
                control_level=float(control["level"]),
            )
            if control is not None else None
        )
        entry_row = (
            feb.first_m1_at_or_after(m1_rows, parse_dt(str(confirmation["available_at"])), end=end)
            if confirmation is not None else None
        )
        initial_valid = bool(
            entry_row is not None
            and parse_dt(str(entry_row["open_at"])) <= boundary_at
            and feb.valid_geometry(float(entry_row["open"]), swing, target, direction)
        )
        executed = False
        route = ""
        entry_at: str | None = None
        entry_price: float | None = None
        filled_stop: float | None = None
        resolution_at: str | None = None
        outcome: str | None = None
        net_r = 0.0
        if initial_valid:
            executed = True
            entry_time = parse_dt(str(entry_row["open_at"]))
            entry_price = float(entry_row["open"])
            entry_at = iso(entry_time)
            filled_stop = swing
            resolved = feb.resolve_path(
                m1_rows,
                entry_at=entry_time,
                entry=entry_price,
                stop=swing,
                target=target,
                direction=direction,
                end=end,
            )
            outcome, resolution_at, net_r = str(resolved["outcome"]), str(resolved["at"]), float(resolved["raw_r"])
            route = f"INITIAL_CONFIRMATION_{outcome}"
        elif str(trade["outcome"]) == "TARGET":
            route = "NO_TRADE_TARGET_BEFORE_CONFIRMATION" if confirmation is None else "NO_TRADE_INITIAL_GEOMETRY_INVALID"
        elif str(trade["outcome"]).startswith("STOP"):
            later_target_at = feb.first_target_after(
                m1_rows, after=boundary_at, direction=direction, target=target, end=end
            )
            h1_review = feb.first_h1_after(h1_rows, boundary_at, end=end)
            if h1_review is None:
                route = "NO_TRADE_NO_H1_REVIEW"
            else:
                review_time = parse_dt(str(h1_review["available_at"]))
                if later_target_at is not None and later_target_at < review_time:
                    route = "NO_TRADE_TARGET_BEFORE_H1_REVIEW"
                elif feb.h1_breached(float(h1_review["close"]), swing, direction):
                    route = "NO_TRADE_H1_CLOSE_INVALIDATED"
                else:
                    recovery_control = feb.latest_control(m5_swings, review_time, direction)
                    next_breach_at = feb.first_h1_breach_after(
                        h1_rows, after=review_time, swing=swing, direction=direction, end=end
                    )
                    cancellation_points = [end]
                    if later_target_at is not None:
                        cancellation_points.append(later_target_at)
                    if next_breach_at is not None:
                        cancellation_points.append(next_breach_at)
                    deadline = min(cancellation_points)
                    recovery_confirmation = (
                        feb.first_confirmation(
                            m5_rows,
                            after=review_time,
                            through=deadline,
                            direction=direction,
                            control_level=float(recovery_control["level"]),
                            required_valid_side=swing,
                        )
                        if recovery_control is not None else None
                    )
                    if recovery_confirmation is not None and not feb.confirmation_precedes_h1_breach(
                        parse_dt(str(recovery_confirmation["available_at"])), next_breach_at
                    ):
                        recovery_confirmation = None
                    if recovery_control is None:
                        route = "NO_TRADE_NO_RECLAIM_CONTROL"
                    elif recovery_confirmation is None:
                        if later_target_at is not None and later_target_at <= deadline:
                            route = "NO_TRADE_TARGET_BEFORE_RECLAIM"
                        elif next_breach_at is not None and next_breach_at <= deadline:
                            route = "NO_TRADE_LATER_H1_INVALIDATED"
                        else:
                            route = "NO_TRADE_NO_RECLAIM_CONFIRMATION"
                    else:
                        confirmation_time = parse_dt(str(recovery_confirmation["available_at"]))
                        reclaim_entry_row = feb.first_m1_at_or_after(m1_rows, confirmation_time, end=end)
                        require(reclaim_entry_row is not None, f"No reclaim M1 entry: {trade['trade_identity']}")
                        excursion = [
                            row for row in m1_rows
                            if row.get("complete") is True
                            and parse_dt(str(row["open_at"])) >= boundary_at
                            and parse_dt(str(row["available_at"])) <= confirmation_time
                        ]
                        require(excursion, f"No reclaim excursion: {trade['trade_identity']}")
                        reclaim_stop = (
                            min(float(row["low"]) for row in excursion) - feb.RECOVERY_BUFFER
                            if direction == "LONG"
                            else max(float(row["high"]) for row in excursion) + feb.RECOVERY_BUFFER
                        )
                        reclaim_entry = float(reclaim_entry_row["open"])
                        if not feb.valid_geometry(reclaim_entry, reclaim_stop, target, direction):
                            route = "NO_TRADE_RECLAIM_GEOMETRY_INVALID"
                        else:
                            executed = True
                            entry_time = parse_dt(str(reclaim_entry_row["open_at"]))
                            entry_at, entry_price, filled_stop = iso(entry_time), reclaim_entry, reclaim_stop
                            resolved = feb.resolve_path(
                                m1_rows,
                                entry_at=entry_time,
                                entry=reclaim_entry,
                                stop=reclaim_stop,
                                target=target,
                                direction=direction,
                                end=end,
                            )
                            outcome, resolution_at, net_r = (
                                str(resolved["outcome"]), str(resolved["at"]), float(resolved["raw_r"])
                            )
                            route = f"RECLAIM_CONFIRMATION_{outcome}"
        else:
            route = "NO_TRADE_MONTH_END_WITHOUT_CONFIRMATION" if confirmation is None else "NO_TRADE_INITIAL_GEOMETRY_INVALID"
        require(not executed or net_r >= -1.0000000001, f"Risk cap breached: {trade['trade_identity']}")
        ledger.append({
            "trade_identity": str(trade["trade_identity"]),
            "pivot_at": str(trade["pivot_at"]),
            "decision_at": str(trade["decision_at"]),
            "direction": direction,
            "control_outcome": str(trade["outcome"]),
            "control_r": float(trade["realized_r"]),
            "executed": executed,
            "route": route,
            "entry_at": entry_at,
            "entry_price": entry_price,
            "stop": filled_stop,
            "target": target,
            "outcome": outcome,
            "resolution_at": resolution_at,
            "net_r": net_r,
            "evidence_segment": "EXPOSED_HISTORICAL_REGRESSION",
        })
    return ledger


def compare_sealed(
    generated_population: Mapping[str, Any],
    generated_ledger: Sequence[Mapping[str, Any]],
    sealed: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    sealed_by_id = {str(row["trade_identity"]): row for row in sealed["case_ledger"]}
    generated_by_id = {str(row["trade_identity"]): row for row in generated_ledger}
    require(set(sealed_by_id) == set(generated_by_id), f"{label} identities differ")
    failures = []
    for identity, row in generated_by_id.items():
        reference = sealed_by_id[identity]
        expected_stop = reference.get("filled_stop", reference.get("stop"))
        comparisons = (
            row["route"] == reference["route"],
            row["executed"] == reference["executed"],
            row["entry_at"] == reference["entry_at"],
            row["stop"] == expected_stop,
            row["outcome"] == reference["outcome"],
            row["resolution_at"] == reference["resolution_at"],
            row["net_r"] == reference["net_r"],
        )
        if not all(comparisons):
            failures.append(identity)
    require(not failures, f"{label} semantic equivalence failed for {len(failures)} cases")
    return {
        "label": label,
        "population": len(generated_population["trades"]),
        "ledger_rows": len(generated_ledger),
        "mismatches": 0,
        "exact": True,
    }


def compact_bars(rows: Sequence[Mapping[str, Any]], timeframe: str, start, end) -> list[list[float | int]]:
    return [
        [
            int(parse_dt(str(row["open_at"])).timestamp()),
            round(float(row["open"]), 4),
            round(float(row["high"]), 4),
            round(float(row["low"]), 4),
            round(float(row["close"]), 4),
        ]
        for row in rows
        if str(row["timeframe"]) == timeframe
        and start <= parse_dt(str(row["open_at"])) < end
        and parse_dt(str(row["available_at"])) <= end
    ]


def evaluate_month(rows: Mapping[str, Sequence[Mapping[str, Any]]], month: Mapping[str, Any]) -> dict[str, Any]:
    population = feb.build_population(rows, start=month["start"], end=month["end"], cutoff=month["cutoff"])
    ledger = apply_policy(population["trades"], rows, end=month["end"])
    control_rows = [{"executed": True, "net_r": row["realized_r"]} for row in population["trades"]]
    return {
        "population": {key: value for key, value in population.items() if key != "trades"},
        "control_metrics": feb.execution_metrics(control_rows),
        "v2_metrics": feb.execution_metrics(ledger),
        "route_counts": dict(sorted(Counter(str(row["route"]) for row in ledger).items())),
        "case_ledger": ledger,
        "chart_bars": {
            "H1": compact_bars(rows["1h"], "1h", month["start"], month["end"]),
            "M15": compact_bars(rows["15m"], "15m", month["start"], month["end"]),
            "M5": compact_bars(rows["5m"], "5m", month["start"], month["end"]),
        },
    }


def run_side(parser: Callable[[str], dict[str, Any]], jan: Mapping[str, Any], prior_feb: Mapping[str, Any]) -> dict[str, Any]:
    rows, diagnostics = load_casebook(parser)
    jan_population = feb.build_population(rows, start=JAN_START, end=FEB_START, cutoff=FEB_START)
    jan_ledger = apply_policy(jan_population["trades"], rows, end=FEB_START)
    jan_equivalence = compare_sealed(jan_population, jan_ledger, jan, label="JANUARY_V2")
    feb_population = feb.build_population(rows, start=FEB_START, end=MAR_START, cutoff=parse_dt("2022-03-03T00:00:00Z"))
    feb_ledger = apply_policy(feb_population["trades"], rows, end=MAR_START)
    feb_equivalence = compare_sealed(feb_population, feb_ledger, prior_feb, label="FEBRUARY_APPLICATION")
    return {
        "source_diagnostics": diagnostics,
        "predecessor_equivalence": {"january": jan_equivalence, "february": feb_equivalence},
        "months": {month["key"]: evaluate_month(rows, month) for month in MONTHS},
    }


def write_month(month: Mapping[str, Any], payload: Mapping[str, Any], bindings: Mapping[str, str]) -> Path:
    month_out = OUT / str(month["key"])
    month_out.mkdir(parents=True, exist_ok=True)
    result_path = month_out / "result.json"
    ledger_path = month_out / "case_ledger.csv"
    chart_path = month_out / "chart_data.json"
    report_path = month_out / "report.md"
    manifest_path = month_out / "manifest.json"

    result = {
        "version": f"GOLD_{str(month['key']).upper()}_H1_CONFIRMATION_ONLY_RECLAIM_APPLICATION_V1",
        "verdict": "COMPLETED_UNCHANGED_MONTHLY_APPLICATION",
        "evidence_status": "EXPOSED_HISTORICAL_REGRESSION_NOT_INDEPENDENT_VALIDATION",
        "period": {"start": iso(month["start"]), "end_exclusive": iso(month["end"])},
        "population": payload["population"],
        "control_metrics": payload["control_metrics"],
        "v2_metrics": payload["v2_metrics"],
        "route_counts": payload["route_counts"],
        "case_ledger": payload["case_ledger"],
        "policy_retuned": False,
        "primary_reference_exact": True,
        "january_and_february_semantic_equivalence_exact": True,
    }
    result["result_sha256"] = canonical_hash(result)
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    with ledger_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result["case_ledger"][0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(result["case_ledger"])

    chart_trades = []
    for index, row in enumerate((item for item in result["case_ledger"] if item["executed"]), start=1):
        chart_trades.append({
            "number": index,
            "tradeIdentity": row["trade_identity"],
            "decision": int(parse_dt(str(row["decision_at"])).timestamp()),
            "entryTime": int(parse_dt(str(row["entry_at"])).timestamp()),
            "resolution": int(parse_dt(str(row["resolution_at"])).timestamp()),
            "direction": row["direction"],
            "route": row["route"],
            "outcome": row["outcome"],
            "entry": round(float(row["entry_price"]), 4),
            "stop": round(float(row["stop"]), 4),
            "target": round(float(row["target"]), 4),
            "netR": round(float(row["net_r"]), 6),
            "evidenceSegment": row["evidence_segment"],
        })
    chart = {
        "version": f"GOLD_{str(month['key']).upper()}_H1_CONFIRMATION_ONLY_CONTINUOUS_CHART_DATA_V1",
        "period": result["period"],
        "month_label": month["label"],
        "bars": payload["chart_bars"],
        "trades": chart_trades,
        "summary": result["v2_metrics"],
    }
    chart["dataSha256"] = canonical_hash(chart)
    chart_path.write_text(json.dumps(chart, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8", newline="\n")

    control = result["control_metrics"]
    v2 = result["v2_metrics"]
    report = [
        f"# {month['label']} confirmation-only V2 application",
        "",
        f"**Verdict:** `{result['verdict']}`",
        "",
        "This is exposed historical regression evidence. The January V2 policy was applied unchanged.",
        "",
        "| Policy | Setups | Trades | No trade | Win rate | Net R | PF | Expectancy/trade | Max DD | $50/R | $100/R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| Original control | {control['setups']} | {control['executed_trades']} | {control['no_trade_setups']} | {100*control['trade_win_rate']:.1f}% | {control['net_r']:+.2f} | {control['profit_factor']:.3f} | {control['expectancy_per_trade_r']:+.3f} | {control['maximum_drawdown_r']:.2f} | {control['net_r']*50:+.2f} | {control['net_r']*100:+.2f} |",
        f"| Confirmation-only V2 | {v2['setups']} | {v2['executed_trades']} | {v2['no_trade_setups']} | {100*v2['trade_win_rate']:.1f}% | {v2['net_r']:+.2f} | {v2['profit_factor']:.3f} | {v2['expectancy_per_trade_r']:+.3f} | {v2['maximum_drawdown_r']:.2f} | {v2['net_r']*50:+.2f} | {v2['net_r']*100:+.2f} |",
        "",
        "## Route counts",
        "",
        *[f"- `{name}`: {count}" for name, count in result["route_counts"].items()],
        "",
        "All values are gross before costs and overlap controls, matching the frozen predecessor semantics.",
    ]
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    sealed = (result_path, ledger_path, chart_path, report_path)
    manifest = {
        "version": f"GOLD_{str(month['key']).upper()}_H1_CONFIRMATION_ONLY_RECLAIM_APPLICATION_V1_MANIFEST",
        "verdict": result["verdict"],
        "result_sha256": result["result_sha256"],
        "policy_retuned": False,
        "primary_reference_exact": True,
        "predecessor_equivalence_exact": True,
        "source_bindings": dict(bindings),
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sealed
        ],
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return manifest_path


def main() -> None:
    bindings = verify_sources()
    jan = json.loads(JAN_RESULT.read_text(encoding="utf-8"))
    prior_feb = json.loads(FEB_RESULT.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    primary = run_side(replay_source.parse_price_primary, jan, prior_feb)
    reference = run_side(replay_source.parse_price_reference, jan, prior_feb)
    require(primary == reference, "Primary/reference March-May application differs")

    source_cert = {
        "version": "GOLD_MARCH_APRIL_MAY_H1_CONFIRMATION_ONLY_SOURCE_CERTIFICATION_V1",
        "verdict": "PASS_PRIMARY_REFERENCE_AND_PREDECESSOR_EQUIVALENCE",
        "bindings": bindings,
        "source_diagnostics": primary["source_diagnostics"],
        "predecessor_equivalence": primary["predecessor_equivalence"],
        "primary_reference_exact": True,
    }
    source_cert["certification_sha256"] = canonical_hash(source_cert)
    SOURCE_CERT.write_text(json.dumps(source_cert, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    month_manifests = [write_month(month, primary["months"][month["key"]], bindings) for month in MONTHS]
    sealed = (SPEC, Path(__file__).resolve(), CASEBOOK_MANIFEST, JAN_MANIFEST, FEB_MANIFEST, SOURCE_CERT, *month_manifests)
    manifest = {
        "version": "GOLD_MARCH_APRIL_MAY_H1_CONFIRMATION_ONLY_RECLAIM_APPLICATION_V1_MANIFEST",
        "verdict": "PASS_THREE_SEPARATE_UNCHANGED_MONTHLY_APPLICATIONS",
        "pooled_performance_reported": False,
        "policy_retuned": False,
        "primary_reference_exact": True,
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sealed
        ],
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    ROOT_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    for month in MONTHS:
        metrics = primary["months"][month["key"]]["v2_metrics"]
        print(json.dumps({"month": month["label"], "verdict": "COMPLETED_UNCHANGED_MONTHLY_APPLICATION", **metrics}, indent=2))


if __name__ == "__main__":
    main()
