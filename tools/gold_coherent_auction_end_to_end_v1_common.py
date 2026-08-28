"""Shared deterministic machinery for the same-month autonomous translation audit."""

from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import math
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from calibrate_gold_coherent_auction_autonomous_semantics_v1 import (  # noqa: E402
    causal_breaks,
    merged_study_inputs,
    prepare_study,
    snapshot_features,
    timeframe_features,
)
from gold_intel.analytics.liquidity_shift_v2 import _confirmed_pivots  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    iso,
    parse_dt,
)


LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
MODEL_EXCLUDED_FIELDS = {
    "case_alias",
    "checkpoint_at",
    "label",
    "human_action",
    "human_decision_at",
    "m1_reference_close",
    "m15_atr_scale",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_stream(path: Path, expected_hash: str) -> dict[str, Any]:
    require(sha256_file(path) == expected_hash, f"Certified stream differs: {path}")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    submitted = payload.pop("stream_sha256")
    require(canonical_hash(payload) == submitted, f"Stream payload differs: {path}")
    payload["stream_sha256"] = submitted
    return payload


def load_certified_streams(
    certification_path: Path, side: str
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    require(
        certification["verdict"] == "PASS_CODEX_OPERATOR_PRIVATE_STREAM_MATERIALIZATION",
        "Replay source certification is not PASS",
    )
    streams: dict[str, dict[str, Any]] = {}
    lineage: list[dict[str, Any]] = []
    for record in certification["case_files"]:
        alias = str(record["case_alias"])
        source = record[side]
        path = ROOT / source["path"]
        streams[alias] = load_stream(path, str(source["sha256"]))
        lineage.append(
            {
                "case_alias": alias,
                "path": source["path"],
                "sha256": source["sha256"],
                "stream_sha256": source["stream_sha256"],
            }
        )
    require(len(streams) == 30, "Expected exactly 30 replay streams")
    return streams, lineage


def prepare_features(streams: Iterable[dict[str, Any]]) -> dict[str, Any]:
    prepared = prepare_study(merged_study_inputs(streams))
    prepared["m1_pivots"] = tuple(
        _confirmed_pivots(
            prepared["inputs"]["1m"], "1m", prepared["v2"].config
        )
    )
    prepared["breaks"]["1m"] = causal_breaks(
        prepared["inputs"]["1m"],
        prepared["m1_pivots"],
        prepared["atrs"]["1m"],
    )
    return prepared


def minute_checkpoints(calendar_date: date) -> list[tuple[str, datetime, int]]:
    points: list[tuple[str, datetime, int]] = []
    for session, timezone in (("LONDON", LONDON), ("NEW_YORK", NEW_YORK)):
        local_open = datetime(
            calendar_date.year,
            calendar_date.month,
            calendar_date.day,
            8,
            tzinfo=timezone,
        )
        for offset in range(240):
            point = (local_open + timedelta(minutes=offset)).astimezone(UTC)
            points.append((session, point, offset))
    return sorted(points, key=lambda item: (item[1], item[0]))


def snapshot(
    *,
    stream: dict[str, Any],
    prepared: dict[str, Any],
    timestamp: datetime,
    session: str,
    offset: int,
) -> dict[str, Any]:
    row = snapshot_features(
        stream=stream,
        inputs=prepared["inputs"],
        v2=prepared["v2"],
        v3=prepared["v3"],
        closes=prepared["closes"],
        atrs=prepared["atrs"],
        breaks=prepared["breaks"],
        timestamp=timestamp,
        session=session,
        session_offset=float(offset),
    )
    m1 = timeframe_features(
        timeframe="1m",
        bars=prepared["inputs"]["1m"],
        closes=prepared["closes"]["1m"],
        atrs=prepared["atrs"]["1m"],
        pivots=prepared["m1_pivots"],
        breaks=prepared["breaks"]["1m"],
        decision_at=timestamp,
    )
    row.update(m1)
    m1_end = bisect.bisect_right(prepared["closes"]["1m"], timestamp)
    m15_end = bisect.bisect_right(prepared["closes"]["15m"], timestamp)
    require(m1_end > 0 and m15_end > 0, f"Reference data unavailable at {timestamp}")
    row["m1_reference_close"] = float(prepared["inputs"]["1m"][m1_end - 1].close)
    row["m15_atr_scale"] = float(prepared["atrs"]["15m"][m15_end - 1])
    return row


def materialize_case(
    *,
    alias: str,
    stream: dict[str, Any],
    prepared: dict[str, Any],
    end_at: datetime | None = None,
) -> list[dict[str, Any]]:
    start = parse_dt(stream["start_inclusive"])
    end = parse_dt(stream["end_exclusive"])
    calendar_date = date.fromisoformat(stream["trading_date_utc"])
    rows: list[dict[str, Any]] = []
    for session, timestamp, offset in minute_checkpoints(calendar_date):
        if timestamp < start or timestamp >= end:
            continue
        if end_at is not None and timestamp > end_at:
            continue
        row = snapshot(
            stream=stream,
            prepared=prepared,
            timestamp=timestamp,
            session=session,
            offset=offset,
        )
        row["case_alias"] = alias
        rows.append(row)
    return rows


def fit_preprocessing(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    keys = sorted(
        set().union(*(row.keys() for row in rows)) - MODEL_EXCLUDED_FIELDS
    )
    numeric: list[str] = []
    categorical: dict[str, list[str]] = {}
    for key in keys:
        observed = [row.get(key) for row in rows if row.get(key) is not None]
        if observed and any(isinstance(value, str) for value in observed):
            categorical[key] = sorted({str(value) for value in observed} | {"__MISSING__"})
        else:
            numeric.append(key)
    feature_names: list[str] = []
    for key in numeric:
        feature_names.extend((key, f"{key}__missing"))
    for key in sorted(categorical):
        feature_names.extend(f"{key}={value}" for value in categorical[key])
    return {
        "numeric": numeric,
        "categorical": categorical,
        "feature_names": feature_names,
        "missing_numeric_sentinel": -999.0,
        "missing_category": "__MISSING__",
    }


def transform_rows(
    rows: Sequence[dict[str, Any]], schema: dict[str, Any]
) -> np.ndarray:
    names = list(schema["feature_names"])
    index = {name: position for position, name in enumerate(names)}
    output = np.zeros((len(rows), len(names)), dtype=np.float64)
    sentinel = float(schema["missing_numeric_sentinel"])
    for row_index, row in enumerate(rows):
        for key in schema["numeric"]:
            value = row.get(key)
            missing = value is None
            if not missing:
                try:
                    number = float(value)
                    missing = not math.isfinite(number)
                except (TypeError, ValueError):
                    missing = True
            output[row_index, index[key]] = sentinel if missing else number
            output[row_index, index[f"{key}__missing"]] = float(missing)
        for key, categories in schema["categorical"].items():
            value = str(row.get(key)) if row.get(key) is not None else "__MISSING__"
            if value not in categories:
                value = "__MISSING__"
            output[row_index, index[f"{key}={value}"]] = 1.0
    return output


def serialize_tree(model: Any, feature_names: Sequence[str], kind: str) -> dict[str, Any]:
    tree = model.tree_
    nodes: list[dict[str, Any]] = []
    for node in range(tree.node_count):
        feature_index = int(tree.feature[node])
        nodes.append(
            {
                "left": int(tree.children_left[node]),
                "right": int(tree.children_right[node]),
                "feature_index": feature_index,
                "feature_name": (
                    feature_names[feature_index] if feature_index >= 0 else None
                ),
                "threshold": float(tree.threshold[node]),
                "value": np.asarray(tree.value[node]).reshape(-1).astype(float).tolist(),
            }
        )
    payload: dict[str, Any] = {
        "kind": kind,
        "node_count": int(tree.node_count),
        "depth": int(tree.max_depth),
        "nodes": nodes,
    }
    if hasattr(model, "classes_"):
        payload["classes"] = [
            value.item() if hasattr(value, "item") else value for value in model.classes_
        ]
    payload["tree_sha256"] = canonical_hash(payload)
    return payload


def traverse_tree(tree: dict[str, Any], vector: np.ndarray) -> dict[str, Any]:
    node_index = 0
    while True:
        node = tree["nodes"][node_index]
        if int(node["left"]) == int(node["right"]):
            return node
        feature_index = int(node["feature_index"])
        node_index = (
            int(node["left"])
            if float(vector[feature_index]) <= float(node["threshold"])
            else int(node["right"])
        )


def predict_regression(tree: dict[str, Any], matrix: np.ndarray) -> np.ndarray:
    return np.asarray(
        [float(traverse_tree(tree, row)["value"][0]) for row in matrix],
        dtype=float,
    )


def predict_class_probability(
    tree: dict[str, Any], matrix: np.ndarray, positive_class: Any
) -> np.ndarray:
    classes = list(tree["classes"])
    positive_index = classes.index(positive_class)
    values: list[float] = []
    for row in matrix:
        counts = np.asarray(traverse_tree(tree, row)["value"], dtype=float)
        denominator = float(counts.sum())
        values.append(float(counts[positive_index] / denominator) if denominator else 0.0)
    return np.asarray(values, dtype=float)


def predict_class(tree: dict[str, Any], matrix: np.ndarray) -> list[Any]:
    classes = list(tree["classes"])
    output: list[Any] = []
    for row in matrix:
        counts = np.asarray(traverse_tree(tree, row)["value"], dtype=float)
        output.append(classes[int(np.argmax(counts))])
    return output


def rounded(value: float | None, digits: int = 10) -> float | None:
    return None if value is None else round(float(value), digits)
