from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
MATCHED = ROOT / "research_artifacts" / "gold_matched_human_replay_v1"
CODEX = ROOT / "research_artifacts" / "gold_blind_codex_operator_replay_v1"
OUTPUT = MATCHED / "comparison"
RESULT_MD = ROOT / "GOLD_MATCHED_HUMAN_CODEX_REPLAY_COMPARISON_V1_RESULT.md"
HUMAN_VISIBLE = MATCHED / "ledgers" / "matched_human_visible_ledger.jsonl"
HUMAN_OUTCOMES = MATCHED / "outcome_vault" / "matched_human_outcome_ledger.jsonl"
CODEX_VISIBLE = CODEX / "ledgers" / "codex_blind_visible_ledger.jsonl"
CODEX_RESULTS = CODEX / "early_stop_case_results.json"
CODEX_FINAL_SEAL = CODEX / "early_stop_final_seal.json"
PROTOCOL = OUTPUT / "preopen_comparison_protocol.json"
AMENDMENT_A = OUTPUT / "preopen_comparison_protocol_amendment_a.json"
AMENDMENT_A_SEAL = OUTPUT / "preopen_comparison_protocol_amendment_a_implementation_seal.json"
OPENING = OUTPUT / "outcome_opening_receipt.json"
CASE_JSON = OUTPUT / "matched_case_comparison.json"
CASE_CSV = OUTPUT / "matched_case_comparison.csv"
REPRODUCTION = OUTPUT / "independent_reproduction.json"
FINAL_SEAL = OUTPUT / "final_seal.json"
ALIASES = [f"CBR-2022-{index:03d}" for index in range(1, 31)]
ZERO_HASH = "0" * 64
BOOTSTRAP_SEED = 20260818
BOOTSTRAP_RESAMPLES = 20_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def write_text_exclusive(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(value.rstrip() + "\n")


def parse_jsonl_bytes(value: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in value.decode("utf-8").splitlines() if line.strip()]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return parse_jsonl_bytes(path.read_bytes())


def verify_chain(rows: Sequence[Mapping[str, Any]], label: str) -> str:
    prior = ZERO_HASH
    for sequence, source in enumerate(rows, start=1):
        row = dict(source)
        if row.get("ledger_sequence") != sequence:
            raise RuntimeError(f"{label} ledger sequence differs at {sequence}")
        if row.get("prior_record_sha256") != prior:
            raise RuntimeError(f"{label} prior hash differs at {sequence}")
        record_hash = str(row.pop("record_sha256", ""))
        if canonical_hash(row) != record_hash:
            raise RuntimeError(f"{label} record hash differs at {sequence}")
        prior = record_hash
    return prior


def decision_map(rows: Sequence[Mapping[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    terminal_counts: Counter[str] = Counter()
    for row in rows:
        alias = str(row.get("case_alias", ""))
        if alias not in ALIASES:
            continue
        event_type = row.get("event_type")
        if event_type in {"DECISION_SEALED", "NO_TRADE_SEALED"}:
            if alias in decisions:
                raise RuntimeError(f"{label} has duplicate decision for {alias}")
            decision = dict(row["data"]["decision"])
            if canonical_hash(decision) != row["data"]["decision_sha256"]:
                raise RuntimeError(f"{label} decision hash differs for {alias}")
            decisions[alias] = decision
        elif event_type == "CASE_TERMINAL_HIDDEN":
            terminal_counts[alias] += 1
    if list(sorted(decisions)) != ALIASES:
        raise RuntimeError(f"{label} does not contain exactly the frozen 30 decisions")
    if any(terminal_counts[alias] != 1 for alias in ALIASES):
        raise RuntimeError(f"{label} does not contain exactly one terminal event per case")
    return decisions


def validate_predecessors() -> dict[str, Any]:
    state = read_json(MATCHED / "state.json")
    registry = read_json(MATCHED / "population_registry.private.json")
    certification = read_json(MATCHED / "stream_materialization_certification.json")
    if registry.get("case_count") != 30:
        raise RuntimeError("Matched registry case count differs")
    if [row["case_alias"] for row in registry["cases"]] != ALIASES:
        raise RuntimeError("Matched population identities differ")
    if canonical_hash(registry["cases"]) != registry["population_sha256"]:
        raise RuntimeError("Matched population hash differs")
    if state["population_sha256"] != registry["population_sha256"]:
        raise RuntimeError("Matched state population hash differs")
    for filename, expected in state["files"].items():
        if sha256_file(MATCHED / filename) != expected:
            raise RuntimeError(f"Matched predecessor differs: {filename}")
    if [row["case_alias"] for row in certification["case_files"]] != ALIASES:
        raise RuntimeError("Certified stream identities differ")
    stream_records = []
    for row in certification["case_files"]:
        if not row.get("bytes_exact"):
            raise RuntimeError(f"Primary/reference stream mismatch: {row['case_alias']}")
        for implementation in ("primary", "reference"):
            record = row[implementation]
            path = ROOT / record["path"]
            if path.stat().st_size != record["bytes"] or sha256_file(path) != record["sha256"]:
                raise RuntimeError(f"Certified stream differs: {record['path']}")
        stream_records.append(
            {
                "case_alias": row["case_alias"],
                "primary_sha256": row["primary"]["sha256"],
                "reference_sha256": row["reference"]["sha256"],
            }
        )
    codex_seal = read_json(CODEX_FINAL_SEAL)
    if codex_seal.get("outcome_opening_count") != 1:
        raise RuntimeError("Codex sealed outcome opening count differs")
    sealed_files = {item["path"]: item for item in codex_seal["files"]}
    codex_result_key = CODEX_RESULTS.relative_to(ROOT).as_posix()
    if codex_result_key not in sealed_files:
        raise RuntimeError("Codex result is absent from its final seal")
    expected_codex_result = sealed_files[codex_result_key]
    if file_record(CODEX_RESULTS) != expected_codex_result:
        raise RuntimeError("Codex sealed result differs")
    human_visible_rows = read_jsonl(HUMAN_VISIBLE)
    codex_visible_rows = read_jsonl(CODEX_VISIBLE)
    human_head = verify_chain(human_visible_rows, "human-visible")
    codex_head = verify_chain(codex_visible_rows, "codex-visible")
    human_decisions = decision_map(human_visible_rows, "human-visible")
    codex_decisions = decision_map(codex_visible_rows, "codex-visible")
    return {
        "state": state,
        "registry": registry,
        "certification": certification,
        "human_visible_rows": human_visible_rows,
        "codex_visible_rows": codex_visible_rows,
        "human_decisions": human_decisions,
        "codex_decisions": codex_decisions,
        "human_visible_head": human_head,
        "codex_visible_head": codex_head,
        "stream_records": stream_records,
        "codex_final_seal": codex_seal,
    }


def verify_frozen_implementation(protocol: Mapping[str, Any]) -> None:
    if not AMENDMENT_A_SEAL.exists():
        if file_record(Path(__file__).resolve()) != protocol["implementation"]:
            raise RuntimeError("Frozen matched comparison implementation differs")
        return
    amendment = read_json(AMENDMENT_A)
    seal = read_json(AMENDMENT_A_SEAL)
    if file_record(PROTOCOL) != seal["base_protocol"]:
        raise RuntimeError("Amendment A base protocol differs")
    if file_record(AMENDMENT_A) != seal["amendment"]:
        raise RuntimeError("Amendment A differs from its implementation seal")
    if amendment["single_permitted_change"] != seal["single_permitted_change"]:
        raise RuntimeError("Amendment A permitted change differs")
    if file_record(Path(__file__).resolve()) != seal["implementation_after"]:
        raise RuntimeError("Amendment A implementation differs")


def freeze() -> dict[str, Any]:
    if PROTOCOL.exists():
        raise RuntimeError("Matched comparison protocol is already frozen")
    if OPENING.exists() or CASE_JSON.exists() or FINAL_SEAL.exists() or RESULT_MD.exists():
        raise RuntimeError("Matched result artifacts already exist")
    predecessor = validate_predecessors()
    human_outcome_bytes = HUMAN_OUTCOMES.read_bytes()
    human_actions = Counter(value["action"] for value in predecessor["human_decisions"].values())
    codex_actions = Counter(value["action"] for value in predecessor["codex_decisions"].values())
    protocol = {
        "version": "GOLD_MATCHED_HUMAN_CODEX_REPLAY_COMPARISON_V1_PREOPEN_PROTOCOL_1_0",
        "frozen_at": utc_now(),
        "research_credit": "ZERO_CREDIT_MATCHED_METHOD_DIAGNOSTIC",
        "population": {
            "aliases": ALIASES,
            "population_sha256": predecessor["registry"]["population_sha256"],
            "dates": ["2022-01-03", "2022-02-16"],
        },
        "collection": {
            "human_decisions": 30,
            "human_actions": dict(sorted(human_actions.items())),
            "codex_decisions": 30,
            "codex_actions": dict(sorted(codex_actions.items())),
            "human_visible_ledger": file_record(HUMAN_VISIBLE),
            "human_visible_head_sha256": predecessor["human_visible_head"],
            "codex_visible_ledger": file_record(CODEX_VISIBLE),
            "codex_visible_head_sha256": predecessor["codex_visible_head"],
            "human_outcome_ledger_raw_preopen": {
                "path": HUMAN_OUTCOMES.relative_to(ROOT).as_posix(),
                "bytes": len(human_outcome_bytes),
                "sha256": sha256_bytes(human_outcome_bytes),
                "access": "RAW_BYTES_HASHED_ONLY_NOT_JSON_PARSED",
            },
            "codex_outcomes": {
                "disposition": "REUSE_ALREADY_OPENED_SEALED_EARLY_STOP_RESULT",
                "result": file_record(CODEX_RESULTS),
                "final_seal": file_record(CODEX_FINAL_SEAL),
                "additional_raw_opening_permitted": False,
            },
        },
        "frozen_metrics": {
            "economic": [
                "trades", "no_trades", "wins", "losses", "scratches", "win_rate",
                "net_pnl_usd", "net_r50", "expectancy_r50_per_trade", "profit_factor",
                "average_win_loss", "maximum_drawdown", "MFE_MAE", "resolution_counts",
                "1_5x_stressed_cost_expectancy",
            ],
            "uncertainty": {
                "method": "COMPLETED_CASE_NONPARAMETRIC_BOOTSTRAP",
                "seed": BOOTSTRAP_SEED,
                "resamples": BOOTSTRAP_RESAMPLES,
                "interval": 0.95,
            },
            "agreement": [
                "trade_vs_no_trade", "direction_when_both_trade", "decision_session",
                "macro_role", "higher_timeframe_state", "setup_class", "location_timeframe",
                "target_type",
            ],
            "path_diagnostics": {
                "bias_right_execution_loss": "NET_PNL_LT_0_AND_TERMINAL_DIRECTIONAL_MOVE_GT_0",
                "stopped_then_later_target": "STOPPED_AND_ORIGINAL_TARGET_TOUCHED_ONLY_ON_A_LATER_COMPLETED_M1_BAR",
                "one_r_available": "FULL_DAY_MFE_DIVIDED_BY_EFFECTIVE_FILL_TO_STOP_DISTANCE_GTE_1",
                "target_under_capture": "TARGET_HIT_AND_FULL_DAY_MFE_GTE_2_TIMES_EFFECTIVE_TARGET_DISTANCE",
                "same_bar_ambiguity": "STOP_FIRST_UNCHANGED",
                "interpretation": "DESCRIPTIVE_DIAGNOSTIC_NOT_CAUSAL_PROOF_OF_BAD_STOP_OR_TARGET",
            },
            "rubric_specificity": {
                "steps": [
                    "POINT_IN_TIME_MACRO_CONTEXT",
                    "HTF_STATE_AND_PREEXISTING_LOCATION",
                    "M15_AUCTION_TRANSITION",
                    "ACTIVE_SESSION_CONTEXT",
                    "STRUCTURAL_INVALIDATION",
                    "OPPOSING_LIQUIDITY_TARGET",
                ],
                "generic_markers": [
                    "unknown", "no eligible", "not applicable", "describe the visible",
                    "mapped sl", "mapped tp", "observation window completed",
                ],
                "keyword_matching": "CASE_INSENSITIVE_LITERAL_REGISTRY_FROZEN_IN_IMPLEMENTATION",
            },
        },
        "verdict_rules": {
            "formal_edge_verdict": "INCONCLUSIVE_ZERO_CREDIT_MATCHED_DIAGNOSTIC",
            "reason": "EXPOSED_MATCHED_SAMPLE_WITH_FEWER_THAN_30_HUMAN_TRADES_AND_ONE_CALENDAR_QUARTER",
            "comparative_label": "HIGHER_NET_R_OPERATOR_WITH_ALL_DIFFERENCES_REPORTED",
            "no_edge_claim_permitted": True,
            "calendar_2025": "LOCKED",
            "calendar_2026": "LOCKED",
        },
        "independent_reproduction": {
            "economic_metrics": "TWO_CODE_PATHS_SAME_SINGLE_OPENED_IMMUTABLE_PAYLOAD",
            "path_diagnostics": "CERTIFIED_PRIMARY_AND_REFERENCE_STREAMS",
            "exact_core_metric_and_CASE_CHECKSUM_AGREEMENT_REQUIRED": True,
        },
        "implementation": file_record(Path(__file__).resolve()),
        "predecessors": {
            "matched_state": file_record(MATCHED / "state.json"),
            "matched_stream_certification": file_record(MATCHED / "stream_materialization_certification.json"),
            "codex_final_seal": file_record(CODEX_FINAL_SEAL),
        },
    }
    write_json_exclusive(PROTOCOL, protocol)
    return protocol


def outcome_map(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any] | None]:
    resolved: dict[str, dict[str, Any]] = {}
    sealed: Counter[str] = Counter()
    no_trade: set[str] = set()
    for row in rows:
        alias = str(row.get("case_alias", ""))
        if alias not in ALIASES:
            raise RuntimeError(f"Human outcome contains an unexpected alias: {alias}")
        if row["event_type"] == "POSITION_RESOLVED":
            if alias in resolved:
                raise RuntimeError(f"Duplicate human resolution: {alias}")
            resolved[alias] = dict(row["data"])
        elif row["event_type"] == "CASE_OUTCOME_SEALED":
            sealed[alias] += 1
            if row["data"].get("state") == "NO_TRADE":
                no_trade.add(alias)
    if any(sealed[alias] != 1 for alias in ALIASES):
        raise RuntimeError("Human outcome ledger does not seal every frozen case exactly once")
    output: dict[str, dict[str, Any] | None] = {}
    for alias in ALIASES:
        if alias in no_trade:
            if alias in resolved:
                raise RuntimeError(f"No-trade case has a resolution: {alias}")
            output[alias] = None
        elif alias in resolved:
            output[alias] = resolved[alias]
        else:
            raise RuntimeError(f"Trade case lacks a resolution: {alias}")
    return output


def session_for(stream: Mapping[str, Any], timestamp: str) -> str:
    active = {
        row["session_code"]
        for row in stream["context_timeline"]["sessions"]
        if row["session_code"] in {"LONDON", "NEW_YORK"}
        and row["decision_at"] <= timestamp < row["observation_end"]
    }
    if active == {"LONDON", "NEW_YORK"}:
        return "LONDON_NEW_YORK_OVERLAP"
    if "LONDON" in active:
        return "LONDON"
    if "NEW_YORK" in active:
        return "NEW_YORK"
    return "NO_TRADE_TERMINAL"


def load_stream(path: Path, expected_stream_hash: str) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        stream = json.load(handle)
    supplied = stream.pop("stream_sha256")
    calculated = canonical_hash(stream)
    stream["stream_sha256"] = supplied
    if supplied != expected_stream_hash or calculated != supplied:
        raise RuntimeError(f"Private stream payload hash differs: {path}")
    return stream


def flat_human_case(
    alias: str,
    decision: Mapping[str, Any],
    outcome: Mapping[str, Any] | None,
    stream: Mapping[str, Any],
) -> dict[str, Any]:
    annotation = dict(decision["annotation"])
    if outcome is None:
        return {
            "case_alias": alias,
            "trading_date_utc": alias,
            "operator": "HUMAN",
            "action": "NO_TRADE",
            "is_trade": False,
            "submitted_at": decision["expected_cursor_at"],
            "session": "NO_TRADE_TERMINAL",
            "annotation": annotation,
            "entry": None,
            "stop": None,
            "target": None,
            "resolution_state": "NO_TRADE",
            "net_pnl_usd": 0.0,
            "r50": 0.0,
            "mfe_r50": 0.0,
            "mae_r50": 0.0,
            "raw_gross_pnl_usd": 0.0,
            "estimated_base_cost_usd": 0.0,
            "stressed_1_5x_cost_pnl_usd": 0.0,
            "post_fill_geometry_invalid": False,
        }
    direction = str(outcome["direction"])
    sign = 1 if direction == "LONG" else -1
    raw_gross = sign * (
        float(outcome["resolution"]["raw_exit_price"]) - float(outcome["fill"]["raw_price"])
    ) * int(outcome["quantity_ounces"])
    base_cost = raw_gross - float(outcome["net_pnl_usd"])
    return {
        "case_alias": alias,
        "trading_date_utc": alias,
        "operator": "HUMAN",
        "action": direction,
        "is_trade": True,
        "submitted_at": outcome["submitted_at"],
        "session": session_for(stream, str(outcome["submitted_at"])),
        "annotation": annotation,
        "entry": float(outcome["entry"]),
        "stop": float(outcome["stop"]),
        "target": float(outcome["target"]),
        "fill_at": outcome["fill"]["fill_at"],
        "fill_price": float(outcome["fill"]["actual_price"]),
        "quantity_ounces": int(outcome["quantity_ounces"]),
        "planned_risk_usd": float(outcome["planned_risk_usd"]),
        "exit_at": outcome["resolution"]["exit_at"],
        "exit_price": float(outcome["resolution"]["actual_exit_price"]),
        "resolution_state": outcome["resolution"]["state"],
        "net_pnl_usd": float(outcome["net_pnl_usd"]),
        "r50": float(outcome["r50"]),
        "mfe_r50": float(outcome["mfe_r50"]),
        "mae_r50": float(outcome["mae_r50"]),
        "raw_gross_pnl_usd": raw_gross,
        "estimated_base_cost_usd": base_cost,
        "stressed_1_5x_cost_pnl_usd": raw_gross - 1.5 * base_cost,
        "post_fill_geometry_invalid": bool(outcome["post_fill_geometry_invalid"]),
    }


def flat_codex_case(
    source: Mapping[str, Any],
    decision: Mapping[str, Any],
    stream: Mapping[str, Any],
) -> dict[str, Any]:
    output = dict(source)
    output["operator"] = "CODEX"
    output["annotation"] = dict(decision["annotation"])
    output["session"] = (
        session_for(stream, str(output["submitted_at"])) if output["is_trade"] else "NO_TRADE_TERMINAL"
    )
    return output


def path_diagnostic(case: Mapping[str, Any], stream: Mapping[str, Any]) -> dict[str, Any]:
    if not case["is_trade"]:
        return {
            "full_day_mfe_effective_r": None,
            "full_day_mae_effective_r": None,
            "terminal_directional_move_effective_r": None,
            "terminal_direction_correct": None,
            "stopped_then_later_target": False,
            "bias_right_execution_loss": False,
            "one_r_available_full_day": False,
            "target_capture_ratio_of_full_mfe": None,
            "target_under_capture": False,
        }
    direction = str(case["action"])
    sign = 1 if direction == "LONG" else -1
    fill = float(case["fill_price"])
    stop = float(case["stop"])
    target = float(case["target"])
    risk = sign * (fill - stop)
    bars = [
        row for row in stream["timeframes"]["1m"]
        if row["open_at"] >= case["fill_at"]
    ]
    if not bars or risk <= 0:
        return {
            "full_day_mfe_effective_r": None,
            "full_day_mae_effective_r": None,
            "terminal_directional_move_effective_r": None,
            "terminal_direction_correct": None,
            "stopped_then_later_target": False,
            "bias_right_execution_loss": False,
            "one_r_available_full_day": False,
            "target_capture_ratio_of_full_mfe": None,
            "target_under_capture": False,
        }
    if direction == "LONG":
        full_mfe = max(0.0, max(float(row["high"]) for row in bars) - fill)
        full_mae = max(0.0, fill - min(float(row["low"]) for row in bars))
        target_touched = lambda row: float(row["high"]) >= target
    else:
        full_mfe = max(0.0, fill - min(float(row["low"]) for row in bars))
        full_mae = max(0.0, max(float(row["high"]) for row in bars) - fill)
        target_touched = lambda row: float(row["low"]) <= target
    terminal_move = sign * (float(bars[-1]["close"]) - fill)
    after_exit = [row for row in bars if row["open_at"] >= case["exit_at"]]
    stopped_then_target = (
        case["resolution_state"] == "STOPPED" and any(target_touched(row) for row in after_exit)
    )
    target_distance = sign * (target - fill)
    full_target_hit = target_distance > 0 and any(target_touched(row) for row in bars)
    capture_ratio = target_distance / full_mfe if full_target_hit and full_mfe > 0 else None
    return {
        "full_day_mfe_effective_r": full_mfe / risk,
        "full_day_mae_effective_r": full_mae / risk,
        "terminal_directional_move_effective_r": terminal_move / risk,
        "terminal_direction_correct": terminal_move > 0,
        "stopped_then_later_target": stopped_then_target,
        "bias_right_execution_loss": float(case["net_pnl_usd"]) < 0 and terminal_move > 0,
        "one_r_available_full_day": full_mfe / risk >= 1.0,
        "target_capture_ratio_of_full_mfe": capture_ratio,
        "target_under_capture": (
            case["resolution_state"] == "TARGET_HIT"
            and target_distance > 0
            and full_mfe >= 2.0 * target_distance
        ),
    }


def wilson_interval(wins: int, trials: int) -> list[float] | None:
    if trials == 0:
        return None
    z = 1.959963984540054
    p = wins / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * trials)) / trials) / denominator
    return [center - margin, center + margin]


