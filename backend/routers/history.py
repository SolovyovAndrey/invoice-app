from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models.invoice import (
    InvoiceData, InvoiceUpdate, HistoryQuery,
    HistoryResponse, DashboardStats, ExportRequest,
)
from backend.services.history_service import HistoryService
from backend.services.export_service import ExportService

router = APIRouter(prefix="/api/history", tags=["history"])
history_service = HistoryService()
export_service = ExportService()


@router.get("/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(get_db)):
    return history_service.get_dashboard_stats(db)


@router.get("/", response_model=HistoryResponse)
def list_invoices(
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    amount_min: Optional[float] = Query(None),
    amount_max: Optional[float] = Query(None),
    currency: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    query = HistoryQuery(
        search=search, date_from=date_from, date_to=date_to,
        amount_min=amount_min, amount_max=amount_max,
        currency=currency, source_type=source_type,
        page=page, page_size=page_size,
        sort_by=sort_by, sort_dir=sort_dir,
    )
    return history_service.search_invoices(db, query)


@router.get("/{invoice_id}", response_model=InvoiceData)
def get_invoice(invoice_id: str, db: Session = Depends(get_db)):
    invoice = history_service.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    return invoice


@router.patch("/{invoice_id}", response_model=InvoiceData)
def update_invoice(invoice_id: str, updates: InvoiceUpdate, db: Session = Depends(get_db)):
    invoice = history_service.update_invoice(db, invoice_id, updates)
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    return invoice


@router.delete("/{invoice_id}")
def delete_invoice(invoice_id: str, db: Session = Depends(get_db)):
    if not history_service.delete_invoice(db, invoice_id):
        raise HTTPException(404, "Invoice not found")
    return {"status": "deleted", "id": invoice_id}


@router.post("/delete-batch")
def delete_batch(invoice_ids: List[str], db: Session = Depends(get_db)):
    count = history_service.delete_batch(db, invoice_ids)
    return {"status": "deleted", "count": count}


@router.post("/export/csv")
def export_csv(request: ExportRequest, db: Session = Depends(get_db)):
    invoices = _resolve(request, db)
    csv_out = export_service.to_csv(invoices)
    return StreamingResponse(
        iter([csv_out.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=invoices.csv"},
    )


@router.post("/export/excel")
def export_excel(request: ExportRequest, db: Session = Depends(get_db)):
    invoices = _resolve(request, db)
    excel_out = export_service.to_excel(invoices)
    return StreamingResponse(
        excel_out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=invoices.xlsx"},
    )


def _resolve(request, db):
    if request.invoice_ids:
        return history_service.get_invoices_by_ids(db, request.invoice_ids)
    elif request.invoices:
        return request.invoices
    raise HTTPException(400, "Provide invoices or invoice_ids")
