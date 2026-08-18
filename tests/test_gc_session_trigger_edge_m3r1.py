from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "run_gc_session_trigger_edge_m3r1.py"
SPEC = importlib.util.spec_from_file_location("gc_session_trigger_edge_m3r1", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r1)


def test_corrected_writer_is_exact_schema_byte_identical_and_round_trip_exact() -> None:
    with tempfile.TemporaryDirectory(prefix="gc_m3r1_test_") as directory:
        proof = r1._serializer_proof(Path(directory) / "proof")
    assert proof["status"] == "PASS_M3_R1_EXACT_SCHEMA_SERIALIZATION_PROOF"
    assert all(proof["checks"].values())
    assert proof["primary"]["sha256"] == proof["reference"]["sha256"]


def test_only_writer_call_order_is_substituted() -> None:
    import inspect

    failed = inspect.getsource(r1.base.write_parquet_exclusive)
    corrected = inspect.getsource(r1.corrected_write_parquet_exclusive)
    assert "pq.write_table(temporary, table," in failed
    assert "pq.write_table(table, temporary," in corrected
    for token in (
        'compression="zstd"',
        "use_dictionary=False",
        "write_statistics=True",
        'data_page_version="1.0"',
        'version="2.6"',
        "row_group_size=65_536",
    ):
        assert token in corrected
