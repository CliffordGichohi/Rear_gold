"""Build a point-in-time H4 chart atlas for the matched human replay trades.

This is a descriptive diagnostic over an already exposed, zero-credit sample.  It
uses only completed H4 candles available at each human decision timestamp.  The
simple fractal markers are chart annotations, not an automatic trend verdict.
"""

from __future__ import annotations

import gzip
import html
import json
import math
from datetime import datetime
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]
COMPARISON = (
    ROOT
    / "research_artifacts/gold_matched_human_replay_v1/comparison/matched_case_comparison.json"
)
STREAM_ROOT = (
    ROOT
    / "research_artifacts/gold_blind_codex_operator_replay_v1/private_streams/primary"
)
RECOVERY_STREAM_ROOT = (
    ROOT
    / "research_artifacts/gold_blind_codex_operator_replay_v1/private_streams_recovery_a/primary"
)
OUTPUT = ROOT / "research_artifacts/gold_human_h4_context_v1"

BAR_LIMIT = 84
CHART_W = 700
CHART_H = 330
PAD_LEFT = 46
PAD_RIGHT = 12
PAD_TOP = 30
PAD_BOTTOM = 34


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_gzip_json(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def available_h4(case_alias: str, decision_at: str) -> tuple[list[dict], str]:
    source = STREAM_ROOT / f"{case_alias}.json.gz"
    if not source.exists():
        source = RECOVERY_STREAM_ROOT / f"{case_alias}.json.gz"
    stream = load_gzip_json(source)
    cutoff = parse_timestamp(decision_at)
    rows = [
        row
        for row in stream["timeframes"]["4h"]
        if row.get("complete") is True and parse_timestamp(row["available_at"]) <= cutoff
    ]
    if not rows:
        raise RuntimeError(f"No completed H4 bars for {case_alias}")
    return rows, str(source.relative_to(ROOT)).replace("\\", "/")


def true_range(rows: list[dict], index: int) -> float:
    row = rows[index]
    previous_close = float(rows[index - 1]["close"]) if index else float(row["open"])
    return max(
        float(row["high"]) - float(row["low"]),
        abs(float(row["high"]) - previous_close),
        abs(float(row["low"]) - previous_close),
    )


def pivots(rows: list[dict], width: int = 2) -> list[dict]:
    found: list[dict] = []
    for index in range(width, len(rows) - width):
        window = rows[index - width : index + width + 1]
        high = float(rows[index]["high"])
        low = float(rows[index]["low"])
        if high == max(float(row["high"]) for row in window) and sum(
            float(row["high"]) == high for row in window
        ) == 1:
            found.append(
                {
                    "kind": "H",
                    "index": index,
                    "available_at": rows[index]["available_at"],
                    "price": high,
                }
            )
        if low == min(float(row["low"]) for row in window) and sum(
            float(row["low"]) == low for row in window
        ) == 1:
            found.append(
                {
                    "kind": "L",
                    "index": index,
                    "available_at": rows[index]["available_at"],
                    "price": low,
                }
            )
    return sorted(found, key=lambda row: (row["index"], row["kind"]))


def structure_evidence(rows: list[dict]) -> dict:
    marked = pivots(rows)
    highs = [row for row in marked if row["kind"] == "H"]
    lows = [row for row in marked if row["kind"] == "L"]
    high_relation = "INSUFFICIENT"
    low_relation = "INSUFFICIENT"
    if len(highs) >= 2:
        high_relation = "HH" if highs[-1]["price"] > highs[-2]["price"] else "LH"
    if len(lows) >= 2:
        low_relation = "HL" if lows[-1]["price"] > lows[-2]["price"] else "LL"
    if high_relation == "HH" and low_relation == "HL":
        swing_state = "BULLISH_SWING_SEQUENCE"
    elif high_relation == "LH" and low_relation == "LL":
        swing_state = "BEARISH_SWING_SEQUENCE"
    else:
        swing_state = "MIXED_OR_TRANSITIONAL_SEQUENCE"

    atr_rows = rows[-14:]
    atr14 = mean(true_range(rows, rows.index(row)) for row in atr_rows)
    last_close = float(rows[-1]["close"])
    close_5 = float(rows[-6]["close"]) if len(rows) >= 6 else float(rows[0]["close"])
    close_15 = float(rows[-16]["close"]) if len(rows) >= 16 else float(rows[0]["close"])
    recent = rows[-24:]
    range_low = min(float(row["low"]) for row in recent)
    range_high = max(float(row["high"]) for row in recent)
    range_location = (
        (last_close - range_low) / (range_high - range_low)
        if range_high > range_low
        else 0.5
    )
    return {
        "last_completed_h4_available_at": rows[-1]["available_at"],
        "last_completed_h4_close": last_close,
        "confirmed_high_relation": high_relation,
        "confirmed_low_relation": low_relation,
        "swing_sequence_evidence": swing_state,
        "atr14": atr14,
        "five_bar_change_atr": (last_close - close_5) / atr14 if atr14 else None,
        "fifteen_bar_change_atr": (last_close - close_15) / atr14 if atr14 else None,
        "twenty_four_bar_range_location": range_location,
        "last_confirmed_pivots": marked[-8:],
    }


def chart_svg(case: dict, rows_all: list[dict], evidence: dict) -> str:
    rows = rows_all[-BAR_LIMIT:]
    offset = len(rows_all) - len(rows)
    marked = [
        {**row, "index": row["index"] - offset}
        for row in pivots(rows_all)
        if row["index"] >= offset
    ]
    low = min(float(row["low"]) for row in rows)
    high = max(float(row["high"]) for row in rows)
    span = high - low or 1.0
    plot_w = CHART_W - PAD_LEFT - PAD_RIGHT
    plot_h = CHART_H - PAD_TOP - PAD_BOTTOM
    step = plot_w / max(len(rows), 1)
    body_w = max(2.0, min(6.0, step * 0.62))

    def x(index: int) -> float:
        return PAD_LEFT + (index + 0.5) * step

    def y(price: float) -> float:
        return PAD_TOP + (high - price) / span * plot_h

    parts = [
        f'<svg viewBox="0 0 {CHART_W} {CHART_H}" role="img" '
        f'aria-label="{html.escape(case["case_alias"])} completed H4 chart">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        price = high - span * fraction
        yy = PAD_TOP + plot_h * fraction
        parts.append(
            f'<line x1="{PAD_LEFT}" y1="{yy:.2f}" x2="{CHART_W-PAD_RIGHT}" '
            f'y2="{yy:.2f}" stroke="#e5e7eb" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{PAD_LEFT-4}" y="{yy+4:.2f}" text-anchor="end" '
            f'font-size="9" fill="#64748b">{price:.1f}</text>'
        )
    for index, row in enumerate(rows):
        xx = x(index)
        open_price = float(row["open"])
        close_price = float(row["close"])
        color = "#089981" if close_price >= open_price else "#f23645"
        top = y(max(open_price, close_price))
        bottom = y(min(open_price, close_price))
        body_h = max(1.0, bottom - top)
        parts.append(
            f'<line x1="{xx:.2f}" y1="{y(float(row["high"])):.2f}" '
            f'x2="{xx:.2f}" y2="{y(float(row["low"])):.2f}" '
            f'stroke="{color}" stroke-width="1"/>'
        )
        parts.append(
            f'<rect x="{xx-body_w/2:.2f}" y="{top:.2f}" width="{body_w:.2f}" '
            f'height="{body_h:.2f}" fill="{color}"/>'
        )
    for pivot in marked:
        xx = x(int(pivot["index"]))
        yy = y(float(pivot["price"]))
        color = "#2563eb" if pivot["kind"] == "H" else "#9333ea"
        dy = -6 if pivot["kind"] == "H" else 11
        parts.append(
            f'<circle cx="{xx:.2f}" cy="{yy:.2f}" r="2.2" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{xx:.2f}" y="{yy+dy:.2f}" text-anchor="middle" '
            f'font-size="8" font-weight="700" fill="{color}">{pivot["kind"]}</text>'
        )
    first_date = rows[0]["open_at"][:10]
    last_date = rows[-1]["open_at"][:10]
    parts.extend(
        [
            f'<text x="{PAD_LEFT}" y="16" font-size="11" font-weight="700" '
            f'fill="#0f172a">{html.escape(case["case_alias"])} | '
            f'{html.escape(case["trading_date_utc"])} | {html.escape(case["result_bucket"])}</text>',
            f'<text x="{PAD_LEFT}" y="{CHART_H-8}" font-size="9" fill="#64748b">'
            f'{first_date} to {last_date} | last H4 available '
            f'{evidence["last_completed_h4_available_at"]}</text>',
            f'<text x="{CHART_W-PAD_RIGHT}" y="16" text-anchor="end" font-size="10" '
            f'fill="#334155">{evidence["confirmed_high_relation"]} / '
            f'{evidence["confirmed_low_relation"]}</text>',
            "</svg>",
        ]
    )
    return "".join(parts)


def write_atlas(group: list[dict], index: int) -> Path:
    cards = "\n".join(
        f'<section class="card">{row["svg"]}<div class="note">'
        f'Human: {html.escape(row["human_htf_context"])}<br>'
        f'Thesis: {html.escape(row["human_thesis"])}</div></section>'
        for row in group
    )
    document = f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box}} body{{margin:0;padding:18px;background:#eef2f7;font-family:Arial,sans-serif}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.card{{background:#fff;border:1px solid #cbd5e1;border-radius:10px;padding:8px;box-shadow:0 2px 8px #0f172a12}}
.note{{font-size:12px;line-height:1.35;color:#334155;padding:4px 12px 8px;min-height:55px}}
svg{{display:block;width:100%;height:auto}}
</style></head><body><div class="grid">{cards}</div></body></html>"""
    path = OUTPUT / f"h4_atlas_{index:02d}.html"
    path.write_text(document, encoding="utf-8", newline="\n")
    return path


def main() -> None:
    comparison = load_json(COMPARISON)
    cases: list[dict] = []
    for record in comparison["cases"]:
        human = record["human"]
        if not human["is_trade"]:
            continue
        rows, stream_source = available_h4(record["case_alias"], human["submitted_at"])
        evidence = structure_evidence(rows)
        if human["r50"] > 0:
            result_bucket = "PROFITABLE"
        elif human["path_diagnostic"]["terminal_direction_correct"]:
            result_bucket = "DIRECTION_RIGHT_NOT_MONETIZED"
        else:
            result_bucket = "DIRECTION_WRONG_BY_CLOSE"
        case = {
            "case_alias": record["case_alias"],
            "trading_date_utc": record["trading_date_utc"],
            "decision_at": human["submitted_at"],
            "stream_source": stream_source,
            "result_bucket": result_bucket,
            "resolution_state": human["resolution_state"],
            "r50": human["r50"],
            "terminal_direction_correct": human["path_diagnostic"][
                "terminal_direction_correct"
            ],
            "human_htf_context": human["annotation"]["higher_timeframe_context"],
            "human_thesis": human["annotation"]["thesis"],
            "evidence": evidence,
        }
        case["svg"] = chart_svg(case, rows, evidence)
        cases.append(case)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    serializable = [{key: value for key, value in row.items() if key != "svg"} for row in cases]
    (OUTPUT / "h4_context_evidence.json").write_text(
        json.dumps(serializable, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    atlas_paths = []
    for index in range(0, len(cases), 4):
        atlas_paths.append(write_atlas(cases[index : index + 4], index // 4 + 1))
    print(
        json.dumps(
            {
                "case_count": len(cases),
                "evidence": str(OUTPUT / "h4_context_evidence.json"),
                "atlases": [str(path) for path in atlas_paths],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
