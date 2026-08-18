from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "GOLD_PULLBACK_BEHAVIOURAL_ARCHETYPES_CONTRACT_V1.md"
PROTOCOL = ROOT / "research_manifests/gold_pullback_behavioural_archetypes_v1_protocol.json"
FEATURE_DIR = ROOT / "research_artifacts/gold_trend_pullback_continuation_edge_v1_v01"
ANATOMY_DIR = ROOT / "research_artifacts/gold_trend_pullback_movement_anatomy_edge_v1_v01"
CENSUS_DIR = ROOT / "research_artifacts/gold_multitimeframe_trend_continuation_census_v1_v02"
OUTPUT = ROOT / "research_artifacts/gold_pullback_behavioural_archetypes_v1"
REPORT = ROOT / "GOLD_PULLBACK_BEHAVIOURAL_ARCHETYPES_V1_REPORT.md"

TIMEFRAMES = ("M15", "H1", "H4")
ARCHETYPES = (
    "RUNAWAY_CONTINUATION",
    "BREAK_RETEST_CONTINUATION",
    "DEEP_RETRACE_CONTINUATION",
    "FALSE_CONTINUATION",
    "IMMEDIATE_FAILURE",
    "TWO_SIDED_CHOPPY",
)
REQUIRED_TRIGGERS = (
    "CONFIRMATION_EXTREME_BREAK",
    "RESPONSE_HALF_RETRACE_LIMIT",
    "BREAK_RETEST_CONFIRM",
)
MONTHS = 41


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def finite(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def rounded(value: Any, places: int = 6) -> float | None:
    number = finite(value)
    return None if number is None else round(number, places)


def percent(numerator: int | float, denominator: int | float) -> float | None:
    return rounded(100.0 * float(numerator) / float(denominator)) if denominator else None


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return finite(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if value is pd.NA or (not isinstance(value, (str, bytes)) and pd.isna(value)):
        return None
    return value


def source_paths(implementation: str) -> dict[str, Path]:
    return {
        "features": FEATURE_DIR / f"{implementation}_features.parquet",
        "outcomes": FEATURE_DIR / f"{implementation}_outcomes.parquet",
        "anatomy": ANATOMY_DIR / f"{implementation}_movement_anatomy.parquet",
        "triggers": ANATOMY_DIR / f"{implementation}_trigger_facts.parquet",
        "census": CENSUS_DIR / f"{implementation}_pullback_cases.parquet",
    }


def formed(trigger: Mapping[str, Any]) -> bool:
    return trigger.get("status") == "FORMED"


def parse_time(value: Any) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value)


def assign_archetype(
    resolution: str,
    confirmation_break: Mapping[str, Any],
    half_retrace: Mapping[str, Any],
    break_retest: Mapping[str, Any],
    barrier_order: str,
) -> tuple[str, str]:
    break_formed = formed(confirmation_break)
    half_formed = formed(half_retrace)
    retest_formed = formed(break_retest)
    half_at = parse_time(half_retrace.get("entry_at_utc"))
    retest_at = parse_time(break_retest.get("entry_at_utc"))

    if resolution == "CONTINUED":
        if half_formed and (not retest_formed or (half_at is not None and retest_at is not None and half_at <= retest_at)):
            return "DEEP_RETRACE_CONTINUATION", "CONTINUED_HALF_RETRACE_FIRST_OR_NO_RETEST"
        if retest_formed:
            return "BREAK_RETEST_CONTINUATION", "CONTINUED_BREAK_RETEST_PRECEDES_HALF_OR_HALF_ABSENT"
        if break_formed and not half_formed:
            return "RUNAWAY_CONTINUATION", "CONTINUED_BREAK_WITHOUT_HALF_RETRACE_OR_RETEST"
        return "TWO_SIDED_CHOPPY", "RESIDUAL_COMPLETED_CONTINUED_PATH"

    if resolution == "FAILED_STRUCTURE_SWITCH":
        if break_formed:
            return "FALSE_CONTINUATION", "FAILED_AFTER_CONFIRMATION_EXTREME_BREAK"
        if barrier_order == "ADVERSE_FIRST":
            return "IMMEDIATE_FAILURE", "FAILED_NO_BREAK_AND_ADVERSE_0P50_ATR_FIRST"
        return "TWO_SIDED_CHOPPY", "RESIDUAL_COMPLETED_FAILED_PATH"
    raise ValueError(resolution)


def technical_issue(anatomy: Mapping[str, Any] | None, triggers: Mapping[str, Mapping[str, Any]]) -> str | None:
    if anatomy is None:
        return "MISSING_ANATOMY_ROW"
    if not bool(anatomy.get("complete_path_available")):
        return str(anatomy.get("unavailable_reason") or "INCOMPLETE_MOVEMENT_PATH")
    for name in REQUIRED_TRIGGERS:
        trigger = triggers.get(name)
        if trigger is None:
            return f"MISSING_TRIGGER::{name}"
        if trigger.get("status") not in {"FORMED", "NO_TRIGGER"}:
            return f"INVALID_TRIGGER_STATUS::{name}::{trigger.get('status')}"
        if trigger.get("status") == "FORMED" and not trigger.get("entry_at_utc"):
            return f"FORMED_TRIGGER_MISSING_TIMESTAMP::{name}"
    return None


def materialize(implementation: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paths = source_paths(implementation)
    features = pd.read_parquet(paths["features"])
    outcomes = pd.read_parquet(paths["outcomes"], columns=["pullback_id", "resolution", "resolution_hash"])
    census = pd.read_parquet(paths["census"], columns=["pullback_id", "pivot_price_e8"])
    population = features.merge(outcomes, on="pullback_id", how="inner", validate="one_to_one").merge(
        census, on="pullback_id", how="inner", validate="one_to_one"
    )
    population = population[
        population["scale"].eq("STANDARD")
        & population["feature_available"].fillna(False)
        & population["actionable_at_known"].fillna(False)
        & population["research_eligible"].fillna(False)
        & population["resolution"].isin(["CONTINUED", "FAILED_STRUCTURE_SWITCH"])
    ].copy()
    population["known_timestamp"] = pd.to_datetime(population["known_at_utc"], utc=True)
    if len(population) != 8_653 or population["known_timestamp"].max() >= pd.Timestamp("2025-01-01", tz="UTC"):
        raise ValueError({"population": len(population), "max_known": str(population["known_timestamp"].max())})

    population_ids = set(population["pullback_id"].astype(str))
    anatomy_rows = {
        str(row["pullback_id"]): row
        for row in pq.read_table(paths["anatomy"]).to_pylist()
        if str(row["pullback_id"]) in population_ids
    }
    trigger_rows: dict[str, dict[str, dict[str, Any]]] = {}
    for row in pq.read_table(paths["triggers"]).to_pylist():
        pullback_id = str(row["pullback_id"])
        if pullback_id not in population_ids:
            continue
        bucket = trigger_rows.setdefault(pullback_id, {})
        name = str(row["trigger"])
        if name in bucket:
            raise ValueError(f"Duplicate trigger row: {pullback_id} {name}")
        bucket[name] = row

    output: list[dict[str, Any]] = []
    for feature in population.sort_values(["known_at_utc", "timeframe", "pullback_id"]).to_dict("records"):
        pullback_id = str(feature["pullback_id"])
        anatomy = anatomy_rows.get(pullback_id)
        triggers = trigger_rows.get(pullback_id, {})
        issue = technical_issue(anatomy, triggers)
        known = pd.Timestamp(feature["known_at_utc"])
        base: dict[str, Any] = {
            "pullback_id": pullback_id,
            "timeframe": str(feature["timeframe"]),
            "direction": str(feature["direction"]),
            "segment_id": str(feature["segment_id"]),
            "known_at_utc": str(feature["known_at_utc"]),
            "calendar_year": int(known.year),
            "calendar_month": str(feature["known_at_utc"])[:7],
            "calendar_week": f"{known.isocalendar().year:04d}-W{known.isocalendar().week:02d}",
            "decision_date": str(feature["known_at_utc"])[:10],
            "resolution": str(feature["resolution"]),
            "archetype": "UNAVAILABLE_TECHNICAL" if issue else "",
            "assignment_reason": issue or "",
            "technical_available": issue is None,
            "technical_unavailable_reason": issue,
            "session_state": str(feature["session_state"]),
            "fundamental_alignment_state": str(feature["fundamental_alignment_state"]),
            "fundamental_score_aligned": finite(feature["fundamental_score_aligned"]),
            "fundamental_confidence": finite(feature["fundamental_confidence"]),
            "higher_timeframe_alignment_count": finite(feature["higher_timeframe_alignment_count"]),
            "higher_timeframe_known_count": finite(feature["higher_timeframe_known_count"]),
            "confirmation_body_state": str(feature["confirmation_body_state"]),
            "confirmation_displacement": bool(feature["confirmation_displacement"]),
            "confirmation_close_location_trend": finite(feature["confirmation_close_location_trend"]),
            "response_displacement_atr": finite(feature["response_displacement_atr"]),
            "response_efficiency": finite(feature["response_efficiency"]),
            "pivot_rejection_strong": bool(feature["pivot_rejection_strong"]),
            "reference_sweep_reclaim": bool(feature["reference_sweep_reclaim"]),
            "asia_sweep_reclaim": bool(feature["asia_sweep_reclaim"]),
            "prior_day_sweep_reclaim": bool(feature["prior_day_sweep_reclaim"]),
            "retracement_zone": str(feature["retracement_zone"]),
            "retracement_depth_atr": finite(feature["retracement_depth_atr"]),
            "trend_age_bars": int(feature["trend_age_bars"]),
            "prior_continuation_count": int(feature["prior_continuation_count"]),
            "cot_available": bool(feature["cot_available"]),
            "cot_managed_money_net_change_aligned": finite(feature["cot_managed_money_net_change_aligned"]),
            "feature_lineage_hash": str(feature["feature_lineage_hash"]),
            "resolution_hash": str(feature["resolution_hash"]),
        }
        if issue:
            base["case_hash"] = canonical_hash([pullback_id, "UNAVAILABLE_TECHNICAL", issue])
            output.append(base)
            continue

        assert anatomy is not None
        confirmation_break = triggers["CONFIRMATION_EXTREME_BREAK"]
        half_retrace = triggers["RESPONSE_HALF_RETRACE_LIMIT"]
        break_retest = triggers["BREAK_RETEST_CONFIRM"]
        archetype, reason = assign_archetype(
            str(feature["resolution"]),
            confirmation_break,
            half_retrace,
            break_retest,
            str(anatomy["barrier_0p5_order"]),
        )
        sign = 1.0 if feature["direction"] == "UP" else -1.0
        atr = float(anatomy["atr14_e8"])
        pivot_to_anchor_atr = sign * (int(anatomy["anchor_open_e8"]) - int(feature["pivot_price_e8"])) / atr
        pivot_to_max_atr = pivot_to_anchor_atr + float(anatomy["complete_mfe_atr"])
        base.update(
            archetype=archetype,
            assignment_reason=reason,
            confirmation_break_formed=formed(confirmation_break),
            confirmation_break_at_utc=confirmation_break.get("entry_at_utc"),
            half_retrace_formed=formed(half_retrace),
            half_retrace_at_utc=half_retrace.get("entry_at_utc"),
            break_retest_formed=formed(break_retest),
            break_retest_at_utc=break_retest.get("entry_at_utc"),
            reference_retest_formed=formed(triggers.get("REFERENCE_LEVEL_RETEST_LIMIT", {})),
            barrier_0p5_order=str(anatomy["barrier_0p5_order"]),
            atr14_usd_oz=atr / 1e8,
            pivot_to_max_atr=pivot_to_max_atr,
            pivot_to_max_usd_oz=pivot_to_max_atr * atr / 1e8,
            post_confirmation_mfe_atr=float(anatomy["complete_mfe_atr"]),
            post_confirmation_mae_atr=float(anatomy["complete_mae_atr"]),
            terminal_displacement_atr=float(anatomy["terminal_displacement_atr"]),
            minutes_to_max_favourable=int(anatomy["minutes_to_max_favourable"]),
            minutes_to_max_adverse=int(anatomy["minutes_to_max_adverse"]),
            oracle_r=pivot_to_max_atr if feature["resolution"] == "CONTINUED" else -1.0,
        )
        base["case_hash"] = canonical_hash(
            [pullback_id, archetype, reason, confirmation_break.get("trigger_lineage_hash"), half_retrace.get("trigger_lineage_hash"), break_retest.get("trigger_lineage_hash"), anatomy["anatomy_lineage_hash"]]
        )
        output.append(clean(base))

    identities = [row["pullback_id"] for row in output]
    if len(output) != 8_653 or len(set(identities)) != 8_653:
        raise ValueError("Assignment denominator is incomplete or duplicated")
    classified = [row for row in output if row["technical_available"]]
    if any(row["archetype"] not in ARCHETYPES for row in classified):
        raise ValueError("Technically available case lacks a frozen archetype")
    diagnostics = {
        "population": len(output),
        "classified": len(classified),
        "unavailable_technical": len(output) - len(classified),
        "unavailable_reasons": dict(sorted(Counter(row["technical_unavailable_reason"] for row in output if not row["technical_available"]).items())),
        "archetype_counts": dict(sorted(Counter(row["archetype"] for row in classified).items())),
        "identity_hash": canonical_hash(identities),
        "assignment_hash": canonical_hash([(row["pullback_id"], row["archetype"], row["case_hash"]) for row in output]),
    }
    return output, diagnostics


def true_pct(rows: list[Mapping[str, Any]], field: str) -> float | None:
    values = [bool(row[field]) for row in rows if row.get(field) is not None]
    return percent(sum(values), len(values))


def median(rows: list[Mapping[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if finite(row.get(field)) is not None]
    return rounded(np.median(values)) if values else None


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    classified = [row for row in cases if row["technical_available"]]
    output: list[dict[str, Any]] = []
    for timeframe in TIMEFRAMES:
        tf_rows = [row for row in classified if row["timeframe"] == timeframe]
        for archetype in ARCHETYPES:
            rows = [row for row in tf_rows if row["archetype"] == archetype]
            if not rows:
                continue
            oracle_values = [float(row["oracle_r"]) for row in rows]
            session_counts = dict(sorted(Counter(row["session_state"] for row in rows).items()))
            top_session, top_session_count = sorted(session_counts.items(), key=lambda item: (-item[1], item[0]))[0]
            htf_full = [
                row
                for row in rows
                if finite(row.get("higher_timeframe_known_count")) is not None
                and float(row["higher_timeframe_known_count"]) > 0
                and float(row["higher_timeframe_alignment_count"]) == float(row["higher_timeframe_known_count"])
            ]
            output.append(
                {
                    "timeframe": timeframe,
                    "archetype": archetype,
                    "cases": len(rows),
                    "share_of_classified_timeframe_pct": percent(len(rows), len(tf_rows)),
                    "dates": len({row["decision_date"] for row in rows}),
                    "weeks": len({row["calendar_week"] for row in rows}),
                    "cases_per_month": rounded(len(rows) / MONTHS),
                    "continued": sum(row["resolution"] == "CONTINUED" for row in rows),
                    "failed": sum(row["resolution"] == "FAILED_STRUCTURE_SWITCH" for row in rows),
                    "continuation_rate_pct": percent(sum(row["resolution"] == "CONTINUED" for row in rows), len(rows)),
                    "direction_counts": dict(sorted(Counter(row["direction"] for row in rows).items())),
                    "session_counts": session_counts,
                    "top_session": top_session,
                    "top_session_pct": percent(top_session_count, len(rows)),
                    "year_counts": {str(year): sum(row["calendar_year"] == year for row in rows) for year in (2021, 2022, 2023, 2024)},
                    "median_pivot_to_max_atr": median(rows, "pivot_to_max_atr"),
                    "median_pivot_to_max_usd_oz": median(rows, "pivot_to_max_usd_oz"),
                    "median_post_confirmation_mfe_atr": median(rows, "post_confirmation_mfe_atr"),
                    "median_post_confirmation_mae_atr": median(rows, "post_confirmation_mae_atr"),
                    "median_minutes_to_max_favourable": median(rows, "minutes_to_max_favourable"),
                    "oracle_net_r": rounded(sum(oracle_values)),
                    "oracle_expectancy_r": rounded(np.mean(oracle_values)),
                    "oracle_net_pnl_usd_at_50_risk": rounded(sum(oracle_values) * 50.0),
                    "oracle_average_monthly_pnl_usd_at_50_risk": rounded(sum(oracle_values) * 50.0 / MONTHS),
                    "confirmation_break_pct": true_pct(rows, "confirmation_break_formed"),
                    "half_retrace_pct": true_pct(rows, "half_retrace_formed"),
                    "break_retest_pct": true_pct(rows, "break_retest_formed"),
                    "reference_retest_pct": true_pct(rows, "reference_retest_formed"),
                    "median_response_displacement_atr": median(rows, "response_displacement_atr"),
                    "median_response_efficiency": median(rows, "response_efficiency"),
                    "median_confirmation_close_location": median(rows, "confirmation_close_location_trend"),
                    "confirmation_aligned_body_pct": percent(sum(row["confirmation_body_state"] == "ALIGNED" for row in rows), len(rows)),
                    "confirmation_displacement_pct": true_pct(rows, "confirmation_displacement"),
                    "pivot_rejection_strong_pct": true_pct(rows, "pivot_rejection_strong"),
                    "reference_sweep_reclaim_pct": true_pct(rows, "reference_sweep_reclaim"),
                    "asia_sweep_reclaim_pct": true_pct(rows, "asia_sweep_reclaim"),
                    "fundamental_aligned_pct": percent(sum(row["fundamental_alignment_state"] == "ALIGNED" for row in rows), len(rows)),
                    "fundamental_opposed_pct": percent(sum(row["fundamental_alignment_state"] == "OPPOSED" for row in rows), len(rows)),
                    "higher_timeframe_full_alignment_pct": percent(len(htf_full), len(rows)),
                    "cot_available_pct": true_pct(rows, "cot_available"),
                    "median_cot_net_change_aligned": median(rows, "cot_managed_money_net_change_aligned"),
                }
            )
    return {
        "classification": "POST_HOC_DEVELOPMENT_DESCRIPTION_ONLY",
        "forward_values_accessed": False,
        "classified_cases": len(classified),
        "unavailable_technical_cases": len(cases) - len(classified),
        "rows": output,
        "summary_hash": canonical_hash(output),
    }


def write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    table = pa.Table.from_pylist(rows)
    pq.write_table(
        table,
        path,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
        row_group_size=16_384,
    )


def md_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    def show(value: Any) -> str:
        if value is None:
            return "NA"
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    return [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
        *("| " + " | ".join(show(value) for value in row) + " |" for row in rows),
    ]


def report_text(diagnostics: Mapping[str, Any], summary: Mapping[str, Any]) -> str:
    rows = list(summary["rows"])
    lines = [
        "# Gold Pullback Behavioural Archetypes V1",
        "",
        "Status: **PASS_COMPLETE_DEVELOPMENT_ARCHETYPE_ATLAS**",
        "",
        "This is a deterministic post-hoc description of 2021-2024. It is not an edge or a live classifier. Calendar 2025 and 2026 were not accessed.",
        "",
        "## Coverage",
        "",
        f"The frozen denominator contains **{diagnostics['population']}** pullbacks. **{diagnostics['classified']}** had complete technical paths and received exactly one archetype; **{diagnostics['unavailable_technical']}** remain `UNAVAILABLE_TECHNICAL`.",
        "",
        "## Group frequency and movement",
        "",
    ]
    lines += md_table(
        ["TF", "Archetype", "Cases", "Share %", "Per month", "Continue %", "Median max ATR", "Median $/oz", "Post MFE", "Post MAE"],
        [
            [
                row["timeframe"], row["archetype"], row["cases"], row["share_of_classified_timeframe_pct"],
                row["cases_per_month"], row["continuation_rate_pct"], row["median_pivot_to_max_atr"],
                row["median_pivot_to_max_usd_oz"], row["median_post_confirmation_mfe_atr"],
                row["median_post_confirmation_mae_atr"],
            ]
            for row in rows
        ],
    )
    lines += [
        "",
        "## Oracle value at fixed $50 risk",
        "",
        "Continued cases receive their complete visual-pivot-to-maximum ATR movement; failed cases lose exactly 1R. Costs, overlap, confirmation delay and fill feasibility are excluded.",
        "",
    ]
    lines += md_table(
        ["TF", "Archetype", "Cases", "Oracle exp. R", "Oracle net R", "Oracle PnL", "Average/month"],
        [
            [
                row["timeframe"], row["archetype"], row["cases"], row["oracle_expectancy_r"],
                row["oracle_net_r"], row["oracle_net_pnl_usd_at_50_risk"],
                row["oracle_average_monthly_pnl_usd_at_50_risk"],
            ]
            for row in rows
        ],
    )
    lines += ["", "## Point-in-time fingerprints", ""]
    lines += md_table(
        ["TF", "Archetype", "Response ATR", "Confirm loc.", "Confirm disp. %", "Aligned body %", "Ref sweep %", "Fund. aligned %", "HTF full %", "Top session"],
        [
            [
                row["timeframe"], row["archetype"], row["median_response_displacement_atr"],
                row["median_confirmation_close_location"], row["confirmation_displacement_pct"],
                row["confirmation_aligned_body_pct"], row["reference_sweep_reclaim_pct"],
                row["fundamental_aligned_pct"], row["higher_timeframe_full_alignment_pct"],
                f"{row['top_session']} ({row['top_session_pct']:.1f}%)",
            ]
            for row in rows
        ],
    )
    lines += [
        "",
        "## Interpretation boundary",
        "",
        "The archetypes tell us how completed pullbacks behaved. The next research task is to determine whether facts known at the decision timestamp can identify the favourable archetypes with enough precision and support. No group may be treated as knowable live merely because its completed path has now been labelled.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    for path in (CONTRACT, PROTOCOL, *source_paths("primary").values(), *source_paths("reference").values()):
        if not path.exists():
            raise FileNotFoundError(path)
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol.get("status") != "FROZEN_BEFORE_ARCHETYPE_ASSIGNMENT":
        raise ValueError("Protocol is not frozen")

    primary_cases, primary_diagnostics = materialize("primary")
    reference_cases, reference_diagnostics = materialize("reference")
    if primary_cases != reference_cases or primary_diagnostics != reference_diagnostics:
        raise ValueError("Independent archetype assignments differ")
    primary_summary = summarize(primary_cases)
    reference_summary = summarize(reference_cases)
    if primary_summary != reference_summary:
        raise ValueError("Independent archetype summaries differ")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    primary_path = OUTPUT / "primary_archetypes.parquet"
    reference_path = OUTPUT / "reference_archetypes.parquet"
    write_parquet(primary_path, primary_cases)
    write_parquet(reference_path, reference_cases)
    if sha256_file(primary_path) != sha256_file(reference_path):
        raise ValueError("Independent Parquet outputs are not byte-identical")

    diagnostic_path = OUTPUT / "diagnostics.json"
    summary_path = OUTPUT / "atlas.json"
    diagnostic_path.write_text(json.dumps(clean(primary_diagnostics), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(json.dumps(clean(primary_summary), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT.write_text(report_text(primary_diagnostics, primary_summary), encoding="utf-8")
    state = {
        "version": "GOLD_PULLBACK_BEHAVIOURAL_ARCHETYPES_V1_STATE_1_0",
        "status": "PASS_COMPLETE_DEVELOPMENT_ARCHETYPE_ATLAS",
        "classification": "POST_HOC_DEVELOPMENT_DESCRIPTION_ONLY",
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "contract": {"path": str(CONTRACT.relative_to(ROOT)), "sha256": sha256_file(CONTRACT)},
        "protocol": {"path": str(PROTOCOL.relative_to(ROOT)), "sha256": sha256_file(PROTOCOL)},
        "source_lineage": {
            str(path.relative_to(ROOT)).replace("\\", "/"): {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in (*source_paths("primary").values(), *source_paths("reference").values())
        },
        "diagnostics": primary_diagnostics,
        "summary_hash": primary_summary["summary_hash"],
        "primary_reference_exact": True,
    }
    state_path = OUTPUT / "state.json"
    state_path.write_text(json.dumps(clean(state), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal = {
        "status": state["status"],
        "forward_values_accessed": False,
        "artifacts": {
            str(path.relative_to(ROOT)).replace("\\", "/"): {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in (primary_path, reference_path, diagnostic_path, summary_path, state_path, REPORT)
        },
    }
    seal_path = OUTPUT / "final_seal.json"
    seal_path.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": state["status"],
        "diagnostics": primary_diagnostics,
        "summary_hash": primary_summary["summary_hash"],
        "final_seal_sha256": sha256_file(seal_path),
        "forward_values_accessed": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
