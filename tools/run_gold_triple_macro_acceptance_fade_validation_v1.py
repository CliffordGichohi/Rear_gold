from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research_artifacts" / "gold_triple_macro_acceptance_fade_validation_v01"
CONTRACT = ROOT / "GOLD_TRIPLE_MACRO_ACCEPTANCE_FADE_VALIDATION_CONTRACT_V1.md"
FREEZE = ROOT / "research_manifests" / "gold_triple_macro_acceptance_fade_validation_v01.json"
AUTHORIZATION = ROOT / "GOLD_TRIPLE_MACRO_ACCEPTANCE_FADE_ACQUISITION_AUTHORIZATION_V1.md"
ACQUISITION = ROOT / "data" / "raw" / "databento_gold_fade_validation_v01" / "acquisition_manifest.json"
EVENT_HISTORY = ROOT / "research_artifacts" / "gold_casebook_v01" / "events.jsonl.gz"
EVENTS_2025 = ROOT / "data" / "mt5" / "calendar" / "us_gold_macro_calendar_2025_p1.json"
EVENTS_2026 = ROOT / "data" / "mt5" / "calendar" / "us_gold_macro_calendar_2026_p1.json"
EVENT_RULES = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "events.py"
ZN_2025 = ROOT / "data" / "raw" / "databento_cme_2025_zn" / "GLBX-20260729-4KJJLBXRRH" / "normalized" / "zn_v_0_2025_ohlcv_1m.csv.gz"
ZT_2025 = ROOT / "data" / "raw" / "databento_gold_fade_validation_v01" / "ZT_2025" / "normalized" / "zt_v_0_ohlcv_1m.csv.gz"
ZT_2026 = ROOT / "data" / "raw" / "databento_gold_fade_validation_v01" / "ZT_ZN_2026_YTD" / "normalized" / "zt_v_0_ohlcv_1m.csv.gz"
ZN_2026 = ROOT / "data" / "raw" / "databento_gold_fade_validation_v01" / "ZT_ZN_2026_YTD" / "normalized" / "zn_v_0_ohlcv_1m.csv.gz"

START_2025 = datetime(2025, 1, 1, tzinfo=UTC)
END_2025 = datetime(2026, 1, 1, tzinfo=UTC)
START_2026 = datetime(2026, 1, 1, tzinfo=UTC)
END_2026 = datetime(2026, 7, 30, tzinfo=UTC)
SEED = 20260807
BOOTSTRAPS = 20_000
PERMUTATIONS = 50_000

EXPECTED_HASHES = {
    CONTRACT: "68554b9a1169ad50d8f89d63a65db3d9c87a390020ba1d2e1b7868c4c36bddd9",
    FREEZE: "7c16670df2e6361c81c762ae34903fd27fc2427a53ec1ff900fe8e1f2b128c3f",
    AUTHORIZATION: "f47f3d8d8e309429a5e07a1b18ada870f8390aaa87bd5b9f3102d552c482fbcf",
    ACQUISITION: "890cfed6d1e7a31f7b210baa2377af1c81c29a7c32832b3074dbd4c3a8c40ef8",
    EVENT_HISTORY: "c7875e09d9ed831ece0f223b8be5efb75550af5bf1996a2dfea9d6119b24e35f",
    EVENTS_2025: "84cf48a760bc61f49fd9bee331d2f29a7b528a606edd035db2b0d09ea67075ab",
    EVENTS_2026: "39a2d8e238aad002083f72a3ea4b7c3d32d09b7c8b0a34614b6d157861abba1b",
    EVENT_RULES: "a30ce15eb42d0717f590ec3ce4c3205c2724db817f0b2a63bf10a251e37e0594",
    ZN_2025: "775050d1991b2df4e9fc53e8cdbed3abdc135b5618e31e95f54786446acf190f",
    ZT_2025: "37c84434fff59eb4c3c3d52075c44af0fa7bdd3aacca6b7350c15d4f2d989740",
    ZT_2026: "2957c82da204177157ea23d995ac6d6dbd961d2406b4287474e40a4020d77317",
    ZN_2026: "3693ee2b831377888c9c602b30f081600187a7ed29c387db4bf28ad40233f29f",
}

EXPECTED_MT5_INVENTORIES = {
    ("EURUSD", 2025): "47d7f6344a5192bfc2863db7894a455a08b20abf75228078b887099fad944985",
    ("EURUSD", 2026): "d5f7ba49d99f379f5dbf5753fb9d804c4a9e7528a04c9a30bfe1fd9bc999669c",
    ("XAUUSD", 2025): "3c360b5e046159bce940734ace932b29e41060eeb41891db464343478b2cc779",
    ("XAUUSD", 2026): "93ae6cc1c560575f709c29edb72ab02d50ef06edff8dd7d39ae620dded8d2771",
}


def main() -> None:
    args = parser().parse_args()
    if args.synthetic_proof:
        synthetic_proof()
        return
    execute()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--synthetic-proof", action="store_true")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def iso(value: datetime | pd.Timestamp) -> str:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    else:
        parsed = parsed.tz_convert("UTC")
    return parsed.isoformat().replace("+00:00", "Z")