def bootstrap_interval(values: Sequence[float]) -> list[float] | None:
    if not values:
        return None
    generator = random.Random(BOOTSTRAP_SEED)
    count = len(values)
    means = sorted(
        sum(values[generator.randrange(count)] for _ in range(count)) / count
        for _ in range(BOOTSTRAP_RESAMPLES)
    )
    return [means[int(0.025 * BOOTSTRAP_RESAMPLES)], means[int(0.975 * BOOTSTRAP_RESAMPLES) - 1]]


def streak(values: Sequence[float], winning: bool) -> int:
    best = current = 0
    for value in values:
        matches = value > 0 if winning else value < 0
        current = current + 1 if matches else 0
        best = max(best, current)
    return best


def rounded(value: float | None, digits: int = 8) -> float | None:
    return None if value is None else round(value, digits)


def metric_summary(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    trades = [row for row in cases if row["is_trade"]]
    pnl = [float(row["net_pnl_usd"]) for row in trades]
    r_values = [float(row["r50"]) for row in trades]
    stress = [float(row["stressed_1_5x_cost_pnl_usd"]) for row in trades]
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    equity = peak = drawdown = 0.0
    for row in cases:
        equity += float(row["r50"])
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "cases": len(cases),
        "trades": len(trades),
        "no_trades": len(cases) - len(trades),
        "direction_counts": dict(sorted(Counter(row["action"] for row in trades).items())),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(pnl) - len(wins) - len(losses),
        "win_rate": rounded(len(wins) / len(trades) if trades else None),
        "win_rate_wilson_95": [rounded(value) for value in wilson_interval(len(wins), len(trades))] if trades else None,
        "net_pnl_usd": rounded(sum(pnl)),
        "net_r50": rounded(sum(r_values)),
        "normalized_account_return_pct": rounded(sum(pnl) / 100.0),
        "expectancy_usd_per_trade": rounded(statistics.mean(pnl) if pnl else None),
        "expectancy_r50_per_trade": rounded(statistics.mean(r_values) if r_values else None),
        "expectancy_r50_bootstrap_95": [rounded(value) for value in bootstrap_interval(r_values)] if r_values else None,
        "median_r50": rounded(statistics.median(r_values) if r_values else None),
        "average_win_usd": rounded(statistics.mean(wins) if wins else None),
        "average_loss_usd": rounded(statistics.mean(losses) if losses else None),
        "profit_factor": rounded(gross_profit / gross_loss if gross_loss else None),
        "gross_profit_usd": rounded(gross_profit),
        "gross_loss_usd": rounded(gross_loss),
        "stressed_1_5x_cost_pnl_usd": rounded(sum(stress)),
        "stressed_1_5x_cost_expectancy_r50": rounded(sum(stress) / 50.0 / len(trades) if trades else None),
        "maximum_drawdown_r50": rounded(drawdown),
        "maximum_drawdown_usd": rounded(drawdown * 50.0),
        "maximum_drawdown_pct_of_10000": rounded(drawdown * 0.5),
        "longest_win_streak": streak(pnl, True),
        "longest_loss_streak": streak(pnl, False),
        "mean_mfe_r50": rounded(statistics.mean(float(row["mfe_r50"]) for row in trades) if trades else None),
        "mean_mae_r50": rounded(statistics.mean(float(row["mae_r50"]) for row in trades) if trades else None),
        "resolution_counts": dict(sorted(Counter(row["resolution_state"] for row in cases).items())),
    }


