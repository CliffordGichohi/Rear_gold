from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import materialize_gc_continuous_state_response_v3_m2 as m2  # noqa: E402


class ContinuousStateResponseM2Tests(unittest.TestCase):
    def test_self_test(self) -> None:
        m2.self_test()

    def test_registry_and_schema_are_frozen(self) -> None:
        protocol = json.loads(m2.PROTOCOL.read_text(encoding="utf-8"))
        self.assertEqual(protocol["population"]["anchors_total"], 5_984)
        self.assertEqual(protocol["feature_implementation"]["feature_count"], 12)
        self.assertEqual(len(m2.FEATURE_IDS), 12)
        self.assertEqual(len(m2.OUTPUT_SCHEMA), 57)
        for feature_id in m2.FEATURE_IDS:
            self.assertIn(f"{feature_id}__value", m2.OUTPUT_SCHEMA.names)
            self.assertIn(f"{feature_id}__availability", m2.OUTPUT_SCHEMA.names)
            self.assertIn(f"{feature_id}__available_at_ns", m2.OUTPUT_SCHEMA.names)
            self.assertIn(f"{feature_id}__lineage_hash", m2.OUTPUT_SCHEMA.names)
        forbidden = {"outcome", "return", "pnl", "trade_id", "entry", "exit", "stop", "target", "r_multiple"}
        self.assertFalse(any(name.lower() in forbidden for name in m2.OUTPUT_SCHEMA.names))

    def test_macro_primary_reference_exact_and_point_in_time(self) -> None:
        available = "2024-03-20T07:00:00Z"

        def fact(value: object) -> dict[str, object]:
            return {
                "value": value,
                "epistemic_status": "CALCULATED",
                "quality": "VALID",
                "available_at": available,
            }

        projection = {
            "record_hash": "a" * 64,
            "source_session_record_id": "SESSION",
            "decision_state": {
                "layers": {
                    "market_regime": {
                        "regime_state": fact({"directional_score": 12.5}),
                        "rates": {
                            "real_yield_10y": fact(
                                {
                                    "absolute_change": -0.05,
                                    "change_epistemic_status": "CALCULATED",
                                    "previous_record_id": "RY0",
                                }
                            ),
                            "treasury_2y": fact(
                                {
                                    "absolute_change": 0.02,
                                    "change_epistemic_status": "CALCULATED",
                                    "previous_record_id": "T20",
                                }
                            ),
                        },
                        "usd": fact(
                            {
                                "value": 101.0,
                                "previous_value": 100.0,
                                "change_epistemic_status": "CALCULATED",
                                "previous_record_id": "USD0",
                            }
                        ),
                    }
                }
            },
        }
        decision = m2.dt_ns(datetime(2024, 3, 20, 8, 0, tzinfo=UTC))
        primary = m2.extract_macro_primary(projection, decision)
        reference = m2.extract_macro_reference(projection, decision)
        self.assertEqual(primary, reference)
        self.assertEqual(primary["CSR_MACRO_ENGINE_SCORE"].value, 12.5)
        self.assertEqual(primary["CSR_MACRO_REAL_YIELD_SUPPORT"].value, 0.05)
        self.assertEqual(primary["CSR_MACRO_2Y_SUPPORT"].value, -2.0)
        self.assertAlmostEqual(primary["CSR_MACRO_USD_SUPPORT"].value or 0.0, -10_000 * np.log(1.01))
        early = m2.extract_macro_primary(projection, m2.dt_ns(datetime(2024, 3, 20, 6, 59, tzinfo=UTC)))
        self.assertTrue(all(item.value is None for item in early.values()))

    def test_dst_anchor_identities(self) -> None:
        london_summer = {
            "row_id": "L",
            "session_date": "2024-07-08",
            "session_code": "LONDON",
            "session_open_utc": "2024-07-08T07:00:00Z",
            "session_timezone": "Europe/London",
            "selected_month_week_id": "B",
        }
        ny_summer = {
            "row_id": "N",
            "session_date": "2024-07-08",
            "session_code": "NEW_YORK",
            "session_open_utc": "2024-07-08T12:00:00Z",
            "session_timezone": "America/New_York",
            "selected_month_week_id": "B",
        }
        self.assertEqual(m2.ns_iso(m2.anchor_identity(london_summer, 0, 1)["decision_at_ns"]), "2024-07-08T07:00:00Z")
        self.assertEqual(m2.ns_iso(m2.anchor_identity(ny_summer, 225, 1)["decision_at_ns"]), "2024-07-08T15:45:00Z")

    def test_technical_latch_is_not_backfilled(self) -> None:
        values = m2.synthetic_micro_values()
        values["book_crossed"][-1] = True
        arrays: dict[str, np.ndarray] = {}
        for name, items in values.items():
            dtype = object if name in {"market_segment", "market_state"} else bool if name in {"state_available", "book_two_sided", "book_locked", "book_crossed"} else np.int64
            arrays[name] = np.asarray(items, dtype=dtype)
        row = {"row_id": "S", "session_code": "LONDON"}
        primary = m2._calculate_micro_numpy(arrays, row, "0" * 64, 900 * m2.ONE_SECOND_NS, 900)
        reference = m2.calculate_micro_reference(values, row, "0" * 64, 900 * m2.ONE_SECOND_NS, 900)
        self.assertEqual(primary, reference)
        self.assertEqual(primary["CSR_BOOK_MICROPRICE_DISLOCATION_T0"].availability, m2.AV_TECH_STATE)
        self.assertIsNone(primary["CSR_BOOK_MICROPRICE_DISLOCATION_T0"].value)

    def test_receipts_and_null_contract(self) -> None:
        record = m2.seal_receipt({"status": "PASS", "receipt": None}, "receipt")
        self.assertTrue(m2.receipt_valid(record, "receipt"))
        unknown = m2.unknown_observation("X", m2.AV_UNKNOWN_CONTEXT, available_at_ns=None, lineage_payload={"a": 1})
        self.assertIsNone(unknown.value)
        with self.assertRaises(ValueError):
            m2.Observation(1.0, m2.AV_UNKNOWN_CONTEXT, None, "0" * 64)


if __name__ == "__main__":
    unittest.main()
