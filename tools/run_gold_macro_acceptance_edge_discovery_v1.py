from __future__ import annotations

import gzip
import hashlib
import itertools
import json
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research_artifacts" / "gold_macro_acceptance_edge_discovery_v01"
CONTRACT = ROOT / "GOLD_MACRO_ACCEPTANCE_EDGE_DISCOVERY_CONTRACT_V1.md"
FREEZE = ROOT / "research_manifests" / "gold_macro_acceptance_edge_discovery_v01.json"
AMENDMENT = ROOT / "GOLD_MACRO_ACCEPTANCE_EDGE_DISCOVERY_V1_RECOVERY_A.md"
SERIALIZATION_AMENDMENT = ROOT / "GOLD_MACRO_ACCEPTANCE_EDGE_DISCOVERY_V1_RECOVERY_B.md"
EVENTS = ROOT / "research_artifacts" / "gold_casebook_v01" / "events.jsonl.gz"
FUNDAMENTALS = ROOT / "research_artifacts" / "gold_casebook_v01" / "fundamentals.jsonl.gz"
POSITIONING = ROOT / "research_artifacts" / "gold_casebook_v01" / "positioning.jsonl.gz"
INVENTORY = (
    ROOT
    / "research_artifacts"
    / "gold_macro_acceptance_source_inventory_v01"
    / "inventory.json"
)

