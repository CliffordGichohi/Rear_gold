from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.audit_multi_asset_macro_session_portfolio_v1_coverage import (
    PROTOCOL,
    ROOT,
    canonical_json_bytes,
    scan_csv_primary,
    scan_csv_reference,
    verify_predecessors,
)


HEADER = "open_time,close_time,available_at,open,high,low,close,volume,volume_type,spread_points,real_volume\n"


class MultiAssetCoverageAuditTests(unittest.TestCase):
    def test_independent_readers_apply_identical_source_preserving_dedup(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as temporary:
            directory = Path(temporary)
            first = directory / "test_1m_ic_markets_mt5_20210802T0700_20210802T0702.csv"
            second = directory / "test_1m_ic_markets_mt5_20210802T0701_20210802T0703.csv"
            first.write_text(
                HEADER
                + "2021-08-02T07:00:00+00:00,2021-08-02T07:01:00+00:00,2021-08-02T07:01:00+00:00,100,101,99,100,5,TICK,2,0\n"
                + "2021-08-02T07:01:00+00:00,2021-08-02T07:02:00+00:00,2021-08-02T07:02:00+00:00,900,999,1,500,9,TICK,3,0\n",
                encoding="utf-8",
            )
            second.write_text(
                HEADER
                + "2021-08-02T07:01:00+00:00,2021-08-02T07:02:00+00:00,2021-08-02T07:02:00+00:00,-1,-1,-1,-1,1,TICK,3,0\n"
                + "2021-08-02T07:02:00+00:00,2021-08-02T07:03:00+00:00,2021-08-02T07:03:00+00:00,200,201,199,200,6,TICK,4,0\n",
                encoding="utf-8",
            )
            paths = [first, second]
            primary = scan_csv_primary("TEST", ("LONDON_DECISION",), paths)
            reference = scan_csv_reference("TEST", ("LONDON_DECISION",), paths)

        self.assertEqual(canonical_json_bytes(primary), canonical_json_bytes(reference))
        self.assertEqual(primary["raw_rows_in_development_window"], 4)
        self.assertEqual(primary["canonical_unique_timestamps"], 3)
        self.assertEqual(primary["duplicate_timestamp_occurrences"], 1)
        self.assertEqual(primary["duplicate_timestamp_groups"], 1)
        self.assertFalse(primary["semantic_market_values_accessed"])
        serialized = json.dumps(primary)
        self.assertNotIn("999", serialized)
        self.assertNotIn("900", serialized)

    def test_protocol_keeps_forward_periods_and_value_access_locked(self) -> None:
        protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        aliases = {item["research_id"]: item["mt5_symbol"] for item in protocol["instruments"]}
        self.assertEqual(aliases["NAS100"], "USTEC")
        self.assertEqual(aliases["WTI"], "XTIUSD")
        self.assertFalse(protocol["market_outcomes_accessed"])
        self.assertFalse(protocol["calendar_2025_market_values_accessed"])
        self.assertFalse(protocol["calendar_2026_market_values_accessed"])
        self.assertEqual(protocol["paid_acquisition_usd"], 0.0)

    def test_bound_predecessor_artifacts_are_intact(self) -> None:
        result = verify_predecessors()
        self.assertTrue(result["all_verified"])
        self.assertEqual(result["gold_only_branch_verdict"], "TERMINATE_GOLD_ONLY_10R_BRANCH")


if __name__ == "__main__":
    unittest.main()
