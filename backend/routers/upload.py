from typing import List
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models.invoice import InvoiceData, InvoiceBatch
from backend.services.ocr_service import OcrService
from backend.services.qr_service import QrService
from backend.services.extraction_service import ExtractionService
from backend.services.history_service import HistoryService
from backend.utils.validators import validate_upload, compute_file_hash
from backend.utils.file_utils import save_temp_file, cleanup_temp_file

router = APIRouter(prefix="/api", tags=["upload"])

ocr_service = OcrService()
qr_service = QrService()
extraction_service = ExtractionService()
history_service = HistoryService()


@router.post("/upload", response_model=InvoiceData)
async def upload_invoice(file: UploadFile = File(...), db: Session = Depends(get_db)):
    contents = await validate_upload(file)
    file_hash = compute_file_hash(contents)
    existing = history_service.check_duplicate(db, file_hash)
    if existing:
        existing.file_name = "[DUPLICATE] " + existing.file_name
        return existing
    temp_path = save_temp_file(contents, file.filename)
    try:
        invoice = _process_file(temp_path, file.filename)
        invoice.file_hash = file_hash
        saved = history_service.save_invoice(db, invoice)
        return saved
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, "Processing error: " + str(e))
    finally:
        cleanup_temp_file(temp_path)


@router.post("/upload-batch", response_model=InvoiceBatch)
async def upload_batch(files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
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
                batch.invoices.append(existing)
                batch.total_processed += 1
                continue
            temp_path = save_temp_file(contents, file.filename)
            try:
                invoice = _process_file(temp_path, file.filename)
                invoice.file_hash = file_hash
                saved = history_service.save_invoice(db, invoice)
                batch.invoices.append(saved)
                batch.total_processed += 1
            finally:
                cleanup_temp_file(temp_path)
        except Exception as e:
            batch.errors.append(file.filename + ": " + str(e))
            batch.total_errors += 1
    return batch


def _process_file(file_path: Path, original_name: str) -> InvoiceData:
    qr_result = qr_service.try_extract(file_path)
    if qr_result:
        qr_result.file_name = original_name
        return qr_result
    raw_text, ocr_confidence = ocr_service.extract_text(file_path)
    if not raw_text or len(raw_text.strip()) < 10:
        raise HTTPException(422, "Could not extract text from " + original_name)
    invoice = extraction_service.extract(raw_text, ocr_confidence)
    invoice.file_name = original_name
    return invoice