def sign(value: float | int | None) -> int | None:
    if value is None or not math.isfinite(float(value)):
        return None
    if float(value) > 1e-12:
        return 1
    if float(value) < -1e-12:
        return -1
    return None


def rounded(value: float | None) -> float | None:
    return None if value is None or not math.isfinite(value) else round(float(value), 12)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def verify_predecessors() -> dict[str, Any]:
    verified: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"Predecessor hash mismatch: {path}: {actual} != {expected}")
        verified[str(path.relative_to(ROOT)).replace("\\", "/")] = actual
    freeze = load_json(FREEZE)
    if freeze.get("status") != "FROZEN_BEFORE_2025_2026_RELATIONSHIP_ACCESS":
        raise RuntimeError("Validation rule is not in the frozen state")
    acquisition = load_json(ACQUISITION)
    expected_seal = canonical_hash(
        {key: value for key, value in acquisition.items() if key != "seal_sha256"}
    )
    if (
        acquisition.get("status") != "NORMALIZED_HASHED_AND_SEALED"
        or acquisition.get("seal_sha256") != expected_seal
        or acquisition.get("actual_combined_cost_usd", 99) > 2.50
        or acquisition.get("card_charge_authorized") is not False
    ):
        raise RuntimeError("Databento acquisition seal or authorization gate failed")
    inventories: dict[str, Any] = {}
    for (symbol, year), expected in EXPECTED_MT5_INVENTORIES.items():
        start, end = (START_2025, END_2025) if year == 2025 else (START_2026, END_2026)
        files = mt5_files(symbol, start, end)
        rows = [
            f"{path.relative_to(ROOT).as_posix()}|{path.stat().st_size}|{sha256(path)}"
            for path in files
        ]
        actual = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
        if actual != expected:
            raise RuntimeError(f"{symbol} {year} source inventory changed: {actual}")
        inventories[f"{symbol}_{year}"] = {
            "file_count": len(files),
            "bytes": sum(path.stat().st_size for path in files),
            "sha256": actual,
        }
    return {
        "verified_file_hashes": verified,
        "mt5_inventories": inventories,
        "acquisition_seal_sha256": expected_seal,
        "actual_acquisition_cost_usd": acquisition["actual_combined_cost_usd"],
    }


def mt5_files(symbol: str, start: datetime, end: datetime) -> list[Path]:
    pattern = re.compile(r"_(20\d{6}T\d{4})_(20\d{6}T\d{4})\.csv$")
    output: list[Path] = []
    for path in (ROOT / "data" / "mt5").rglob(f"{symbol.lower()}_1m_*.csv"):
        match = pattern.search(path.name)
        if not match:
            continue
        file_start = datetime.strptime(match.group(1), "%Y%m%dT%H%M").replace(tzinfo=UTC)
        file_end = datetime.strptime(match.group(2), "%Y%m%dT%H%M").replace(tzinfo=UTC)
        if file_end >= start and file_start < end:
            output.append(path)
    return sorted(output, key=lambda item: str(item.resolve()).lower())


def load_mt5(symbol: str, start: datetime, end: datetime) -> tuple[pd.DataFrame, dict[str, Any]]:
    columns = [
        "open_time",
        "close_time",
        "available_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "volume_type",
        "spread_points",
        "real_volume",
    ]
    frames: list[pd.DataFrame] = []
    for path in mt5_files(symbol, start, end):
        frame = pd.read_csv(path, usecols=columns)
        for field in ("open_time", "close_time", "available_at"):
            frame[field] = pd.to_datetime(frame[field], utc=True)
        frame = frame[
            (frame["open_time"] >= pd.Timestamp(start))
            & (frame["open_time"] < pd.Timestamp(end))
        ].copy()
        frame["source_file"] = str(path.relative_to(ROOT)).replace("\\", "/")
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    semantic = [field for field in columns if field != "open_time"]
    combined["semantic_hash"] = pd.util.hash_pandas_object(
        combined[semantic], index=False
    ).astype("uint64")
    duplicate_groups = combined[combined.duplicated("open_time", keep=False)].groupby(
        "open_time", sort=True
    )["semantic_hash"].nunique()
    conflict_count = int((duplicate_groups > 1).sum())
    if conflict_count:
        raise RuntimeError(f"{symbol} has {conflict_count} conflicting duplicate timestamps")
    raw_rows = len(combined)
    combined.sort_values(["open_time", "source_file"], inplace=True, kind="mergesort")
    combined.drop_duplicates("open_time", keep="first", inplace=True)
    if combined["open_time"].duplicated().any():
        raise RuntimeError(f"{symbol} canonical timestamps are not unique")
    if not (
        (combined["close_time"] == combined["open_time"] + pd.Timedelta(minutes=1)).all()
        and (combined["available_at"] == combined["close_time"]).all()
    ):
        raise RuntimeError(f"{symbol} timestamp availability semantics failed")
    combined.sort_values("open_time", inplace=True)
    diagnostics = {
        "raw_rows": raw_rows,
        "canonical_rows": len(combined),
        "duplicates_beyond_first": raw_rows - len(combined),
        "duplicate_conflict_groups": conflict_count,
        "first": iso(combined["open_time"].iloc[0]),
        "last": iso(combined["open_time"].iloc[-1]),
    }
    return combined.set_index("open_time", drop=False), diagnostics


