# backend/models/invoice.py

from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel


# ── Enums ─────────────────────────────────────────────────────────────────────

class SourceType(str, Enum):
    QR_BILL = "qr_bill"
    OCR = "ocr"
    HYBRID = "hybrid"
    MANUAL = "manual"


# ── Core data class ───────────────────────────────────────────────────────────

@dataclass
class InvoiceData:
    # Database / identity
    id: Optional[int] = None
    file_name: str = ""
    file_hash: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    # Source
    source_type: SourceType = SourceType.OCR
    confidence_score: float = 0.0

    # Creditor (vendor)
    vendor_name: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_iban: Optional[str] = None
    vendor_vat_uid: Optional[str] = None

    # Debtor (recipient)
    debtor_name: Optional[str] = None
    debtor_address: Optional[str] = None

    # Invoice details
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    client_number: Optional[str] = None

    # Amounts
    currency: str = "CHF"
    subtotal: Optional[float] = None
    vat_rate: Optional[float] = None
    vat_amount: Optional[float] = None
    total: Optional[float] = None

    # Reference
    reference_number: Optional[str] = None
    creditor_reference: Optional[str] = None

    # Raw
    raw_text: Optional[str] = None


# ── Pydantic models for API ───────────────────────────────────────────────────

class InvoiceBatch(BaseModel):
    """Response model for batch upload."""
    invoices: list = []
    total_processed: int = 0
    total_errors: int = 0
    errors: List[str] = []


class InvoiceUpdate(BaseModel):
    vendor_name: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_iban: Optional[str] = None
    vendor_vat_uid: Optional[str] = None
    debtor_name: Optional[str] = None
    debtor_address: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    client_number: Optional[str] = None
    currency: Optional[str] = None
    subtotal: Optional[float] = None
    vat_rate: Optional[float] = None
    vat_amount: Optional[float] = None
    total: Optional[float] = None
    reference_number: Optional[str] = None
    creditor_reference: Optional[str] = None


class ExportRequest(BaseModel):
    """Request model for export operations."""
    invoice_ids: List[str] = []
    invoices: List[dict] = []
    format: str = "csv"


class HistoryQuery(BaseModel):
    search: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    currency: Optional[str] = None
    source_type: Optional[str] = None
    sort_by: str = "created_at"
    sort_dir: str = "desc"
    page: int = 1
    page_size: int = 20


class HistoryResponse(BaseModel):
    invoices: list
    total_count: int
    page: int
    page_size: int
    total_pages: int


class DashboardStats(BaseModel):
    total_invoices: int = 0
    total_amount_chf: float = 0.0
    total_amount_eur: float = 0.0
    total_vat_chf: float = 0.0
    avg_confidence: float = 0.0
    qr_bill_count: int = 0
    ocr_count: int = 0
    hybrid_count: int = 0
    this_month_count: int = 0
    top_vendors: list = []