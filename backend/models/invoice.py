from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class SourceType(str, Enum):
    QR_BILL = "qr_bill"
    OCR = "ocr"
    MANUAL = "manual"


class InvoiceData(BaseModel):
    id: Optional[str] = None
    file_name: str = ""
    file_hash: Optional[str] = None
    source_type: SourceType = SourceType.OCR
    confidence_score: float = Field(default=0.0, ge=0.0, le=100.0)

    # Vendor (seller)
    vendor_name: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_iban: Optional[str] = None
    vendor_vat_uid: Optional[str] = None

    # Recipient (buyer)
    recipient_name: Optional[str] = None
    recipient_address: Optional[str] = None
    recipient_vat_uid: Optional[str] = None
    recipient_company_code: Optional[str] = None

    # Invoice details
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    currency: str = "CHF"
    subtotal: Optional[float] = None
    vat_rate: Optional[float] = None
    vat_amount: Optional[float] = None
    total: Optional[float] = None
    reference_number: Optional[str] = None
    raw_text: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class InvoiceBatch(BaseModel):
    invoices: List[InvoiceData] = []
    total_processed: int = 0
    total_errors: int = 0
    errors: List[str] = []


class ExportRequest(BaseModel):
    invoices: List[InvoiceData] = []
    invoice_ids: List[str] = []
    format: str = "csv"
    include_raw_text: bool = False


class HistoryQuery(BaseModel):
    search: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    currency: Optional[str] = None
    source_type: Optional[str] = None
    page: int = 1
    page_size: int = 20
    sort_by: str = "created_at"
    sort_dir: str = "desc"


class HistoryResponse(BaseModel):
    invoices: List[InvoiceData]
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
    this_month_count: int = 0
    top_vendors: List[dict] = []


class InvoiceUpdate(BaseModel):
    # Vendor
    vendor_name: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_iban: Optional[str] = None
    vendor_vat_uid: Optional[str] = None

    # Recipient
    recipient_name: Optional[str] = None
    recipient_address: Optional[str] = None
    recipient_vat_uid: Optional[str] = None
    recipient_company_code: Optional[str] = None

    # Invoice details
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    currency: Optional[str] = None
    subtotal: Optional[float] = None
    vat_rate: Optional[float] = None
    vat_amount: Optional[float] = None
    total: Optional[float] = None
    reference_number: Optional[str] = None