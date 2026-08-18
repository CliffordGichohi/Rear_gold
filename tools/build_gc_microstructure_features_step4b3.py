#!/usr/bin/env python3
"""Run the sealed Step 4A feature engine over the Step 4B engineering dates.

This tool is deliberately feature-engineering-only.  It imports the two
independent, sealed Step 4A calculations unchanged and generalizes only the
date-scoped parameters authorized by the Step 4B.3 protocol.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any

import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4b3_protocol_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4b3_freeze_v01.json"
)
STEP4B2_MANIFEST_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_4b2_v01"
    / "manifest.json"
)
STEP4B2_VERDICT_PATH = STEP4B2_MANIFEST_PATH.parent / "verdict.json"
STEP4A3_MANIFEST_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_4a3_v01"
    / "manifest.json"
)
STEP4A3_VERDICT_PATH = STEP4A3_MANIFEST_PATH.parent / "verdict.json"
ACQUISITION_MANIFEST_PATH = (
    REPO_ROOT
    / "data"
    / "raw"
    / "databento_gc_multiday_engineering_v01"
    / "acquisition_manifest.json"
)
BASE_ENGINE_PATH = (
    REPO_ROOT / "tools" / "build_gc_microstructure_features_step4a.py"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_4b3_v01"
)
REPORT_PATH = REPO_ROOT / "GC_MICROSTRUCTURE_STEP_4B3_REPORT.md"

# These two values are patched only after the pre-value protocol and its
# receipt are frozen.  No feature action runs while either value is blank.
EXPECTED_PROTOCOL_SHA256 = (
    "8a67158b943add18bdeaea5b8b87a8c41fd1427ef6aa45248a38eb03293539cd"
)
EXPECTED_FREEZE_SHA256 = (
    "7836a77a55f6dc3b436c42e7a5325deeed353e5c06d4de7a208f06b4597fb296"
)

EXPECTED_BASE_ENGINE_SHA256 = (
    "c5589914a1acae6a3a1e9079c302821477866bba3741317392c567bb590c2369"
)
EXPECTED_FEATURE_SCHEMA_SHA256 = (
    "dfaf74cdc55b37469966857fc1ed2279b3d18c98f90454ced65859cb32494232"
)
EXPECTED_STEP4B2_MANIFEST_FILE_SHA256 = (
    "ff1ad43729343b37c35dfbd60cfc06384c4846661cf41a123c05e61e2fad7966"
)
EXPECTED_STEP4B2_MANIFEST_HASH = (
    "899ee63ba569b2df08b34feb495739bcc17a556ef9c31c9607b32cd258881397"
)
EXPECTED_STEP4B2_VERDICT_FILE_SHA256 = (
    "c560b07798530e8dfbb79ebbaf34bb886f178fc4ddb2b7f1b4b6641f04c1245e"
)
EXPECTED_STEP4B2_VERDICT_HASH = (
    "ece7ac4c8d2c975d3a05fe455c379fceaae8c18fef231600e8f064bb11df01e7"
)
EXPECTED_ACQUISITION_MANIFEST_SHA256 = (
    "674c71ddd25ba21f50b60469fc3a3131e7d4c9bb5a88471b1c94861645dd6dca"
)
EXPECTED_STEP4A3_MANIFEST_FILE_SHA256 = (
    "633a5cee430cbb785f7d84c96af519127406d177427ae439c4886abc6ad6368d"
)
EXPECTED_STEP4A3_MANIFEST_HASH = (
    "879a4321c535a02ad89905a3a4d926e052a8c611b36af9774d5ba403485e610e"
)
EXPECTED_STEP4A3_VERDICT_FILE_SHA256 = (
    "d55367d7e128e9eafa12cb1df483bb39deb1ccbf3dc1726eb7f829dd8187cf77"
)
EXPECTED_STEP4A3_VERDICT_HASH = (
    "f959516ceea67ca69648850196dc6bdd24f2b8229ea61222059a7f5b52729a0b"
)

BUCKET_WIDTH_NS = 1_000_000_000
BUCKET_COUNT = 86_400
FEATURE_COLUMN_COUNT = 85
EXPECTED_MBP_DUPLICATES_TOTAL = 776


@dataclass(frozen=True)
class SourceSpec:
    schema: str
    relative_path: str
    records: int
    size_bytes: int
    sha256: str
    quality_relative_path: str
    quality_bytes: int
    quality_sha256: str
    bad_ts_recv_rows: int
    adjacent_duplicates: int


@dataclass(frozen=True)
class DateSpec:
    date: str
    day_start_ns: int
    instrument_id: int
    dst_window_class: str
    mbo: SourceSpec
    mbp10: SourceSpec

    @property
    def day_end_ns(self) -> int:
        return self.day_start_ns + BUCKET_COUNT * BUCKET_WIDTH_NS

    @property
    def segments(self) -> tuple[tuple[str, str, int, int], ...]:
        start = self.day_start_ns
        if self.dst_window_class == "UTC-06:00_CST":
            offsets = (0, 79_200, 81_900, 82_800, 86_400)
            names = (
                "CONTINUOUS_00_22",
                "MAINTENANCE_22_2245",
                "PRE_OPEN_2245_23",
                "CONTINUOUS_23_24",
            )
        elif self.dst_window_class == "UTC-05:00_CDT":
            offsets = (0, 75_600, 78_300, 79_200, 86_400)
            names = (
                "CONTINUOUS_00_21",
                "MAINTENANCE_21_2145",
                "PRE_OPEN_2145_22",
                "CONTINUOUS_22_24",
            )
        else:
            raise ValueError(f"Unsupported frozen DST window: {self.dst_window_class}")
        states = (
            "CONTINUOUS_MATCHING",
            "MAINTENANCE",
            "PRE_OPEN",
            "CONTINUOUS_MATCHING",
        )
        return tuple(
            (
                names[index],
                states[index],
                start + offsets[index] * BUCKET_WIDTH_NS,
                start + offsets[index + 1] * BUCKET_WIDTH_NS,
            )
            for index in range(4)
        )


def _source(
    schema: str,
    job: str,
    filename: str,
    records: int,
    size_bytes: int,
    sha256: str,
    quality_bytes: int,
    quality_sha256: str,
    bad_ts_recv_rows: int,
    adjacent_duplicates: int,
) -> SourceSpec:
    root = f"data/raw/databento_gc_multiday_engineering_v01/{job}/normalized"
    return SourceSpec(
        schema=schema,
        relative_path=f"{root}/{filename}",
        records=records,
        size_bytes=size_bytes,
        sha256=sha256,
        quality_relative_path=f"{root}/data_quality.json",
        quality_bytes=quality_bytes,
        quality_sha256=quality_sha256,
        bad_ts_recv_rows=bad_ts_recv_rows,
        adjacent_duplicates=adjacent_duplicates,
    )


DATE_SPECS: dict[str, DateSpec] = {
    "2024-01-05": DateSpec(
        date="2024-01-05",
        day_start_ns=1_704_412_800_000_000_000,
        instrument_id=41_512,
        dst_window_class="UTC-06:00_CST",
        mbo=_source(
            "mbo", "GLBX-20260731-5B8UC56H64",
            "gc_v_0_2024_01_05_mbo.parquet", 3_264_913, 44_647_988,
            "3efa36a1845567773fd6cc9414547761e325e3967baf9e291f52ef2b251604f6",
            3_924, "e15a79f5aee4b6b2fe7664d881add3946f369a239cd6dad3de33f65401b0b3b7",
            2_590, 0,
        ),
        mbp10=_source(
            "mbp-10", "GLBX-20260731-XDNE766EPK",
            "gc_v_0_2024_01_05_mbp10.parquet", 2_699_804, 113_910_007,
            "55c227e4ea2d5371959d43cf3c8e3a31a451697f21e7b71d15ec5a5878c9d232",
            4_701, "da9e047b27a9f49541d8749a618b55be40eb5c02df2bfaf8e139e5f41263d087",
            1, 166,
        ),
    ),
    "2024-01-11": DateSpec(
        date="2024-01-11",
        day_start_ns=1_704_931_200_000_000_000,
        instrument_id=41_512,
        dst_window_class="UTC-06:00_CST",
        mbo=_source(
            "mbo", "GLBX-20260731-8METPEGFM3",
            "gc_v_0_2024_01_11_mbo.parquet", 3_823_552, 51_521_121,
            "de34cb5ffc55bf20c451dbe1d0c597739e83538ae2ae369a5313457a31b9d521",
            3_926, "477d5cc7c0871a67eab5bef91ba36c9b2b875127be4fc7ffa07bcd4d112d8971",
            3_019, 0,
        ),
        mbp10=_source(
            "mbp-10", "GLBX-20260731-Y937HJFMBF",
            "gc_v_0_2024_01_11_mbp10.parquet", 3_203_119, 134_400_537,
            "ccaa46003b56a18dbdbd7bab8bb984bad22840bcb4a400aeb633f97b3876eae9",
            4_702, "835b8fd3559491d4b5f62e34969f262ccbecd2a88a8d3b469105f69819d45b00",
            1, 342,
        ),
    ),
    "2024-01-30": DateSpec(
        date="2024-01-30",
        day_start_ns=1_706_572_800_000_000_000,
        instrument_id=41_512,
        dst_window_class="UTC-06:00_CST",
        mbo=_source(
            "mbo", "GLBX-20260731-5GBR4MMQQW",
            "gc_v_0_2024_01_30_mbo.parquet", 143_495, 2_282_903,
            "392ec7cbfb2dfa8d87da7f64c1d212a2a0882e9731ab9ca5ff07c5b0d9681406",
            3_911, "7761fb03ba2292bbacc8fbfec13584176049d48eaf91aa19d8ab11b7779617b0",
            213, 0,
        ),
        mbp10=_source(
            "mbp-10", "GLBX-20260731-JL3F6Y4A68",
            "gc_v_0_2024_01_30_mbp10.parquet", 140_265, 5_790_550,
            "cfbca8db717ba4177c572bd88f6b4a6e6e033780aff3cce5804dd61583d0dc8e",
            4_691, "10ee34908409feba3fd51f4c7542fe579c9d0398751925c0aea90028b1ef5927",
            1, 3,
        ),
    ),
    "2024-01-31": DateSpec(
        date="2024-01-31",
        day_start_ns=1_706_659_200_000_000_000,
        instrument_id=44_740,
        dst_window_class="UTC-06:00_CST",
        mbo=_source(
            "mbo", "GLBX-20260731-VPT4NJWMXQ",
            "gc_v_0_2024_01_31_mbo.parquet", 3_229_893, 43_416_688,
            "361016be38684e2e9722a1efa2185918d9c466202d62cfe397afc74d480b02c1",
            3_926, "0a3c19e4ac54b3ab81339c483e70c8d9b65d7ad3f7900152f2f58f577c1a9367",
            2_212, 0,
        ),
        mbp10=_source(
            "mbp-10", "GLBX-20260731-UC9PNQYEPY",
            "gc_v_0_2024_01_31_mbp10.parquet", 2_648_313, 111_243_904,
            "ca81dcbfc58234a2d0432687057f3d9e2843816d04c3b784af07d2a4fc83174e",
            4_701, "56f7d4c8c6f36dbc78787e5833f33e3d606459225dc79c1e1260ed96f4d7d674",
            1, 95,
        ),
    ),
    "2024-03-20": DateSpec(
        date="2024-03-20",
        day_start_ns=1_710_892_800_000_000_000,
        instrument_id=44_740,
        dst_window_class="UTC-05:00_CDT",
        mbo=_source(
            "mbo", "GLBX-20260731-EA9VSU99GN",
            "gc_v_0_2024_03_20_mbo.parquet", 3_333_973, 44_999_484,
            "bb142abf8b251a2b1f4a6e992273554c3bb02d3da3c105f85c974349cf21c2ce",
            3_926, "382d9919e38e59ea5268b22afb0fe12de86f800d0270fd31a1cf18bbdd85df2e",
            3_194, 0,
        ),
        mbp10=_source(
            "mbp-10", "GLBX-20260731-67BQQDVWG7",
            "gc_v_0_2024_03_20_mbp10.parquet", 2_660_637, 112_098_896,
            "5dd8210f37b61b4d2bbdd988a494786cc3599615c5a5a4cdd74444fc51aee990",
            4_703, "7d269d9ca79e65c6924fa0f0a8ffe506bf6e0fcbe4454e1f0d15d465092c7565",
            1, 170,
        ),
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("preflight", "primary", "reference", "seal", "verify")
    )
    parser.add_argument("--date", choices=tuple(DATE_SPECS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    output = Path(args.output)
    if args.action in {"primary", "reference"} and args.date is None:
        parser.error("--date is required for primary and reference")
    if args.action == "preflight":
        _preflight(output)
    elif args.action in {"primary", "reference"}:
        _run_date(args.action, DATE_SPECS[args.date], output)
    elif args.action == "seal":
        _seal(output)
    else:
        _verify_seal(output)


def _load_base_engine() -> Any:
    if _sha256(BASE_ENGINE_PATH) != EXPECTED_BASE_ENGINE_SHA256:
        raise ValueError("Sealed Step 4A feature engine changed")
    spec = importlib.util.spec_from_file_location(
        "gc_microstructure_step4a_sealed_engine", BASE_ENGINE_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load sealed Step 4A engine")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if module._feature_schema_hash() != EXPECTED_FEATURE_SCHEMA_SHA256:
        raise ValueError("Frozen Step 4A feature schema changed")
    if len(module.FEATURE_COLUMNS) != FEATURE_COLUMN_COUNT:
        raise ValueError("Frozen Step 4A feature count changed")
    return module


def _configure_engine(base: Any, date_spec: DateSpec) -> None:
    base.MBO_PATH = REPO_ROOT / date_spec.mbo.relative_path
    base.MBP_PATH = REPO_ROOT / date_spec.mbp10.relative_path
    base.EXPECTED_MBO_SHA256 = date_spec.mbo.sha256
    base.EXPECTED_MBP_SHA256 = date_spec.mbp10.sha256
    base.EXPECTED_MBO_RECORDS = date_spec.mbo.records
    base.EXPECTED_MBP_RECORDS = date_spec.mbp10.records
    base.EXPECTED_PUBLISHER_ID = 1
    base.EXPECTED_INSTRUMENT_ID = date_spec.instrument_id
    base.DAY_START_NS = date_spec.day_start_ns
    base.DAY_END_NS = date_spec.day_end_ns
    base.BUCKET_WIDTH_NS = BUCKET_WIDTH_NS
    base.BUCKET_COUNT = BUCKET_COUNT
    base.SEGMENTS = date_spec.segments


def _verify_protocol_and_freeze() -> dict[str, Any]:
    if not EXPECTED_PROTOCOL_SHA256 or not EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 4B.3 protocol/freeze hashes have not been bound")
    if _sha256(PROTOCOL_PATH) != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Step 4B.3 protocol changed after freeze")
    if _sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 4B.3 freeze receipt changed")
    protocol = _read_json(PROTOCOL_PATH)
    freeze = _read_json(FREEZE_PATH)
    if freeze["protocol"]["sha256"] != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Freeze receipt does not bind the frozen protocol")
    _assert_protocol_matches_code(protocol)
    return protocol


def _verify_predecessors() -> None:
    if _sha256(STEP4B2_MANIFEST_PATH) != EXPECTED_STEP4B2_MANIFEST_FILE_SHA256:
        raise ValueError("Step 4B.2 manifest file changed")
    if _sha256(STEP4B2_VERDICT_PATH) != EXPECTED_STEP4B2_VERDICT_FILE_SHA256:
        raise ValueError("Step 4B.2 verdict file changed")
    manifest = _read_json(STEP4B2_MANIFEST_PATH)
    verdict = _read_json(STEP4B2_VERDICT_PATH)
    if (
        manifest.get("manifest_hash") != EXPECTED_STEP4B2_MANIFEST_HASH
        or _canonical_hash(_without_hash(manifest, "manifest_hash"))
        != EXPECTED_STEP4B2_MANIFEST_HASH
        or manifest.get("status") != "PASS_ENGINEERING_SOURCE_ACQUISITION"
        or manifest.get("verdict_hash") != EXPECTED_STEP4B2_VERDICT_HASH
        or verdict.get("verdict_hash") != EXPECTED_STEP4B2_VERDICT_HASH
        or _canonical_hash(_without_hash(verdict, "verdict_hash"))
        != EXPECTED_STEP4B2_VERDICT_HASH
    ):
        raise ValueError("Step 4B.2 predecessor seal or verdict changed")
    if _sha256(ACQUISITION_MANIFEST_PATH) != EXPECTED_ACQUISITION_MANIFEST_SHA256:
        raise ValueError("Step 4B.2 acquisition manifest changed")

    if _sha256(STEP4A3_MANIFEST_PATH) != EXPECTED_STEP4A3_MANIFEST_FILE_SHA256:
        raise ValueError("Step 4A.3 manifest file changed")
    if _sha256(STEP4A3_VERDICT_PATH) != EXPECTED_STEP4A3_VERDICT_FILE_SHA256:
        raise ValueError("Step 4A.3 verdict file changed")
    manifest_4a3 = _read_json(STEP4A3_MANIFEST_PATH)
    verdict_4a3 = _read_json(STEP4A3_VERDICT_PATH)
    if (
        manifest_4a3.get("manifest_hash") != EXPECTED_STEP4A3_MANIFEST_HASH
        or _canonical_hash(_without_hash(manifest_4a3, "manifest_hash"))
        != EXPECTED_STEP4A3_MANIFEST_HASH
        or manifest_4a3.get("status")
        != "PASS_FEATURE_INTEGRITY_RECERTIFICATION"
        or verdict_4a3.get("verdict_hash") != EXPECTED_STEP4A3_VERDICT_HASH
        or _canonical_hash(_without_hash(verdict_4a3, "verdict_hash"))
        != EXPECTED_STEP4A3_VERDICT_HASH
    ):
        raise ValueError("Step 4A.3 predecessor seal or verdict changed")


def _verify_source(source: SourceSpec, base: Any) -> dict[str, Any]:
    path = REPO_ROOT / source.relative_path
    quality_path = REPO_ROOT / source.quality_relative_path
    if path.stat().st_size != source.size_bytes or _sha256(path) != source.sha256:
        raise ValueError(f"Sealed normalized source changed: {path}")
    if (
        quality_path.stat().st_size != source.quality_bytes
        or _sha256(quality_path) != source.quality_sha256
    ):
        raise ValueError(f"Sealed source-quality record changed: {quality_path}")
    parquet = pq.ParquetFile(path)
    required = base.MBO_COLUMNS if source.schema == "mbo" else base.MBP_COLUMNS
    if parquet.metadata.num_rows != source.records:
        raise ValueError(f"Source record count changed: {path}")
    if not set(required).issubset(parquet.schema_arrow.names):
        raise ValueError(f"Required frozen columns are missing: {path}")
    quality = _read_json(quality_path)
    supplemental = quality["supplemental_validation"]
    if quality.get("quality_gate") != "PASS":
        raise ValueError(f"Sealed source quality no longer passes: {quality_path}")
    expected = {
        "record_count": source.records,
        "adjacent_exact_duplicate_records": source.adjacent_duplicates,
        "bad_ts_recv_flag_rows": source.bad_ts_recv_rows,
        "bad_ts_recv_snapshot_semantic_violations": 0,
        "source_ordinal_regressions": 0,
    }
    observed = {key: int(supplemental[key]) for key in expected}
    if observed != expected:
        raise ValueError(f"Frozen technical source classifications changed: {path}")
    return {
        "source": _file_record(path),
        "quality": _file_record(quality_path),
        "records": source.records,
        "bad_ts_recv_rows": source.bad_ts_recv_rows,
        "bad_ts_recv_snapshot_semantic_violations": 0,
        "adjacent_exact_duplicate_records": source.adjacent_duplicates,
    }


def _preflight(output: Path) -> None:
    protocol = _verify_protocol_and_freeze()
    _verify_predecessors()
    base = _load_base_engine()
    sources: dict[str, Any] = {}
    for date, spec in DATE_SPECS.items():
        sources[date] = {
            "mbo": _verify_source(spec.mbo, base),
            "mbp10": _verify_source(spec.mbp10, base),
        }
    output.mkdir(parents=True, exist_ok=True)
    path = output / "preflight.json"
    if path.exists():
        raise FileExistsError("Refusing to overwrite Step 4B.3 preflight")
    receipt = {
        "version": "GC_MICROSTRUCTURE_STEP_4B3_PREFLIGHT_V0_1",
        "status": "PASS_PRE_VALUE_READINESS",
        "classification": "ENGINEERING_ONLY_MULTI_DAY_FEATURE_ROBUSTNESS",
        "research_or_validation_credit": "NONE",
        "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "base_engine_sha256": EXPECTED_BASE_ENGINE_SHA256,
        "feature_schema_sha256": EXPECTED_FEATURE_SCHEMA_SHA256,
        "predecessor_step_4b2_status": "PASS_ENGINEERING_SOURCE_ACQUISITION",
        "date_count": len(DATE_SPECS),
        "source_count": len(DATE_SPECS) * 2,
        "sources": sources,
        "sealed_mbp10_adjacent_duplicate_total": sum(
            spec.mbp10.adjacent_duplicates for spec in DATE_SPECS.values()
        ),
        "all_parameter_and_source_gates_passed": True,
        "market_values_or_feature_values_accessed_or_reported": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    if receipt["sealed_mbp10_adjacent_duplicate_total"] != EXPECTED_MBP_DUPLICATES_TOTAL:
        raise ValueError("Frozen MBP-10 duplicate total changed")
    _write_json_atomic(path, receipt)
    print(json.dumps({
        "stage": "GC_MICROSTRUCTURE_STEP_4B3_PREFLIGHT_COMPLETE",
        "status": receipt["status"],
        "dates": receipt["date_count"],
        "sources": receipt["source_count"],
        "sealed_mbp10_adjacent_duplicates": EXPECTED_MBP_DUPLICATES_TOTAL,
        "market_values_reported": False,
    }, sort_keys=True))


def _run_date(implementation: str, spec: DateSpec, output: Path) -> None:
    _verify_protocol_and_freeze()
    _verify_predecessors()
    base = _load_base_engine()
    source_context = {
        "mbo": _verify_source(spec.mbo, base),
        "mbp10": _verify_source(spec.mbp10, base),
    }
    _configure_engine(base, spec)
    date_dir = output / spec.date
    date_dir.mkdir(parents=True, exist_ok=True)
    feature_path = date_dir / f"{implementation}_features.parquet"
    summary_path = date_dir / f"{implementation}_summary.json"
    if feature_path.exists() or summary_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite Step 4B.3 {spec.date} {implementation} output"
        )

    if implementation == "primary":
        columns, audits, input_checksums = base._calculate_primary()
    else:
        columns, audits, input_checksums = base._calculate_reference()
    base._validate_column_lengths(columns)
    original_integrity = base._integrity_checks(
        columns,
        audits,
        {
            "predecessor_and_source_seals_valid": True,
            "required_input_columns_present": True,
        },
    )
    bucket_classification = _bucket_classification(
        implementation, columns, spec
    )
    snapshot_exception = _snapshot_exception(columns, source_context, spec)
    duplicate_contribution = _duplicate_contribution(columns, spec)
    integrity = _amended_integrity_checks(
        original_integrity,
        bucket_classification,
        snapshot_exception,
        duplicate_contribution,
    )
    hashes = base._feature_hashes(columns)
    base._write_feature_parquet(feature_path, columns)
    summary = {
        "version": "GC_MICROSTRUCTURE_STEP_4B3_DATE_RUN_V0_1",
        "implementation": implementation,
        "engineering_date": spec.date,
        "classification": "ENGINEERING_ONLY",
        "research_or_validation_credit": "NONE",
        "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "tool_sha256": _sha256(Path(__file__)),
        "base_engine_sha256": EXPECTED_BASE_ENGINE_SHA256,
        "mbo_source_sha256": spec.mbo.sha256,
        "mbp10_source_sha256": spec.mbp10.sha256,
        "source_input_checksums": input_checksums,
        "feature_rows": BUCKET_COUNT,
        "feature_columns": list(base.FEATURE_COLUMNS),
        "feature_column_count": len(base.FEATURE_COLUMNS),
        "feature_schema_hash": base._feature_schema_hash(),
        "feature_hashes": hashes,
        "feature_parquet": _file_record(feature_path),
        "audits": audits,
        "snapshot_semantic_exception": snapshot_exception,
        "bucket_close_classification": bucket_classification,
        "mbp10_duplicate_contribution": duplicate_contribution,
        "original_integrity_checks": original_integrity,
        "superseded_original_gate_results": {
            "bad_ts_recv_flag_rows_zero": original_integrity[
                "bad_ts_recv_flag_rows_zero"
            ],
            "continuous_crossed_book_rows_zero": original_integrity[
                "continuous_crossed_book_rows_zero"
            ],
        },
        "amended_integrity_checks": integrity,
        "formal_integrity_pass": all(integrity.values()),
        "calendar_date_state_initialized_empty": True,
        "mbo_mbp_alignment_attempts": 0,
        "source_rows_filtered_deduplicated_repaired_relabeled_or_substituted": 0,
        "additional_data_acquired": False,
        "another_date_accessed_in_this_run": False,
        "market_values_human_or_model_inspected": False,
        "feature_values_human_or_model_inspected": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    _write_json_atomic(summary_path, summary)
    print(json.dumps({
        "stage": "GC_MICROSTRUCTURE_STEP_4B3_DATE_RUN_COMPLETE",
        "implementation": implementation,
        "engineering_date": spec.date,
        "mbo_records": audits["mbo"]["records"],
        "mbp10_records": audits["mbp10"]["records"],
        "feature_rows": BUCKET_COUNT,
        "feature_columns": len(base.FEATURE_COLUMNS),
        "integrity_pass": all(integrity.values()),
        "mbp10_adjacent_duplicates_processed": spec.mbp10.adjacent_duplicates,
        "market_values_reported": False,
        "feature_values_reported": False,
    }, sort_keys=True))


def _snapshot_exception(
    columns: dict[str, list[Any]],
    source_context: dict[str, Any],
    spec: DateSpec,
) -> dict[str, Any]:
    mbo_rows = int(sum(columns["mbo_bad_ts_recv_flag_count"]))
    mbp_rows = int(sum(columns["mbp_bad_ts_recv_flag_count"]))
    expected_mbo = spec.mbo.bad_ts_recv_rows
    expected_mbp = spec.mbp10.bad_ts_recv_rows
    violations = int(
        source_context["mbo"]["bad_ts_recv_snapshot_semantic_violations"]
        + source_context["mbp10"]["bad_ts_recv_snapshot_semantic_violations"]
    )
    return {
        "authority": "SEALED_STEP_4B2_SOURCE_QUALITY_CLASSIFICATION",
        "mbo_bad_ts_recv_rows": mbo_rows,
        "mbp10_bad_ts_recv_rows": mbp_rows,
        "combined_bad_ts_recv_rows": mbo_rows + mbp_rows,
        "expected_mbo_bad_ts_recv_rows": expected_mbo,
        "expected_mbp10_bad_ts_recv_rows": expected_mbp,
        "snapshot_semantic_violations": violations,
        "all_bad_ts_recv_rows_match_sealed_counts": (
            mbo_rows == expected_mbo and mbp_rows == expected_mbp
        ),
        "all_bad_ts_recv_rows_satisfy_confirmed_snapshot_semantics": (
            violations == 0 and mbo_rows == expected_mbo and mbp_rows == expected_mbp
        ),
        "source_rows_changed_or_filtered": False,
    }


def _duplicate_contribution(
    columns: dict[str, list[Any]], spec: DateSpec
) -> dict[str, Any]:
    updates = int(sum(columns["mbp_update_count"]))
    duplicates = spec.mbp10.adjacent_duplicates
    return {
        "sealed_exact_adjacent_provider_emissions": duplicates,
        "contribution_to_mbp_update_count": duplicates,
        "nonduplicate_provider_emissions": spec.mbp10.records - duplicates,
        "total_mbp_update_count": updates,
        "expected_total_mbp_update_count": spec.mbp10.records,
        "all_provider_emissions_processed_once": updates == spec.mbp10.records,
        "duplicates_deduplicated_filtered_repaired_relabeled_or_substituted": 0,
    }


def _bucket_classification(
    implementation: str,
    columns: dict[str, list[Any]],
    spec: DateSpec,
) -> dict[str, Any]:
    expected_segment = {
        name: {"bucket_closes": (end - start) // BUCKET_WIDTH_NS}
        for name, _state, start, end in spec.segments
    }
    if implementation == "primary":
        by_segment = {
            name: {"bucket_closes": 0, "crossed_bucket_closes": 0}
            for name in expected_segment
        }
        by_state: dict[str, dict[str, int]] = {
            state: {"bucket_closes": 0, "crossed_bucket_closes": 0}
            for _name, state, _start, _end in spec.segments
        }
        for index in range(BUCKET_COUNT):
            segment = str(columns["market_segment"][index])
            state = str(columns["market_state"][index])
            crossed = int(bool(columns["book_crossed"][index]))
            by_segment[segment]["bucket_closes"] += 1
            by_segment[segment]["crossed_bucket_closes"] += crossed
            by_state[state]["bucket_closes"] += 1
            by_state[state]["crossed_bucket_closes"] += crossed
    else:
        segment_totals = Counter(map(str, columns["market_segment"]))
        state_totals = Counter(map(str, columns["market_state"]))
        segment_crosses = Counter(
            str(segment)
            for segment, crossed in zip(
                columns["market_segment"], columns["book_crossed"]
            )
            if bool(crossed)
        )
        state_crosses = Counter(
            str(state)
            for state, crossed in zip(
                columns["market_state"], columns["book_crossed"]
            )
            if bool(crossed)
        )
        by_segment = {
            name: {
                "bucket_closes": int(segment_totals[name]),
                "crossed_bucket_closes": int(segment_crosses[name]),
            }
            for name in expected_segment
        }
        by_state = {
            state: {
                "bucket_closes": int(state_totals[state]),
                "crossed_bucket_closes": int(state_crosses[state]),
            }
            for state in ("CONTINUOUS_MATCHING", "MAINTENANCE", "PRE_OPEN")
        }
    expected_counts_match = all(
        by_segment[name]["bucket_closes"] == expected["bucket_closes"]
        for name, expected in expected_segment.items()
    )
    continuous_crossed = int(
        by_state["CONTINUOUS_MATCHING"]["crossed_bucket_closes"]
    )
    return {
        "by_segment": by_segment,
        "by_market_state": by_state,
        "segment_bucket_counts_match_frozen_windows": expected_counts_match,
        "continuous_matching_crossed_bucket_closes": continuous_crossed,
        "pre_open_crossed_bucket_closes": int(
            by_state["PRE_OPEN"]["crossed_bucket_closes"]
        ),
        "maintenance_crossed_bucket_closes": int(
            by_state["MAINTENANCE"]["crossed_bucket_closes"]
        ),
        "continuous_matching_crossed_bucket_closes_zero": continuous_crossed == 0,
    }


def _amended_integrity_checks(
    original: dict[str, bool],
    bucket_classification: dict[str, Any],
    snapshot_exception: dict[str, Any],
    duplicate_contribution: dict[str, Any],
) -> dict[str, bool]:
    superseded = {
        "bad_ts_recv_flag_rows_zero",
        "continuous_crossed_book_rows_zero",
    }
    checks = {
        name: bool(value) for name, value in original.items() if name not in superseded
    }
    checks.update({
        "bad_ts_recv_rows_all_confirmed_snapshot_semantics": bool(
            snapshot_exception[
                "all_bad_ts_recv_rows_satisfy_confirmed_snapshot_semantics"
            ]
        ),
        "continuous_matching_bucket_close_crossed_states_zero": bool(
            bucket_classification[
                "continuous_matching_crossed_bucket_closes_zero"
            ]
        ),
        "segment_bucket_counts_match_frozen_dst_windows": bool(
            bucket_classification["segment_bucket_counts_match_frozen_windows"]
        ),
        "all_provider_rows_processed_once_including_duplicates": bool(
            duplicate_contribution["all_provider_emissions_processed_once"]
        ),
        "provider_rows_not_filtered_deduplicated_repaired_relabeled_or_substituted": (
            duplicate_contribution[
                "duplicates_deduplicated_filtered_repaired_relabeled_or_substituted"
            ]
            == 0
        ),
        "calendar_date_state_initialized_empty": True,
    })
    return checks


def _seal(output: Path) -> None:
    protocol = _verify_protocol_and_freeze()
    _verify_predecessors()
    base = _load_base_engine()
    preflight_path = output / "preflight.json"
    if not preflight_path.exists():
        raise FileNotFoundError("Step 4B.3 preflight is required")
    preflight = _read_json(preflight_path)
    if (
        preflight.get("status") != "PASS_PRE_VALUE_READINESS"
        or preflight.get("protocol_sha256") != EXPECTED_PROTOCOL_SHA256
        or preflight.get("freeze_sha256") != EXPECTED_FREEZE_SHA256
    ):
        raise ValueError("Step 4B.3 preflight is not valid")

    date_verdicts: list[dict[str, Any]] = []
    artifact_paths: list[Path] = [preflight_path]
    tool_hash = _sha256(Path(__file__))
    for date, spec in DATE_SPECS.items():
        date_dir = output / date
        primary_path = date_dir / "primary_summary.json"
        reference_path = date_dir / "reference_summary.json"
        primary = _read_json(primary_path)
        reference = _read_json(reference_path)
        for run, implementation in ((primary, "primary"), (reference, "reference")):
            _verify_run_payload(run, implementation, spec, tool_hash)

        compared_sections = (
            "source_input_checksums",
            "feature_rows",
            "feature_columns",
            "feature_column_count",
            "feature_schema_hash",
            "feature_hashes",
            "audits",
            "snapshot_semantic_exception",
            "bucket_close_classification",
            "mbp10_duplicate_contribution",
            "original_integrity_checks",
            "superseded_original_gate_results",
            "amended_integrity_checks",
            "formal_integrity_pass",
        )
        matching = {
            name: primary[name] == reference[name] for name in compared_sections
        }
        parquet_identical = (
            primary["feature_parquet"]["sha256"]
            == reference["feature_parquet"]["sha256"]
            and primary["feature_parquet"]["bytes"]
            == reference["feature_parquet"]["bytes"]
        )
        reproduction_pass = all(matching.values()) and parquet_identical
        integrity_pass = bool(
            primary["formal_integrity_pass"]
            and reference["formal_integrity_pass"]
        )
        if not integrity_pass:
            status = "FAIL_FEATURE_INTEGRITY"
        elif not reproduction_pass:
            status = "FAIL_REPRODUCTION"
        else:
            status = "PASS_FEATURE_ROBUSTNESS"
        formal_gates = {
            "primary_integrity_pass": bool(primary["formal_integrity_pass"]),
            "reference_integrity_pass": bool(reference["formal_integrity_pass"]),
            "exact_source_row_allocation_identical": bool(
                matching["audits"]
                and primary["amended_integrity_checks"][
                    "every_source_row_allocated_exactly_once"
                ]
            ),
            "feature_rows_columns_and_schema_identical": all(
                matching[name]
                for name in (
                    "feature_rows", "feature_columns", "feature_column_count",
                    "feature_schema_hash",
                )
            ),
            "null_counts_identical": (
                primary["feature_hashes"]["null_counts"]
                == reference["feature_hashes"]["null_counts"]
            ),
            "per_column_checksums_identical": (
                primary["feature_hashes"]["column_checksums"]
                == reference["feature_hashes"]["column_checksums"]
            ),
            "complete_row_checksums_identical": (
                primary["feature_hashes"]["complete_row_checksum"]
                == reference["feature_hashes"]["complete_row_checksum"]
            ),
            "technical_diagnostics_identical": all(
                matching[name]
                for name in (
                    "audits", "snapshot_semantic_exception",
                    "bucket_close_classification", "mbp10_duplicate_contribution",
                    "amended_integrity_checks",
                )
            ),
            "parquet_outputs_byte_identical": parquet_identical,
            "all_duplicate_provider_emissions_processed": bool(
                primary["mbp10_duplicate_contribution"]
                ["all_provider_emissions_processed_once"]
            ),
            "no_prohibited_work": _no_prohibited_work(primary, reference),
        }
        date_verdict = {
            "version": "GC_MICROSTRUCTURE_STEP_4B3_DATE_VERDICT_V0_1",
            "engineering_date": date,
            "status": status,
            "formal_pass": status == "PASS_FEATURE_ROBUSTNESS",
            "classification": "ENGINEERING_ONLY",
            "research_or_validation_credit": "NONE",
            "formal_gates": formal_gates,
            "passed_formal_gates": sum(formal_gates.values()),
            "total_formal_gates": len(formal_gates),
            "reproduction": {
                "pass": reproduction_pass,
                "matching_sections": matching,
                "parquet_outputs_byte_identical": parquet_identical,
            },
            "technical_counts": primary["audits"],
            "snapshot_semantic_exception": primary[
                "snapshot_semantic_exception"
            ],
            "bucket_close_classification": primary[
                "bucket_close_classification"
            ],
            "mbp10_duplicate_contribution": primary[
                "mbp10_duplicate_contribution"
            ],
            "feature_rows": primary["feature_rows"],
            "feature_columns": primary["feature_column_count"],
            "complete_row_checksum": primary["feature_hashes"]
            ["complete_row_checksum"],
            "feature_parquet_sha256": primary["feature_parquet"]["sha256"],
            "market_values_or_feature_values_reported": False,
            "outcomes_accessed": False,
            "signals_calculated": False,
            "execution_optimized": False,
            "pnl_calculated": False,
        }
        date_verdict["verdict_hash"] = _canonical_hash(date_verdict)
        date_verdict_path = date_dir / "verdict.json"
        _write_json_atomic(date_verdict_path, date_verdict)
        date_verdicts.append(date_verdict)
        artifact_paths.extend([
            date_dir / "primary_features.parquet",
            primary_path,
            date_dir / "reference_features.parquet",
            reference_path,
            date_verdict_path,
        ])

    all_dates_pass = all(item["formal_pass"] for item in date_verdicts)
    overall_status = (
        "PASS_MULTIDAY_FEATURE_ROBUSTNESS"
        if all_dates_pass
        else "FAIL_MULTIDAY_FEATURE_ROBUSTNESS"
    )
    overall_gates = {
        "preflight_passed": True,
        "exactly_five_frozen_dates_evaluated": len(date_verdicts) == 5,
        "every_date_integrity_passed": all(
            all(item["formal_gates"][key] for key in (
                "primary_integrity_pass", "reference_integrity_pass"
            ))
            for item in date_verdicts
        ),
        "every_date_reproduced_exactly": all(
            item["reproduction"]["pass"] for item in date_verdicts
        ),
        "every_date_passed": all_dates_pass,
        "all_776_duplicate_provider_emissions_processed": sum(
            item["mbp10_duplicate_contribution"]
            ["contribution_to_mbp_update_count"]
            for item in date_verdicts
        ) == EXPECTED_MBP_DUPLICATES_TOTAL,
        "no_additional_data_or_prohibited_work": True,
    }
    verdict = {
        "version": "GC_MICROSTRUCTURE_STEP_4B3_VERDICT_V0_1",
        "status": overall_status,
        "formal_pass": all_dates_pass,
        "classification": "ENGINEERING_ONLY_MULTI_DAY_FEATURE_ROBUSTNESS",
        "research_or_validation_credit": "NONE",
        "predecessor_step_4b2_status": "PASS_ENGINEERING_SOURCE_ACQUISITION",
        "predecessor_verdicts_preserved": True,
        "date_verdicts": [{
            "engineering_date": item["engineering_date"],
            "status": item["status"],
            "formal_pass": item["formal_pass"],
            "verdict_hash": item["verdict_hash"],
        } for item in date_verdicts],
        "overall_gates": overall_gates,
        "passed_overall_gates": sum(overall_gates.values()),
        "total_overall_gates": len(overall_gates),
        "date_count": len(date_verdicts),
        "source_rows_processed_per_implementation": sum(
            spec.mbo.records + spec.mbp10.records for spec in DATE_SPECS.values()
        ),
        "feature_rows_per_date": BUCKET_COUNT,
        "feature_columns": FEATURE_COLUMN_COUNT,
        "sealed_mbp10_adjacent_duplicate_total": EXPECTED_MBP_DUPLICATES_TOTAL,
        "duplicate_provider_emission_contribution_to_updates": sum(
            item["mbp10_duplicate_contribution"]
            ["contribution_to_mbp_update_count"]
            for item in date_verdicts
        ),
        "additional_data_acquired": False,
        "market_values_or_feature_values_reported": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
        "completion_policy": (
            "Preserve and seal Step 4B.3, then stop without edge discovery, "
            "outcome inspection, signal testing, execution, or PnL."
        ),
    }
    verdict["verdict_hash"] = _canonical_hash(verdict)
    verdict_path = output / "verdict.json"
    _write_json_atomic(verdict_path, verdict)
    _write_text_atomic(REPORT_PATH, _render_report(verdict, date_verdicts))
    artifact_paths.extend([verdict_path, REPORT_PATH])

    source_records = []
    for spec in DATE_SPECS.values():
        for source in (spec.mbo, spec.mbp10):
            source_records.extend([
                _file_record(REPO_ROOT / source.relative_path),
                _file_record(REPO_ROOT / source.quality_relative_path),
            ])
    manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_4B3_MANIFEST_V0_1",
        "status": overall_status,
        "sealed_at_utc": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "classification": "ENGINEERING_ONLY_MULTI_DAY_FEATURE_ROBUSTNESS",
        "research_or_validation_credit": "NONE",
        "protocol": _file_record(PROTOCOL_PATH),
        "freeze_receipt": _file_record(FREEZE_PATH),
        "step4b2_manifest": _file_record(STEP4B2_MANIFEST_PATH),
        "step4a3_manifest": _file_record(STEP4A3_MANIFEST_PATH),
        "acquisition_manifest": _file_record(ACQUISITION_MANIFEST_PATH),
        "base_feature_engine": _file_record(BASE_ENGINE_PATH),
        "multiday_feature_tool": _file_record(Path(__file__)),
        "sealed_sources_and_quality_records": source_records,
        "artifacts": [_file_record(path) for path in artifact_paths],
        "verdict_hash": verdict["verdict_hash"],
        "predecessor_verdicts_preserved": True,
        "date_count": len(date_verdicts),
        "source_count": 10,
        "additional_data_acquired": False,
        "market_values_or_feature_values_reported": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    manifest["manifest_hash"] = _canonical_hash(manifest)
    _write_json_atomic(output / "manifest.json", manifest)
    print(json.dumps({
        "stage": "GC_MICROSTRUCTURE_STEP_4B3_SEALED",
        "status": overall_status,
        "formal_pass": all_dates_pass,
        "dates_passed": sum(item["formal_pass"] for item in date_verdicts),
        "dates_total": len(date_verdicts),
        "mbp10_adjacent_duplicates_processed": EXPECTED_MBP_DUPLICATES_TOTAL,
        "manifest_hash": manifest["manifest_hash"],
        "market_values_reported": False,
        "feature_values_reported": False,
    }, sort_keys=True))


def _verify_run_payload(
    run: dict[str, Any], implementation: str, spec: DateSpec, tool_hash: str
) -> None:
    if run.get("implementation") != implementation:
        raise ValueError("Run implementation identity changed")
    if run.get("engineering_date") != spec.date:
        raise ValueError("Run date identity changed")
    if run.get("protocol_sha256") != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Run protocol hash changed")
    if run.get("freeze_sha256") != EXPECTED_FREEZE_SHA256:
        raise ValueError("Run freeze hash changed")
    if run.get("tool_sha256") != tool_hash:
        raise ValueError("Step 4B.3 tool changed between run and seal")
    if run.get("base_engine_sha256") != EXPECTED_BASE_ENGINE_SHA256:
        raise ValueError("Run base-engine binding changed")
    feature = run["feature_parquet"]
    path = Path(feature["path"])
    if (
        path.stat().st_size != feature["bytes"]
        or _sha256(path) != feature["sha256"]
        or pq.ParquetFile(path).metadata.num_rows != BUCKET_COUNT
    ):
        raise ValueError("Sealed date feature payload changed")
    if run.get("feature_column_count") != FEATURE_COLUMN_COUNT:
        raise ValueError("Run feature-column count changed")


def _no_prohibited_work(*runs: dict[str, Any]) -> bool:
    prohibited_true = (
        "additional_data_acquired",
        "market_values_human_or_model_inspected",
        "feature_values_human_or_model_inspected",
        "outcomes_accessed",
        "signals_calculated",
        "execution_optimized",
        "pnl_calculated",
    )
    return all(
        not bool(run[key])
        and run["source_rows_filtered_deduplicated_repaired_relabeled_or_substituted"] == 0
        and run["mbo_mbp_alignment_attempts"] == 0
        for run in runs
        for key in prohibited_true
    )


def _render_report(
    verdict: dict[str, Any], date_verdicts: list[dict[str, Any]]
) -> str:
    lines = [
        "# GC Microstructure Step 4B.3 — Multi-Day Feature Robustness",
        "",
        "## Formal verdict",
        "",
        f"`{verdict['status']}`",
        "",
        "| Engineering date | Verdict | MBO rows | MBP-10 rows | Duplicate emissions | Continuous crossed bucket closes |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in date_verdicts:
        lines.append(
            "| {date} | {status} | {mbo:,} | {mbp:,} | {dups:,} | {crossed:,} |".format(
                date=item["engineering_date"],
                status=item["status"],
                mbo=item["technical_counts"]["mbo"]["records"],
                mbp=item["technical_counts"]["mbp10"]["records"],
                dups=item["mbp10_duplicate_contribution"]
                ["contribution_to_mbp_update_count"],
                crossed=item["bucket_close_classification"]
                ["continuous_matching_crossed_bucket_closes"],
            )
        )
    lines.extend([
        "",
        "## Reproduction and scope",
        "",
        f"- Dates passed: `{sum(item['formal_pass'] for item in date_verdicts)}/{len(date_verdicts)}`.",
        f"- Each date contains `{BUCKET_COUNT:,}` ordered one-second buckets and `{FEATURE_COLUMN_COUNT}` frozen columns.",
        f"- All `{EXPECTED_MBP_DUPLICATES_TOTAL}` sealed exact-adjacent MBP-10 provider emissions were processed and contributed to technical update counts.",
        "- Primary and reference results were compared for schemas, null counts, per-column hashes, complete-row hashes, diagnostics, and byte-identical Parquet payloads.",
        "- State was initialized empty for every date and cleared at every frozen market-segment boundary.",
        "",
        "## Restrictions honored",
        "",
        "No data was acquired. No prices, depths, order-flow values, feature values, outcomes, directional relationships, signals, execution, trades, PnL, R multiples, or account returns were inspected or reported.",
        "",
        "All five dates remain permanently engineering-only and receive zero research or validation credit.",
        "",
    ])
    return "\n".join(lines)


def _verify_seal(output: Path) -> None:
    _verify_protocol_and_freeze()
    _verify_predecessors()
    manifest_path = output / "manifest.json"
    verdict_path = output / "verdict.json"
    manifest = _read_json(manifest_path)
    verdict = _read_json(verdict_path)
    if manifest["manifest_hash"] != _canonical_hash(
        _without_hash(manifest, "manifest_hash")
    ):
        raise ValueError("Step 4B.3 manifest canonical hash mismatch")
    if verdict["verdict_hash"] != _canonical_hash(
        _without_hash(verdict, "verdict_hash")
    ):
        raise ValueError("Step 4B.3 verdict canonical hash mismatch")
    if manifest["status"] != verdict["status"]:
        raise ValueError("Step 4B.3 manifest and verdict statuses differ")
    for record in (
        manifest["protocol"], manifest["freeze_receipt"],
        manifest["step4b2_manifest"], manifest["step4a3_manifest"],
        manifest["acquisition_manifest"], manifest["base_feature_engine"],
        manifest["multiday_feature_tool"],
        *manifest["sealed_sources_and_quality_records"],
        *manifest["artifacts"],
    ):
        _verify_file_record(record)
    print(json.dumps({
        "stage": "GC_MICROSTRUCTURE_STEP_4B3_SEAL_VERIFIED",
        "status": manifest["status"],
        "manifest_hash": manifest["manifest_hash"],
        "dates": manifest["date_count"],
        "sources": manifest["source_count"],
        "market_values_reported": False,
        "feature_values_reported": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "pnl_calculated": False,
    }, sort_keys=True))


def _assert_protocol_matches_code(protocol: dict[str, Any]) -> None:
    if protocol.get("version") != "GC_MICROSTRUCTURE_STEP_4B3_PROTOCOL_V0_1":
        raise ValueError("Unexpected Step 4B.3 protocol version")
    if protocol["feature_engine"]["base_engine_sha256"] != EXPECTED_BASE_ENGINE_SHA256:
        raise ValueError("Protocol base-engine binding differs from code")
    if protocol["feature_engine"]["feature_schema_sha256"] != EXPECTED_FEATURE_SCHEMA_SHA256:
        raise ValueError("Protocol feature-schema binding differs from code")
    if protocol["feature_engine"]["feature_column_count"] != FEATURE_COLUMN_COUNT:
        raise ValueError("Protocol feature count differs from code")
    if protocol["temporal_contract"]["bucket_count_per_date"] != BUCKET_COUNT:
        raise ValueError("Protocol bucket count differs from code")
    if protocol["temporal_contract"]["bucket_width_ns"] != BUCKET_WIDTH_NS:
        raise ValueError("Protocol bucket width differs from code")
    frozen_dates = protocol["frozen_dates"]
    if tuple(frozen_dates) != tuple(DATE_SPECS):
        raise ValueError("Protocol date order differs from code")
    for date, spec in DATE_SPECS.items():
        frozen = frozen_dates[date]
        if (
            frozen["day_start_inclusive_ns"] != spec.day_start_ns
            or frozen["day_end_exclusive_ns"] != spec.day_end_ns
            or frozen["expected_instrument_id"] != spec.instrument_id
            or frozen["dst_window_class"] != spec.dst_window_class
        ):
            raise ValueError(f"Protocol date parameters differ for {date}")
        frozen_segments = tuple(
            (
                item["segment_id"], item["state"],
                item["start_inclusive_ns"], item["end_exclusive_ns"],
            )
            for item in frozen["segments"]
        )
        if frozen_segments != spec.segments:
            raise ValueError(f"Protocol segment parameters differ for {date}")
        for key, source in (("mbo", spec.mbo), ("mbp10", spec.mbp10)):
            source_frozen = frozen[key]
            expected = {
                "path": source.relative_path,
                "records": source.records,
                "bytes": source.size_bytes,
                "sha256": source.sha256,
                "quality_path": source.quality_relative_path,
                "quality_bytes": source.quality_bytes,
                "quality_sha256": source.quality_sha256,
                "bad_ts_recv_rows": source.bad_ts_recv_rows,
                "adjacent_exact_duplicates": source.adjacent_duplicates,
            }
            if source_frozen != expected:
                raise ValueError(f"Protocol source parameters differ for {date} {key}")
    if protocol["duplicate_policy"]["sealed_mbp10_duplicate_total"] != EXPECTED_MBP_DUPLICATES_TOTAL:
        raise ValueError("Protocol duplicate total differs from code")


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _verify_file_record(record: dict[str, Any]) -> None:
    path = Path(record["path"])
    if (
        not path.exists()
        or path.stat().st_size != record["bytes"]
        or _sha256(path) != record["sha256"]
    ):
        raise ValueError(f"Sealed file changed: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _without_hash(value: dict[str, Any], name: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != name}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _write_text_atomic(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
