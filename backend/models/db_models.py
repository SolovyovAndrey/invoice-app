# backend/models/db_models.py

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from backend.database import Base


class InvoiceRecord(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String(255), nullable=False)
    file_hash = Column(String(64), unique=True, index=True)
    is_deleted = Column(String(1), default="N")

    # Source
    source_type = Column(String(20), default="ocr")
    confidence_score = Column(Float, default=0.0)

    # Creditor
    vendor_name = Column(String(255))
    vendor_address = Column(Text)
    vendor_iban = Column(String(34))
    vendor_vat_uid = Column(String(20))

    # Debtor  ← NEW
    debtor_name = Column(String(255))
    debtor_address = Column(Text)

    # Invoice details
    invoice_number = Column(String(50))
    invoice_date = Column(String(20))              # ← NEW
    client_number = Column(String(50))                  # ← NEW

    # Amounts
    currency = Column(String(3), default="CHF")
    subtotal = Column(Float)
    vat_rate = Column(Float)
    vat_amount = Column(Float)
    total = Column(Float)

    # Reference
    reference_number = Column(String(50))
    creditor_reference = Column(String(50))      # ← NEW

    # Raw
    raw_text = Column(Text)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))