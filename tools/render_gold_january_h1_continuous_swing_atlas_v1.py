#!/usr/bin/env python3
"""Render the continuous January 2022 XAUUSD H1 swing atlas."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT / "tools")]

from gold_coherent_auction_end_to_end_v1_common import (  # noqa: E402
    load_certified_streams,
    require,
    sha256_file,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    ATR_WINDOW,
    PIVOT_PROMINENCE_ATR,
    PIVOT_WIDTH,
    TICK_FLOOR,
    canonical_hash,
    confirmed_swings,
    parse_dt,
)


SPEC = ROOT / "GOLD_JANUARY_H1_CONTINUOUS_SWING_ATLAS_V1.md"
CERTIFICATION = ROOT / "research_artifacts" / "gold_matched_human_replay_v1" / "stream_materialization_certification.json"
OUT = ROOT / "research_artifacts" / "gold_january_h1_continuous_swing_atlas_v1"
TEMPLATE = OUT / "h1-continuous-swing-atlas.template.html"
FRAGMENT = OUT / "gold-january-h1-continuous-swing-atlas.html"
MANIFEST = OUT / "visual_manifest.json"
START = "2022-01-01T00:00:00Z"
END = "2022-02-01T00:00:00Z"
CONFIRMATION_CUTOFF = "2022-02-03T00:00:00Z"


def sec(value: str) -> int:
    return int(parse_dt(value).timestamp())


def compact_bar(row: Mapping[str, Any]) -> list[float | int]:
    return [
        sec(str(row["open_at"])),
        sec(str(row["available_at"])),
        round(float(row["open"]), 4),
        round(float(row["high"]), 4),
        round(float(row["low"]), 4),
        round(float(row["close"]), 4),
    ]


def canonical_h1(streams: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "open_at", "available_at", "open", "high", "low", "close",
        "complete", "source_record_hash", "bar_id",
    )
    by_open: dict[str, dict[str, Any]] = {}
    for alias in sorted(streams):
        for source in streams[alias]["timeframes"]["1h"]:
            row = {field: source[field] for field in fields}
            key = str(row["open_at"])
            if key in by_open:
                require(by_open[key] == row, f"Conflicting overlapping H1 record: {key}")
            else:
                by_open[key] = row
    return sorted(by_open.values(), key=lambda row: parse_dt(str(row["open_at"])))


def relation_rows(swings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    previous: dict[str, float] = {}
    output: list[dict[str, Any]] = []
    for number, source in enumerate(
        sorted(swings, key=lambda row: (parse_dt(str(row["pivot_at"])), str(row["kind"]), str(row["identity"]))),
        start=1,
    ):
        kind = str(source["kind"])
        level = float(source["level"])
        prior = previous.get(kind)
        if prior is None:
            relation = "H" if kind == "HIGH" else "L"
        elif level > prior + TICK_FLOOR:
            relation = "HH" if kind == "HIGH" else "HL"
        elif level < prior - TICK_FLOOR:
            relation = "LH" if kind == "HIGH" else "LL"
        else:
            relation = "EH" if kind == "HIGH" else "EL"
        previous[kind] = level
        output.append({
            "number": number,
            "id": str(source["identity"]),
            "kind": kind,
            "relation": relation,
            "pivotTime": sec(str(source["pivot_at"])),
            "knownTime": sec(str(source["detected_at"])),
            "level": round(level, 4),
            "atr": round(float(source["atr"]), 5),
            "prominenceAtr": round(float(source["prominence_atr"]), 5),
            "delayMinutes": round((parse_dt(str(source["detected_at"])) - parse_dt(str(source["pivot_at"]))).total_seconds() / 60.0, 2),
        })
    return output


def side_payload(side: str) -> dict[str, Any]:
    streams, lineage = load_certified_streams(CERTIFICATION, side)
    rows = canonical_h1(streams)
    require(rows and parse_dt(str(rows[0]["open_at"])) < parse_dt(START), "H1 ATR context is absent")
    context = [row for row in rows if parse_dt(str(row["open_at"])) < parse_dt(CONFIRMATION_CUTOFF)]
    displayed = [row for row in rows if parse_dt(START) <= parse_dt(str(row["open_at"])) < parse_dt(END)]
    require(len(displayed) == 436, "January continuous H1 candle count differs")
    _, swings = confirmed_swings(context, CONFIRMATION_CUTOFF, "H1")
    january_swings = [
        row for row in swings
        if parse_dt(START) <= parse_dt(str(row["pivot_at"])) < parse_dt(END)
        and parse_dt(str(row["detected_at"])) <= parse_dt(CONFIRMATION_CUTOFF)
    ]
    related = relation_rows(january_swings)
    require(len(related) == 115, "January H1 swing count differs")
    require(sum(row["kind"] == "HIGH" for row in related) == 55, "H1 swing-high count differs")
    require(sum(row["kind"] == "LOW" for row in related) == 60, "H1 swing-low count differs")
    return {
        "bars": [compact_bar(row) for row in displayed],
        "swings": related,
        "lineageSha256": canonical_hash(lineage),
        "semanticSha256": canonical_hash({"bars": [compact_bar(row) for row in displayed], "swings": related}),
    }


def main() -> None:
    for path in (SPEC, CERTIFICATION, TEMPLATE):
        require(path.is_file(), f"Required input absent: {path}")
    certification = json.loads(CERTIFICATION.read_text(encoding="utf-8"))
    require(certification["verdict"] == "PASS_CODEX_OPERATOR_PRIVATE_STREAM_MATERIALIZATION", "Stream certification is not PASS")
    primary = side_payload("primary")
    reference = side_payload("reference")
    require(primary["bars"] == reference["bars"], "Primary/reference continuous H1 bars differ")
    require(primary["swings"] == reference["swings"], "Primary/reference H1 swings differ")
    require(primary["semanticSha256"] == reference["semanticSha256"], "Primary/reference semantic hash differs")

    dataset: dict[str, Any] = {
        "version": "GOLD_JANUARY_H1_CONTINUOUS_SWING_ATLAS_V1",
        "period": {"start": START, "endExclusive": END, "confirmationCutoff": CONFIRMATION_CUTOFF},
        "definition": {
            "timeframe": "H1",
            "atrWindow": ATR_WINDOW,
            "pivotLeft": PIVOT_WIDTH,
            "pivotRight": PIVOT_WIDTH,
            "prominenceAtr": PIVOT_PROMINENCE_ATR,
            "tickFloor": TICK_FLOOR,
        },
        "summary": {
            "candles": len(primary["bars"]),
            "swings": len(primary["swings"]),
            "highs": sum(row["kind"] == "HIGH" for row in primary["swings"]),
            "lows": sum(row["kind"] == "LOW" for row in primary["swings"]),
        },
        "bars": primary["bars"],
        "swings": primary["swings"],
        "guards": {
            "continuousNotCases": True,
            "fixedLightTheme": True,
            "pivotAndConfirmationSeparated": True,
            "outcomesIncluded": False,
            "pnlCalculated": False,
            "laterYearsOpened": False,
        },
        "sourceHashes": {
            "certification": sha256_file(CERTIFICATION),
            "primaryLineage": primary["lineageSha256"],
            "referenceLineage": reference["lineageSha256"],
            "semantic": primary["semanticSha256"],
        },
    }
    dataset["dataSha256"] = canonical_hash(dataset)
    template = TEMPLATE.read_text(encoding="utf-8")
    marker = "__H1_CONTINUOUS_SWING_DATA__"
    require(template.count(marker) == 1, "Template data marker differs")
    encoded = json.dumps(dataset, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    fragment = template.replace(marker, encoded)
    require(len(fragment.encode("utf-8")) < 1_000_000, "Visualization fragment exceeds 1 MB")
    FRAGMENT.write_text(fragment, encoding="utf-8", newline="\n")

    manifest = {
        "version": "GOLD_JANUARY_H1_CONTINUOUS_SWING_ATLAS_V1_MANIFEST",
        "verdict": "PASS_CONTINUOUS_H1_SWING_PAYLOAD_REPRODUCTION",
        "summary": dataset["summary"],
        "definition": dataset["definition"],
        "data_sha256": dataset["dataSha256"],
        "primary_reference_exact": True,
        "guards": dataset["guards"],
        "fragment_bytes": FRAGMENT.stat().st_size,
        "files": [
            {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in (SPEC, CERTIFICATION, TEMPLATE, FRAGMENT)
        ],
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"verdict": manifest["verdict"], **dataset["summary"], "fragment_bytes": manifest["fragment_bytes"]}, indent=2))


if __name__ == "__main__":
    main()
