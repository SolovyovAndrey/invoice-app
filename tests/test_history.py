import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.services.history_service import HistoryService
from backend.models.invoice import InvoiceData, SourceType, HistoryQuery, InvoiceUpdate

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
service = HistoryService()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _make(vendor="Test AG", total=1000.0):
    return InvoiceData(
        file_name="test.pdf", vendor_name=vendor,
        total=total, currency="CHF", source_type=SourceType.OCR,
        confidence_score=75.0,
    )


class TestSaveAndGet:
    def test_save_and_retrieve(self):
        db = TestSession()
        saved = service.save_invoice(db, _make())
        assert saved.id is not None
        found = service.get_invoice(db, saved.id)
        assert found.vendor_name == "Test AG"
        db.close()

    def test_duplicate_check(self):
        db = TestSession()
        inv = _make()
        inv.file_hash = "abc123"
        service.save_invoice(db, inv)
        assert service.check_duplicate(db, "abc123") is not None
        assert service.check_duplicate(db, "other") is None
        db.close()


class TestSearch:
    def test_search_by_vendor(self):
        db = TestSession()
        service.save_invoice(db, _make("Alpha AG"))
        service.save_invoice(db, _make("Beta GmbH"))
        result = service.search_invoices(db, HistoryQuery(search="Alpha"))
        assert result.total_count == 1
        db.close()


class TestUpdateDelete:
    def test_update(self):
        db = TestSession()
        saved = service.save_invoice(db, _make())
        updated = service.update_invoice(db, saved.id, InvoiceUpdate(vendor_name="New Name"))
        assert updated.vendor_name == "New Name"
        db.close()

    def test_soft_delete(self):
        db = TestSession()
        saved = service.save_invoice(db, _make())
        assert service.delete_invoice(db, saved.id)
        assert service.get_invoice(db, saved.id) is None
        db.close()
