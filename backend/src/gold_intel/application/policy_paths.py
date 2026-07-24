from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.infrastructure.models import (
    IngestionBatch,
    PolicyPathPoint,
    Provider,
    RawRecord,
)


@dataclass(frozen=True, slots=True)
class PolicyPathIngestionResult:
    batch: IngestionBatch
    duplicate: bool
    snapshot_count: int
    point_count: int


async def ingest_policy_path_bundle(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    raw_store_root: Path,
) -> PolicyPathIngestionResult:
    provider_code = str(payload["provider_code"])
    dataset_code = str(payload["dataset_code"])
    canonical = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
    )
    content_hash = hashlib.sha256(canonical.encode()).hexdigest()
    existing_batch = await session.scalar(
        select(IngestionBatch).where(
            IngestionBatch.provider_code == provider_code,
            IngestionBatch.dataset_code == dataset_code,
            IngestionBatch.content_hash == content_hash,
        )
    )
    if existing_batch is not None:
        return PolicyPathIngestionResult(
            batch=existing_batch,
            duplicate=True,
            snapshot_count=0,
            point_count=0,
        )
    if await session.get(Provider, provider_code) is None:
        session.add(
            Provider(
                code=provider_code,
                name=f"{provider_code} policy-path source",
                provider_type="MANUAL_OR_LICENSED_EXPECTATIONS_FEED",
                license_class="USER_SUPPLIED_OR_LICENSED",
                enabled=True,
                metadata_json={
                    "contract": (
                        "Complete probability distribution by meeting and target-midpoint outcome."
                    )
                },
            )
        )
        await session.flush()

    destination = (
        raw_store_root
        / provider_code.lower()
        / dataset_code.lower()
        / content_hash
        / "policy_path.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(canonical + "\n", encoding="utf-8")
    batch = IngestionBatch(
        id=uuid4(),
        provider_code=provider_code,
        dataset_code=dataset_code,
        schema_version=payload["schema_version"],
        content_hash=content_hash,
        raw_object_path=str(destination),
        status="PROCESSING",
        record_count=0,
        is_synthetic=payload["is_synthetic"],
        source_published_at=None,
    )
    session.add(batch)
    await session.flush()

    inserted_points = 0
    inserted_snapshots = 0
    for record_number, snapshot in enumerate(payload["snapshots"], start=1):
        session.add(
            RawRecord(
                id=uuid4(),
                batch_id=batch.id,
                record_number=record_number,
                source_record_key=snapshot["snapshot_as_of"].isoformat(),
                payload=_jsonable(snapshot),
                parsed_ok=True,
            )
        )
        snapshot_inserted = False
        for outcome in snapshot["outcomes"]:
            existing = await session.scalar(
                select(PolicyPathPoint).where(
                    PolicyPathPoint.provider_code == provider_code,
                    PolicyPathPoint.snapshot_as_of == snapshot["snapshot_as_of"],
                    PolicyPathPoint.meeting_date == outcome["meeting_date"],
                    PolicyPathPoint.outcome_basis_points == outcome["outcome_basis_points"],
                    PolicyPathPoint.available_at == snapshot["available_at"],
                )
            )
            if existing is not None:
                continue
            metadata = {
                **snapshot["metadata"],
                **outcome["metadata"],
            }
            metadata.setdefault(
                "outcome_semantics",
                "TARGET_MIDPOINT_BASIS_POINTS",
            )
            session.add(
                PolicyPathPoint(
                    id=uuid4(),
                    provider_code=provider_code,
                    snapshot_as_of=snapshot["snapshot_as_of"],
                    meeting_date=outcome["meeting_date"],
                    outcome_basis_points=outcome["outcome_basis_points"],
                    probability=_decimal(outcome["probability"]),
                    expected_rate=_optional_decimal(outcome.get("expected_rate")),
                    available_at=snapshot["available_at"],
                    source_record_key=outcome["source_record_key"],
                    batch_id=batch.id,
                    is_synthetic=payload["is_synthetic"],
                    metadata_json=metadata,
                )
            )
            inserted_points += 1
            snapshot_inserted = True
        if snapshot_inserted:
            inserted_snapshots += 1
    batch.record_count = inserted_points
    batch.status = "COMPLETED"
    await session.flush()
    return PolicyPathIngestionResult(
        batch=batch,
        duplicate=False,
        snapshot_count=inserted_snapshots,
        point_count=inserted_points,
    )


def policy_path_rows_to_dict(
    rows: list[PolicyPathPoint],
) -> list[dict[str, Any]]:
    grouped: dict[
        tuple[str, datetime, datetime, bool],
        list[PolicyPathPoint],
    ] = {}
    for row in rows:
        grouped.setdefault(
            (
                row.provider_code,
                row.snapshot_as_of,
                row.available_at,
                row.is_synthetic,
            ),
            [],
        ).append(row)
    output: list[dict[str, Any]] = []
    for key, points in sorted(
        grouped.items(),
        key=lambda item: item[0][1],
        reverse=True,
    ):
        provider_code, snapshot_as_of, available_at, is_synthetic = key
        meetings: dict[Any, list[PolicyPathPoint]] = {}
        for point in points:
            meetings.setdefault(point.meeting_date, []).append(point)
        output.append(
            {
                "provider_code": provider_code,
                "snapshot_as_of": snapshot_as_of,
                "available_at": available_at,
                "is_synthetic": is_synthetic,
                "meetings": [
                    {
                        "meeting_date": meeting_date.isoformat(),
                        "probability_sum": round(
                            sum(float(point.probability) for point in outcomes),
                            8,
                        ),
                        "expected_rate": round(
                            sum(
                                float(point.probability)
                                * (
                                    float(point.expected_rate)
                                    if point.expected_rate is not None
                                    else point.outcome_basis_points / 100
                                )
                                for point in outcomes
                            ),
                            6,
                        ),
                        "outcomes": [
                            {
                                "outcome_basis_points": point.outcome_basis_points,
                                "probability": float(point.probability),
                                "expected_rate": (
                                    float(point.expected_rate)
                                    if point.expected_rate is not None
                                    else None
                                ),
                                "source_record_key": point.source_record_key,
                            }
                            for point in sorted(
                                outcomes,
                                key=lambda item: item.outcome_basis_points,
                            )
                        ],
                    }
                    for meeting_date, outcomes in sorted(meetings.items())
                ],
            }
        )
    return output


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: Any | None) -> Decimal | None:
    return None if value is None else _decimal(value)
