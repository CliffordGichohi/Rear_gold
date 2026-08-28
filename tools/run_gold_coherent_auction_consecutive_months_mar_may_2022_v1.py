#!/usr/bin/env python3
"""Freeze and run the unchanged coherent-auction translator on Mar-May 2022."""

from __future__ import annotations

import argparse
import gc
import gzip
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import materialize_gold_annotated_replay_v3 as replay  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import require, sha256_file  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402
from run_gold_coherent_auction_end_to_end_v1_inference import summarize  # noqa: E402
from run_gold_coherent_auction_frozen_translator_unseen_block_v1 import (  # noqa: E402
    infer_streams,
)


CONTRACT = ROOT / "GOLD_COHERENT_AUCTION_CONSECUTIVE_MONTHS_MAR_MAY_2022_V1.md"
AMENDMENT = ROOT / "GOLD_COHERENT_AUCTION_CONSECUTIVE_MONTHS_MAR_MAY_2022_V1_AMENDMENT_A.md"
TRANSLATOR = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_end_to_end_same_month_v1"
    / "translator.json"
)
EXPOSED_CONTROL = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_end_to_end_same_month_v1"
    / "autonomous_result.json"
)
OUT = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_consecutive_months_mar_may_2022_v1"
)
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY_STREAM = OUT / "daily_streams.primary.jsonl.gz"
REFERENCE_STREAM = OUT / "daily_streams.reference.jsonl.gz"
PRIMARY_RESULT = OUT / "monthly_test.primary.json"
REFERENCE_RESULT = OUT / "monthly_test.reference.json"
FINAL_RESULT = OUT / "final_result.json"
FINAL_SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_COHERENT_AUCTION_CONSECUTIVE_MONTHS_MAR_MAY_2022_V1_REPORT.md"

TRANSLATOR_SHA256 = "c95e200194bece77ed435741202d1bacd4f267ab0f1d1ed7803dd9d4ebd30841"
EXPOSED_CONTROL_SHA256 = "c2ff398eaf3cb865191e85bace5542a79a9d23063fe51d164c4b31bc7979637d"
SOURCE_HASHES = {
    "research_artifacts/gold_casebook_v01/price_bars.jsonl.gz": "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e",
    "research_artifacts/gold_casebook_v01/fundamentals.jsonl.gz": "d2b776f60c4535978bbfb28706b4700e6d054a10f8d57cfee171c83b212b7235",
    "research_artifacts/gold_casebook_v01/structure_snapshots.jsonl.gz": "31eea2decc8ed3f8d3e498a9339e7f59ee101e7c787da47a831e63bfb97c1064",
    "research_artifacts/gold_casebook_v01/cross_market_snapshots.jsonl.gz": "470a2e1c020cd2f97f2ad5b0d7f9c5220aff4f644689c4d680c24373964eb285",
    "research_artifacts/gold_casebook_v01/positioning.jsonl.gz": "e6d1aabf0d4401f3af4e54dc8ef4c0e4074772ec3f2199cfe9009b5a0b267228",
    "research_artifacts/gold_casebook_v01/events.jsonl.gz": "c7875e09d9ed831ece0f223b8be5efb75550af5bf1996a2dfea9d6119b24e35f",
    "research_artifacts/gold_casebook_v01/sessions.jsonl.gz": "2695a2c0b9e8f41fcbf64c9f388e8883ebf7e1f0b3b09b90fb3a60ba7e64966a",
}

START = date(2022, 3, 1)
END_EXCLUSIVE = date(2022, 6, 1)
DOCUMENTED_CLOSURES = {date(2022, 4, 15): "GOOD_FRIDAY"}
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical_dates() -> list[date]:
    current = START
    output: list[date] = []
    while current < END_EXCLUSIVE:
        if current.weekday() < 5 and current not in DOCUMENTED_CLOSURES:
            output.append(current)
        current += timedelta(days=1)
    return output


