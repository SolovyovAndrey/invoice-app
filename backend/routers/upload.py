# backend/routers/upload.py

import traceback
from typing import List
from pathlib import Path
from dataclasses import asdict
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.invoice import InvoiceData, InvoiceBatch
from backend.services.ocr_service import OcrService
from backend.services.history_service import HistoryService
from backend.utils.validators import validate_upload, compute_file_hash
from backend.utils.file_utils import save_temp_file, cleanup_temp_file

router = APIRouter(prefix="/api", tags=["upload"])

ocr_service = OcrService()
history_service = HistoryService()


@router.post("/upload")
async def upload_invoice(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    print('start')
    contents = await validate_upload(file)
    file_hash = compute_file_hash(contents)

    # ── Duplicate check (including soft-deleted) ─────────
    existing = history_service.check_duplicate(db, file_hash)
    if existing:
        existing.file_name = "[DUPLICATE] " + existing.file_name
        return _to_response(existing)

    # ── Process ──────────────────────────────────────────
    temp_path = save_temp_file(contents, file.filename)
    try:
        invoice = ocr_service.extract_invoice(temp_path)
        invoice.file_name = file.filename
        invoice.file_hash = file_hash
        saved = history_service.save_invoice(db, invoice)
        return _to_response(saved)
    except HTTPException:
        traceback.print_exc()
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"Processing error: {e}")
    finally:
        cleanup_temp_file(temp_path)


@router.post("/upload-batch")
async def upload_batch(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    if len(files) > 50:
        raise HTTPException(400, "Maximum 50 files per batch")

    batch = InvoiceBatch()

    for file in files:
        try:
            contents = await validate_upload(file)
            file_hash = compute_file_hash(contents)

            existing = history_service.check_duplicate(db, file_hash)
            if existing:
                existing.file_name = "[DUPLICATE] " + existing.file_name
                batch.invoices.append(_to_response(existing))
                batch.total_processed += 1
                continue

            temp_path = save_temp_file(contents, file.filename)
            try:
                invoice = ocr_service.extract_invoice(temp_path)
                invoice.file_name = file.filename
                invoice.file_hash = file_hash
                saved = history_service.save_invoice(db, invoice)
                batch.invoices.append(_to_response(saved))
                batch.total_processed += 1
            finally:
                cleanup_temp_file(temp_path)

        except Exception as e:
            batch.errors.append(f"{file.filename}: {e}")
            batch.total_errors += 1

    return batch


def _to_response(invoice: InvoiceData) -> dict:
    """Convert dataclass → dict for JSON response."""
    data = asdict(invoice)
    if hasattr(data.get("source_type"), "value"):
        data["source_type"] = data["source_type"].value
    return data