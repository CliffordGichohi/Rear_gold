from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.api.schemas import IngestionBatchResponse
from gold_intel.config import get_settings
from gold_intel.infrastructure.database import get_session
from gold_intel.infrastructure.models import IngestionBatch
from gold_intel.ingestion.service import ingest_csv_path

router = APIRouter(prefix="/ingestions", tags=["ingestions"])


@router.post("/files", response_model=IngestionBatchResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    provider_code: str = Form(..., min_length=2, max_length=64),
    dataset_code: str = Form(..., min_length=2, max_length=96),
    schema_version: str = Form("1"),
    is_synthetic: bool = Form(False),
    source_published_at: datetime | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> IngestionBatchResponse:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Only CSV files are supported in this slice.")

    settings = get_settings()
    staging = Path(settings.raw_store_path) / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    temporary_path = staging / f"{uuid4()}.csv"
    size = 0
    try:
        with temporary_path.open("wb") as stream:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 50 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="CSV exceeds the 50 MB limit.")
                stream.write(chunk)
        try:
            async with session.begin():
                result = await ingest_csv_path(
                    session,
                    source_path=temporary_path,
                    original_filename=file.filename,
                    raw_store_root=Path(settings.raw_store_path),
                    provider_code=provider_code.upper(),
                    dataset_code=dataset_code.upper(),
                    schema_version=schema_version,
                    is_synthetic=is_synthetic,
                    source_published_at=source_published_at,
                )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        temporary_path.unlink(missing_ok=True)
        await file.close()

    return _batch_response(
        result.batch,
        duplicate=result.duplicate,
        valid=result.valid_records,
        invalid=result.invalid_records,
        issues=result.quality_issue_count,
    )


@router.get("/{batch_id}", response_model=IngestionBatchResponse)
async def get_batch(
    batch_id: UUID, session: AsyncSession = Depends(get_session)
) -> IngestionBatchResponse:
    batch = await session.get(IngestionBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Ingestion batch not found.")
    return _batch_response(
        batch,
        duplicate=False,
        valid=batch.record_count,
        invalid=0,
        issues=0,
    )


def _batch_response(
    batch: IngestionBatch, *, duplicate: bool, valid: int, invalid: int, issues: int
) -> IngestionBatchResponse:
    return IngestionBatchResponse(
        batch_id=batch.id,
        provider_code=batch.provider_code,
        dataset_code=batch.dataset_code,
        status=batch.status,
        duplicate=duplicate,
        content_hash=batch.content_hash,
        record_count=batch.record_count,
        valid_records=valid,
        invalid_records=invalid,
        quality_issue_count=issues,
        is_synthetic=batch.is_synthetic,
        ingested_at=batch.ingested_at,
    )
