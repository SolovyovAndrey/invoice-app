import pytest
from backend.services.extraction_service import ExtractionService

service = ExtractionService()


class TestSwissAmounts:
    def test_total_german(self):
        result = service.extract("Rechnungsbetrag CHF 1'234.56")
        assert result.total == 1234.56

    def test_total_french(self):
        result = service.extract("Montant total EUR 567.80")
        assert result.total == 567.80
        assert result.currency == "EUR"


class TestSwissDates:
    def test_german_date(self):
        result = service.extract("Rechnungsdatum: 15.03.2024")
        assert result.invoice_date == "15.03.2024"

    def test_due_date(self):
        result = service.extract("Zahlbar bis 30.04.2024")
        assert result.due_date == "30.04.2024"


class TestSwissIBAN:
    def test_valid_ch_iban(self):
        result = service.extract("IBAN: CH93 0076 2011 6238 5295 7")
        assert result.vendor_iban == "CH9300762011623852957"


class TestVAT:
    def test_mwst(self):
        result = service.extract("MwSt 8.1% CHF 100.05")
        assert result.vat_rate == 8.1
        assert result.vat_amount == 100.05

    def test_vat_uid(self):
        result = service.extract("CHE-123.456.789 MWST")
        assert result.vendor_vat_uid == "CHE-123.456.789"


class TestFullInvoice:
    def test_complete_german(self):
        text = """
        Muster AG
        Bahnhofstrasse 1
        8001 Zurich

        CHE-123.456.789 MWST

        Rechnung Nr: 2024-0042
        Rechnungsdatum: 01.06.2024
        Zahlbar bis: 30.06.2024

        IBAN: CH93 0076 2011 6238 5295 7

        Nettobetrag                    CHF  1'500.00
        MwSt 8.1%                      CHF    121.50
        Gesamtbetrag                   CHF  1'621.50
        """
        result = service.extract(text)
        assert result.vendor_name == "Muster AG"
        assert result.invoice_number == "2024-0042"
        assert result.invoice_date == "01.06.2024"
        assert result.total == 1621.50
        assert result.vendor_iban == "CH9300762011623852957"
