from __future__ import annotations

import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.backtesting.casebook_baseline import (
    BaselineExecutionConfig,
    BaselinePriceBar,
)
from gold_intel.backtesting.casebook_discovery_v2_holdout import (
    ZnHoldoutSample,
    ZnHoldoutSeries,
)

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import run_gold_casebook_discovery_v2_holdout as runner  # noqa: E402
import validate_gold_casebook_discovery_v2_holdout as validator  # noqa: E402


def test_runner_and_independent_decision_reconstruction_match() -> None:
    session_dates = [date(2025, 1, 6), date(2025, 1, 7)]
    xau: dict[datetime, runner.SealedXauExecutionBar] = {}
    for index, session_date in enumerate(session_dates):
        decision = datetime.combine(session_date, time(8), tzinfo=UTC)
        for offset, price in (
            (timedelta(minutes=1), 2_600.0 + index),
            (timedelta(hours=3, minutes=59), 2_604.0 + index),
        ):
            open_time = decision + offset
            identity = runner._xau_identity(
                record_id=f"xau-{session_date}-{offset}",
                open_time=open_time,
                close_time=open_time + timedelta(minutes=1),
                available_at=open_time + timedelta(minutes=1),
                reference_open=price,
                reference_close=price,
                spread_price=0.2,
                batch_id="batch",
                source_record_key=f"source-{open_time}",
                batch_content_hash="a" * 64,
                dataset_code="XAUUSD_1M",
                raw_object_path="data/mt5/source.csv",
            )
            bar = BaselinePriceBar(
                record_id=str(identity["record_id"]),
                record_hash=canonical_hash(identity),
                open_time=open_time,
                close_time=open_time + timedelta(minutes=1),
                open=price,
                close=price,
                spread_price=0.2,
                available_at=open_time + timedelta(minutes=1),
            )
            xau[open_time] = runner.SealedXauExecutionBar(
                bar=bar,
                identity=identity,
            )

    samples: list[ZnHoldoutSample] = []
    for index, session_date in enumerate(session_dates):
        decision = datetime.combine(session_date, time(8), tzinfo=UTC)
        for ordinal, (available_at, close) in enumerate(
            (
                (decision - timedelta(hours=4), 110.0 + index),
                (decision, 111.0 + index),
            ),
            start=index * 2 + 1,
        ):
            samples.append(
                ZnHoldoutSample(
                    source_record_id=f"zn-{ordinal}",
                    source_file_sha256="b" * 64,
                    source_row_ordinal=ordinal,
                    open_time=available_at - timedelta(minutes=1),
                    available_at=available_at,
                    continuous_symbol="ZN.v.0",
                    instrument_id=42,
                    underlying_raw_symbol="ZNH5",
                    close=close,
                )
            )
    series = ZnHoldoutSeries.from_samples(samples)
    config = BaselineExecutionConfig(
        execution_manifest_hash="execution",
    )

    materialized = runner._materialize_cases(
        session_dates,
        xau_bars=xau,
        zn_series=series,
        config=config,
        research_hash="research",
        readiness_hash="readiness",
    )
    records = [
        runner._decision_record(
            item,
            research_hash="research",
            readiness_hash="readiness",
            stress_multiplier=1.5,
        )
        for item in materialized
    ]

    for record in records:
        validator._verify_record_hash(json_ready(record))
        entry = validator._bar_from_record(json_ready(record["execution"]["entry_bar"]))
        assert entry.record_hash == record["execution"]["entry_bar"]["record_hash"]
        reconstructed = validator._reconstruct_feature(
            json_ready(record["feature"]),
            decision_at=validator._timestamp(record["decision_at"]),
            timestamp_lineage={
                "available_times": [item.available_at for item in samples],
                "rows": [
                    {
                        "source_record_id": item.source_record_id,
                        "source_file_sha256": item.source_file_sha256,
                        "source_row_ordinal": item.source_row_ordinal,
                        "open_time": item.open_time,
                        "available_at": item.available_at,
                        "continuous_symbol": item.continuous_symbol,
                        "instrument_id": item.instrument_id,
                        "underlying_raw_symbol": (item.underlying_raw_symbol),
                    }
                    for item in samples
                ],
            },
        )
        assert reconstructed.bias == record["bias"]

    validator._verify_chronological_halves([item.case for item in materialized])
