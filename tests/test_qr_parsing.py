import pytest

try:
    from pyzbar.pyzbar import decode as decode_qr
    PYZBAR_AVAILABLE = True
except (ImportError, FileNotFoundError):
    PYZBAR_AVAILABLE = False

from backend.services.qr_service import QrService

service = QrService()
python -m pytest tests/ -v

@pytest.mark.skipif(not PYZBAR_AVAILABLE, reason="pyzbar/ZBar not installed")
class TestQrParsing:
    def test_rejects_non_spc(self):
        assert service._parse_swiss_qr("NOT_QR\ndata") is None

    def test_rejects_short_payload(self):
        assert service._parse_swiss_qr("SPC\n0200\n1") is None

    def test_parses_valid_payload(self):
        lines = ["SPC","0200","1","CH4431999123000889012",
                 "S","Max Muster","Musterstr","123","8000","Zurich","CH",
                 "","","","","","","",
                 "1949.75","CHF",
                 "S","Simon Muster","Musterstr","1","8000","Zurich",
                 "QRR","210000000003139471430009017","Invoice 123","EPD"]
        payload = "\n".join(lines)
        result = service._parse_swiss_qr(payload)
        assert result is not None
        assert result.total == 1949.75
        assert result.currency == "CHF"
        assert result.vendor_name == "Max Muster"


# These tests always run (no pyzbar needed - just string parsing)
class TestQrParsingLogic:
    def test_rejects_non_spc(self):
        assert service._parse_swiss_qr("NOT_QR\ndata") is None

    def test_rejects_short(self):
        assert service._parse_swiss_qr("SPC\n0200\n1") is None