import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Text, DateTime, Index
from backend.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InvoiceRecord(Base):
    __tablename__ = "invoices"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    file_name = Column(String(255), nullable=False, index=True)
    file_hash = Column(String(64), nullable=True, index=True)
    source_type = Column(String(20), nullable=False, default="ocr")
    confidence_score = Column(Float, default=0.0)
    vendor_name = Column(String(255), nullable=True, index=True)
    vendor_address = Column(Text, nullable=True)
    vendor_iban = Column(String(34), nullable=True)
    vendor_vat_uid = Column(String(20), nullable=True)
    invoice_number = Column(String(100), nullable=True, index=True)
    invoice_date = Column(String(20), nullable=True, index=True)
    currency = Column(String(3), default="CHF")
    subtotal = Column(Float, nullable=True)
    vat_rate = Column(Float, nullable=True)
    vat_amount = Column(Float, nullable=True)
    total = Column(Float, nullable=True, index=True)
    reference_number = Column(String(50), nullable=True)
    creditor_reference = Column(String(30), nullable=True)
    raw_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    is_deleted = Column(String(1), default="N", nullable=False)

    __table_args__ = (
        Index("ix_vendor_date", "vendor_name", "invoice_date"),
        Index("ix_date_total", "invoice_date", "total"),
        Index("ix_active_records", "is_deleted", "created_at"),
    )
