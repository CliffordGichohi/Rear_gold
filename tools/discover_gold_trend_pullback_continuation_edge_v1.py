from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
OUTPUT = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"

DESIGN_FREEZE = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_design_freeze.json"
PREOUTCOME_FREEZE = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_preoutcome_freeze.json"
PROTOCOL = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_protocol.json"
TEST_REGISTRY = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_test_registry.json"
FEATURE_REGISTRY = MANIFESTS / "gold_trend_pullback_continuation_edge_v1_feature_registry.json"
CENSUS = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"

PRIMARY_FEATURES = OUTPUT / "primary_features.parquet"
REFERENCE_FEATURES = OUTPUT / "reference_features.parquet"
AUTHORIZATION = OUTPUT / "outcome_opening_authorization.json"
PRIMARY_OUTCOMES = OUTPUT / "primary_outcomes.parquet"
REFERENCE_OUTCOMES = OUTPUT / "reference_outcomes.parquet"
PRIMARY_RESULTS = OUTPUT / "primary_relationship_results.json"
REFERENCE_RESULTS = OUTPUT / "reference_relationship_results.json"
CANDIDATES = OUTPUT / "frozen_provisional_candidates.json"
REPORT = ROOT / "GOLD_TREND_PULLBACK_CONTINUATION_EDGE_V1_REPORT.md"
FINAL_SEAL = OUTPUT / "final_seal.json"
STATE = OUTPUT / "state_m3.json"

OUTCOME_COLUMNS = [
    "pullback_id", "timeframe", "scale", "resolution", "resolved_at_utc",
    "resolution_event_id", "bars_to_resolution", "actionable_at_known",
    "research_eligible", "resolution_hash",
]
OUTCOME_SCHEMA = pa.schema([
    pa.field("pullback_id", pa.string(), False),
    pa.field("timeframe", pa.string(), False),
    pa.field("scale", pa.string(), False),
    pa.field("resolution", pa.string(), False),
    pa.field("resolved_at_utc", pa.string(), True),
    pa.field("resolution_event_id", pa.string(), True),
    pa.field("bars_to_resolution", pa.int64(), True),
    pa.field("actionable_at_known", pa.bool_(), False),
    pa.field("research_eligible", pa.bool_(), False),
    pa.field("resolution_hash", pa.string(), False),
])
NY = ZoneInfo("America/New_York")


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed.astimezone(UTC)


