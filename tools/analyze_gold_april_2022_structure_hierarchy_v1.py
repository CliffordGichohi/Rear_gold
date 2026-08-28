#!/usr/bin/env python3
"""Count April 2022 M5/M15 structure breaks inside causal H4 regimes."""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gold_intel.analytics.auction_control_router_v1 import strong_breaks  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    iso,
    parse_dt,
    structural_breaks,
)


SOURCE_ROOT = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_consecutive_months_mar_may_2022_v1"
)
PRIMARY_SOURCE = SOURCE_ROOT / "daily_streams.primary.jsonl.gz"
REFERENCE_SOURCE = SOURCE_ROOT / "daily_streams.reference.jsonl.gz"
EXPECTED_SOURCE_SHA256 = "120b88417ea40f7cd89842d2f77a79cd1f4d381c290751612ad939356e64794c"

START = datetime(2022, 4, 1, tzinfo=UTC)
END = datetime(2022, 5, 1, tzinfo=UTC)
TIMEFRAME_KEYS = {"M5": "5m", "M15": "15m", "H1": "1h", "H4": "4h"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_streams(path: Path) -> list[dict[str, Any]]:
    if sha256_file(path) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(f"Sealed source differs: {path}")
    output: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            stream = json.loads(line)
            submitted = str(stream.pop("stream_sha256"))
            if canonical_hash(stream) != submitted:
                raise RuntimeError(f"Stream hash differs: {stream.get('case_alias')}")
            stream["stream_sha256"] = submitted
            output.append(stream)
    if len(output) != 65:
        raise RuntimeError(f"Expected 65 March-May streams, received {len(output)}")
    return output


def deduplicated_rows(
    streams: list[dict[str, Any]], timeframe_key: str
) -> list[dict[str, Any]]:
    by_timestamp: dict[tuple[str, str], dict[str, Any]] = {}
    for stream in streams:
        for row in stream["timeframes"][timeframe_key]:
            if parse_dt(row["available_at"]) > END:
                continue
            key = (iso(row["open_at"]), iso(row["available_at"]))
            previous = by_timestamp.get(key)
            if previous is not None and canonical_hash(previous) != canonical_hash(row):
                raise RuntimeError(f"Conflicting duplicate {timeframe_key} bar: {key}")
            by_timestamp[key] = row
    return sorted(
        by_timestamp.values(),
        key=lambda row: (parse_dt(row["open_at"]), parse_dt(row["available_at"])),
    )


def all_breaks(rows: list[dict[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    if timeframe in {"M5", "M15"}:
        return strong_breaks(rows, END, timeframe)
    events = [
        *structural_breaks(rows, END, timeframe, "LONG"),
        *structural_breaks(rows, END, timeframe, "SHORT"),
    ]
    return sorted(
        events,
        key=lambda row: (
            parse_dt(row["break_at"]),
            str(row["direction"]),
            str(row["identity"]),
        ),
    )


def direction_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(event["direction"]) for event in events)
    return {"bullish": counts["LONG"], "bearish": counts["SHORT"]}


def analyse(path: Path) -> dict[str, Any]:
    streams = load_streams(path)
    rows = {
        timeframe: deduplicated_rows(streams, key)
        for timeframe, key in TIMEFRAME_KEYS.items()
    }
    events = {
        timeframe: all_breaks(rows[timeframe], timeframe)
        for timeframe in TIMEFRAME_KEYS
    }

    h4_before = [event for event in events["H4"] if parse_dt(event["break_at"]) < START]
    carry = h4_before[-1] if h4_before else None
    h4_month = [
        event for event in events["H4"] if START <= parse_dt(event["break_at"]) < END
    ]
    governing = ([carry] if carry is not None else []) + h4_month
    if not governing:
        raise RuntimeError("No causal H4 state is available for April 2022")

    segments: list[dict[str, Any]] = []
    for index, event in enumerate(governing):
        raw_start = parse_dt(event["break_at"])
        segment_start = max(raw_start, START)
        segment_end = (
            parse_dt(governing[index + 1]["break_at"])
            if index + 1 < len(governing)
            else END
        )
        if segment_end <= START or segment_start >= END:
            continue
        nested: dict[str, dict[str, int]] = {}
        nested_identities: dict[str, list[str]] = {}
        for timeframe in ("M15", "M5"):
            selected = [
                child
                for child in events[timeframe]
                if segment_start <= parse_dt(child["break_at"]) < segment_end
            ]
            nested[timeframe] = direction_counts(selected)
            nested_identities[timeframe] = [str(child["identity"]) for child in selected]
        segments.append(
            {
                "ordinal": len(segments) + 1,
                "h4_direction": "bullish" if event["direction"] == "LONG" else "bearish",
                "h4_break_at": iso(event["break_at"]),
                "april_interval_start": iso(segment_start),
                "april_interval_end_exclusive": iso(segment_end),
                "carry_in_from_march": raw_start < START,
                "nested_counts": nested,
                "nested_identities": nested_identities,
            }
        )

    april_events = {
        timeframe: [
            event
            for event in values
            if START <= parse_dt(event["break_at"]) < END
        ]
        for timeframe, values in events.items()
    }
    result = {
        "period": {"start": iso(START), "end_exclusive": iso(END)},
        "definition": {
            "h4_h1": "confirmed structural break with the frozen 0.10 ATR buffer",
            "m15_m5": "frozen strong structural break: 0.05 ATR break buffer, minimum range 0.90/0.80 ATR, minimum body ratio 0.55",
            "nesting": "child break_at in [H4 regime start, next H4 break_at)",
            "session_filter": "NONE",
        },
        "source": {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(path),
            "stream_count": len(streams),
            "deduplicated_bar_counts": {
                timeframe: len(values) for timeframe, values in rows.items()
            },
        },
        "h4": {
            "carry_in_direction": segments[0]["h4_direction"],
            "month_end_direction": segments[-1]["h4_direction"],
            "new_break_counts": direction_counts(april_events["H4"]),
            "regime_segments_overlapping_month": len(segments),
            "segments": segments,
        },
        "april_break_totals": {
            timeframe: direction_counts(april_events[timeframe])
            for timeframe in ("H4", "H1", "M15", "M5")
        },
    }
    result["result_sha256"] = canonical_hash(result)
    return result


def main() -> None:
    primary = analyse(PRIMARY_SOURCE)
    reference = analyse(REFERENCE_SOURCE)
    primary_without_source = dict(primary)
    reference_without_source = dict(reference)
    primary_without_source["source"] = dict(primary_without_source["source"])
    reference_without_source["source"] = dict(reference_without_source["source"])
    primary_without_source["source"]["path"] = "SOURCE"
    reference_without_source["source"]["path"] = "SOURCE"
    primary_without_source.pop("result_sha256")
    reference_without_source.pop("result_sha256")
    if canonical_hash(primary_without_source) != canonical_hash(reference_without_source):
        raise RuntimeError("Primary/reference structure analyses differ")
    output = {
        "primary_reference_exact": True,
        "analysis": primary,
        "reproduction_sha256": canonical_hash(primary_without_source),
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
