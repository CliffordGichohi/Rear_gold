#!/usr/bin/env python3
"""One-time exact historical replication under the sealed EER V1 protocol."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from external_evidence_replication_v1_engine import (
    CANDIDATE_ORDER,
    base_case_identity_view,
    build_base_cases,
    canonical_hash,
    evaluate_candidate,
    portfolio_metrics,
    read_required_anchors_primary,
    read_required_anchors_reference,
    rounded,
    select_portfolio,
    simulate_candidate,
    apply_holm_and_verdict,
)


ROOT = Path(__file__).resolve().parents[1]
FREEZE = Path("research_manifests/external_evidence_edge_replication_v1_preoutcome_freeze.json")
CERTIFICATION = Path("research_artifacts/multi_asset_macro_session_portfolio_v1_m2/certification.json")
ARTIFACT_DIR = Path("research_artifacts/external_evidence_edge_replication_v1")
SYMBOLS = ("US500", "USTEC", "XTIUSD")


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


def write_new_text(relative: Path, text: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text.replace("\r\n", "\n"))


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


def source_paths() -> dict[str, list[str]]:
    certification = json.loads((ROOT / CERTIFICATION).read_text(encoding="utf-8"))
    output: dict[str, list[str]] = {}
    for item in certification["instrument_certifications"]:
        symbol = item.get("mt5_symbol")
        if symbol in SYMBOLS:
            output[symbol] = [source["path"].replace("\\", "/") for source in item["coverage"]["source_files"]]
    if set(output) != set(SYMBOLS):
        raise RuntimeError("Required source path registry is incomplete")
    return output


def materialize(reader: str, paths: dict[str, list[str]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    base: dict[str, list[dict[str, Any]]] = {}
    diagnostics: dict[str, Any] = {"implementation": reader, "symbols": {}}
    for symbol in SYMBOLS:
        if reader == "PRIMARY_PANDAS":
            anchors = read_required_anchors_primary(ROOT, paths[symbol])
        elif reader == "REFERENCE_CSV_STREAM":
            anchors = read_required_anchors_reference(ROOT, paths[symbol])
        else:
            raise KeyError(reader)
        base[symbol] = build_base_cases(symbol, anchors)
        identity = base_case_identity_view(base[symbol])
        diagnostics["symbols"][symbol] = {
            "anchor_session_dates": len(anchors),
            "base_cases": len(base[symbol]),
            "base_case_checksum": canonical_hash(identity),
        }
    diagnostics["complete_checksum"] = canonical_hash(diagnostics["symbols"])
    return base, diagnostics


def evaluate(base: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    simulations = {candidate: simulate_candidate(candidate, base) for candidate in CANDIDATE_ORDER}
    initial = [evaluate_candidate(simulations[candidate]) for candidate in CANDIDATE_ORDER]
    results = apply_holm_and_verdict(initial)
    views = {
        candidate: {
            "candidate_id": candidate,
            "daily": simulations[candidate]["daily"],
            "legs": simulations[candidate]["legs"],
        }
        for candidate in CANDIDATE_ORDER
    }
    checksums = {
        candidate: {
            "daily_checksum": canonical_hash(views[candidate]["daily"]),
            "legs_checksum": canonical_hash(views[candidate]["legs"]),
            "result_checksum": canonical_hash(results[index]),
        }
        for index, candidate in enumerate(CANDIDATE_ORDER)
    }
    return views, checksums, results


def _report(final: dict[str, Any]) -> str:
    lines = [
        "# External Evidence Edge Replication and Transfer V1 — Final Report",
        "",
        f"Formal verdict: **{final['verdict']}**",
        "",
        "The three external rules were frozen before local market values were opened. All figures below are the unchanged 2022–2024 economic-gate results; partial 2021 data are descriptive only.",
        "",
        "| Candidate | Verdict | Dates | Win rate | Expectancy R | PF | Net R/month | USD/month | Max DD R | 1.5x-cost expectancy | Failed gates |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in final["candidate_results"]:
        eco = item["economics"]
        pf = "n/a" if eco["profit_factor"] is None else f"{eco['profit_factor']:.3f}"
        lines.append(
            f"| {item['candidate_id']} | {item['verdict']} | {item['population']['gate_dates']} | "
            f"{100 * eco['win_rate']:.2f}% | {eco['net_expectancy_r']:.4f} | {pf} | "
            f"{eco['net_r_per_month']:.3f} | ${eco['usd_per_month']:.2f} | {eco['maximum_drawdown_r']:.3f} | "
            f"{eco['stress_1p5_expectancy_r']:.4f} | {', '.join(item['failed_gates']) or 'none'} |"
        )
    lines.extend(
        [
            "",
            f"Passing candidates: {', '.join(final['passing_candidates']) if final['passing_candidates'] else 'none'}.",
            f"Frozen portfolio: {', '.join(final['selected_portfolio']) if final['selected_portfolio'] else 'none'}.",
            f"2025 disposition: {final['forward_disposition']['calendar_2025']}.",
            f"2026 disposition: {final['forward_disposition']['calendar_2026']}.",
            f"Prospective ledger: {final['prospective_disposition']}.",
            "",
            "No external rule was inverted, filtered, retuned, or cosmetically repaired. The primary pandas implementation and the independent CSV-stream implementation reproduced every base identity, direction, cost input, position size, daily result, statistic, and verdict exactly.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if (ROOT / ARTIFACT_DIR).exists():
        raise RuntimeError(f"Append-only branch artifact directory already exists: {ARTIFACT_DIR}")
    verify_freeze()
    paths = source_paths()
    write_new_json(
        ARTIFACT_DIR / "development_outcome_opening.json",
        {
            "version": "EER_V1_DEVELOPMENT_OUTCOME_OPENING_1_0",
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "opening_count": 1,
            "authorized_by": FREEZE.as_posix(),
            "window": "2021-08-01T00:00:00Z/2025-01-01T00:00:00Z",
            "forward_2025_opened": False,
            "forward_2026_opened": False,
        },
    )

    primary_base, primary_diagnostics = materialize("PRIMARY_PANDAS", paths)
    reference_base, reference_diagnostics = materialize("REFERENCE_CSV_STREAM", paths)
    base_agreement: dict[str, Any] = {}
    for symbol in SYMBOLS:
        primary_view = base_case_identity_view(primary_base[symbol])
        reference_view = base_case_identity_view(reference_base[symbol])
        base_agreement[symbol] = {
            "primary_checksum": canonical_hash(primary_view),
            "reference_checksum": canonical_hash(reference_view),
            "exact": primary_view == reference_view,
        }
    if not all(item["exact"] for item in base_agreement.values()):
        write_new_json(ARTIFACT_DIR / "formal_failure.json", {"verdict": "FAIL_INDEPENDENT_BASE_CASE_REPRODUCTION", "base_agreement": base_agreement})
        raise RuntimeError("Independent base-case reproduction failed")

    primary_views, primary_checksums, primary_results = evaluate(primary_base)
    reference_views, reference_checksums, reference_results = evaluate(reference_base)
    reproduction = {
        "base_agreement": base_agreement,
        "primary_diagnostics": primary_diagnostics,
        "reference_diagnostics": reference_diagnostics,
        "candidate_checksums_primary": primary_checksums,
        "candidate_checksums_reference": reference_checksums,
        "candidate_checksums_exact": primary_checksums == reference_checksums,
        "complete_results_exact": primary_results == reference_results,
    }
    reproduction["pass"] = reproduction["candidate_checksums_exact"] and reproduction["complete_results_exact"]
    if not reproduction["pass"]:
        write_new_json(ARTIFACT_DIR / "formal_failure.json", {"verdict": "FAIL_INDEPENDENT_RESULT_REPRODUCTION", "reproduction": reproduction})
        raise RuntimeError("Independent result reproduction failed")

    for candidate in CANDIDATE_ORDER:
        write_new_json(ARTIFACT_DIR / f"primary_{candidate.lower()}_paths.json", primary_views[candidate])
        write_new_json(ARTIFACT_DIR / f"reference_{candidate.lower()}_paths.json", reference_views[candidate])
    write_new_json(ARTIFACT_DIR / "primary_results.json", primary_results)
    write_new_json(ARTIFACT_DIR / "reference_results.json", reference_results)
    write_new_json(ARTIFACT_DIR / "independent_reproduction.json", reproduction)

    passing = [item["candidate_id"] for item in primary_results if item["verdict"] == "PASS"]
    selected = select_portfolio(primary_results)
    portfolio = portfolio_metrics(selected, {candidate: primary_views[candidate] for candidate in CANDIDATE_ORDER})
    if passing:
        verdict = "PASS_DEVELOPMENT_REPLICATION__FREE_FORWARD_SOURCE_REQUIRED"
        forward = {"calendar_2025": "NOT_OPENED_REQUIRED_FREE_SOURCE_UNAVAILABLE", "calendar_2026": "NOT_OPENED_REQUIRED_FREE_SOURCE_UNAVAILABLE"}
        prospective = "NOT_INITIALIZED_PENDING_UNCHANGED_EXPOSED_PERIOD_APPLICATION"
    else:
        verdict = "REJECT_NO_EXTERNALLY_EVIDENCED_RULE_REPLICATED_ECONOMICALLY"
        forward = {"calendar_2025": "LOCKED_NOT_OPENED_BY_FROZEN_POLICY", "calendar_2026": "LOCKED_NOT_OPENED_BY_FROZEN_POLICY"}
        prospective = "NOT_INITIALIZED_NO_PASSING_RULE"
    final = {
        "version": "EXTERNAL_EVIDENCE_EDGE_REPLICATION_V1_FINAL_RESULT_1_0",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "candidate_results": primary_results,
        "passing_candidates": passing,
        "selected_portfolio": selected,
        "portfolio": portfolio,
        "independent_reproduction": {"pass": True, "checksum": canonical_hash(reproduction)},
        "development_opening_count": 1,
        "forward_disposition": forward,
        "prospective_disposition": prospective,
        "paid_acquisition": False,
        "charge_usd": 0.0,
        "post_hoc_changes": 0,
    }
    write_new_json(ARTIFACT_DIR / "final_result.json", final)
    write_new_text(Path("EXTERNAL_EVIDENCE_EDGE_REPLICATION_AND_TRANSFER_V1_REPORT.md"), _report(final))

    seal_targets = sorted(
        [path for path in (ROOT / ARTIFACT_DIR).rglob("*") if path.is_file()]
        + [ROOT / "EXTERNAL_EVIDENCE_EDGE_REPLICATION_AND_TRANSFER_V1_REPORT.md"],
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )
    artifacts = [
        {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in seal_targets
    ]
    final_seal = {
        "version": "EXTERNAL_EVIDENCE_EDGE_REPLICATION_V1_FINAL_SEAL_1_0",
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "artifacts_sha256": canonical_hash(artifacts),
        "preoutcome_freeze_sha256": sha256_file(ROOT / FREEZE),
        "development_opening_count": 1,
        "forward_2025_opened": False,
        "forward_2026_opened": False,
        "charge_usd": 0.0,
    }
    write_new_json(ARTIFACT_DIR / "final_seal.json", final_seal)
    print(json.dumps({"verdict": verdict, "passing_candidates": passing, "results": primary_results, "portfolio": portfolio}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
