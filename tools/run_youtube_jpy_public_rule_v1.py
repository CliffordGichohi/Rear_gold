#!/usr/bin/env python3
"""One controlled stage-gated falsification of the frozen YouTube JPY rule."""

from __future__ import annotations

import gc
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from youtube_jpy_public_rule_v1_engine import (
    attach_locations,
    build_stage1_cases,
    canonical_hash,
    evaluate_stage1,
    evaluate_stage2,
    evaluate_stage3,
    evaluate_stage4,
    identity_view,
    market_integrity,
    materialize_economics,
    materialize_triggers,
    prepare_market,
    read_market_primary,
    read_market_reference,
    read_news_primary,
    read_news_reference,
    rounded,
)


ROOT = Path(__file__).resolve().parents[1]
FREEZE = Path("research_manifests/youtube_jpy_public_rule_v1_preoutcome_freeze.json")
CERTIFICATION = Path("research_artifacts/multi_asset_macro_session_portfolio_v1_m2/certification.json")
CALENDAR = Path("data/mt5/calendar/mt5_us_calendar_raw.csv")
ARTIFACT_DIR = Path("research_artifacts/youtube_jpy_public_rule_v1")
REPORT = Path("YOUTUBE_JPY_PUBLIC_RULE_TRANSLATION_AND_FALSIFICATION_V1_REPORT.md")
FINAL_SEAL = Path("research_manifests/youtube_jpy_public_rule_translation_v1_final_seal.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new_json(relative: Path, value: Any) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(rounded(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def write_new_text(relative: Path, value: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(value.replace("\r\n", "\n"))


def verify_freeze() -> dict[str, Any]:
    freeze = json.loads((ROOT / FREEZE).read_text(encoding="utf-8"))
    if freeze.get("status") != "SEALED_AND_AUTHORIZED_FOR_ONE_DEVELOPMENT_OPENING":
        raise RuntimeError("Pre-outcome freeze is not authorized")
    failures = []
    for item in freeze["sealed_files"]:
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            failures.append(item["path"])
    if failures:
        raise RuntimeError(f"Pre-outcome seal verification failed: {failures}")
    return freeze


def source_paths() -> list[str]:
    certification = json.loads((ROOT / CERTIFICATION).read_text(encoding="utf-8"))
    records = [item for item in certification["instrument_certifications"] if item.get("mt5_symbol") == "USDJPY"]
    if len(records) != 1 or records[0].get("classification") != "PRESENT_AND_ADEQUATE":
        raise RuntimeError("Sealed USDJPY registry unavailable")
    return [item["path"].replace("\\", "/") for item in records[0]["coverage"]["source_files"]]


def _timestamp_checksum(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for stamp in frame["open_time"]:
        digest.update((pd.Timestamp(stamp).isoformat().replace("+00:00", "Z") + "\n").encode("utf-8"))
    return digest.hexdigest()


def _frame_checksum(frame: pd.DataFrame, columns: Sequence[str]) -> str:
    rows = []
    for record in frame.loc[:, list(columns)].to_dict("records"):
        rows.append(rounded(record))
    return canonical_hash(rows)


def prepared_diagnostics(prepared: Mapping[str, Any], integrity: Mapping[str, Any]) -> dict[str, Any]:
    daily_columns = (
        "eat_date", "open", "high", "low", "close", "rows", "first_utc", "last_utc",
        "complete", "true_range", "atr20",
    )
    m15_columns = (
        "m15_start", "open", "high", "low", "close", "rows", "first_utc", "last_utc",
        "complete", "end_time", "eat_date", "true_range", "atr14",
    )
    h1_columns = (
        "h1_start", "open", "high", "low", "close", "rows", "first_utc", "last_utc",
        "complete", "end_time", "eat_date",
    )
    sessions = {
        day: rounded({
            "rows": item["rows"],
            "complete": item["complete"],
            "first_utc": item["first_utc"],
            "last_utc": item["last_utc"],
        })
        for day, item in sorted(prepared["sessions"].items())
    }
    return rounded({
        "market_integrity": dict(integrity),
        "m1_rows": len(prepared["m1"]),
        "m1_identity_sha256": _timestamp_checksum(prepared["m1"]),
        "daily_rows": len(prepared["daily"]),
        "daily_sha256": _frame_checksum(prepared["daily"], daily_columns),
        "m15_rows": len(prepared["m15"]),
        "m15_sha256": _frame_checksum(prepared["m15"], m15_columns),
        "h1_rows": len(prepared["h1"]),
        "h1_sha256": _frame_checksum(prepared["h1"], h1_columns),
        "session_rows": len(sessions),
        "session_metadata_sha256": canonical_hash(sessions),
    })


def load_prepared(reader: str, paths: Sequence[str]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if reader == "PRIMARY_PANDAS":
        market = read_market_primary(ROOT, paths)
        news = read_news_primary(ROOT / CALENDAR)
    elif reader == "REFERENCE_CSV_STREAM":
        market = read_market_reference(ROOT, paths)
        news = read_news_reference(ROOT / CALENDAR)
    else:
        raise KeyError(reader)
    integrity = market_integrity(market)
    if not integrity["pass"]:
        raise RuntimeError(f"{reader} market integrity failed: {integrity}")
    prepared = prepare_market(market)
    diagnostics = prepared_diagnostics(prepared, integrity)
    del market
    gc.collect()
    return prepared, news, diagnostics


def run_for_reader(
    reader: str,
    paths: Sequence[str],
    stage: int,
    prior_rows: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    prepared, news, diagnostics = load_prepared(reader, paths)
    try:
        if stage == 1:
            rows = build_stage1_cases(prepared, news)
            result = evaluate_stage1(rows)
        elif stage == 2:
            if prior_rows is None:
                raise RuntimeError("Stage 2 requires frozen Stage-1 rows")
            rows = attach_locations(prior_rows, prepared["daily"])
            result = evaluate_stage2(rows)
        elif stage == 3:
            if prior_rows is None:
                raise RuntimeError("Stage 3 requires frozen Stage-2 rows")
            rows = materialize_triggers(prior_rows, prepared)
            result = evaluate_stage3(rows)
        elif stage == 4:
            if prior_rows is None:
                raise RuntimeError("Stage 4 requires frozen Stage-3 rows")
            rows = materialize_economics(prior_rows, prepared)
            result = evaluate_stage4(rows)
        else:
            raise KeyError(stage)
        return identity_view(rows), result, diagnostics, news
    finally:
        del prepared
        gc.collect()


def compare_stage(
    stage: int,
    paths: Sequence[str],
    primary_prior: Sequence[Mapping[str, Any]] | None,
    reference_prior: Sequence[Mapping[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    primary_rows, primary_result, primary_diag, primary_news = run_for_reader("PRIMARY_PANDAS", paths, stage, primary_prior)
    reference_rows, reference_result, reference_diag, reference_news = run_for_reader("REFERENCE_CSV_STREAM", paths, stage, reference_prior)
    reproduction = {
        "stage": stage,
        "primary_rows": len(primary_rows),
        "reference_rows": len(reference_rows),
        "primary_row_sha256": canonical_hash(primary_rows),
        "reference_row_sha256": canonical_hash(reference_rows),
        "rows_exact": primary_rows == reference_rows,
        "primary_result_sha256": canonical_hash(primary_result),
        "reference_result_sha256": canonical_hash(reference_result),
        "results_exact": primary_result == reference_result,
        "prepared_diagnostics_exact": primary_diag == reference_diag,
        "news_metadata_exact": primary_news == reference_news,
        "primary_prepared_diagnostics": primary_diag,
        "reference_prepared_diagnostics": reference_diag,
    }
    reproduction["pass"] = all(
        reproduction[key]
        for key in ("rows_exact", "results_exact", "prepared_diagnostics_exact", "news_metadata_exact")
    )
    if not reproduction["pass"]:
        write_new_json(ARTIFACT_DIR / f"stage_{stage}_reproduction_failure.json", reproduction)
        raise RuntimeError(f"Stage {stage} independent reproduction failed")
    write_new_json(ARTIFACT_DIR / f"stage_{stage}_primary_rows.json", primary_rows)
    write_new_json(ARTIFACT_DIR / f"stage_{stage}_reference_rows.json", reference_rows)
    write_new_json(ARTIFACT_DIR / f"stage_{stage}_result.json", primary_result)
    write_new_json(ARTIFACT_DIR / f"stage_{stage}_reproduction.json", reproduction)
    return primary_rows, reference_rows, primary_result, reference_result, reproduction


def make_report(final: Mapping[str, Any]) -> str:
    lines = [
        "# YouTube JPY Public-Rule Translation and Falsification V1 — Final Report",
        "",
        f"Formal verdict: **{final['verdict']}**",
        "",
        "This is a falsification of one frozen, public-rule translation. It is not a claim about any creator's private or undisclosed method.",
        "",
        "## Stage waterfall",
        "",
        "| Stage | Status | Support | Main estimate | Failed gates |",
        "|---|---:|---:|---|---|",
    ]
    for item in final["stages"]:
        result = item["result"]
        support = result.get("support")
        if isinstance(support, dict):
            support_text = str(support.get("overall"))
        else:
            support_text = str(support)
        if item["stage"] == 1:
            estimate = f"mean {result.get('mean_signed_displacement_pips')} pips; hit {result.get('direction_hit_rate')}"
        elif item["stage"] == 2:
            estimate = f"increment {result.get('incremental_mean_pips')} pips"
        elif item["stage"] == 3:
            estimate = f"gross expectancy {result.get('gross_expectancy_r')}R; PF {result.get('profit_factor')}"
        else:
            estimate = f"net expectancy {result.get('net_expectancy_r')}R; PF {result.get('profit_factor')}"
        lines.append(
            f"| {item['stage']} — {result.get('stage')} | {result.get('verdict')} | {support_text} | "
            f"{estimate} | {', '.join(result.get('failed_gates', [])) or 'none'} |"
        )
    lines.extend(
        [
            "",
            f"Early-stop stage: {final['early_stop_stage'] if final['early_stop_stage'] is not None else 'none'}.",
            f"2025: {final['forward_disposition']['calendar_2025']}.",
            f"2026: {final['forward_disposition']['calendar_2026']}.",
            "",
            "The primary pandas path and independent CSV-stream source path produced exact row, aggregate, result and verdict checksums at every stage reached. No rule was inverted, retuned, filtered, or repaired after outcome access. No data was acquired and no charge was incurred.",
            "",
        ]
    )
    return "\n".join(lines)


def seal_final() -> None:
    files = sorted(path for path in (ROOT / ARTIFACT_DIR).rglob("*") if path.is_file()) + [ROOT / REPORT, ROOT / FREEZE]
    records = [
        {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in files
    ]
    seal = {
        "version": "YOUTUBE_JPY_PUBLIC_RULE_TRANSLATION_V1_FINAL_SEAL_1_0",
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "status": "SEALED_FINAL",
        "files": records,
        "manifest_sha256": canonical_hash(records),
    }
    write_new_json(FINAL_SEAL, seal)


def main() -> int:
    for target in (ROOT / ARTIFACT_DIR, ROOT / REPORT, ROOT / FINAL_SEAL):
        if target.exists():
            raise RuntimeError(f"Append-only target already exists: {target.relative_to(ROOT)}")
    freeze = verify_freeze()
    paths = source_paths()
    write_new_json(
        ARTIFACT_DIR / "development_outcome_opening.json",
        {
            "version": "YOUTUBE_JPY_PUBLIC_RULE_TRANSLATION_V1_OUTCOME_OPENING_1_0",
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "authorized_by": FREEZE.as_posix(),
            "predecessor_manifest_sha256": freeze["sealed_files_manifest_sha256"],
            "controlled_opening_count": 1,
            "development_window": "2021-08-01T00:00:00Z/2025-01-01T00:00:00Z",
            "strict_credit_window": "2023-01-01/2024-12-31",
            "calendar_2025_opened": False,
            "calendar_2026_opened": False,
        },
    )

    stage_records = []
    primary_rows: list[dict[str, Any]] | None = None
    reference_rows: list[dict[str, Any]] | None = None
    early_stop = None
    for stage in (1, 2, 3, 4):
        primary_rows, reference_rows, result, _, reproduction = compare_stage(
            stage, paths, primary_rows, reference_rows
        )
        stage_records.append({"stage": stage, "result": result, "reproduction_sha256": canonical_hash(reproduction)})
        if result["verdict"] != "PASS":
            early_stop = stage
            break

    if early_stop is None:
        verdict = "PASS_STAGE_4_PUBLIC_RULE_ECONOMIC_EDGE"
        forward = {
            "calendar_2025": "POLICY_FROZEN_BUT_NO_EXISTING_AUTHORIZED_SOURCE_IN_THIS_CONTRACT",
            "calendar_2026": "POLICY_FROZEN_BUT_NO_EXISTING_AUTHORIZED_SOURCE_IN_THIS_CONTRACT",
        }
    else:
        names = {1: "CONTEXTUAL_PREMISE", 2: "LOCATION_INCREMENT", 3: "TRIGGER_INCREMENT", 4: "PUBLISHED_ECONOMICS"}
        verdict = f"REJECT_STAGE_{early_stop}_{names[early_stop]}"
        forward = {"calendar_2025": "LOCKED_NOT_OPENED", "calendar_2026": "LOCKED_NOT_OPENED"}
    final = {
        "version": "YOUTUBE_JPY_PUBLIC_RULE_TRANSLATION_V1_FINAL_RESULT_1_0",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "early_stop_stage": early_stop,
        "stages_reached": len(stage_records),
        "stages": stage_records,
        "forward_disposition": forward,
        "prospective_ledger": "NOT_INITIALIZED_UNLESS_STAGE_4_PASS",
        "optimization_performed": False,
        "rule_changes_after_opening": 0,
        "acquisition_performed": False,
        "charge_usd": 0.0,
        "independent_reproduction": "PASS_ALL_REACHED_STAGES",
    }
    write_new_json(ARTIFACT_DIR / "final_result.json", final)
    write_new_text(REPORT, make_report(final))
    seal_final()
    print(json.dumps({"verdict": verdict, "early_stop_stage": early_stop, "stages_reached": len(stage_records)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
