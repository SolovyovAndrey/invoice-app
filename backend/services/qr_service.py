from PIL import Image
from pathlib import Path
from typing import Optional
from backend.models.invoice import InvoiceData, SourceType
from backend.utils.image_preprocessing import pdf_to_images, extract_qr_region

try:
    from pyzbar.pyzbar import decode as decode_qr
    PYZBAR_AVAILABLE = True
except (ImportError, FileNotFoundError):
    PYZBAR_AVAILABLE = False
    print("[WARN] pyzbar not available - QR-bill scanning disabled")
    print("       Install ZBar: https://github.com/NaturalHistoryMuseum/pyzbar#installation")


class QrService:
    def try_extract(self, file_path: Path) -> Optional[InvoiceData]:
        if not PYZBAR_AVAILABLE:
            return None
        ext = file_path.suffix.lower()
        if ext == ".pdf":
            images = pdf_to_images(file_path, dpi=300)
        else:
            images = [Image.open(file_path)]
        for image in images:
            result = self._scan_image(image)
            if result:
                result.file_name = file_path.name
                return result
        return None

    def _scan_image(self, image: Image.Image) -> Optional[InvoiceData]:
        qr_region = extract_qr_region(image)
        if qr_region:
            result = self._try_decode(qr_region)
            if result:
                return result
        result = self._try_decode(image)
        if result:
            return result
        if image.mode != "L":
            result = self._try_decode(image.convert("L"))
            if result:
                return result
        return None

    def _try_decode(self, image: Image.Image) -> Optional[InvoiceData]:
        if not PYZBAR_AVAILABLE:
            return None
        try:
            codes = decode_qr(image)
        except Exception:
            return None
        for code in codes:
            raw = code.data.decode("utf-8", errors="ignore")
            result = self._parse_swiss_qr(raw)
            if result:
                return result
        return None

    def _parse_swiss_qr(self, raw_data: str) -> Optional[InvoiceData]:
        lines = raw_data.strip().split("\n")
        if len(lines) < 28:
            return None
        if lines[0].strip() != "SPC":
            return None
        if not lines[1].strip().startswith("02"):
            return None
        try:
            def get(index: int) -> str:
                return lines[index].strip() if index < len(lines) else ""

            iban = get(3)
            creditor_name = get(5)
            creditor_street = get(6)
            creditor_building = get(7)
            creditor_zip = get(8)
            creditor_city = get(9)
            creditor_country = get(10)
            amount_str = get(18)
            currency = get(19)
            ref_type = get(26)
            reference = get(27)
            message = get(28)

            address_parts = [
                p for p in [
                    creditor_street, creditor_building,
                    (creditor_zip + " " + creditor_city).strip(),
                    creditor_country,
                ] if p
            ]
            address = ", ".join(address_parts) if address_parts else None

            total = None
            if amount_str:
                try:
                    total = float(amount_str)
                except ValueError:
                    pass

            return InvoiceData(
                source_type=SourceType.QR_BILL,
                confidence_score=99.0,
                vendor_name=creditor_name or None,
                vendor_address=address,
                vendor_iban=iban or None,
                currency=currency or "CHF",
                total=total,
                reference_number=reference if ref_type == "QRR" else None,
                creditor_reference=reference if ref_type == "SCOR" else None,
                raw_text=raw_data,
            )
        except (IndexError, ValueError):
            return None