EXPECTED_HASHES = {
    CONTRACT: "04f1cff4d4ea05710262f512a750c857d7aa990f06b9073afcc10ae433324075",
    FREEZE: "1298fcdd038f4dc0aeaa36ee22aa166e9984cf70055d8705966d6f0039838bcd",
    AMENDMENT: "83ccb9e4982e591ceebad1fbd842f5653291d4efe540857889b0f6b13401441e",
    SERIALIZATION_AMENDMENT: "98e1fcb6eb25a44b831b4452f9b1866c047c3d7175058f5d4ee0b30ad01e46b9",
    EVENTS: "c7875e09d9ed831ece0f223b8be5efb75550af5bf1996a2dfea9d6119b24e35f",
    FUNDAMENTALS: "d2b776f60c4535978bbfb28706b4700e6d054a10f8d57cfee171c83b212b7235",
    POSITIONING: "e6d1aabf0d4401f3af4e54dc8ef4c0e4074772ec3f2199cfe9009b5a0b267228",
    INVENTORY: "a50f016a3b2a723bc710f9b35d1f60aab7fec6c9f81056ca9a2232d65abe07c0",
}
RAW_XAU_INVENTORY_HASH = "470a967e087130d749e12d13ec7014f9ed6b171edaa8244b183cf97d62da7744"
START = datetime(2021, 8, 1, tzinfo=UTC)
END = datetime(2025, 1, 1, tzinfo=UTC)
SEED = 20260806
BOOTSTRAPS = 10_000
PERMUTATIONS = 20_000
TOKYO = ZoneInfo("Asia/Tokyo")
LONDON = ZoneInfo("Europe/London")
EVENT_FAMILIES = (
    "CPI",
    "FOMC",
    "GDP",
    "JOBLESS_CLAIMS",
    "NFP",
    "PCE",
    "RETAIL_SALES",
)
BLOCKS = (
    ("B1_2021AUG_2022H1", datetime(2021, 8, 1, tzinfo=UTC), datetime(2022, 7, 1, tzinfo=UTC)),
    ("B2_2022H2", datetime(2022, 7, 1, tzinfo=UTC), datetime(2023, 1, 1, tzinfo=UTC)),
    ("B3_2023H1", datetime(2023, 1, 1, tzinfo=UTC), datetime(2023, 7, 1, tzinfo=UTC)),
    ("B4_2023H2", datetime(2023, 7, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC)),
    ("B5_2024H1", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 7, 1, tzinfo=UTC)),
    ("B6_2024H2", datetime(2024, 7, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def sign(value: float | int | None, *, epsilon: float = 1e-12) -> int | None:
    if value is None or not math.isfinite(float(value)):
        return None
    if float(value) > epsilon:
        return 1
    if float(value) < -epsilon:
        return -1
    return None


def verify_predecessors() -> dict[str, str]:
    verified: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"Predecessor hash mismatch: {path}: {actual} != {expected}")
        verified[str(path.relative_to(ROOT)).replace("\\", "/")] = actual
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze["status"] != "FROZEN_BEFORE_OUTCOME_ACCESS":
        raise RuntimeError("Research freeze is not active")
    if freeze["prohibitions"]["open_2025"] is not True:
        raise RuntimeError("2025 is not locked")
    return verified


def pre2025_xau_files() -> list[Path]:
    found: list[Path] = []
    pattern = re.compile(r"_(20\d{6})T")
    for path in (ROOT / "data" / "mt5").rglob("xauusd_1m_*.csv"):
        match = pattern.search(path.name)
        if match and int(match.group(1)[:4]) <= 2024:
            found.append(path)
    return sorted(found, key=lambda item: str(item.resolve()).lower())


def verify_xau_file_inventory(paths: list[Path]) -> dict[str, Any]:
    rows: list[str] = []
    total_bytes = 0
    for path in paths:
        relative = str(path.relative_to(ROOT)).replace("\\", "/")
        size = path.stat().st_size
        total_bytes += size
        rows.append(f"{relative}|{size}|{sha256(path)}")
    digest = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
    if digest != RAW_XAU_INVENTORY_HASH:
        raise RuntimeError(f"XAU file inventory mismatch: {digest}")
    return {"file_count": len(paths), "bytes": total_bytes, "inventory_sha256": digest}


def read_jsonl_gz(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def load_point_in_time_contexts() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    snapshots: list[dict[str, Any]] = []
    with gzip.open(FUNDAMENTALS, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("record_type") == "FUNDAMENTAL_SNAPSHOT":
                snapshots.append(row)
    snapshots.sort(key=lambda row: (parse_ts(row["available_at"]), row["record_id"]))
    positioning = read_jsonl_gz(POSITIONING)
    positioning.sort(key=lambda row: (parse_ts(row["available_at"]), row["record_id"]))
    return snapshots, positioning


def latest_at(rows: list[dict[str, Any]], decision: datetime) -> dict[str, Any] | None:
    eligible = [row for row in rows if parse_ts(row["available_at"]) <= decision]
    return eligible[-1] if eligible else None


def load_xau_bars(paths: list[Path]) -> pd.DataFrame:
    usecols = ["open_time", "close_time", "available_at", "high", "low", "close"]
    frames: list[pd.DataFrame] = []
    boundary = pd.Timestamp(END)
    for path in paths:
        timestamp_only = pd.to_datetime(
            pd.read_csv(path, usecols=["open_time"])["open_time"],
            utc=True,
        )
        pre_boundary_count = int((timestamp_only < boundary).sum())
        if not (timestamp_only.iloc[:pre_boundary_count] < boundary).all():
            raise RuntimeError(f"Pre-boundary rows are not a source prefix: {path}")
        if not (timestamp_only.iloc[pre_boundary_count:] >= boundary).all():
            raise RuntimeError(f"Post-boundary rows are not a source suffix: {path}")
        frames.append(pd.read_csv(path, usecols=usecols, nrows=pre_boundary_count))
    frame = pd.concat(frames, ignore_index=True)
    for column in ("open_time", "close_time", "available_at"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    frame.sort_values(["open_time", "available_at"], inplace=True, kind="mergesort")
    if frame["open_time"].duplicated().any():
        raise RuntimeError("Unexpected duplicate XAUUSD timestamps")
    if len(frame) != 1_218_292:
        raise RuntimeError(f"Unexpected XAUUSD row count: {len(frame)}")
    if frame["open_time"].max() >= boundary:
        raise RuntimeError("XAUUSD holdout boundary violated")
    return frame.set_index("open_time", drop=False)


def reaction(event: dict[str, Any], horizon: str, instrument: str) -> dict[str, Any] | None:
    item = event.get("fixed_horizon_reactions", {}).get(horizon, {}).get("instruments", {}).get(instrument)
    if not item or item.get("status") != "READY":
        return None
    return item


def common_reaction(group: list[dict[str, Any]], horizon: str, instrument: str) -> dict[str, Any] | None:
    values = [reaction(event, horizon, instrument) for event in group]
    ready = [item for item in values if item is not None]
    if not ready:
        return None
    canonical = canonical_hash(ready[0])
    if any(canonical_hash(item) != canonical for item in ready[1:]):
        raise RuntimeError(f"Coincident event reaction mismatch: {horizon} {instrument}")
    if len(ready) != len(values):
        return None
    return ready[0]


def block_for(timestamp: datetime) -> str:
    for code, start, end in BLOCKS:
        if start <= timestamp < end:
            return code
    raise RuntimeError(f"No chronological block for {timestamp}")


def asia_state(
    bars: pd.DataFrame,
    released_at: datetime,
    decision_at: datetime,
    macro_direction: int | None,
) -> dict[str, Any]:
    london_date = released_at.astimezone(LONDON).date()
    start = datetime.combine(london_date, time(10, 5), tzinfo=TOKYO).astimezone(UTC)
    end = datetime.combine(london_date, time(16, 0), tzinfo=TOKYO).astimezone(UTC)
    expected = pd.date_range(start=pd.Timestamp(start), end=pd.Timestamp(end) - pd.Timedelta(minutes=1), freq="min")
    selected = bars.reindex(expected)
    complete = (
        len(expected) == 355
        and selected["open_time"].notna().all()
        and (selected["available_at"] <= pd.Timestamp(released_at)).all()
    )
    if not complete:
        return {"status": "UNKNOWN", "reason": "INCOMPLETE_OR_UNAVAILABLE_ASIA_RANGE"}
    high = float(selected["high"].max())
    low = float(selected["low"].min())
    post = bars[(bars["close_time"] > pd.Timestamp(released_at)) & (bars["close_time"] <= pd.Timestamp(decision_at))]
    post = post[post["available_at"] <= pd.Timestamp(decision_at)].sort_values("close_time")
    if len(post) < 2:
        return {"status": "UNKNOWN", "reason": "INSUFFICIENT_POST_RELEASE_BARS"}
    last_two = post.tail(2)["close"].astype(float).tolist()
    decision_close = float(post.iloc[-1]["close"])
    accepted = False
    failed = False
    if macro_direction == 1:
        accepted = all(value > high for value in last_two)
        failed = bool((post["high"] > high).any() and low <= decision_close <= high)
    elif macro_direction == -1:
        accepted = all(value < low for value in last_two)
        failed = bool((post["low"] < low).any() and low <= decision_close <= high)
    return {
        "status": "READY",
        "source_open_count": 355,
        "post_release_bar_count": int(len(post)),
        "same_direction_accepted": accepted,
        "same_direction_failed": failed,
        "range_identity_sha256": canonical_hash(
            {
                "date": london_date.isoformat(),
                "start": iso(start),
                "end": iso(end),
                "source_open_times": [stamp.isoformat() for stamp in expected],
            }
        ),
    }


def construct_anchor(
    released_at: datetime,
    group: list[dict[str, Any]],
    fundamentals: list[dict[str, Any]],
    positioning: list[dict[str, Any]],
    bars: pd.DataFrame,
) -> dict[str, Any]:
    decision = released_at + timedelta(minutes=5)
    surprise_ids: set[str] = set()
    fundamental_parts: list[float] = []
    for event in group:
        for item in event.get("standardized_surprises", []):
            if parse_ts(item["available_at"]) > decision:
                continue
            identity = str(item.get("surprise_id") or item.get("data_hash"))
            if identity in surprise_ids:
                continue
            surprise_ids.add(identity)
            value = float(item["gold_direction"])
            if math.isfinite(value):
                fundamental_parts.append(value)
    fundamental_sum = float(sum(fundamental_parts)) if fundamental_parts else None
    f_sign = sign(fundamental_sum)

    five = {
        instrument: common_reaction(group, "5_MINUTES", instrument)
        for instrument in ("ZT.v.0", "ZN.v.0", "EURUSD", "XAUUSD")
    }
    market_votes: list[int] = []
    for instrument in ("ZT.v.0", "ZN.v.0", "EURUSD"):
        item = five[instrument]
        vote = sign(float(item["absolute_change"])) if item else None
        if vote is not None:
            market_votes.append(vote)
    m_sign = sign(sum(market_votes)) if len(market_votes) == 3 else None
    g_sign = sign(float(five["XAUUSD"]["absolute_change"])) if five["XAUUSD"] else None

    fifteen = common_reaction(group, "15_MINUTES", "XAUUSD")
    one_hour = common_reaction(group, "1_HOUR", "XAUUSD")
    xau5 = five["XAUUSD"]
    outcome15_abs = (
        float(fifteen["absolute_change"]) - float(xau5["absolute_change"])
        if fifteen and xau5
        else None
    )
    outcome15_pct = (
        float(fifteen["percent_change"]) - float(xau5["percent_change"])
        if fifteen and xau5
        else None
    )
    outcome60_abs = (
        float(one_hour["absolute_change"]) - float(xau5["absolute_change"])
        if one_hour and xau5
        else None
    )
    outcome60_pct = (
        float(one_hour["percent_change"]) - float(xau5["percent_change"])
        if one_hour and xau5
        else None
    )

    prior = latest_at(fundamentals, decision)
    b_score = float(prior["engine_state"]["directional_score"]) if prior else None
    b_sign = sign(b_score)
    cot = latest_at(positioning, decision)
    crowding = cot.get("inferred", {}).get("crowding_state") if cot else None
    asia = asia_state(bars, released_at, decision, m_sign)
    families = sorted({str(event["event_type"]) for event in group})

    return {
        "anchor_id": f"MACRO_ACCEPTANCE::{iso(released_at)}",
        "released_at": iso(released_at),
        "decision_at": iso(decision),
        "year": released_at.year,
        "month": released_at.strftime("%Y-%m"),
        "block": block_for(released_at),
        "event_case_count": len(group),
        "event_families": families,
        "event_record_ids": sorted(str(event["record_id"]) for event in group),
        "fundamental_component_count": len(fundamental_parts),
        "fundamental_sum": fundamental_sum,
        "F": f_sign,
        "market_vote_count": len(market_votes),
        "market_vote_sum": sum(market_votes) if len(market_votes) == 3 else None,
        "M": m_sign,
        "G": g_sign,
        "prior_bias_score": b_score,
        "B": b_sign,
        "crowding": crowding,
        "asia": asia,
        "outcome_15_abs": outcome15_abs,
        "outcome_15_pct": outcome15_pct,
        "outcome_15_sign": sign(outcome15_abs),
        "outcome_60_abs": outcome60_abs,
        "outcome_60_pct": outcome60_pct,
        "outcome_60_sign": sign(outcome60_abs),
    }


def build_primary(
    event_rows: list[dict[str, Any]],
    fundamentals: list[dict[str, Any]],
    positioning: list[dict[str, Any]],
    bars: pd.DataFrame,
) -> list[dict[str, Any]]:
    groups: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for event in event_rows:
        released = parse_ts(event["released_at"])
        if START <= released < END:
            groups[released].append(event)
    return [
        construct_anchor(timestamp, sorted(groups[timestamp], key=lambda row: row["record_id"]), fundamentals, positioning, bars)
        for timestamp in sorted(groups)
    ]


def build_reference(
    event_rows: list[dict[str, Any]],
    fundamentals: list[dict[str, Any]],
    positioning: list[dict[str, Any]],
    bars: pd.DataFrame,
) -> list[dict[str, Any]]:
    eligible = sorted(
        (row for row in event_rows if START <= parse_ts(row["released_at"]) < END),
        key=lambda row: (parse_ts(row["released_at"]), row["record_id"]),
    )
    output: list[dict[str, Any]] = []
    for timestamp, iterator in itertools.groupby(eligible, key=lambda row: parse_ts(row["released_at"])):
        output.append(construct_anchor(timestamp, list(iterator), fundamentals, positioning, bars))
    return output


def stage1_signal(code: str, row: dict[str, Any]) -> int | None:
    f, m, g, b = row["F"], row["M"], row["G"], row["B"]
    if code == "MACRO_FUNDAMENTAL_ONLY":
        return f
    if code == "MARKET_REPRICING_ONLY":
        return m
    if code == "INITIAL_GOLD_MOMENTUM":
        return g
    if code == "FUNDAMENTAL_MARKET_CONSENSUS":
        return m if f is not None and f == m else None
    if code == "MARKET_GOLD_ACCEPTANCE":
        return m if m is not None and m == g else None
    if code == "TRIPLE_MACRO_ACCEPTANCE":
        return m if f is not None and f == m == g else None
    if code == "TRIPLE_WITH_PRIOR_BIAS":
        return m if b is not None and b == f == m == g else None
    if code == "TRIPLE_NOT_CROWDED":
        if f is None or not (f == m == g):
            return None
        if (m == 1 and row["crowding"] == "CROWDED_LONGS") or (m == -1 and row["crowding"] == "CROWDED_SHORTS"):
            return None
        return m
    if code == "TRIPLE_ASIA_BREAK_ACCEPTANCE":
        ready = row["asia"].get("status") == "READY" and row["asia"].get("same_direction_accepted") is True
        return m if ready and f is not None and f == m == g else None
    if code == "MACRO_REJECTION_TOWARD_MACRO":
        return m if f is not None and f == m and g == -m else None
    if code == "FUNDAMENTAL_MARKET_CONTRADICTION_TRUST_MARKET":
        return m if f is not None and m is not None and f == -m else None
    if code == "FAILED_ASIA_BREAK_STRUCTURE_OVERRIDE":
        ready = row["asia"].get("status") == "READY" and row["asia"].get("same_direction_failed") is True
        return -m if ready and f is not None and f == m else None
    raise KeyError(code)


STAGE1 = (
    "MACRO_FUNDAMENTAL_ONLY",
    "MARKET_REPRICING_ONLY",
    "INITIAL_GOLD_MOMENTUM",
    "FUNDAMENTAL_MARKET_CONSENSUS",
    "MARKET_GOLD_ACCEPTANCE",
    "TRIPLE_MACRO_ACCEPTANCE",
    "TRIPLE_WITH_PRIOR_BIAS",
    "TRIPLE_NOT_CROWDED",
    "TRIPLE_ASIA_BREAK_ACCEPTANCE",
    "MACRO_REJECTION_TOWARD_MACRO",
    "FUNDAMENTAL_MARKET_CONTRADICTION_TRUST_MARKET",
    "FAILED_ASIA_BREAK_STRUCTURE_OVERRIDE",
)


def registry() -> list[dict[str, Any]]:
    tests = [{"code": code, "stage": 1, "family": None} for code in STAGE1]
    for family in EVENT_FAMILIES:
        tests.append({"code": f"MARKET_GOLD_ACCEPTANCE::{family}", "stage": 2, "family": family, "base": "MARKET_GOLD_ACCEPTANCE"})
        tests.append({"code": f"MACRO_REJECTION_TOWARD_MACRO::{family}", "stage": 2, "family": family, "base": "MACRO_REJECTION_TOWARD_MACRO"})
    return tests


def signal_for(test: dict[str, Any], row: dict[str, Any]) -> int | None:
    if test["stage"] == 1:
        return stage1_signal(test["code"], row)
    if test["family"] not in row["event_families"]:
        return None
    return stage1_signal(test["base"], row)


def balanced_hit(signals: np.ndarray, outcomes: np.ndarray) -> float:
    bullish = signals == 1
    bearish = signals == -1
    if not bullish.any() or not bearish.any():
        return float("nan")
    return float(((outcomes[bullish] == 1).mean() + (outcomes[bearish] == -1).mean()) / 2)


def bh_adjust(pairs: list[tuple[str, float]]) -> dict[str, float]:
    ordered = sorted(pairs, key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 1.0
    for rank_from_end in range(count - 1, -1, -1):
        code, p_value = ordered[rank_from_end]
        rank = rank_from_end + 1
        running = min(running, p_value * count / rank)
        adjusted[code] = min(1.0, running)
    return adjusted


def evaluate(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tests = registry()
    n_rows = len(rows)
    primary_outcomes = np.array([row["outcome_15_sign"] or 0 for row in rows], dtype=np.int8)
    signals_by_test = {
        test["code"]: np.array([signal_for(test, row) or 0 for row in rows], dtype=np.int8)
        for test in tests
    }
    months = sorted({row["month"] for row in rows})
    month_index = {month: idx for idx, month in enumerate(months)}
    rng_boot = np.random.default_rng(SEED)
    sampled_months = rng_boot.integers(0, len(months), size=(BOOTSTRAPS, len(months)))
    month_weights = np.zeros((BOOTSTRAPS, len(months)), dtype=np.int16)
    for index in range(len(months)):
        month_weights[:, index] = (sampled_months == index).sum(axis=1)

    valid_global = primary_outcomes != 0
    perm_matrix = np.tile(primary_outcomes, (PERMUTATIONS, 1))
    rng_perm = np.random.default_rng(SEED)
    for year in sorted({row["year"] for row in rows}):
        indices = np.array([idx for idx, row in enumerate(rows) if row["year"] == year and valid_global[idx]], dtype=int)
        values = primary_outcomes[indices]
        for sample in range(PERMUTATIONS):
            perm_matrix[sample, indices] = values[rng_perm.permutation(len(values))]

    results: list[dict[str, Any]] = []
    support_eligible: list[tuple[str, float]] = []
    for test in tests:
        code = test["code"]
        signal_vector = signals_by_test[code]
        eligible = (signal_vector != 0) & (primary_outcomes != 0)
        indices = np.flatnonzero(eligible)
        signal = signal_vector[indices]
        outcome = primary_outcomes[indices]
        support = len(indices)
        bullish = int((signal == 1).sum())
        bearish = int((signal == -1).sum())
        required_total = 40 if test["stage"] == 1 else 18
        required_each = 12 if test["stage"] == 1 else 5
        required_blocks = 4 if test["stage"] == 1 else 3
        per_block: list[dict[str, Any]] = []
        qualifying_blocks = 0
        block_minimum = 5 if test["stage"] == 1 else 4
        for block, _, _ in BLOCKS:
            block_indices = [idx for idx in indices if rows[idx]["block"] == block]
            if len(block_indices) >= block_minimum:
                qualifying_blocks += 1
            hits = [signal_vector[idx] * primary_outcomes[idx] > 0 for idx in block_indices]
            per_block.append({"block": block, "n": len(block_indices), "raw_hit_rate": (sum(hits) / len(hits) if hits else None)})
        support_pass = support >= required_total and bullish >= required_each and bearish >= required_each and qualifying_blocks >= required_blocks
        result: dict[str, Any] = {
            **test,
            "support": support,
            "bullish": bullish,
            "bearish": bearish,
            "qualifying_blocks": qualifying_blocks,
            "support_pass": support_pass,
            "blocks": per_block,
            "status": "SUPPORT_FAIL" if not support_pass else "PENDING_MULTIPLICITY",
        }
        if not support_pass:
            results.append(result)
            continue

        raw_hit = float((signal * outcome > 0).mean())
        dbhr = balanced_hit(signal, outcome)
        signed_abs = np.array([signal_vector[idx] * float(rows[idx]["outcome_15_abs"]) for idx in indices], dtype=float)
        signed_pct = np.array([signal_vector[idx] * float(rows[idx]["outcome_15_pct"]) for idx in indices], dtype=float)

        month_bull_total = np.zeros(len(months), dtype=float)
        month_bull_hits = np.zeros(len(months), dtype=float)
        month_bear_total = np.zeros(len(months), dtype=float)
        month_bear_hits = np.zeros(len(months), dtype=float)
        for idx in indices:
            mi = month_index[rows[idx]["month"]]
            if signal_vector[idx] == 1:
                month_bull_total[mi] += 1
                month_bull_hits[mi] += primary_outcomes[idx] == 1
            else:
                month_bear_total[mi] += 1
                month_bear_hits[mi] += primary_outcomes[idx] == -1
        bull_den = month_weights @ month_bull_total
        bear_den = month_weights @ month_bear_total
        valid_boot = (bull_den > 0) & (bear_den > 0)
        boot_values = 0.5 * (
            (month_weights[valid_boot] @ month_bull_hits) / bull_den[valid_boot]
            + (month_weights[valid_boot] @ month_bear_hits) / bear_den[valid_boot]
        )
        ci_low, ci_high = np.quantile(boot_values, [0.05, 0.95])

        perm_selected = perm_matrix[:, indices]
        bull_mask = signal == 1
        bear_mask = signal == -1
        perm_dbhr = 0.5 * (
            (perm_selected[:, bull_mask] == 1).mean(axis=1)
            + (perm_selected[:, bear_mask] == -1).mean(axis=1)
        )
        permutation_p = float((1 + np.count_nonzero(perm_dbhr >= dbhr - 1e-15)) / (PERMUTATIONS + 1))

        hour_indices = [idx for idx in indices if rows[idx]["outcome_60_sign"] is not None]
        hour_signal = np.array([signal_vector[idx] for idx in hour_indices], dtype=np.int8)
        hour_outcome = np.array([rows[idx]["outcome_60_sign"] for idx in hour_indices], dtype=np.int8)
        hour_dbhr = balanced_hit(hour_signal, hour_outcome) if len(hour_indices) else float("nan")
        hour_signed_abs = [signal_vector[idx] * float(rows[idx]["outcome_60_abs"]) for idx in hour_indices]

        result.update(
            {
                "raw_hit_rate": raw_hit,
                "direction_balanced_hit_rate": dbhr,
                "mean_signed_absolute_change": float(signed_abs.mean()),
                "median_signed_absolute_change": float(np.median(signed_abs)),
                "mean_signed_percent_change": float(signed_pct.mean()),
                "median_signed_percent_change": float(np.median(signed_pct)),
                "bootstrap_90_ci_direction_balanced_hit_rate": [float(ci_low), float(ci_high)],
                "bootstrap_valid_resamples": int(valid_boot.sum()),
                "permutation_p": permutation_p,
                "one_hour_support": len(hour_indices),
                "one_hour_direction_balanced_hit_rate": hour_dbhr,
                "one_hour_mean_signed_absolute_change": (float(np.mean(hour_signed_abs)) if hour_signed_abs else None),
            }
        )
        support_eligible.append((code, permutation_p))
        results.append(result)

    adjusted = bh_adjust(support_eligible)
    candidates: list[dict[str, Any]] = []
    for result in results:
        if not result["support_pass"]:
            continue
        result["bh_q"] = adjusted[result["code"]]
        eligible_blocks = [item for item in result["blocks"] if item["n"] >= (5 if result["stage"] == 1 else 4)]
        positive_blocks = sum(item["raw_hit_rate"] > 0.50 for item in eligible_blocks)
        no_bad_block = all(item["raw_hit_rate"] >= 0.42 for item in eligible_blocks)
        gates = {
            "primary_dbhr_gte_threshold": result["direction_balanced_hit_rate"] >= (0.56 if result["stage"] == 1 else 0.60),
            "primary_mean_signed_positive": result["mean_signed_absolute_change"] > 0,
            "primary_median_signed_positive": result["median_signed_absolute_change"] > 0,
            "bootstrap_lower_gt_half": result["bootstrap_90_ci_direction_balanced_hit_rate"][0] > 0.50,
            "bh_q_lte_0_10": result["bh_q"] <= 0.10,
            "at_least_four_positive_blocks": positive_blocks >= 4,
            "no_eligible_block_below_0_42": no_bad_block,
            "one_hour_dbhr_gte_0_47": math.isfinite(result["one_hour_direction_balanced_hit_rate"]) and result["one_hour_direction_balanced_hit_rate"] >= 0.47,
            "one_hour_mean_signed_nonnegative": result["one_hour_mean_signed_absolute_change"] is not None and result["one_hour_mean_signed_absolute_change"] >= 0,
        }
        result["gates"] = gates
        result["failed_gates"] = [code for code, passed in gates.items() if not passed]
        if all(gates.values()):
            result["status"] = "PASS_PROVISIONAL_UNVALIDATED"
            candidates.append(result)
        else:
            result["status"] = "REJECT"

    candidates.sort(
        key=lambda row: (
            row["bh_q"],
            -row["direction_balanced_hit_rate"],
            -row["median_signed_absolute_change"],
            -row["support"],
            row["code"],
        )
    )
    selected = [row["code"] for row in candidates[:3]]
    if len(candidates) > 3:
        raise RuntimeError("Frozen candidate limit exceeded")
    diagnostics = {
        "test_count": len(tests),
        "support_eligible_count": len(support_eligible),
        "support_fail_count": sum(not row["support_pass"] for row in results),
        "rejected_count": sum(row["status"] == "REJECT" for row in results),
        "candidate_count": len(candidates),
        "selected_candidates": selected,
        "bootstrap_resamples": BOOTSTRAPS,
        "permutations": PERMUTATIONS,
        "seed": SEED,
    }
    return results, diagnostics


def rounded(value: Any) -> Any:
    if isinstance(value, np.generic):
        return rounded(value.item())
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return round(value, 10)
    if isinstance(value, list):
        return [rounded(item) for item in value]
    if isinstance(value, dict):
        return {key: rounded(item) for key, item in value.items()}
    return value


def write_report(payload: dict[str, Any]) -> str:
    diagnostics = payload["diagnostics"]
    candidates = diagnostics["selected_candidates"]
    lines = [
        "# Gold Macro-Acceptance Edge Discovery V1 Result",
        "",
        "## Verdict",
        "",
        f"Formal verdict: `{payload['verdict']}`.",
        "",
        f"The frozen study tested {diagnostics['test_count']} preregistered conditions. "
        f"{diagnostics['support_eligible_count']} met support, {diagnostics['support_fail_count']} failed support, "
        f"and {diagnostics['rejected_count']} support-eligible tests were rejected.",
        "",
        f"Provisional unvalidated candidates: {', '.join(candidates) if candidates else 'none'}.",
        "",
        "This is a development result only. It contains no entries, exits, costs, trades, PnL, R multiples, or account-return claims. No 2025 observation was used. The preserved failed loader deserialized 2,164 January-2025 XAUUSD rows before stopping, so 2025 retains zero validation credit; 2026 remained unopened.",
        "",
        "## Population and reproduction",
        "",
        f"- Event cases: {payload['population']['event_cases']}",
        f"- Unique release anchors: {payload['population']['anchors']}",
        f"- Coincident release timestamps: {payload['population']['coincident_anchors']}",
        f"- Primary/reference anchor checksum: `{payload['reproduction']['anchor_checksum']}`",
        f"- Complete result checksum: `{payload['reproduction']['result_checksum']}`",
        f"- Independent reproduction: `{payload['reproduction']['status']}`",
        "",
        "## Test results",
        "",
        "| Test | Stage | N | Bull/Bear | Balanced hit | 90% block CI | Permutation p | BH q | Verdict | Failed gates |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in payload["results"]:
        if not row["support_pass"]:
            lines.append(
                f"| `{row['code']}` | {row['stage']} | {row['support']} | {row['bullish']}/{row['bearish']} | — | — | — | — | `SUPPORT_FAIL` | support |"
            )
            continue
        ci = row["bootstrap_90_ci_direction_balanced_hit_rate"]
        lines.append(
            f"| `{row['code']}` | {row['stage']} | {row['support']} | {row['bullish']}/{row['bearish']} | "
            f"{100 * row['direction_balanced_hit_rate']:.2f}% | {100 * ci[0]:.2f}%–{100 * ci[1]:.2f}% | "
            f"{row['permutation_p']:.5f} | {row['bh_q']:.5f} | `{row['status']}` | "
            f"{', '.join(row.get('failed_gates', [])) or 'none'} |"
        )
    lines.extend(
        [
            "",
            "## Controls",
            "",
            "- The protocol and complete 26-test registry were hashed before outcomes were opened.",
            "- Coincident releases were collapsed to one timestamp-level anchor.",
            "- Signals used information available no later than release plus five minutes.",
            "- Multiplicity was applied across all support-eligible primary tests.",
            "- No test was inverted, retuned, added, or removed after outcome access.",
            "- No provider request, download, or charge occurred.",
            "- No 2025 value entered this analysis. Recovery A records the failed loader's technical deserialization of 2,164 January-2025 rows; 2026 remained unopened.",
            "",
            "## Interpretation boundary",
            "",
            "A PASS is only a provisional development candidate requiring forward validation. A zero-candidate result rejects this bounded family; it does not prove that every possible gold process is random.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    predecessor_hashes = verify_predecessors()
    xau_paths = pre2025_xau_files()
    xau_inventory = verify_xau_file_inventory(xau_paths)
    OUT.mkdir(parents=True, exist_ok=True)

    events = read_jsonl_gz(EVENTS)
    fundamentals, positioning = load_point_in_time_contexts()
    bars = load_xau_bars(xau_paths)
    primary = build_primary(events, fundamentals, positioning, bars)
    reference = build_reference(events, fundamentals, positioning, bars)
    if len(primary) != 346 or len(reference) != 346:
        raise RuntimeError(f"Anchor count mismatch: {len(primary)}, {len(reference)}")
    primary_rounded = rounded(primary)
    reference_rounded = rounded(reference)
    anchor_checksum = canonical_hash(primary_rounded)
    if anchor_checksum != canonical_hash(reference_rounded):
        raise RuntimeError("Primary/reference anchor reproduction mismatch")

    results_primary, diagnostics_primary = evaluate(primary)
    results_reference, diagnostics_reference = evaluate(reference)
    result_checksum = canonical_hash(rounded({"results": results_primary, "diagnostics": diagnostics_primary}))
    if result_checksum != canonical_hash(rounded({"results": results_reference, "diagnostics": diagnostics_reference})):
        raise RuntimeError("Primary/reference result reproduction mismatch")

    candidate_count = diagnostics_primary["candidate_count"]
    verdict = "PASS_PROVISIONAL_CANDIDATES_FOUND" if candidate_count else "REJECT_NO_PROVISIONAL_MACRO_ACCEPTANCE_EDGE"
    event_case_count = sum(row["event_case_count"] for row in primary)
    payload = rounded(
        {
            "version": "GOLD_MACRO_ACCEPTANCE_EDGE_DISCOVERY_RESULT_V0_1",
            "verdict": verdict,
            "population": {
                "start_inclusive": iso(START),
                "end_exclusive": iso(END),
                "event_cases": event_case_count,
                "anchors": len(primary),
                "coincident_anchors": sum(row["event_case_count"] > 1 for row in primary),
                "event_family_counts": dict(sorted(Counter(family for row in primary for family in row["event_families"]).items())),
            },
            "source_integrity": {
                "predecessor_hashes": predecessor_hashes,
                "xau_raw_inventory": xau_inventory,
                "calendar_2025_rows_deserialized_in_preserved_failed_attempt": 2164,
                "calendar_2025_rows_used_in_analysis": 0,
                "calendar_2026_source_opened": False,
                "downloads": 0,
                "charges_usd": 0.0,
            },
            "feature_availability": {
                "F": sum(row["F"] is not None for row in primary),
                "M": sum(row["M"] is not None for row in primary),
                "G": sum(row["G"] is not None for row in primary),
                "B": sum(row["B"] is not None for row in primary),
                "COT": sum(row["crowding"] is not None for row in primary),
                "ASIA": sum(row["asia"].get("status") == "READY" for row in primary),
                "OUTCOME_15": sum(row["outcome_15_sign"] is not None for row in primary),
                "OUTCOME_60": sum(row["outcome_60_sign"] is not None for row in primary),
            },
            "diagnostics": diagnostics_primary,
            "results": results_primary,
            "reproduction": {
                "status": "PASS_EXACT_PRIMARY_REFERENCE_REPRODUCTION",
                "anchor_checksum": anchor_checksum,
                "result_checksum": result_checksum,
            },
            "research_boundaries": {
                "candidates_are_unvalidated": True,
                "execution_optimized": False,
                "trades_calculated": False,
                "pnl_calculated": False,
                "calendar_2025_technical_source_opening_recorded": True,
                "calendar_2025_rows_used": 0,
                "calendar_2026_opened": False,
            },
        }
    )

    cases_path = OUT / "anchors.jsonl"
    with cases_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in primary_rounded:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    results_path = OUT / "results.json"
    results_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    report_path = ROOT / "GOLD_MACRO_ACCEPTANCE_EDGE_DISCOVERY_V1_RESULT.md"
    report_path.write_text(write_report(payload), encoding="utf-8", newline="\n")

    seal = {
        "version": "GOLD_MACRO_ACCEPTANCE_EDGE_DISCOVERY_FINAL_SEAL_V0_1",
        "verdict": verdict,
        "artifacts": [
            {"path": str(cases_path.relative_to(ROOT)).replace("\\", "/"), "bytes": cases_path.stat().st_size, "sha256": sha256(cases_path)},
            {"path": str(results_path.relative_to(ROOT)).replace("\\", "/"), "bytes": results_path.stat().st_size, "sha256": sha256(results_path)},
            {"path": str(report_path.relative_to(ROOT)).replace("\\", "/"), "bytes": report_path.stat().st_size, "sha256": sha256(report_path)},
        ],
        "contract_sha256": EXPECTED_HASHES[CONTRACT],
        "freeze_sha256": EXPECTED_HASHES[FREEZE],
        "recovery_amendment_sha256": EXPECTED_HASHES[AMENDMENT],
        "serialization_amendment_sha256": EXPECTED_HASHES[SERIALIZATION_AMENDMENT],
        "tool_sha256": sha256(Path(__file__).resolve()),
        "anchor_checksum": anchor_checksum,
        "result_checksum": result_checksum,
        "candidate_count": candidate_count,
        "calendar_2025_technical_source_opening_recorded": True,
        "calendar_2025_rows_used": 0,
        "calendar_2026_opened": False,
        "charges_usd": 0.0,
        "stop_required": True,
    }
    seal_path = OUT / "final_seal.json"
    seal_path.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"verdict": verdict, "candidate_count": candidate_count, "selected_candidates": diagnostics_primary["selected_candidates"], "anchors": len(primary), "support_eligible": diagnostics_primary["support_eligible_count"], "seal_sha256": sha256(seal_path)}, indent=2))


if __name__ == "__main__":
    main()