def cluster_trading_date(value: str) -> str:
    return (parse_dt(value).astimezone(NY) - timedelta(hours=17)).date().isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_text_exclusive(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> None:
    if path.exists():
        raise FileExistsError(path)
    table = pa.Table.from_pylist(list(rows), schema=schema)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6")
    temporary.replace(path)


def verify_preoutcome() -> tuple[dict[str, Any], dict[str, Any]]:
    freeze = json.loads(DESIGN_FREEZE.read_text(encoding="utf-8"))
    pre = json.loads(PREOUTCOME_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "SEALED_BEFORE_CONDITIONAL_FEATURE_OR_OUTCOME_ACCESS":
        raise ValueError("Design freeze invalid")
    if pre.get("status") != "SEALED_AFTER_FEATURES_BEFORE_OUTCOME_JOIN":
        raise ValueError("Pre-outcome freeze invalid")
    for name, path in {
        "protocol": PROTOCOL,
        "feature_registry": FEATURE_REGISTRY,
        "test_registry": TEST_REGISTRY,
    }.items():
        if sha256_file(path) != freeze["controls"][name]["sha256"]:
            raise ValueError(f"Frozen control changed: {name}")
    if sha256_file(PRIMARY_FEATURES) != pre["feature_matrix_primary"]["sha256"]:
        raise ValueError("Primary features changed")
    if sha256_file(REFERENCE_FEATURES) != pre["feature_matrix_reference"]["sha256"]:
        raise ValueError("Reference features changed")
    if sha256_file(PRIMARY_FEATURES) != sha256_file(REFERENCE_FEATURES):
        raise ValueError("Feature implementations differ")
    census_seal = json.loads((CENSUS / "final_seal.json").read_text(encoding="utf-8"))
    if census_seal.get("status") != "PASS_COMPLETE_DESCRIPTIVE_CENSUS":
        raise ValueError("Census predecessor invalid")
    return freeze, pre


def synthetic_proof() -> dict[str, Any]:
    rows = [
        {"pullback_id": "a", "timeframe": "M15", "scale": "STANDARD", "resolution": "CONTINUED", "resolved_at_utc": "2024-01-01T01:00:00Z", "resolution_event_id": "e1", "bars_to_resolution": 2, "actionable_at_known": True, "research_eligible": True, "resolution_hash": "h1"},
        {"pullback_id": "b", "timeframe": "M15", "scale": "STANDARD", "resolution": "FAILED_STRUCTURE_SWITCH", "resolved_at_utc": "2024-01-01T02:00:00Z", "resolution_event_id": "e2", "bars_to_resolution": 3, "actionable_at_known": True, "research_eligible": True, "resolution_hash": "h2"},
    ]
    table = pa.Table.from_pylist(rows, schema=OUTCOME_SCHEMA)
    if table.to_pylist() != rows:
        raise ValueError("Synthetic outcome round trip failed")
    sample = np.array([0.1, 0.2, -0.1, 0.3])
    if not math.isclose(float(np.quantile(sample, 0.05)), -0.07):
        raise ValueError("Synthetic quantile proof failed")
    return {"status": "PASS", "schema_hash": canonical_hash(str(OUTCOME_SCHEMA)), "rows_hash": canonical_hash(rows)}


def read_outcomes(path: Path) -> list[dict[str, Any]]:
    rows = pq.read_table(path, columns=OUTCOME_COLUMNS).to_pylist()
    rows.sort(key=lambda row: row["pullback_id"])
    return rows


def load_features(path: Path) -> list[dict[str, Any]]:
    rows = pq.read_table(path).to_pylist()
    rows.sort(key=lambda row: row["pullback_id"])
    return rows


Condition = Callable[[Mapping[str, Any]], bool | None]


def boolean_field(field: str) -> Condition:
    def predicate(row: Mapping[str, Any]) -> bool | None:
        value = row.get(field)
        return None if value is None else bool(value)
    return predicate


def eq_field(field: str, expected: Any, unknown: set[Any] | None = None) -> Condition:
    unknown = unknown or set()
    def predicate(row: Mapping[str, Any]) -> bool | None:
        value = row.get(field)
        return None if value is None or value in unknown else value == expected
    return predicate


def conditions(registry: Mapping[str, Any]) -> tuple[dict[str, Condition], dict[str, Condition]]:
    stage1: dict[str, Condition] = {
        "RET_236_382": eq_field("retracement_zone", "RET_236_382", {"UNKNOWN"}),
        "RET_382_500": eq_field("retracement_zone", "RET_382_500", {"UNKNOWN"}),
        "RET_500_618": eq_field("retracement_zone", "RET_500_618", {"UNKNOWN"}),
        "RET_618_786": eq_field("retracement_zone", "RET_618_786", {"UNKNOWN"}),
        "PIVOT_REJECTION_STRONG": boolean_field("pivot_rejection_strong"),
        "PIVOT_ENGULFING_ALIGNED": boolean_field("pivot_engulfing_aligned"),
        "CONFIRMATION_DISPLACEMENT": boolean_field("confirmation_displacement"),
        "CONFIRMATION_ENGULFING_ALIGNED": boolean_field("confirmation_engulfing_aligned"),
        "REFERENCE_SWEEP_RECLAIM": boolean_field("reference_sweep_reclaim"),
        "PRIOR_DAY_SWEEP_RECLAIM": boolean_field("prior_day_sweep_reclaim"),
        "ASIA_SWEEP_RECLAIM": boolean_field("asia_sweep_reclaim"),
        "HTF_FULL_ALIGNMENT": lambda row: None if int(row.get("higher_timeframe_known_count") or 0) < 2 else int(row["higher_timeframe_alignment_count"]) == int(row["higher_timeframe_known_count"]),
        "FUNDAMENTAL_ALIGNED": eq_field("fundamental_alignment_state", "ALIGNED", {"UNKNOWN"}),
        "IMPULSE_EFFICIENT": lambda row: None if row.get("impulse_efficiency") is None else float(row["impulse_efficiency"]) >= 0.60,
        "PULLBACK_ORDERLY": lambda row: None if row.get("pullback_efficiency") is None or row.get("compression_ratio") is None else float(row["pullback_efficiency"]) >= 0.60 and float(row["compression_ratio"]) <= 0.80,
        "RESPONSE_DISPLACEMENT_HALF_ATR": lambda row: None if row.get("response_displacement_atr") is None else float(row["response_displacement_atr"]) >= 0.50,
    }
    if set(stage1) != set(registry["stage_1_conditions"]):
        raise ValueError("Stage-1 implementation does not match frozen registry")
    stage2: dict[str, Condition] = {}
    for name, members in registry["stage_2_conditions"].items():
        left, right = members
        def combined(row: Mapping[str, Any], left: str = left, right: str = right) -> bool | None:
            a, b = stage1[left](row), stage1[right](row)
            return None if a is None or b is None else bool(a and b)
        stage2[name] = combined
    return stage1, stage2


def effect(rows: Sequence[Mapping[str, Any]], predicate: Condition) -> dict[str, Any]:
    known = [(row, predicate(row)) for row in rows]
    known = [(row, state) for row, state in known if state is not None]
    selected = [row for row, state in known if state]
    complement = [row for row, state in known if not state]
    selected_success = sum(int(row["outcome"]) for row in selected)
    complement_success = sum(int(row["outcome"]) for row in complement)
    selected_rate = selected_success / len(selected) if selected else None
    complement_rate = complement_success / len(complement) if complement else None
    lift = (selected_rate - complement_rate) * 100 if selected_rate is not None and complement_rate is not None else None
    a, b = selected_success, len(selected) - selected_success
    c, d = complement_success, len(complement) - complement_success
    odds_ratio = ((a + 0.5) * (d + 0.5)) / ((b + 0.5) * (c + 0.5)) if selected and complement else None
    return {
        "known": len(known),
        "condition_cases": len(selected),
        "condition_dates": len({row["cluster_date"] for row in selected}),
        "condition_continued": selected_success,
        "condition_failed": len(selected) - selected_success,
        "condition_rate_pct": selected_rate * 100 if selected_rate is not None else None,
        "complement_cases": len(complement),
        "complement_rate_pct": complement_rate * 100 if complement_rate is not None else None,
        "lift_pp": lift,
        "odds_ratio": odds_ratio,
    }


def cluster_bootstrap(rows: Sequence[Mapping[str, Any]], predicate: Condition, seed: int, resamples: int) -> dict[str, Any]:
    by_date: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        state = predicate(row)
        if state is not None:
            by_date[str(row["cluster_date"])].append({**row, "condition": bool(state)})
    dates = sorted(by_date)
    if not dates:
        return {"ci90": [None, None], "ci95": [None, None], "p_one_sided": None, "valid_resamples": 0}
    condition_n = np.array([sum(item["condition"] for item in by_date[key]) for key in dates], dtype=np.int64)
    condition_y = np.array([sum(item["condition"] and item["outcome"] for item in by_date[key]) for key in dates], dtype=np.int64)
    complement_n = np.array([sum(not item["condition"] for item in by_date[key]) for key in dates], dtype=np.int64)
    complement_y = np.array([sum((not item["condition"]) and item["outcome"] for item in by_date[key]) for key in dates], dtype=np.int64)
    rng = np.random.default_rng(seed)
    output: list[float] = []
    batch = 200
    for left in range(0, resamples, batch):
        size = min(batch, resamples - left)
        sample = rng.integers(0, len(dates), size=(size, len(dates)))
        cn, cy = condition_n[sample].sum(axis=1), condition_y[sample].sum(axis=1)
        nn, ny = complement_n[sample].sum(axis=1), complement_y[sample].sum(axis=1)
        valid = (cn > 0) & (nn > 0)
        values = (cy[valid] / cn[valid] - ny[valid] / nn[valid]) * 100
        output.extend(float(item) for item in values)
    if not output:
        return {"ci90": [None, None], "ci95": [None, None], "p_one_sided": None, "valid_resamples": 0}
    values = np.array(output)
    return {
        "ci90": [float(np.quantile(values, 0.05)), float(np.quantile(values, 0.95))],
        "ci95": [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))],
        "p_one_sided": float((1 + np.sum(values <= 0)) / (len(values) + 1)),
        "valid_resamples": len(values),
    }