def write_new_json(path: Path, payload: dict[str, Any]) -> None:
    require(not path.exists(), f"Append-only output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def verify_static_inputs() -> None:
    require(CONTRACT.is_file(), "Contract is absent")
    require(AMENDMENT.is_file(), "Coverage Amendment A is absent")
    require(sha256_file(TRANSLATOR) == TRANSLATOR_SHA256, "Translator differs")
    require(
        sha256_file(EXPOSED_CONTROL) == EXPOSED_CONTROL_SHA256,
        "Exposed control differs",
    )
    for relative, expected in SOURCE_HASHES.items():
        path = ROOT / relative
        require(path.is_file(), f"Frozen source absent: {relative}")
        require(sha256_file(path) == expected, f"Frozen source differs: {relative}")


def freeze() -> None:
    require(not FREEZE.exists(), "Prevalue freeze already exists")
    verify_static_inputs()
    dates = canonical_dates()
    counts = Counter(day.strftime("%Y-%m") for day in dates)
    require(counts == {"2022-03": 23, "2022-04": 20, "2022-05": 22}, "Date population differs")
    payload: dict[str, Any] = {
        "version": "GOLD_COHERENT_AUCTION_CONSECUTIVE_MONTHS_MAR_MAY_2022_V1_FREEZE_1_0",
        "sealed_at": now(),
        "status": "SEALED_BEFORE_MARCH_MAY_2022_OUTCOME_OPEN",
        "contract": file_record(CONTRACT),
        "translator": file_record(TRANSLATOR),
        "exposed_control": file_record(EXPOSED_CONTROL),
        "sources": [file_record(ROOT / relative) for relative in SOURCE_HASHES],
        "calendar_months": ["2022-03", "2022-04", "2022-05"],
        "dates": [day.isoformat() for day in dates],
        "date_counts": dict(sorted(counts.items())),
        "documented_closures": {day.isoformat(): reason for day, reason in DOCUMENTED_CLOSURES.items()},
        "population_sha256": canonical_hash([day.isoformat() for day in dates]),
        "scan_policy": "EVERY_COMPLETED_MINUTE_LONDON_AND_NEW_YORK_FIRST_SIGNAL_MAX_ONE_DECISION_PER_DAY",
        "translator_fitting_permitted": False,
        "retuning_permitted": False,
        "outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_new_json(FREEZE, payload)
    print(json.dumps({"status": payload["status"], "dates": len(dates), "date_counts": payload["date_counts"], "freeze_sha256": payload["freeze_sha256"]}, indent=2))


def verify_freeze() -> dict[str, Any]:
    require(FREEZE.is_file(), "Prevalue freeze is absent")
    payload = json.loads(FREEZE.read_text(encoding="utf-8"))
    submitted = payload.pop("freeze_sha256")
    require(canonical_hash(payload) == submitted, "Prevalue freeze differs")
    payload["freeze_sha256"] = submitted
    require(payload["dates"] == [day.isoformat() for day in canonical_dates()], "Frozen dates differ")
    verify_static_inputs()
    for record in [payload["contract"], payload["translator"], payload["exposed_control"], *payload["sources"]]:
        path = ROOT / record["path"]
        require(path.is_file(), f"Frozen input absent: {path}")
        require(path.stat().st_size == record["bytes"], f"Frozen input size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"Frozen input hash differs: {path}")
    return payload


def load_prices_primary(maximum: datetime) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with gzip.open(replay.PRICE, "rt", encoding="utf-8") as handle:
        for line in handle:
            source = json.loads(line)
            if (
                source.get("instrument_code") != "XAUUSD"
                or source.get("timeframe") not in replay.SOURCE_TIMEFRAMES
                or not replay.display_eligible(source)
            ):
                continue
            if replay.parse_time(str(source["close_time"])) > maximum:
                continue
            rows[str(source["timeframe"])].append(replay.price_record(source))
    for timeframe in rows:
        rows[timeframe].sort(key=lambda item: (item["close_at"], item["bar_id"]))
    return dict(rows)


def load_prices_reference(maximum: datetime) -> dict[str, list[dict[str, Any]]]:
    tuples: list[tuple[str, str, str, dict[str, Any]]] = []
    with gzip.GzipFile(filename=replay.PRICE, mode="rb") as handle:
        for raw in handle:
            source = json.loads(raw.decode("utf-8"))
            timeframe = str(source.get("timeframe"))
            if (
                source.get("instrument_code") != "XAUUSD"
                or timeframe not in replay.SOURCE_TIMEFRAMES
                or not replay.display_eligible(source)
            ):
                continue
            if replay.parse_time(str(source["close_time"])) > maximum:
                continue
            record = replay.price_record(source)
            tuples.append((timeframe, record["close_at"], record["bar_id"], record))
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for timeframe, _, _, record in sorted(tuples, key=lambda item: item[:3]):
        output[timeframe].append(record)
    return dict(output)


def utc_bounds(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    opened = datetime.combine(day, time(8, 0), tzinfo=zone).astimezone(UTC)
    return opened, opened + timedelta(hours=4)


def count_session_closes(m1: list[dict[str, Any]], day: date, zone: ZoneInfo) -> int:
    start, end = utc_bounds(day, zone)
    return sum(start <= replay.parse_time(row["close_at"]) < end for row in m1)


def cases_from_prices(prices: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    m1 = prices.get("1m", [])
    cases: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for sequence, day in enumerate(canonical_dates(), start=1):
        start = datetime.combine(day, time.min, tzinfo=UTC)
        end = start + timedelta(days=1)
        observed = sum(start <= replay.parse_time(row["close_at"]) < end for row in m1)
        london = count_session_closes(m1, day, LONDON)
        new_york = count_session_closes(m1, day, NEW_YORK)
        require(observed > 0, f"No M1 path for {day}")
        require(london >= 216, f"London coverage below 90% for {day}: {london}")
        require(new_york >= 216, f"New York coverage below 90% for {day}: {new_york}")
        alias = f"CAM-2022-{sequence:03d}"
        identity = canonical_hash({"alias": alias, "date": day.isoformat(), "start": replay.iso(start), "end": replay.iso(end)})
        cases.append(
            {
                "case_alias": alias,
                "mode_sequence": sequence,
                "trading_date_utc": day.isoformat(),
                "start_inclusive": replay.iso(start),
                "end_exclusive": replay.iso(end),
                "observed_m1_minutes": observed,
                "minute_identity_sha256": identity,
            }
        )
        coverage.append({"case_alias": alias, "trading_date_utc": day.isoformat(), "observed_m1_closes": observed, "london_m1_closes": london, "new_york_m1_closes": new_york})
    return cases, coverage


def build_streams(
    loader: Callable[[datetime], dict[str, list[dict[str, Any]]]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    maximum = datetime(2022, 6, 1, tzinfo=UTC)
    prices = loader(maximum)
    cases, coverage = cases_from_prices(prices)
    contexts = replay.build_contexts()
    streams: dict[str, dict[str, Any]] = {}
    lineage: list[dict[str, Any]] = []
    for case in cases:
        stream = replay.timeline_for_case(case, prices, contexts)
        alias = str(case["case_alias"])
        streams[alias] = stream
        lineage.append({"case_alias": alias, "stream_sha256": stream["stream_sha256"], "minute_identity_sha256": case["minute_identity_sha256"]})
    return streams, lineage, coverage


def write_stream_bundle(path: Path, streams: dict[str, dict[str, Any]]) -> None:
    require(not path.exists(), f"Append-only stream exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            for alias in sorted(streams):
                zipped.write((json.dumps(streams[alias], sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def signal_session(signal_at: str | None) -> str | None:
    if signal_at is None:
        return None
    point = replay.parse_time(signal_at)
    london = point.astimezone(LONDON).time()
    new_york = point.astimezone(NEW_YORK).time()
    if time(8, 0) <= london < time(12, 0):
        return "LONDON"
    if time(8, 0) <= new_york < time(12, 0):
        return "NEW_YORK"
    raise RuntimeError(f"Signal outside frozen sessions: {signal_at}")


def metric_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    base = summarize(rows)
    executed = [row for row in rows if row.get("result") is not None and row["result"].get("executed")]
    values = [float(row["result"]["net_r50"]) for row in executed]
    positive = sum(value for value in values if value > 0)
    negative = abs(sum(value for value in values if value < 0))
    return {
        **base,
        "executed_trades": len(executed),
        "expectancy_r50": sum(values) / len(values) if values else 0.0,
        "profit_factor_recalculated": positive / negative if negative else (math.inf if positive else 0.0),
        "stressed_1p5x_cost_net_r50": sum(float(row["result"]["stressed_1_5x_cost_r50"]) for row in executed),
        "signal_session_counts": dict(sorted(Counter(signal_session(row.get("signal_at")) for row in rows if row.get("signal_at")).items())),
    }


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Gold Coherent-Auction Consecutive Calendar-Month Test V1 — Result",
        "",
        f"Verdict: `{result['verdict']}`",
        "",
        "The exact frozen +10.6935R translator was applied without changes to every eligible trading day in March, April and May 2022.",
        "",
        "| Month | Dates | Signals | Admitted | Trades | Wins | Losses | Win % | Net R | USD | Exp R | PF | Max DD R | 1.5x-cost R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for month in ["2022-03", "2022-04", "2022-05", "COMBINED"]:
        row = result["by_month"][month] if month != "COMBINED" else result["combined"]
        lines.append(
            f"| {month} | {row['cases']} | {row['signal_days']} | {row['admitted']} | {row['executed_trades']} | {row['wins']} | {row['losses']} | {100 * float(row['win_rate'] or 0):.2f} | {row['net_r50']:+.4f} | {row['net_usd']:+.2f} | {row['expectancy_r50']:+.4f} | {row['profit_factor_recalculated']} | {row['maximum_drawdown_r50']:.4f} | {row['stressed_1p5x_cost_net_r50']:+.4f} |"
        )
    lines.extend(["", "## Every eligible day", "", "| Date | Signal session | Signal | Disposition | Family | Net R |", "|---|---|---|---|---|---:|"])
    for row in result["rows"]:
        classification = row.get("classification")
        disposition = "NO_SIGNAL" if classification is None else classification["primary_disposition"]
        family = "NONE" if classification is None else classification["family"]
        net_r = 0.0 if row.get("result") is None else float(row["result"]["net_r50"])
        lines.append(f"| {row['trading_date_utc']} | {row.get('signal_session') or 'NONE'} | {row.get('signal_at') or 'NONE'} | {disposition} | {family} | {net_r:+.4f} |")
    lines.extend(["", "No fitting or retuning was performed. This is historical robustness evidence, not independent validation.", ""])
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    for path in (PRIMARY_STREAM, REFERENCE_STREAM, PRIMARY_RESULT, REFERENCE_RESULT, FINAL_RESULT, FINAL_SEAL, REPORT):
        require(not path.exists(), f"One-shot output already exists: {path}")
    translator = json.loads(TRANSLATOR.read_text(encoding="utf-8"))
    require(translator["status"] == "PASS_PREPATH_TRANSLATOR_FREEZE", "Translator status differs")

    primary_streams, primary_lineage, primary_coverage = build_streams(load_prices_primary)
    write_stream_bundle(PRIMARY_STREAM, primary_streams)
    primary = infer_streams(streams=primary_streams, lineage=primary_lineage, translator=translator, side="primary", include_validation_metadata=False)
    del primary_streams, primary_lineage
    gc.collect()

    reference_streams, reference_lineage, reference_coverage = build_streams(load_prices_reference)
    write_stream_bundle(REFERENCE_STREAM, reference_streams)
    reference = infer_streams(streams=reference_streams, lineage=reference_lineage, translator=translator, side="reference", include_validation_metadata=False)
    del reference_streams, reference_lineage
    gc.collect()

    require(primary_coverage == reference_coverage, "Primary/reference coverage differs")
    require(primary["rows"] == reference["rows"], "Primary/reference inference rows differ")
    require(primary["summary"] == reference["summary"], "Primary/reference summaries differ")
    require(len(primary["rows"]) == 65, "Expected 65 daily rows")
    require([row["trading_date_utc"] for row in primary["rows"]] == frozen["dates"], "Daily identity order differs")
    require(sha256_file(PRIMARY_STREAM) == sha256_file(REFERENCE_STREAM), "Primary/reference stream bytes differ")

    write_new_json(PRIMARY_RESULT, primary)
    write_new_json(REFERENCE_RESULT, reference)
    rows = []
    for row in primary["rows"]:
        enriched = dict(row)
        enriched["signal_session"] = signal_session(row.get("signal_at"))
        rows.append(enriched)
    by_month = {
        month: metric_block([row for row in rows if row["trading_date_utc"].startswith(month)])
        for month in ("2022-03", "2022-04", "2022-05")
    }
    combined = metric_block(rows)
    result: dict[str, Any] = {
        "version": "GOLD_COHERENT_AUCTION_CONSECUTIVE_MONTHS_MAR_MAY_2022_V1_RESULT_1_0",
        "completed_at": now(),
        "verdict": "COMPLETE_UNCHANGED_THREE_CALENDAR_MONTH_TEST",
        "freeze_sha256": frozen["freeze_sha256"],
        "coverage_amendment": file_record(AMENDMENT),
        "translator_sha256": TRANSLATOR_SHA256,
        "population_sha256": frozen["population_sha256"],
        "primary_reference_exact": True,
        "stream_bytes_exact": True,
        "coverage": primary_coverage,
        "by_month": by_month,
        "combined": combined,
        "rows": rows,
        "fitting_performed": False,
        "retuning_performed": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    result["result_sha256"] = canonical_hash(result)
    write_new_json(FINAL_RESULT, result)
    REPORT.write_text(markdown(result), encoding="utf-8", newline="\n")
    seal: dict[str, Any] = {
        "version": "GOLD_COHERENT_AUCTION_CONSECUTIVE_MONTHS_MAR_MAY_2022_V1_SEAL_1_0",
        "sealed_at": now(),
        "verdict": result["verdict"],
        "files": [file_record(path) for path in (CONTRACT, AMENDMENT, FREEZE, PRIMARY_STREAM, REFERENCE_STREAM, PRIMARY_RESULT, REFERENCE_RESULT, FINAL_RESULT, REPORT)],
        "translator_unchanged": True,
        "primary_reference_exact": True,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    write_new_json(FINAL_SEAL, seal)
    print(json.dumps({"verdict": result["verdict"], "by_month": by_month, "combined": combined}, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run"))
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
    else:
        run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
