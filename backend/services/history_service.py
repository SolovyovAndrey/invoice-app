import math
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc, or_
from backend.models.db_models import InvoiceRecord
from backend.models.invoice import (
    InvoiceData, InvoiceUpdate, HistoryQuery, HistoryResponse, DashboardStats,
)


class HistoryService:
    @staticmethod
    def _to_pydantic(record: InvoiceRecord) -> InvoiceData:
        return InvoiceData(
            id=record.id,
            file_name=record.file_name,
            file_hash=record.file_hash,
            source_type=record.source_type,
            confidence_score=record.confidence_score or 0.0,
            vendor_name=record.vendor_name,
            vendor_address=record.vendor_address,
            vendor_iban=record.vendor_iban,
            vendor_vat_uid=record.vendor_vat_uid,
            invoice_number=record.invoice_number,
            invoice_date=record.invoice_date,
            currency=record.currency or "CHF",
            subtotal=record.subtotal,
            vat_rate=record.vat_rate,
            vat_amount=record.vat_amount,
            total=record.total,
            reference_number=record.reference_number,
            raw_text=record.raw_text,
            created_at=record.created_at.isoformat() if record.created_at else None,
            updated_at=record.updated_at.isoformat() if record.updated_at else None,
        )

    @staticmethod
    def _to_record(invoice: InvoiceData) -> InvoiceRecord:
        return InvoiceRecord(
            file_name=invoice.file_name,
            file_hash=invoice.file_hash,
            source_type=invoice.source_type.value if hasattr(invoice.source_type, "value") else str(invoice.source_type),
            confidence_score=invoice.confidence_score,
            vendor_name=invoice.vendor_name,
            vendor_address=invoice.vendor_address,
            vendor_iban=invoice.vendor_iban,
            vendor_vat_uid=invoice.vendor_vat_uid,
            invoice_number=invoice.invoice_number,
            invoice_date=invoice.invoice_date,
            currency=invoice.currency,
            subtotal=invoice.subtotal,
            vat_rate=invoice.vat_rate,
            vat_amount=invoice.vat_amount,
            total=invoice.total,
            reference_number=invoice.reference_number,
            raw_text=invoice.raw_text,
        )

    def save_invoice(self, db: Session, invoice: InvoiceData) -> InvoiceData:
        record = self._to_record(invoice)
        db.add(record)
        db.commit()
        db.refresh(record)
        return self._to_pydantic(record)

    def save_batch(self, db: Session, invoices: List[InvoiceData]) -> List[InvoiceData]:
        records = [self._to_record(inv) for inv in invoices]
        db.add_all(records)
        db.commit()
        for record in records:
            db.refresh(record)
        return [self._to_pydantic(r) for r in records]

    def get_invoice(self, db: Session, invoice_id: str) -> Optional[InvoiceData]:
        record = (
            db.query(InvoiceRecord)
            .filter(InvoiceRecord.id == invoice_id, InvoiceRecord.is_deleted == "N")
            .first()
        )
        return self._to_pydantic(record) if record else None

    def search_invoices(self, db: Session, query: HistoryQuery) -> HistoryResponse:
        q = db.query(InvoiceRecord).filter(InvoiceRecord.is_deleted == "N")
        if query.search:
            term = "%" + query.search + "%"
            q = q.filter(or_(
                InvoiceRecord.vendor_name.ilike(term),
                InvoiceRecord.invoice_number.ilike(term),
                InvoiceRecord.file_name.ilike(term),
                InvoiceRecord.vendor_iban.ilike(term),
            ))
        if query.date_from:
            q = q.filter(InvoiceRecord.invoice_date >= query.date_from)
        if query.date_to:
            q = q.filter(InvoiceRecord.invoice_date <= query.date_to)
        if query.amount_min is not None:
            q = q.filter(InvoiceRecord.total >= query.amount_min)
        if query.amount_max is not None:
            q = q.filter(InvoiceRecord.total <= query.amount_max)
        if query.currency:
            q = q.filter(InvoiceRecord.currency == query.currency.upper())
        if query.source_type:
            q = q.filter(InvoiceRecord.source_type == query.source_type)
        total_count = q.count()
        sort_column = getattr(InvoiceRecord, query.sort_by, InvoiceRecord.created_at)
        q = q.order_by(asc(sort_column) if query.sort_dir == "asc" else desc(sort_column))
        page_size = min(query.page_size, 100)
        offset = (query.page - 1) * page_size
        records = q.offset(offset).limit(page_size).all()
        total_pages = math.ceil(total_count / page_size) if page_size > 0 else 0
        return HistoryResponse(
            invoices=[self._to_pydantic(r) for r in records],
            total_count=total_count,
            page=query.page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def check_duplicate(self, db: Session, file_hash: str) -> Optional[InvoiceData]:
        record = (
            db.query(InvoiceRecord)
            .filter(InvoiceRecord.file_hash == file_hash, InvoiceRecord.is_deleted == "N")
            .first()
        )
        return self._to_pydantic(record) if record else None

    def update_invoice(self, db: Session, invoice_id: str, updates: InvoiceUpdate) -> Optional[InvoiceData]:
        record = (
            db.query(InvoiceRecord)
            .filter(InvoiceRecord.id == invoice_id, InvoiceRecord.is_deleted == "N")
            .first()
        )
        if not record:
            return None
        update_data = updates.model_dump(exclude_unset=True)
        for field_name, value in update_data.items():
            if hasattr(record, field_name):
                setattr(record, field_name, value)
        if update_data:
            record.source_type = "manual"
            record.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(record)
        return self._to_pydantic(record)

    def delete_invoice(self, db: Session, invoice_id: str) -> bool:
        record = db.query(InvoiceRecord).filter(InvoiceRecord.id == invoice_id).first()
        if not record:
            return False
        record.is_deleted = "Y"
        record.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True

    def delete_batch(self, db: Session, invoice_ids: List[str]) -> int:
        count = (
            db.query(InvoiceRecord)
            .filter(InvoiceRecord.id.in_(invoice_ids))
            .update(
                {InvoiceRecord.is_deleted: "Y", InvoiceRecord.updated_at: datetime.now(timezone.utc)},
                synchronize_session="fetch",
            )
        )
        db.commit()
        return count

    def get_dashboard_stats(self, db: Session) -> DashboardStats:
        active = db.query(InvoiceRecord).filter(InvoiceRecord.is_deleted == "N")
        total_invoices = active.count()
        total_chf = active.filter(InvoiceRecord.currency == "CHF").with_entities(
            func.coalesce(func.sum(InvoiceRecord.total), 0)).scalar()
        total_eur = active.filter(InvoiceRecord.currency == "EUR").with_entities(
            func.coalesce(func.sum(InvoiceRecord.total), 0)).scalar()
        total_vat = active.filter(InvoiceRecord.currency == "CHF").with_entities(
            func.coalesce(func.sum(InvoiceRecord.vat_amount), 0)).scalar()
        avg_conf = active.with_entities(
            func.coalesce(func.avg(InvoiceRecord.confidence_score), 0)).scalar()
        qr_count = active.filter(InvoiceRecord.source_type == "qr_bill").count()
        ocr_count = active.filter(InvoiceRecord.source_type == "ocr").count()
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        this_month = active.filter(InvoiceRecord.created_at >= month_start).count()
        top_vendors_raw = (
            active.filter(InvoiceRecord.vendor_name.isnot(None))
            .with_entities(
                InvoiceRecord.vendor_name,
                func.count(InvoiceRecord.id).label("count"),
                func.coalesce(func.sum(InvoiceRecord.total), 0).label("total"),
            )
            .group_by(InvoiceRecord.vendor_name)
            .order_by(desc("count"))
            .limit(5)
            .all()
        )
        top_vendors = [
            {"name": v[0], "invoice_count": v[1], "total_amount": round(float(v[2]), 2)}
            for v in top_vendors_raw
        ]
        return DashboardStats(
            total_invoices=total_invoices,
            total_amount_chf=round(float(total_chf), 2),
            total_amount_eur=round(float(total_eur), 2),
            total_vat_chf=round(float(total_vat), 2),
            avg_confidence=round(float(avg_conf), 1),
            qr_bill_count=qr_count,
            ocr_count=ocr_count,
            this_month_count=this_month,
            top_vendors=top_vendors,
        )

    def get_invoices_by_ids(self, db: Session, invoice_ids: List[str]) -> List[InvoiceData]:
        records = (
            db.query(InvoiceRecord)
            .filter(InvoiceRecord.id.in_(invoice_ids), InvoiceRecord.is_deleted == "N")
            .all()
        )
        return [self._to_pydantic(r) for r in records]