def load_cme(paths: Iterable[Path], symbol: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        frame = pd.read_csv(
            path,
            compression="gzip",
            usecols=["open_time", "available_at", "continuous_symbol", "instrument_id", "close"],
        )
        frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
        frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True)
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    if set(combined["continuous_symbol"].astype(str).unique()) != {symbol}:
        raise RuntimeError(f"Unexpected symbol in {symbol} normalized sources")
    combined.sort_values("open_time", inplace=True, kind="mergesort")
    if combined["open_time"].duplicated().any():
        raise RuntimeError(f"Duplicate CME {symbol} timestamp")
    if not (combined["available_at"] == combined["open_time"] + pd.Timedelta(minutes=1)).all():
        raise RuntimeError(f"CME {symbol} availability semantics failed")
    return combined.set_index("open_time", drop=False)


def surprise_history() -> dict[str, list[float]]:
    unique: dict[tuple[str, str], tuple[datetime, float]] = {}
    with gzip.open(EVENT_HISTORY, "rt", encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            released = parse_ts(event["released_at"])
            if released >= START_2025:
                continue
            for item in event.get("standardized_surprises", []):
                key = (str(item["component_code"]), str(item["release_id"]))
                candidate = (released, float(item["raw_surprise"]))
                existing = unique.get(key)
                if existing is not None and existing != candidate:
                    raise RuntimeError("Historical surprise-version values conflict")
                unique[key] = candidate
    histories: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for (component, _), item in unique.items():
        histories[component].append(item)
    return {
        component: [value for _, value in sorted(items)]
        for component, items in histories.items()
    }


def build_forward_facts() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    backend_src = ROOT / "backend" / "src"
    import sys

    if str(backend_src) not in sys.path:
        sys.path.insert(0, str(backend_src))
    from gold_intel.analytics.events import SURPRISE_SPEC_BY_CODE

    history = surprise_history()
    grouped: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    event_counts = Counter()
    for path in (EVENTS_2025, EVENTS_2026):
        bundle = load_json(path)
        for event in bundle["events"]:
            released_raw = event.get("released_at")
            if event.get("status") != "RELEASED" or not released_raw:
                continue
            released = parse_ts(released_raw)
            if not (START_2025 <= released < END_2026):
                continue
            forecasts: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in event.get("forecasts", []):
                if parse_ts(item["available_at"]) <= released:
                    forecasts[str(item["component_code"])].append(item)
            components: list[dict[str, Any]] = []
            for release in event.get("releases", []):
                component = str(release["component_code"])
                specification = SURPRISE_SPEC_BY_CODE.get(component)
                candidates = forecasts.get(component, [])
                if specification is None or not candidates:
                    continue
                forecast = max(
                    candidates,
                    key=lambda item: (parse_ts(item["available_at"]), parse_ts(item["forecast_as_of"])),
                )
                raw = float(release["actual_value"]) - float(forecast["forecast_value"])
                prior = history.setdefault(component, [])
                scale = float(specification.fallback_scale)
                method = "CONFIGURED_FALLBACK_SCALE"
                if len(prior) >= 5:
                    deviation = statistics.stdev(prior)
                    if deviation > 1e-12:
                        scale = deviation
                        method = "EXPANDING_PRIOR_STD"
                standardized = max(-4.0, min(4.0, raw / scale))
                direction = max(-1.0, min(1.0, float(specification.gold_sign) * standardized))
                components.append(
                    {
                        "component_code": component,
                        "raw_surprise": raw,
                        "gold_direction": direction,
                        "history_count": len(prior),
                        "method": method,
                        "source_value_id": release["metadata"]["source_value_id"],
                    }
                )
                prior.append(raw)
            grouped[released].append(
                {
                    "event_code": event["event_code"],
                    "event_type": event["event_type"],
                    "components": components,
                }
            )
            event_counts[str(event["event_type"])] += 1

    output: list[dict[str, Any]] = []
    for released, events in sorted(grouped.items()):
        components = [item for event in events for item in event["components"]]
        component_ids = [
            (item["component_code"], item["source_value_id"]) for item in components
        ]
        if len(component_ids) != len(set(component_ids)):
            raise RuntimeError(f"Duplicate forward event-component at {released}")
        total = sum(float(item["gold_direction"]) for item in components)
        output.append(
            {
                "released_at": iso(released),
                "year": released.year,
                "month": released.strftime("%Y-%m"),
                "event_families": sorted({event["event_type"] for event in events}),
                "event_codes": sorted({event["event_code"] for event in events}),
                "component_count": len(components),
                "component_codes": sorted(item["component_code"] for item in components),
                "F": sign(total) if components else None,
                "fundamental_sum": rounded(total) if components else None,
            }
        )
    return output, {
        "unique_release_timestamps": len(output),
        "timestamps_with_fundamental_direction": sum(row["F"] is not None for row in output),
        "events_by_family": dict(sorted(event_counts.items())),
    }


def endpoint(timestamp: datetime, minutes: int) -> pd.Timestamp:
    return pd.Timestamp(timestamp + timedelta(minutes=minutes - 1))


def lookup_frame(frame: pd.DataFrame, timestamp: pd.Timestamp, as_of: pd.Timestamp) -> tuple[float, int | None] | None:
    if timestamp not in frame.index:
        return None
    row = frame.loc[timestamp]
    if isinstance(row, pd.DataFrame):
        raise RuntimeError("Nonunique source timestamp")
    if pd.Timestamp(row["available_at"]) > as_of:
        return None
    instrument = int(row["instrument_id"]) if "instrument_id" in row else None
    return float(row["close"]), instrument


def frame_to_lookup(frame: pd.DataFrame) -> dict[int, tuple[float, int | None, int]]:
    output: dict[int, tuple[float, int | None, int]] = {}
    has_instrument = "instrument_id" in frame.columns
    for row in frame.itertuples(index=False):
        key = int(pd.Timestamp(row.open_time).value)
        instrument = int(row.instrument_id) if has_instrument else None
        output[key] = (float(row.close), instrument, int(pd.Timestamp(row.available_at).value))
    return output


def lookup_dict(
    values: dict[int, tuple[float, int | None, int]],
    timestamp: pd.Timestamp,
    as_of: pd.Timestamp,
) -> tuple[float, int | None] | None:
    row = values.get(int(timestamp.value))
    if row is None or row[2] > int(as_of.value):
        return None
    return row[0], row[1]


def construct_anchors_primary(
    facts: list[dict[str, Any]],
    sources: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    return [construct_anchor(row, lambda name, ts, cutoff: lookup_frame(sources[name], ts, cutoff)) for row in facts]


def construct_anchors_reference(
    facts: list[dict[str, Any]],
    sources: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    lookups = {name: frame_to_lookup(frame) for name, frame in sources.items()}
    return [construct_anchor(row, lambda name, ts, cutoff: lookup_dict(lookups[name], ts, cutoff)) for row in facts]


def construct_anchor(row: dict[str, Any], getter: Any) -> dict[str, Any]:
    released = parse_ts(row["released_at"])
    ref_ts = endpoint(released, 0)
    five_ts = endpoint(released, 5)
    fifteen_ts = endpoint(released, 15)
    hour_ts = endpoint(released, 60)
    ref_asof = pd.Timestamp(released)
    five_asof = pd.Timestamp(released + timedelta(minutes=5))
    fifteen_asof = pd.Timestamp(released + timedelta(minutes=15))
    hour_asof = pd.Timestamp(released + timedelta(minutes=60))

    points: dict[str, Any] = {}
    for source in ("ZT", "ZN", "EURUSD", "XAUUSD"):
        points[f"{source}_REF"] = getter(source, ref_ts, ref_asof)
        points[f"{source}_5"] = getter(source, five_ts, five_asof)
    points["XAUUSD_15"] = getter("XAUUSD", fifteen_ts, fifteen_asof)
    points["XAUUSD_60"] = getter("XAUUSD", hour_ts, hour_asof)

    missing = sorted(key for key, value in points.items() if value is None)
    market_votes: list[int] = []
    roll_crossing = False
    if not missing:
        for source in ("ZT", "ZN", "EURUSD"):
            reference = points[f"{source}_REF"]
            five = points[f"{source}_5"]
            if source in {"ZT", "ZN"} and reference[1] != five[1]:
                roll_crossing = True
            vote = sign(five[0] - reference[0])
            if vote is not None:
                market_votes.append(vote)
    m_value = sign(sum(market_votes)) if len(market_votes) == 3 and not roll_crossing else None
    g_value = (
        sign(points["XAUUSD_5"][0] - points["XAUUSD_REF"][0])
        if not missing
        else None
    )
    eligible = row["F"] is not None and row["F"] == m_value == g_value
    prediction = -m_value if eligible and m_value is not None else None
    outcome15 = (
        points["XAUUSD_15"][0] - points["XAUUSD_5"][0]
        if not missing
        else None
    )
    outcome60 = (
        points["XAUUSD_60"][0] - points["XAUUSD_5"][0]
        if not missing
        else None
    )
    exclusion = None
    if missing:
        exclusion = "MISSING_EXACT_ENDPOINT"
    elif roll_crossing:
        exclusion = "CONTINUOUS_CONTRACT_CHANGED_WITHIN_REACTION_WINDOW"
    elif row["F"] is None:
        exclusion = "NO_ELIGIBLE_FUNDAMENTAL_SURPRISE"
    elif m_value is None or g_value is None:
        exclusion = "FLAT_OR_UNAVAILABLE_INITIAL_REACTION"
    elif not eligible:
        exclusion = "TRIPLE_CONFIRMATION_NOT_PRESENT"
    elif sign(outcome15) is None:
        exclusion = "FLAT_PRIMARY_OUTCOME"
    return {
        "anchor_id": f"TRIPLE_FADE::{row['released_at']}",
        "released_at": row["released_at"],
        "year": row["year"],
        "month": row["month"],
        "event_families": row["event_families"],
        "event_codes": row["event_codes"],
        "component_count": row["component_count"],
        "F": row["F"],
        "M": m_value,
        "G": g_value,
        "prediction": prediction,
        "eligible": bool(eligible and sign(outcome15) is not None),
        "outcome_15_displacement": rounded(outcome15),
        "outcome_15_sign": sign(outcome15),
        "outcome_60_displacement": rounded(outcome60),
        "outcome_60_sign": sign(outcome60),
        "missing_endpoints": missing,
        "roll_crossing": roll_crossing,
        "exclusion": exclusion,
    }


def balanced_hit(signals: np.ndarray, outcomes: np.ndarray) -> float | None:
    values: list[float] = []
    for direction in (-1, 1):
        selected = signals == direction
        if selected.any():
            values.append(float(np.mean(outcomes[selected] == signals[selected])))
    return float(np.mean(values)) if len(values) == 2 else None


def statistics_primary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    signals = np.asarray([row["prediction"] for row in rows], dtype=np.int8)
    outcomes15 = np.asarray([row["outcome_15_sign"] for row in rows], dtype=np.int8)
    outcomes60 = np.asarray([row["outcome_60_sign"] or 0 for row in rows], dtype=np.int8)
    displacements = np.asarray([row["outcome_15_displacement"] for row in rows], dtype=float)
    aligned = signals * displacements
    result = base_statistics(signals, outcomes15, outcomes60, aligned)
    result.update(resampling_primary(rows, signals, outcomes15))
    return result


def statistics_reference(rows: list[dict[str, Any]]) -> dict[str, Any]:
    signals = [int(row["prediction"]) for row in rows]
    outcomes15 = [int(row["outcome_15_sign"]) for row in rows]
    outcomes60 = [int(row["outcome_60_sign"] or 0) for row in rows]
    aligned = [signals[index] * float(rows[index]["outcome_15_displacement"]) for index in range(len(rows))]
    result = base_statistics(
        np.asarray(signals, dtype=np.int8),
        np.asarray(outcomes15, dtype=np.int8),
        np.asarray(outcomes60, dtype=np.int8),
        np.asarray(aligned, dtype=float),
    )
    result.update(resampling_reference(rows, signals, outcomes15))
    return result


def base_statistics(
    signals: np.ndarray,
    outcomes15: np.ndarray,
    outcomes60: np.ndarray,
    aligned: np.ndarray,
) -> dict[str, Any]:
    by_direction: dict[str, Any] = {}
    for direction, label in ((1, "BULLISH_FADE"), (-1, "BEARISH_FADE")):
        selected = signals == direction
        by_direction[label] = {
            "n": int(selected.sum()),
            "hit_rate": rounded(float(np.mean(outcomes15[selected] == signals[selected]))) if selected.any() else None,
        }
    valid60 = outcomes60 != 0
    return {
        "n": len(signals),
        "raw_hit_rate": rounded(float(np.mean(signals == outcomes15))) if len(signals) else None,
        "direction_balanced_hit_rate": rounded(balanced_hit(signals, outcomes15)),
        "by_prediction_direction": by_direction,
        "mean_signal_aligned_displacement": rounded(float(np.mean(aligned))) if len(aligned) else None,
        "median_signal_aligned_displacement": rounded(float(np.median(aligned))) if len(aligned) else None,
        "one_hour_n": int(valid60.sum()),
        "one_hour_direction_balanced_hit_rate": rounded(balanced_hit(signals[valid60], outcomes60[valid60])) if valid60.any() else None,
    }


def resampling_primary(
    rows: list[dict[str, Any]], signals: np.ndarray, outcomes: np.ndarray
) -> dict[str, Any]:
    months = sorted({row["month"] for row in rows})
    month_indices = {
        month: np.asarray([index for index, row in enumerate(rows) if row["month"] == month], dtype=int)
        for month in months
    }
    rng = np.random.default_rng(SEED)
    boot: list[float] = []
    for _ in range(BOOTSTRAPS):
        selected_months = rng.integers(0, len(months), size=len(months))
        indices = np.concatenate([month_indices[months[int(value)]] for value in selected_months])
        value = balanced_hit(signals[indices], outcomes[indices])
        if value is not None:
            boot.append(value)
    observed = balanced_hit(signals, outcomes)
    exceed = 0
    for _ in range(PERMUTATIONS):
        permuted = outcomes[rng.permutation(len(outcomes))]
        value = balanced_hit(signals, permuted)
        if value is not None and observed is not None and value >= observed - 1e-15:
            exceed += 1
    interval = np.quantile(np.asarray(boot), [0.05, 0.95], method="linear") if boot else [math.nan, math.nan]
    return {
        "bootstrap_90_interval": [rounded(float(interval[0])), rounded(float(interval[1]))],
        "bootstrap_valid_resamples": len(boot),
        "permutation_p_one_sided": rounded((exceed + 1) / (PERMUTATIONS + 1)),
        "permutation_count": PERMUTATIONS,
    }


def balanced_hit_list(signals: list[int], outcomes: list[int]) -> float | None:
    rates: list[float] = []
    for direction in (-1, 1):
        indices = [index for index, signal_value in enumerate(signals) if signal_value == direction]
        if indices:
            rates.append(sum(outcomes[index] == signals[index] for index in indices) / len(indices))
    return sum(rates) / len(rates) if len(rates) == 2 else None


def resampling_reference(
    rows: list[dict[str, Any]], signals: list[int], outcomes: list[int]
) -> dict[str, Any]:
    months = sorted({row["month"] for row in rows})
    by_month = {
        month: [index for index, row in enumerate(rows) if row["month"] == month]
        for month in months
    }
    rng = np.random.default_rng(SEED)
    boot: list[float] = []
    for _ in range(BOOTSTRAPS):
        choices = rng.integers(0, len(months), size=len(months)).tolist()
        indices = [index for choice in choices for index in by_month[months[int(choice)]]]
        value = balanced_hit_list(
            [signals[index] for index in indices],
            [outcomes[index] for index in indices],
        )
        if value is not None:
            boot.append(value)
    observed = balanced_hit_list(signals, outcomes)
    exceed = 0
    outcome_array = np.asarray(outcomes, dtype=np.int8)
    for _ in range(PERMUTATIONS):
        permuted = outcome_array[rng.permutation(len(outcomes))].tolist()
        value = balanced_hit_list(signals, permuted)
        if value is not None and observed is not None and value >= observed - 1e-15:
            exceed += 1
    interval = np.quantile(np.asarray(boot), [0.05, 0.95], method="linear") if boot else [math.nan, math.nan]
    return {
        "bootstrap_90_interval": [rounded(float(interval[0])), rounded(float(interval[1]))],
        "bootstrap_valid_resamples": len(boot),
        "permutation_p_one_sided": rounded((exceed + 1) / (PERMUTATIONS + 1)),
        "permutation_count": PERMUTATIONS,
    }


def disposition(year: int, result: dict[str, Any]) -> tuple[str, list[str]]:
    bullish = result["by_prediction_direction"]["BULLISH_FADE"]["n"]
    bearish = result["by_prediction_direction"]["BEARISH_FADE"]["n"]
    support = result["n"] >= (20 if year == 2025 else 10) and min(bullish, bearish) >= (5 if year == 2025 else 3)
    failed: list[str] = []
    if not support:
        failed.append("SUPPORT")
        return "INCONCLUSIVE", failed
    balanced = result["direction_balanced_hit_rate"]
    mean = result["mean_signal_aligned_displacement"]
    median = result["median_signal_aligned_displacement"]
    hour = result["one_hour_direction_balanced_hit_rate"]
    p_value = result["permutation_p_one_sided"]
    if year == 2025:
        gates = {
            "BALANCED_HIT_GTE_0_56": balanced is not None and balanced >= 0.56,
            "MEAN_POSITIVE": mean is not None and mean > 0,
            "MEDIAN_POSITIVE": median is not None and median > 0,
            "BOOTSTRAP_LOWER_GT_0_50": result["bootstrap_90_interval"][0] > 0.50,
            "PERMUTATION_P_LTE_0_10": p_value is not None and p_value <= 0.10,
            "ONE_HOUR_BALANCED_GTE_0_50": hour is not None and hour >= 0.50,
        }
        failed = [key for key, passed in gates.items() if not passed]
        return ("PASS" if not failed else "REJECT"), failed
    pass_gates = {
        "BALANCED_HIT_GTE_0_60": balanced is not None and balanced >= 0.60,
        "MEAN_POSITIVE": mean is not None and mean > 0,
        "MEDIAN_POSITIVE": median is not None and median > 0,
        "PERMUTATION_P_LTE_0_10": p_value is not None and p_value <= 0.10,
        "ONE_HOUR_BALANCED_GTE_0_50": hour is not None and hour >= 0.50,
    }
    failed = [key for key, passed in pass_gates.items() if not passed]
    if not failed:
        return "PASS", []
    rejection = (
        (balanced is not None and balanced <= 0.50)
        or (mean is not None and mean <= 0)
        or (hour is not None and hour < 0.45)
    )
    return ("REJECT" if rejection else "INCONCLUSIVE"), failed


def write_anchors(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("wb") as binary:
        with gzip.GzipFile(filename="", mode="wb", fileobj=binary, mtime=0) as compressed:
            for row in rows:
                compressed.write(
                    (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                )


def execute() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    state_path = OUT / "execution_state.json"
    result_path = OUT / "validation_result.json"
    if result_path.exists() or state_path.exists():
        raise FileExistsError("Validation has already been opened or completed")
    predecessors = verify_predecessors()
    facts, event_diagnostics = build_forward_facts()
    state = {
        "version": "GOLD_TRIPLE_MACRO_ACCEPTANCE_FADE_VALIDATION_EXECUTION_V0_1",
        "status": "OUTCOME_SOURCE_OPENING_RECORDED",
        "outcome_source_opening_count": 1,
        "opened_at": datetime.now(UTC).isoformat(),
        "predecessors": predecessors,
        "frozen_candidate": "TRIPLE_MACRO_ACCEPTANCE_FADE_V0_1",
        "fact_population_sha256": canonical_hash(facts),
        "event_diagnostics": event_diagnostics,
    }
    write_json_atomic(state_path, state)

    xau2025, xau2025_diag = load_mt5("XAUUSD", START_2025, END_2025)
    xau2026, xau2026_diag = load_mt5("XAUUSD", START_2026, END_2026)
    eur2025, eur2025_diag = load_mt5("EURUSD", START_2025, END_2025)
    eur2026, eur2026_diag = load_mt5("EURUSD", START_2026, END_2026)
    xau = pd.concat([xau2025, xau2026]).sort_index()
    eur = pd.concat([eur2025, eur2026]).sort_index()
    zt = load_cme([ZT_2025, ZT_2026], "ZT.v.0")
    zn = load_cme([ZN_2025, ZN_2026], "ZN.v.0")
    sources = {"XAUUSD": xau, "EURUSD": eur, "ZT": zt, "ZN": zn}

    primary = construct_anchors_primary(facts, sources)
    reference = construct_anchors_reference(facts, sources)
    if canonical_hash(primary) != canonical_hash(reference):
        raise RuntimeError("Primary/reference anchor reproduction failed")

    segments: dict[str, Any] = {}
    for year, code in ((2025, "EXPOSED_2025"), (2026, "INDEPENDENT_2026_YTD")):
        population = [row for row in primary if row["year"] == year]
        eligible = [row for row in population if row["eligible"]]
        primary_stats = statistics_primary(eligible)
        reference_stats = statistics_reference(eligible)
        if canonical_hash(primary_stats) != canonical_hash(reference_stats):
            raise RuntimeError(f"Primary/reference statistical reproduction failed for {year}")
        verdict, failed = disposition(year, primary_stats)
        segments[code] = {
            "year": year,
            "independent_validation_credit": year == 2026,
            "release_timestamp_population": len(population),
            "eligible_observations": len(eligible),
            "exclusion_counts": dict(sorted(Counter(row["exclusion"] or "ELIGIBLE" for row in population).items())),
            "event_family_counts_eligible": dict(
                sorted(Counter(family for row in eligible for family in row["event_families"]).items())
            ),
            "statistics": primary_stats,
            "verdict": verdict,
            "failed_gates": failed,
            "primary_reference_reproduced": True,
        }

    v2025 = segments["EXPOSED_2025"]["verdict"]
    v2026 = segments["INDEPENDENT_2026_YTD"]["verdict"]
    if v2025 == "PASS" and v2026 == "PASS":
        overall = "PASS_INDEPENDENT_DIRECTIONAL_NONRANDOMNESS"
    elif v2026 == "REJECT":
        overall = "REJECT_FADE_CANDIDATE"
    else:
        overall = "INCONCLUSIVE_CONTINUE_PROSPECTIVE"

    anchors_path = OUT / "validation_anchors.jsonl.gz"
    write_anchors(anchors_path, primary)
    payload = {
        "version": "GOLD_TRIPLE_MACRO_ACCEPTANCE_FADE_VALIDATION_RESULT_V0_1",
        "candidate": "TRIPLE_MACRO_ACCEPTANCE_FADE_V0_1",
        "overall_verdict": overall,
        "segments": segments,
        "population": event_diagnostics,
        "source_diagnostics": {
            "XAUUSD_2025": xau2025_diag,
            "XAUUSD_2026_YTD": xau2026_diag,
            "EURUSD_2025": eur2025_diag,
            "EURUSD_2026_YTD": eur2026_diag,
        },
        "reproduction": {
            "anchor_sha256": canonical_hash(primary),
            "primary_reference_exact": True,
            "bootstrap_resamples": BOOTSTRAPS,
            "permutations": PERMUTATIONS,
            "seed": SEED,
        },
        "artifacts": {
            "anchors_path": str(anchors_path.relative_to(ROOT)).replace("\\", "/"),
            "anchors_sha256": sha256(anchors_path),
        },
        "limitations": [
            "Calendar 2025 is exposed historical forward data and receives no independent-validation credit.",
            "The verdict concerns one exact conditional macro-acceptance fade state, not every gold price movement.",
            "No execution, transaction-cost, trade, PnL, R-multiple or account-return calculation was performed.",
        ],
    }
    payload["result_hash"] = canonical_hash(payload)
    write_json_atomic(result_path, payload)
    write_report(OUT / "validation_report.md", payload)

    ledger = OUT / "prospective_decision_ledger.jsonl"
    ledger.touch(exist_ok=False)
    ledger_manifest = {
        "version": "GOLD_TRIPLE_MACRO_ACCEPTANCE_FADE_PROSPECTIVE_LEDGER_V0_1",
        "initialized_at": datetime.now(UTC).isoformat(),
        "candidate": payload["candidate"],
        "append_only": True,
        "backfill_permitted": False,
        "initial_record_count": 0,
        "ledger_sha256": sha256(ledger),
    }
    write_json_atomic(OUT / "prospective_ledger_manifest.json", ledger_manifest)
    state.update(
        {
            "status": "VALIDATION_COMPLETED_AND_SEALED",
            "completed_at": datetime.now(UTC).isoformat(),
            "overall_verdict": overall,
            "result_path": str(result_path.relative_to(ROOT)).replace("\\", "/"),
            "result_file_sha256": sha256(result_path),
            "result_hash": payload["result_hash"],
            "prospective_ledger_initialized": True,
        }
    )
    state["state_hash"] = canonical_hash(state)
    write_json_atomic(state_path, state)
    print(
        json.dumps(
            {
                "overall_verdict": overall,
                "segments": {
                    key: {
                        "verdict": value["verdict"],
                        "eligible_observations": value["eligible_observations"],
                        **value["statistics"],
                        "failed_gates": value["failed_gates"],
                    }
                    for key, value in segments.items()
                },
                "result_hash": payload["result_hash"],
                "state_hash": state["state_hash"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def write_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Gold Triple Macro-Acceptance Fade Validation V1",
        "",
        "## Overall verdict",
        "",
        f"`{payload['overall_verdict']}`",
        "",
    ]
    for code in ("EXPOSED_2025", "INDEPENDENT_2026_YTD"):
        segment = payload["segments"][code]
        stats = segment["statistics"]
        lines.extend(
            [
                f"## {code}",
                "",
                f"- Verdict: `{segment['verdict']}`",
                f"- Eligible observations: {segment['eligible_observations']}",
                f"- Direction-balanced 15-minute hit rate: {100 * stats['direction_balanced_hit_rate']:.2f}%" if stats["direction_balanced_hit_rate"] is not None else "- Direction-balanced 15-minute hit rate: unavailable",
                f"- Raw hit rate: {100 * stats['raw_hit_rate']:.2f}%" if stats["raw_hit_rate"] is not None else "- Raw hit rate: unavailable",
                f"- Bullish-fade support/hit: {stats['by_prediction_direction']['BULLISH_FADE']['n']} / " + (f"{100 * stats['by_prediction_direction']['BULLISH_FADE']['hit_rate']:.2f}%" if stats['by_prediction_direction']['BULLISH_FADE']['hit_rate'] is not None else "unavailable"),
                f"- Bearish-fade support/hit: {stats['by_prediction_direction']['BEARISH_FADE']['n']} / " + (f"{100 * stats['by_prediction_direction']['BEARISH_FADE']['hit_rate']:.2f}%" if stats['by_prediction_direction']['BEARISH_FADE']['hit_rate'] is not None else "unavailable"),
                f"- Mean signal-aligned displacement: {stats['mean_signal_aligned_displacement']}",
                f"- Median signal-aligned displacement: {stats['median_signal_aligned_displacement']}",
                f"- Calendar-month bootstrap 90% interval: {stats['bootstrap_90_interval']}",
                f"- One-sided permutation p-value: {stats['permutation_p_one_sided']}",
                f"- One-hour direction-balanced hit rate: {100 * stats['one_hour_direction_balanced_hit_rate']:.2f}%" if stats["one_hour_direction_balanced_hit_rate"] is not None else "- One-hour direction-balanced hit rate: unavailable",
                f"- Failed gates: {segment['failed_gates'] or ['NONE']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation boundary",
            "",
            "This result tests one frozen conditional state only. It does not establish that all gold movement is predictable or random. No execution or PnL was tested.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def synthetic_proof() -> None:
    base = pd.Timestamp("2026-01-02T12:30:00Z")
    timestamps = pd.date_range(base - pd.Timedelta(minutes=1), periods=61, freq="min")
    def frame(values: list[float], instrument: int | None = None) -> pd.DataFrame:
        result = pd.DataFrame(
            {
                "open_time": timestamps,
                "available_at": timestamps + pd.Timedelta(minutes=1),
                "close": values,
            }
        )
        if instrument is not None:
            result["instrument_id"] = instrument
        return result.set_index("open_time", drop=False)
    values = [100.0 + index for index in range(len(timestamps))]
    sources = {
        "XAUUSD": frame(values),
        "EURUSD": frame(values),
        "ZT": frame(values, 1),
        "ZN": frame(values, 2),
    }
    facts = [
        {
            "released_at": iso(base),
            "year": 2026,
            "month": "2026-01",
            "event_families": ["CPI"],
            "event_codes": ["US_CPI"],
            "component_count": 1,
            "F": 1,
        }
    ]
    primary = construct_anchors_primary(facts, sources)
    reference = construct_anchors_reference(facts, sources)
    if primary != reference or primary[0]["prediction"] != -1:
        raise RuntimeError("Synthetic endpoint/join proof failed")
    if primary[0]["outcome_15_displacement"] != 10.0:
        raise RuntimeError("Synthetic [start,end) outcome boundary failed")
    print(
        json.dumps(
            {
                "status": "PASS_SYNTHETIC_SERIALIZER_JOIN_AND_BOUNDARY_PROOF",
                "primary_reference_exact": True,
                "future_bar_used_at_decision": False,
                "primary_outcome_displacement": 10.0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