def metric_summary_reference(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    trades = tuple(filter(lambda row: bool(row["is_trade"]), cases))
    positives = tuple(row for row in trades if float(row["net_pnl_usd"]) > 0)
    negatives = tuple(row for row in trades if float(row["net_pnl_usd"]) < 0)
    running = 0.0
    peaks = [0.0]
    drawdowns = [0.0]
    for row in cases:
        running = math.fsum((running, float(row["r50"])))
        peaks.append(max(peaks[-1], running))
        drawdowns.append(peaks[-1] - running)
    gross_profit = math.fsum(float(row["net_pnl_usd"]) for row in positives)
    gross_loss = -math.fsum(float(row["net_pnl_usd"]) for row in negatives)
    return {
        "cases": len(cases),
        "trades": len(trades),
        "no_trades": len(cases) - len(trades),
        "wins": len(positives),
        "losses": len(negatives),
        "scratches": len(trades) - len(positives) - len(negatives),
        "net_pnl_usd": rounded(math.fsum(float(row["net_pnl_usd"]) for row in trades)),
        "net_r50": rounded(math.fsum(float(row["r50"]) for row in trades)),
        "expectancy_r50_per_trade": rounded(math.fsum(float(row["r50"]) for row in trades) / len(trades) if trades else None),
        "profit_factor": rounded(gross_profit / gross_loss if gross_loss else None),
        "maximum_drawdown_r50": rounded(max(drawdowns)),
    }


TRIGGER_KEYWORDS = (
    "break", "bos", "shift", "sweep", "reclaim", "reject", "accept", "displacement",
    "retest", "momentum", "liquidity", "structure", "engulf", "close above", "close below",
)
LOCATION_KEYWORDS = (
    "support", "resistance", "liquidity", "premium", "discount", "range", "high", "low",
    "supply", "demand", "level", "zone",
)
INVALIDATION_KEYWORDS = (
    "structure", "break", "close", "accept", "swing", "high", "low", "zone", "origin",
)
TARGET_KEYWORDS = LOCATION_KEYWORDS
GENERIC_MARKERS = (
    "unknown", "no eligible", "not applicable", "describe the visible", "mapped sl", "mapped tp",
    "observation window completed",
)


def has_keyword(value: str, keywords: Iterable[str]) -> bool:
    lowered = value.lower()
    return any(keyword in lowered for keyword in keywords)


def specific(value: str, keywords: Iterable[str]) -> bool:
    lowered = value.strip().lower()
    return len(lowered) >= 20 and not any(marker in lowered for marker in GENERIC_MARKERS) and has_keyword(lowered, keywords)


def rubric(case: Mapping[str, Any]) -> dict[str, Any]:
    if not case["is_trade"]:
        return {"score": None, "steps": {}}
    annotation = case["annotation"]
    thesis = str(annotation.get("thesis") or "")
    location_text = " ".join((
        str(annotation.get("higher_timeframe_context") or ""),
        str(annotation.get("preexisting_location") or ""),
        thesis,
    ))
    trigger_text = " ".join((str(annotation.get("m15_transition") or ""), thesis))
    invalidation_text = " ".join((str(annotation.get("invalidation_condition") or ""), thesis))
    target_text = " ".join((str(annotation.get("target_logic") or ""), thesis))
    session_text = " ".join((str(annotation.get("session_liquidity_context") or ""), thesis))
    steps = {
        "macro_context": (
            str(annotation.get("macro_regime", "UNKNOWN")).upper() != "UNKNOWN"
            and str(annotation.get("macro_directional_pressure", "UNKNOWN")).upper() != "UNKNOWN"
        ),
        "htf_location": (
            str(annotation.get("higher_timeframe_state", "UNKNOWN")).upper() != "UNKNOWN"
            and specific(location_text, LOCATION_KEYWORDS)
        ),
        "m15_transition": specific(trigger_text, TRIGGER_KEYWORDS),
        "active_session": case["session"] in {"LONDON", "LONDON_NEW_YORK_OVERLAP", "NEW_YORK"}
        and specific(session_text, ("london", "new york", "session", "liquidity", "range", "sweep", "overlap")),
        "structural_invalidation": specific(invalidation_text, INVALIDATION_KEYWORDS),
        "liquidity_target": specific(target_text, TARGET_KEYWORDS),
    }
    return {"score": sum(steps.values()), "steps": steps}


def subset_metrics(cases: Mapping[str, Mapping[str, Any]], aliases: Sequence[str]) -> dict[str, Any]:
    return metric_summary([cases[alias] for alias in aliases])


def format_metric(value: Any, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def build_report(result: Mapping[str, Any]) -> str:
    human = result["metrics"]["human"]
    codex = result["metrics"]["codex"]
    agreement = result["agreement"]
    diagnostics = result["diagnostics"]
    disagreements = [row for row in result["cases"] if not row["action_agreement"]]
    lines = [
        "# Gold Matched Human-Codex Replay Comparison V1 — Result",
        "",
        "## Verdict",
        "",
        f"**{result['verdict']['formal']}**",
        "",
        result["verdict"]["plain_language"],
        "",
        "This is a zero-credit matched diagnostic over 30 already exposed days. It can diagnose method and execution differences; it cannot validate a durable edge.",
        "",
        "## Performance",
        "",
        "| Metric | Human | Codex |",
        "|---|---:|---:|",
        f"| Trades / no-trades | {human['trades']} / {human['no_trades']} | {codex['trades']} / {codex['no_trades']} |",
        f"| Wins / losses / scratches | {human['wins']} / {human['losses']} / {human['scratches']} | {codex['wins']} / {codex['losses']} / {codex['scratches']} |",
        f"| Win rate | {format_metric(100 * human['win_rate'])}% | {format_metric(100 * codex['win_rate'])}% |",
        f"| Net R | {format_metric(human['net_r50'])} | {format_metric(codex['net_r50'])} |",
        f"| Net PnL | ${format_metric(human['net_pnl_usd'])} | ${format_metric(codex['net_pnl_usd'])} |",
        f"| Expectancy / trade | {format_metric(human['expectancy_r50_per_trade'], 3)}R | {format_metric(codex['expectancy_r50_per_trade'], 3)}R |",
        f"| Profit factor | {format_metric(human['profit_factor'], 3)} | {format_metric(codex['profit_factor'], 3)} |",
        f"| 95% bootstrap expectancy | {human['expectancy_r50_bootstrap_95']} | {codex['expectancy_r50_bootstrap_95']} |",
        f"| Max drawdown | {format_metric(human['maximum_drawdown_r50'])}R | {format_metric(codex['maximum_drawdown_r50'])}R |",
        f"| 1.5x-cost expectancy | {format_metric(human['stressed_1_5x_cost_expectancy_r50'], 3)}R | {format_metric(codex['stressed_1_5x_cost_expectancy_r50'], 3)}R |",
        "",
        "## Matched-decision agreement",
        "",
        f"- Same exact action: {agreement['exact_action']['count']} / 30 ({format_metric(100 * agreement['exact_action']['rate'])}%).",
        f"- Same trade/no-trade choice: {agreement['trade_choice']['count']} / 30 ({format_metric(100 * agreement['trade_choice']['rate'])}%).",
        f"- Both traded: {agreement['both_trade']['count']}; same direction in {agreement['same_direction_when_both_trade']['count']} / {agreement['both_trade']['count']}.",
        f"- Human-only trades: {agreement['human_only_trade']['count']}; Codex-only trades: {agreement['codex_only_trade']['count']}; both no-trade: {agreement['both_no_trade']['count']}.",
        "",
        "## Execution diagnosis",
        "",
        f"- Human losses with direction favourable by the frozen day close: {diagnostics['human']['bias_right_execution_loss']}.",
        f"- Human stops followed by the original target on a later completed M1 bar: {diagnostics['human']['stopped_then_later_target']}.",
        f"- Human trades with at least +1 effective R available at some point: {diagnostics['human']['one_r_available_full_day']} / {human['trades']}.",
        f"- Human targets that hit but captured at most half of the later full-day MFE: {diagnostics['human']['target_under_capture']}.",
        f"- Human post-fill geometry failures: {diagnostics['human']['post_fill_geometry_invalid']}.",
        f"- Codex stops followed by the original target later: {diagnostics['codex']['stopped_then_later_target']}.",
        "",
        "These path labels are diagnostics, not hindsight permission to widen every stop or target. A stopped-then-target case may reflect premature entry, invalidation geometry, or a genuinely separate later setup.",
        "",
        "## Rubric specificity",
        "",
        f"- Human mean observable six-step specificity: {format_metric(result['rubric']['human_mean_score'])} / 6.",
        f"- Codex mean observable six-step specificity: {format_metric(result['rubric']['codex_mean_score'])} / 6.",
        "- This measures whether the sealed text documents each step, not whether eloquent text predicts price.",
        "",
        "## Action disagreements",
        "",
        "| Case | Date | Human | Human R | Codex | Codex R |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in disagreements:
        lines.append(
            f"| {row['case_alias']} | {row['trading_date_utc']} | {row['human']['action']} | "
            f"{format_metric(row['human']['r50'])} | {row['codex']['action']} | {format_metric(row['codex']['r50'])} |"
        )
    lines.extend(
        [
            "",
            "## What the sample supports",
            "",
            *[f"- {item}" for item in result["verdict"]["findings"]],
            "",
            "## What it does not support",
            "",
            "- It does not prove a live edge: the dates and aggregate Codex result were already exposed.",
            "- It does not support retuning from 16 human trades as though they were an independent sample.",
            "- It does not inspect 2025 or 2026, which remain locked.",
            "",
            "Detailed case rows and every rationale are preserved in `research_artifacts/gold_matched_human_replay_v1/comparison/matched_case_comparison.json`.",
        ]
    )
    return "\n".join(lines)


def analyze() -> dict[str, Any]:
    if not PROTOCOL.exists():
        raise RuntimeError("Freeze the matched comparison protocol before opening outcomes")
    if OPENING.exists() or CASE_JSON.exists() or FINAL_SEAL.exists() or RESULT_MD.exists():
        raise RuntimeError("The single controlled matched outcome opening was already attempted")
    protocol = read_json(PROTOCOL)
    verify_frozen_implementation(protocol)
    predecessor = validate_predecessors()
    if file_record(HUMAN_VISIBLE) != protocol["collection"]["human_visible_ledger"]:
        raise RuntimeError("Human visible ledger changed after the freeze")
    raw_expected = protocol["collection"]["human_outcome_ledger_raw_preopen"]
    human_outcome_bytes = HUMAN_OUTCOMES.read_bytes()
    if len(human_outcome_bytes) != raw_expected["bytes"] or sha256_bytes(human_outcome_bytes) != raw_expected["sha256"]:
        raise RuntimeError("Human outcome vault changed after the freeze")
    opening = {
        "version": "GOLD_MATCHED_HUMAN_CODEX_REPLAY_COMPARISON_V1_OUTCOME_OPENING_1_0",
        "opened_at": utc_now(),
        "human_outcome_opening_count": 1,
        "human_outcome_ledger": {
            "path": raw_expected["path"],
            "bytes": len(human_outcome_bytes),
            "sha256": sha256_bytes(human_outcome_bytes),
        },
        "codex_disposition": "REUSED_PRIOR_SEALED_RESULT_WITHOUT_RAW_LEDGER_REOPENING",
        "protocol": file_record(PROTOCOL),
        "preopen_amendment_a": file_record(AMENDMENT_A),
        "preopen_amendment_a_implementation_seal": file_record(AMENDMENT_A_SEAL),
    }
    write_json_exclusive(OPENING, opening)

    human_outcome_rows = parse_jsonl_bytes(human_outcome_bytes)
    human_outcome_head = verify_chain(human_outcome_rows, "human-outcome")
    human_outcomes = outcome_map(human_outcome_rows)
    codex_result = read_json(CODEX_RESULTS)
    codex_sources = {row["case_alias"]: row for row in codex_result["cases"]}
    if list(sorted(codex_sources)) != ALIASES:
        raise RuntimeError("Sealed Codex result does not cover the matched population")

    human_cases: dict[str, dict[str, Any]] = {}
    codex_cases: dict[str, dict[str, Any]] = {}
    primary_diagnostics: dict[str, dict[str, Any]] = {}
    reference_diagnostics: dict[str, dict[str, Any]] = {}
    session_dates: dict[str, str] = {}
    certification_rows = {row["case_alias"]: row for row in predecessor["certification"]["case_files"]}
    for alias in ALIASES:
        source = certification_rows[alias]
        primary = load_stream(ROOT / source["primary"]["path"], source["primary"]["stream_sha256"])
        human_case = flat_human_case(alias, predecessor["human_decisions"][alias], human_outcomes[alias], primary)
        codex_case = flat_codex_case(codex_sources[alias], predecessor["codex_decisions"][alias], primary)
        trading_date = str(primary["trading_date_utc"])
        session_dates[alias] = trading_date
        human_case["trading_date_utc"] = trading_date
        codex_case["trading_date_utc"] = trading_date
        human_cases[alias] = human_case
        codex_cases[alias] = codex_case
        primary_diagnostics[alias] = {
            "human": path_diagnostic(human_case, primary),
            "codex": path_diagnostic(codex_case, primary),
        }
        reference = load_stream(ROOT / source["reference"]["path"], source["reference"]["stream_sha256"])
        reference_diagnostics[alias] = {
            "human": path_diagnostic(human_case, reference),
            "codex": path_diagnostic(codex_case, reference),
        }
        del primary
        del reference
    if canonical_hash(primary_diagnostics) != canonical_hash(reference_diagnostics):
        raise RuntimeError("Primary/reference path diagnostics differ")

    human_ordered = [human_cases[alias] for alias in ALIASES]
    codex_ordered = [codex_cases[alias] for alias in ALIASES]
    human_metrics = metric_summary(human_ordered)
    codex_metrics = metric_summary(codex_ordered)
    core_fields = (
        "cases", "trades", "no_trades", "wins", "losses", "scratches", "net_pnl_usd",
        "net_r50", "expectancy_r50_per_trade", "profit_factor", "maximum_drawdown_r50",
    )
    human_reference = metric_summary_reference(human_ordered)
    codex_reference = metric_summary_reference(codex_ordered)
    if any(human_metrics[key] != human_reference[key] for key in core_fields):
        raise RuntimeError("Independent human economic metrics differ")
    if any(codex_metrics[key] != codex_reference[key] for key in core_fields):
        raise RuntimeError("Independent Codex economic metrics differ")
    sealed_codex = codex_result["all_30_sensitivity"]
    sealed_comparison_fields = (
        "cases", "trades", "no_trades", "wins", "losses", "scratches", "net_pnl_usd",
        "net_r50", "expectancy_r50_per_trade", "profit_factor",
    )
    def codex_prior_field_reproduced(key: str) -> bool:
        if key == "profit_factor":
            return rounded(codex_metrics[key], 6) == sealed_codex[key]
        return codex_metrics[key] == sealed_codex[key]

    if any(not codex_prior_field_reproduced(key) for key in sealed_comparison_fields):
        raise RuntimeError("Reproduced Codex metrics differ from the prior final seal")

    cases = []
    groups: defaultdict[str, list[str]] = defaultdict(list)
    agreement_counts: Counter[str] = Counter()
    human_rubric_scores = []
    codex_rubric_scores = []
    for alias in ALIASES:
        human = human_cases[alias]
        codex = codex_cases[alias]
        human_rubric = rubric(human)
        codex_rubric = rubric(codex)
        if human_rubric["score"] is not None:
            human_rubric_scores.append(human_rubric["score"])
        if codex_rubric["score"] is not None:
            codex_rubric_scores.append(codex_rubric["score"])
        both_trade = human["is_trade"] and codex["is_trade"]
        if human["action"] == codex["action"]:
            agreement_counts["exact_action"] += 1
        if human["is_trade"] == codex["is_trade"]:
            agreement_counts["trade_choice"] += 1
        if both_trade:
            agreement_counts["both_trade"] += 1
            if human["action"] == codex["action"]:
                agreement_counts["same_direction"] += 1
                groups["both_trade_same_direction"].append(alias)
            else:
                groups["both_trade_opposite_direction"].append(alias)
        elif human["is_trade"]:
            agreement_counts["human_only_trade"] += 1
            groups["human_only_trade"].append(alias)
        elif codex["is_trade"]:
            agreement_counts["codex_only_trade"] += 1
            groups["codex_only_trade"].append(alias)
        else:
            agreement_counts["both_no_trade"] += 1
            groups["both_no_trade"].append(alias)
        annotation_agreement = {}
        for field in ("macro_role", "higher_timeframe_state", "setup_class", "location_timeframe", "target_type"):
            annotation_agreement[field] = human["annotation"].get(field) == codex["annotation"].get(field)
        cases.append(
            {
                "case_alias": alias,
                "trading_date_utc": session_dates[alias],
                "action_agreement": human["action"] == codex["action"],
                "trade_choice_agreement": human["is_trade"] == codex["is_trade"],
                "same_direction_when_both_trade": both_trade and human["action"] == codex["action"],
                "session_agreement_when_both_trade": both_trade and human["session"] == codex["session"],
                "annotation_agreement": annotation_agreement,
                "human": {**human, "path_diagnostic": primary_diagnostics[alias]["human"], "rubric": human_rubric},
                "codex": {**codex, "path_diagnostic": primary_diagnostics[alias]["codex"], "rubric": codex_rubric},
                "human_minus_codex_r50": rounded(float(human["r50"]) - float(codex["r50"])),
            }
        )

    both_trade = agreement_counts["both_trade"]
    agreement = {
        "exact_action": {"count": agreement_counts["exact_action"], "rate": agreement_counts["exact_action"] / 30},
        "trade_choice": {"count": agreement_counts["trade_choice"], "rate": agreement_counts["trade_choice"] / 30},
        "both_trade": {"count": both_trade},
        "same_direction_when_both_trade": {
            "count": agreement_counts["same_direction"],
            "rate": agreement_counts["same_direction"] / both_trade if both_trade else None,
        },
        "human_only_trade": {"count": agreement_counts["human_only_trade"]},
        "codex_only_trade": {"count": agreement_counts["codex_only_trade"]},
        "both_no_trade": {"count": agreement_counts["both_no_trade"]},
    }
    diagnostics = {}
    for operator, operator_cases in (("human", human_cases), ("codex", codex_cases)):
        path_rows = [primary_diagnostics[alias][operator] for alias in ALIASES]
        diagnostics[operator] = {
            "bias_right_execution_loss": sum(bool(row["bias_right_execution_loss"]) for row in path_rows),
            "stopped_then_later_target": sum(bool(row["stopped_then_later_target"]) for row in path_rows),
            "one_r_available_full_day": sum(bool(row["one_r_available_full_day"]) for row in path_rows),
            "target_under_capture": sum(bool(row["target_under_capture"]) for row in path_rows),
            "terminal_direction_correct": sum(row["terminal_direction_correct"] is True for row in path_rows),
            "terminal_direction_wrong": sum(row["terminal_direction_correct"] is False for row in path_rows),
            "post_fill_geometry_invalid": sum(bool(row["post_fill_geometry_invalid"]) for row in operator_cases.values()),
        }
    subset_results = {}
    for group, aliases in sorted(groups.items()):
        subset_results[group] = {
            "aliases": aliases,
            "human": subset_metrics(human_cases, aliases),
            "codex": subset_metrics(codex_cases, aliases),
        }

    comparative = "HUMAN_OUTPERFORMED_CODEX" if human_metrics["net_r50"] > codex_metrics["net_r50"] else "CODEX_OUTPERFORMED_HUMAN"
    findings = [
        f"{comparative.replace('_', ' ').title()}: human {human_metrics['net_r50']:.2f}R versus Codex {codex_metrics['net_r50']:.2f}R.",
        f"The human operator was more selective: {human_metrics['trades']} trades versus {codex_metrics['trades']}.",
        f"Human and Codex chose the exact same action on {agreement_counts['exact_action']} of 30 cases.",
        f"Human stopped-then-later-target cases: {diagnostics['human']['stopped_then_later_target']}; target-under-capture cases: {diagnostics['human']['target_under_capture']}.",
        "The human sample remains formally inconclusive because it has fewer than 30 trades, covers one quarter, and is zero-credit exposed calibration.",
    ]
    result = {
        "version": "GOLD_MATCHED_HUMAN_CODEX_REPLAY_COMPARISON_V1_RESULT_1_0",
        "completed_at": utc_now(),
        "research_credit": "ZERO_CREDIT_MATCHED_METHOD_DIAGNOSTIC",
        "outcome_opening": file_record(OPENING),
        "human_outcome_ledger_head_sha256": human_outcome_head,
        "metrics": {"human": human_metrics, "codex": codex_metrics},
        "agreement": agreement,
        "subsets": subset_results,
        "diagnostics": diagnostics,
        "rubric": {
            "human_mean_score": rounded(statistics.mean(human_rubric_scores) if human_rubric_scores else None),
            "codex_mean_score": rounded(statistics.mean(codex_rubric_scores) if codex_rubric_scores else None),
        },
        "verdict": {
            "formal": "INCONCLUSIVE_ZERO_CREDIT_MATCHED_DIAGNOSTIC",
            "comparative": comparative,
            "plain_language": (
                "The comparison can tell us which operator handled these 30 exposed days better and where value was lost, "
                "but it cannot promote either result to a validated trading edge."
            ),
            "findings": findings,
            "edge_claim_permitted": False,
            "calendar_2025": "LOCKED_NOT_INSPECTED",
            "calendar_2026": "LOCKED_NOT_INSPECTED",
        },
        "cases": cases,
    }
    write_json_exclusive(CASE_JSON, result)
    with CASE_CSV.open("x", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "case_alias", "trading_date_utc", "human_action", "human_session", "human_r50",
            "human_resolution", "human_bias_right_execution_loss", "human_stopped_then_later_target",
            "human_target_under_capture", "codex_action", "codex_session", "codex_r50",
            "codex_resolution", "action_agreement", "human_minus_codex_r50",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in cases:
            writer.writerow(
                {
                    "case_alias": row["case_alias"],
                    "trading_date_utc": row["trading_date_utc"],
                    "human_action": row["human"]["action"],
                    "human_session": row["human"]["session"],
                    "human_r50": row["human"]["r50"],
                    "human_resolution": row["human"]["resolution_state"],
                    "human_bias_right_execution_loss": row["human"]["path_diagnostic"]["bias_right_execution_loss"],
                    "human_stopped_then_later_target": row["human"]["path_diagnostic"]["stopped_then_later_target"],
                    "human_target_under_capture": row["human"]["path_diagnostic"]["target_under_capture"],
                    "codex_action": row["codex"]["action"],
                    "codex_session": row["codex"]["session"],
                    "codex_r50": row["codex"]["r50"],
                    "codex_resolution": row["codex"]["resolution_state"],
                    "action_agreement": row["action_agreement"],
                    "human_minus_codex_r50": row["human_minus_codex_r50"],
                }
            )
    reproduction = {
        "version": "GOLD_MATCHED_HUMAN_CODEX_REPLAY_COMPARISON_V1_REPRODUCTION_1_0",
        "economic_core_fields": list(core_fields),
        "human_primary_reference_exact": all(human_metrics[key] == human_reference[key] for key in core_fields),
        "codex_primary_reference_exact": all(codex_metrics[key] == codex_reference[key] for key in core_fields),
        "codex_prior_sealed_result_reproduced": all(codex_prior_field_reproduced(key) for key in sealed_comparison_fields),
        "codex_prior_profit_factor_comparison_precision": 6,
        "path_primary_reference_checksum_exact": canonical_hash(primary_diagnostics) == canonical_hash(reference_diagnostics),
        "path_diagnostic_checksum": canonical_hash(primary_diagnostics),
        "case_result_checksum": canonical_hash(cases),
    }
    write_json_exclusive(REPRODUCTION, reproduction)
    write_text_exclusive(RESULT_MD, build_report(result))
    final = {
        "version": "GOLD_MATCHED_HUMAN_CODEX_REPLAY_COMPARISON_V1_FINAL_SEAL_1_0",
        "sealed_at": utc_now(),
        "verdict": result["verdict"]["formal"],
        "comparative": comparative,
        "human_outcome_opening_count": 1,
        "codex_additional_raw_outcome_opening_count": 0,
        "files": [
            file_record(PROTOCOL), file_record(AMENDMENT_A), file_record(AMENDMENT_A_SEAL),
            file_record(OPENING), file_record(CASE_JSON), file_record(CASE_CSV),
            file_record(REPRODUCTION), file_record(RESULT_MD),
        ],
        "independent_reproduction": reproduction,
        "calendar_2025": "LOCKED_NOT_INSPECTED",
        "calendar_2026": "LOCKED_NOT_INSPECTED",
    }
    write_json_exclusive(FINAL_SEAL, final)
    return result


def self_test() -> dict[str, Any]:
    cases = [
        {
            "is_trade": True, "action": "LONG", "net_pnl_usd": 50.0, "r50": 1.0,
            "stressed_1_5x_cost_pnl_usd": 45.0, "mfe_r50": 1.2, "mae_r50": 0.2,
            "resolution_state": "TARGET_HIT",
        },
        {
            "is_trade": True, "action": "SHORT", "net_pnl_usd": -25.0, "r50": -0.5,
            "stressed_1_5x_cost_pnl_usd": -30.0, "mfe_r50": 0.3, "mae_r50": 0.6,
            "resolution_state": "STOPPED",
        },
        {
            "is_trade": False, "action": "NO_TRADE", "net_pnl_usd": 0.0, "r50": 0.0,
            "stressed_1_5x_cost_pnl_usd": 0.0, "mfe_r50": 0.0, "mae_r50": 0.0,
            "resolution_state": "NO_TRADE",
        },
    ]
    primary = metric_summary(cases)
    reference = metric_summary_reference(cases)
    for key in ("cases", "trades", "no_trades", "wins", "losses", "scratches", "net_pnl_usd", "net_r50", "expectancy_r50_per_trade", "profit_factor", "maximum_drawdown_r50"):
        if primary[key] != reference[key]:
            raise RuntimeError(f"Synthetic economic reproduction differs: {key}")
    synthetic_case = {
        "is_trade": True,
        "action": "LONG",
        "fill_price": 100.0,
        "stop": 99.0,
        "target": 102.0,
        "fill_at": "2022-01-01T08:01:00Z",
        "exit_at": "2022-01-01T08:02:00Z",
        "resolution_state": "STOPPED",
        "net_pnl_usd": -50.0,
    }
    synthetic_stream = {
        "timeframes": {
            "1m": [
                {"open_at": "2022-01-01T08:01:00Z", "high": 100.2, "low": 98.9, "close": 99.0},
                {"open_at": "2022-01-01T08:02:00Z", "high": 101.0, "low": 99.0, "close": 100.5},
                {"open_at": "2022-01-01T08:03:00Z", "high": 102.2, "low": 100.0, "close": 102.0},
            ]
        }
    }
    diagnostic = path_diagnostic(synthetic_case, synthetic_stream)
    if not diagnostic["stopped_then_later_target"] or not diagnostic["terminal_direction_correct"]:
        raise RuntimeError("Synthetic stopped-then-target diagnostic differs")
    return {
        "status": "PASS_SYNTHETIC_MATCHED_ANALYSIS_PROOF",
        "economic_checksum": canonical_hash(primary),
        "path_checksum": canonical_hash(diagnostic),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("self-test", "freeze", "analyze"))
    args = parser.parse_args()
    if args.command == "self-test":
        output = self_test()
    elif args.command == "freeze":
        output = freeze()
    else:
        output = analyze()
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