def bh_adjust(indexed_p: Sequence[tuple[int, float]]) -> dict[int, float]:
    ordered = sorted(indexed_p, key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted: dict[int, float] = {}
    running = 1.0
    for rank in range(count, 0, -1):
        index, p_value = ordered[rank - 1]
        running = min(running, p_value * count / rank)
        adjusted[index] = min(1.0, running)
    return adjusted


def block_for(value: str, blocks: Sequence[Sequence[str]]) -> int | None:
    day = value[:10]
    for index, (start, end) in enumerate(blocks, 1):
        if start <= day <= end:
            return index
    return None


def subset_effect(rows: Sequence[Mapping[str, Any]], predicate: Condition) -> float | None:
    return effect(rows, predicate)["lift_pp"]


def support_pass(summary: Mapping[str, Any], timeframe: str, registry: Mapping[str, Any]) -> tuple[bool, list[str]]:
    floor = registry["support_floors"][timeframe]
    failures = []
    if summary["condition_cases"] < floor["cases"]:
        failures.append("CONDITION_CASES")
    if summary["condition_dates"] < floor["dates"]:
        failures.append("CONDITION_DATES")
    if summary["condition_continued"] < registry["support_floors"]["continued"]:
        failures.append("CONDITION_CONTINUED")
    if summary["condition_failed"] < registry["support_floors"]["failed"]:
        failures.append("CONDITION_FAILED")
    if summary["complement_cases"] < floor["cases"]:
        failures.append("COMPLEMENT_CASES")
    return not failures, failures


def evaluate_test(
    rows: Sequence[Mapping[str, Any]],
    all_rows: Sequence[Mapping[str, Any]],
    timeframe: str,
    stage: int,
    name: str,
    predicate: Condition,
    seed: int,
    protocol: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    summary = effect(rows, predicate)
    supported, support_failures = support_pass(summary, timeframe, registry)
    bootstrap = cluster_bootstrap(rows, predicate, seed, int(protocol["cluster_bootstrap_resamples"])) if supported else {"ci90": [None, None], "ci95": [None, None], "p_one_sided": None, "valid_resamples": 0}
    blocks = []
    for index, bounds in enumerate(registry["chronological_blocks"], 1):
        selected = [row for row in rows if block_for(str(row["known_at_utc"]), registry["chronological_blocks"]) == index]
        blocks.append({"block": index, "start": bounds[0], "end": bounds[1], "cases": len(selected), "lift_pp": subset_effect(selected, predicate)})
    years = []
    for year in (2021, 2022, 2023, 2024):
        selected = [row for row in rows if str(row["known_at_utc"]).startswith(str(year))]
        years.append({"year": year, "cases": len(selected), "lift_pp": subset_effect(selected, predicate)})
    sides = []
    for direction in ("UP", "DOWN"):
        selected = [row for row in rows if row["direction"] == direction]
        sides.append({"direction": direction, "cases": len(selected), "lift_pp": subset_effect(selected, predicate)})
    first_by_segment: dict[str, Mapping[str, Any]] = {}
    for row in sorted(rows, key=lambda item: (item["known_at_utc"], item["pullback_id"])):
        first_by_segment.setdefault(str(row["segment_id"]), row)
    first_effect = subset_effect(list(first_by_segment.values()), predicate)
    scale_replication = []
    for scale in ("MICRO", "MAJOR"):
        selected = [row for row in all_rows if row["timeframe"] == timeframe and row["scale"] == scale]
        scale_replication.append({"scale": scale, "cases": len(selected), **effect(selected, predicate)})
    return {
        "test_id": f"{timeframe}|S{stage}|{name}",
        "timeframe": timeframe,
        "stage": stage,
        "condition": name,
        "support_pass": supported,
        "support_failures": support_failures,
        **summary,
        "bootstrap": bootstrap,
        "blocks": blocks,
        "years": years,
        "sides": sides,
        "first_case_per_segment": {"cases": len(first_by_segment), "lift_pp": first_effect},
        "scale_replication": scale_replication,
        "bh_q": None,
        "verdict": "PENDING_MULTIPLICITY" if supported else "SUPPORT_FAIL",
        "failed_gates": list(support_failures),
    }


def finalize_stage(tests: list[dict[str, Any]], registry: Mapping[str, Any]) -> None:
    eligible = [(index, float(item["bootstrap"]["p_one_sided"])) for index, item in enumerate(tests) if item["support_pass"] and item["bootstrap"]["p_one_sided"] is not None]
    adjusted = bh_adjust(eligible)
    rules = registry["pass_rules"]
    for index, item in enumerate(tests):
        if not item["support_pass"]:
            continue
        item["bh_q"] = adjusted[index]
        failures = []
        if item["lift_pp"] is None or item["lift_pp"] < rules["minimum_lift_percentage_points"]:
            failures.append("LIFT_LT_5PP")
        lower = item["bootstrap"]["ci90"][0]
        if lower is None or lower <= 0:
            failures.append("CI90_LOWER_NOT_POSITIVE")
        if item["bh_q"] > rules["bh_q_max"]:
            failures.append("BH_Q_GT_0_10")
        valid_blocks = [entry["lift_pp"] for entry in item["blocks"] if entry["lift_pp"] is not None]
        if sum(value >= 0 for value in valid_blocks) < rules["nonnegative_blocks_min"]:
            failures.append("BLOCK_NONNEGATIVE_COUNT")
        if not valid_blocks or min(valid_blocks) < rules["worst_block_lift_min_percentage_points"]:
            failures.append("WORST_BLOCK_LT_MINUS_10PP")
        first = item["first_case_per_segment"]["lift_pp"]
        if first is None or first <= 0:
            failures.append("FIRST_SEGMENT_LIFT_NOT_POSITIVE")
        item["failed_gates"] = failures
        item["verdict"] = "PROVISIONAL_DEVELOPMENT_RELATIONSHIP" if not failures else "REJECT"


def prepare_join(features: Sequence[Mapping[str, Any]], outcomes: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    outcome_map = {str(row["pullback_id"]): row for row in outcomes}
    if len(outcome_map) != len(outcomes):
        raise ValueError("Duplicate outcome identity")
    joined: list[dict[str, Any]] = []
    counts = Counter()
    for feature in features:
        outcome = outcome_map.get(str(feature["pullback_id"]))
        if outcome is None:
            raise ValueError(f"Missing outcome: {feature['pullback_id']}")
        if outcome["timeframe"] != feature["timeframe"] or outcome["scale"] != feature["scale"]:
            raise ValueError("Outcome identity mismatch")
        counts[str(outcome["resolution"])] += 1
        if not feature["feature_available"] or not feature["actionable_at_known"] or not feature["research_eligible"]:
            continue
        if outcome["resolution"] not in {"CONTINUED", "FAILED_STRUCTURE_SWITCH"}:
            continue
        row = dict(feature)
        row["outcome"] = 1 if outcome["resolution"] == "CONTINUED" else 0
        row["resolution"] = outcome["resolution"]
        row["cluster_date"] = cluster_trading_date(str(feature["known_at_utc"]))
        joined.append(row)
    joined.sort(key=lambda row: (row["known_at_utc"], row["pullback_id"]))
    return joined, {"all_resolution_counts": dict(sorted(counts.items())), "eligible_joined_rows": len(joined), "by_population": dict(sorted(Counter(f"{row['timeframe']}|{row['scale']}" for row in joined).items()))}


def run_analysis(features: Sequence[Mapping[str, Any]], outcomes: Sequence[Mapping[str, Any]], protocol: Mapping[str, Any], registry: Mapping[str, Any]) -> dict[str, Any]:
    joined, join_diagnostics = prepare_join(features, outcomes)
    stage1, stage2 = conditions(registry)
    tests: list[dict[str, Any]] = []
    seed_base = int(protocol["bootstrap_seed"])
    for tf_index, timeframe in enumerate(("M15", "H1", "H4")):
        primary = [row for row in joined if row["timeframe"] == timeframe and row["scale"] == "STANDARD"]
        for stage, mapping in ((1, stage1), (2, stage2)):
            stage_tests = []
            for test_index, (name, predicate) in enumerate(mapping.items()):
                seed = seed_base + tf_index * 10_000 + stage * 1_000 + test_index
                stage_tests.append(evaluate_test(primary, joined, timeframe, stage, name, predicate, seed, protocol, registry))
            finalize_stage(stage_tests, registry)
            tests.extend(stage_tests)
    passing = [item for item in tests if item["verdict"] == "PROVISIONAL_DEVELOPMENT_RELATIONSHIP"]
    frozen = []
    for timeframe in ("M15", "H1", "H4"):
        selected = [item for item in passing if item["timeframe"] == timeframe]
        selected.sort(key=lambda item: (-float(item["bootstrap"]["ci90"][0]), -float(item["lift_pp"]), -int(item["condition_cases"]), item["test_id"]))
        frozen.extend(selected[: int(registry["candidate_limit_per_timeframe"])])
    verdict = "PASS_PROVISIONAL_DEVELOPMENT_RELATIONSHIP" if frozen else "REJECT_NO_PROVISIONAL_RELATIONSHIP"
    return {
        "version": "GOLD_TPCE_V1_RELATIONSHIP_RESULTS_1_0",
        "verdict": verdict,
        "join_diagnostics": join_diagnostics,
        "test_count": len(tests),
        "support_pass_count": sum(item["support_pass"] for item in tests),
        "provisional_pass_count_before_limit": len(passing),
        "candidate_count": len(frozen),
        "candidate_ids": [item["test_id"] for item in frozen],
        "tests": tests,
        "result_hash": canonical_hash(tests),
        "forward_values_accessed": False,
        "execution_or_pnl_calculated": False,
    }


def report_text(results: Mapping[str, Any]) -> str:
    candidates = {item["test_id"] for item in results["tests"] if item["test_id"] in results["candidate_ids"]}
    lines = [
        "# Gold Trend-Pullback Continuation Edge Discovery V1",
        "",
        f"Status: **{results['verdict']}**",
        "",
        "## Verdict",
        "",
    ]
    if candidates:
        lines.append("At least one preregistered condition distinguished continuation from failure in 2021-2024 development data. These are provisional directional relationships, not yet economically tradable edges; execution and forward testing remain unopened.")
    else:
        lines.append("No preregistered technical/context condition passed every development relationship gate. This does not erase the continuation pattern; it means the frozen clues did not reliably classify continuation versus failure.")
    lines.extend(["", "## Frozen candidates", ""])
    if not candidates:
        lines.append("None.")
    else:
        lines.extend(["| Candidate | Cases | Continue rate | Lift | 90% CI | BH q |", "|---|---:|---:|---:|---|---:|"])
        for item in results["tests"]:
            if item["test_id"] not in candidates:
                continue
            ci = item["bootstrap"]["ci90"]
            lines.append(f"| {item['test_id']} | {item['condition_cases']} | {item['condition_rate_pct']:.2f}% | {item['lift_pp']:.2f} pp | [{ci[0]:.2f}, {ci[1]:.2f}] | {item['bh_q']:.4f} |")
    lines.extend(["", "## Complete test matrix", "", "| Test | N | Rate | Lift | 90% lower | q | Verdict | Failed gates |", "|---|---:|---:|---:|---:|---:|---|---|"])
    for item in results["tests"]:
        rate = "NA" if item["condition_rate_pct"] is None else f"{item['condition_rate_pct']:.2f}%"
        lift = "NA" if item["lift_pp"] is None else f"{item['lift_pp']:.2f}"
        lower = item["bootstrap"]["ci90"][0]
        lower_text = "NA" if lower is None else f"{lower:.2f}"
        q_text = "NA" if item["bh_q"] is None else f"{item['bh_q']:.4f}"
        lines.append(f"| {item['test_id']} | {item['condition_cases']} | {rate} | {lift} | {lower_text} | {q_text} | {item['verdict']} | {', '.join(item['failed_gates']) or '-'} |")
    lines.extend([
        "",
        "## Integrity",
        "",
        f"The controlled development outcome join contained {results['join_diagnostics']['eligible_joined_rows']} actionable resolved cases across all scales. Primary and reference joins, tests and checksums reproduced exactly. Calendar 2025 and 2026 remained locked. No execution, trade, R, PnL or account-return calculation was performed.",
        "",
    ])
    return "\n".join(lines)


def execute() -> dict[str, Any]:
    if any(path.exists() for path in (AUTHORIZATION, PRIMARY_OUTCOMES, REFERENCE_OUTCOMES, PRIMARY_RESULTS, REFERENCE_RESULTS, CANDIDATES, REPORT, FINAL_SEAL, STATE)):
        raise FileExistsError("TPCE outcome/result artifact already exists")
    freeze, pre = verify_preoutcome()
    proof = synthetic_proof()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    registry = json.loads(TEST_REGISTRY.read_text(encoding="utf-8"))
    authorization = {
        "version": "GOLD_TPCE_V1_OUTCOME_OPENING_AUTHORIZATION_1_0",
        "status": "AUTHORIZED_EXACTLY_ONE_CONTROLLED_DEVELOPMENT_OUTCOME_JOIN",
        "authorized_at_utc": utc_now(),
        "design_freeze": file_record(DESIGN_FREEZE),
        "preoutcome_freeze": file_record(PREOUTCOME_FREEZE),
        "implementation": file_record(Path(__file__).resolve()),
        "synthetic_proof": proof,
        "source_opening_limit": 1,
        "calendar_2025_authorized": False,
        "calendar_2026_authorized": False,
        "execution_or_pnl_authorized": False,
    }
    write_json_exclusive(AUTHORIZATION, authorization)

    primary_outcomes = read_outcomes(CENSUS / "primary_pullback_cases.parquet")
    reference_outcomes = read_outcomes(CENSUS / "reference_pullback_cases.parquet")
    if primary_outcomes != reference_outcomes:
        raise ValueError("Primary/reference outcomes differ")
    write_parquet_exclusive(PRIMARY_OUTCOMES, primary_outcomes, OUTCOME_SCHEMA)
    write_parquet_exclusive(REFERENCE_OUTCOMES, reference_outcomes, OUTCOME_SCHEMA)
    if sha256_file(PRIMARY_OUTCOMES) != sha256_file(REFERENCE_OUTCOMES):
        raise ValueError("Outcome Parquet bytes differ")

    primary_features = load_features(PRIMARY_FEATURES)
    reference_features = load_features(REFERENCE_FEATURES)
    primary = run_analysis(primary_features, primary_outcomes, protocol, registry)
    reference = run_analysis(reference_features, reference_outcomes, protocol, registry)
    if primary != reference:
        raise ValueError("Independent relationship results differ")
    write_json_exclusive(PRIMARY_RESULTS, primary)
    write_json_exclusive(REFERENCE_RESULTS, reference)
    if sha256_file(PRIMARY_RESULTS) != sha256_file(REFERENCE_RESULTS):
        raise ValueError("Result bytes differ")
    candidate_tests = [item for item in primary["tests"] if item["test_id"] in primary["candidate_ids"]]
    write_json_exclusive(
        CANDIDATES,
        {
            "version": "GOLD_TPCE_V1_FROZEN_PROVISIONAL_CANDIDATES_1_0",
            "status": "FROZEN_AFTER_DEVELOPMENT_RELATIONSHIP_DISCOVERY",
            "candidate_count": len(candidate_tests),
            "candidates": candidate_tests,
            "candidate_ids": primary["candidate_ids"],
            "retuning_permitted": False,
            "economic_edge_claim_permitted": False,
            "forward_values_accessed": False,
        },
    )
    write_text_exclusive(REPORT, report_text(primary))
    artifacts = [AUTHORIZATION, PRIMARY_OUTCOMES, REFERENCE_OUTCOMES, PRIMARY_RESULTS, REFERENCE_RESULTS, CANDIDATES, REPORT, PREOUTCOME_FREEZE, OUTPUT / "materialization_certification.json"]
    seal = {
        "version": "GOLD_TPCE_V1_FINAL_SEAL_1_0",
        "status": primary["verdict"],
        "sealed_at_utc": utc_now(),
        "artifacts": {path.name: file_record(path) for path in artifacts},
        "artifact_set_hash": canonical_hash({path.name: sha256_file(path) for path in artifacts}),
        "source_opening_count": 1,
        "primary_reference_exact": True,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "execution_or_pnl_calculated": False,
        "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(FINAL_SEAL, seal)
    write_json_exclusive(
        STATE,
        {
            "version": "GOLD_TPCE_V1_STATE_M3_1_0",
            "status": primary["verdict"],
            "recorded_at_utc": utc_now(),
            "candidate_count": len(candidate_tests),
            "candidate_ids": primary["candidate_ids"],
            "next_step": "FREEZE_CONSTANT_EXECUTION_TEST" if candidate_tests else "STOP_ZERO_CANDIDATES",
            "final_seal": file_record(FINAL_SEAL),
            "forward_locked": ["2025", "2026"],
        },
    )
    return primary


def selftest() -> None:
    proof = synthetic_proof()
    assert proof["status"] == "PASS"
    adjusted = bh_adjust([(0, 0.01), (1, 0.04), (2, 0.03)])
    assert math.isclose(adjusted[0], 0.03) and math.isclose(adjusted[1], 0.04)
    sample = [
        {"outcome": 1, "cluster_date": "a", "flag": True},
        {"outcome": 0, "cluster_date": "b", "flag": False},
        {"outcome": 1, "cluster_date": "c", "flag": False},
    ]
    result = effect(sample, boolean_field("flag"))
    assert result["condition_rate_pct"] == 100 and result["complement_rate_pct"] == 50
    registry = json.loads(TEST_REGISTRY.read_text(encoding="utf-8"))
    stage1, stage2 = conditions(registry)
    assert len(stage1) == 16 and len(stage2) == 13
    feature_rows = load_features(PRIMARY_FEATURES)[:8]
    synthetic_outcomes = [
        {
            "pullback_id": row["pullback_id"], "timeframe": row["timeframe"],
            "scale": row["scale"], "resolution": "CONTINUED" if index % 2 == 0 else "FAILED_STRUCTURE_SWITCH",
            "resolved_at_utc": row["known_at_utc"], "resolution_event_id": f"synthetic-{index}",
            "bars_to_resolution": 1, "actionable_at_known": row["actionable_at_known"],
            "research_eligible": row["research_eligible"], "resolution_hash": f"synthetic-hash-{index}",
        }
        for index, row in enumerate(feature_rows)
    ]
    joined, diagnostics = prepare_join(feature_rows, synthetic_outcomes)
    assert diagnostics["eligible_joined_rows"] <= 8 and all("cluster_date" in row for row in joined)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selftest()
    if args.selftest:
        print(json.dumps({"status": "PASS_SYNTHETIC_PREOUTCOME_PROOF"}, indent=2))
        return
    result = execute()
    print(json.dumps({
        "status": result["verdict"],
        "joined": result["join_diagnostics"],
        "tests": result["test_count"],
        "support_pass": result["support_pass_count"],
        "candidate_count": result["candidate_count"],
        "candidate_ids": result["candidate_ids"],
        "final_seal": file_record(FINAL_SEAL),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
