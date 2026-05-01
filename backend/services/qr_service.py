import logging
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
from PIL import Image
from pathlib import Path

from backend.models.invoice import InvoiceData, SourceType
from backend.utils.image_preprocessing import pdf_to_images, extract_qr_region

logger = logging.getLogger(__name__)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class SwissEntity:
    name: str = ""
    street: str = ""
    building_nr: str = ""
    postal_code: str = ""
    city: str = ""
    country: str = "CH"

    @property
    def full_address(self) -> str:
        line1 = f"{self.street} {self.building_nr}".strip()
        line2 = f"{self.postal_code} {self.city}".strip()
        return ", ".join(p for p in [line1, line2] if p)


@dataclass
class SwissInvoiceEntities:
    creditor: SwissEntity = field(default_factory=SwissEntity)
    debtor: SwissEntity = field(default_factory=SwissEntity)
    iban: str = ""
    amount: str = ""
    currency: str = ""
    reference: str = ""
    source: str = "unknown"  # "qr" | "ocr"


# ── QR Service ────────────────────────────────────────────────────────────────

class QrService:
    """
    Extracts structured data from Swiss QR-bill invoices (SIX standard v2.2).
    Uses OpenCV only — fully offline, no pyzbar dependency.

    Scan order per page:
      1. Cropped QR region  (fastest, least noise)
      2. Full image (grayscale + threshold variants)
    """

    # Max dimension before we downscale (QR doesn't need 4000px+)
    _MAX_DECODE_SIZE = 1500

    def __init__(self):
        # Reuse one detector instance (avoid re-allocation per call)
        self._detector = cv2.QRCodeDetector()

        # Use the newer Aruco-based detector if available (OpenCV ≥ 4.8)
        # It's significantly better at finding QR codes in noisy images
        self._multi_detector: Optional[cv2.QRCodeDetector] = None
        if hasattr(cv2, "QRCodeDetectorAruco"):
            self._multi_detector = cv2.QRCodeDetectorAruco()
            logger.info("Using QRCodeDetectorAruco (OpenCV ≥ 4.8)")
        else:
            logger.info("Using classic QRCodeDetector")

    # ── Public API ────────────────────────────────────────────────────────

    def try_extract(self, file_path: Path) -> Optional[InvoiceData]:
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

    # ── Image scanning pipeline ───────────────────────────────────────────

    def _scan_image(self, image: Image.Image) -> Optional[InvoiceData]:
        """Try multiple strategies, return on first success."""

        # Strategy 1 — Cropped QR region (fastest path)
        qr_region = extract_qr_region(image)
        if qr_region:
            cv_region = self._pil_to_cv(qr_region)
            result = self._decode_pipeline(cv_region)
            if result:
                return result

        # Strategy 2 — Full image pipeline
        cv_full = self._pil_to_cv(image)
        result = self._decode_pipeline(cv_full)
        if result:
            return result

        return None

    def _decode_pipeline(self, cv_image: np.ndarray) -> Optional[InvoiceData]:
        """
        Run decode attempts in order of speed.
        Each step is cheap; we short-circuit on first success.
        """

        # Downscale large images (QR codes don't need high resolution)
        cv_image = self._maybe_downscale(cv_image)

        # ① Direct grayscale
        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY) \
            if len(cv_image.shape) == 3 else cv_image

        result = self._try_decode(gray)
        if result:
            return result

        # ② Otsu binary threshold
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        result = self._try_decode(otsu)
        if result:
            return result

        # ③ Adaptive threshold (handles uneven lighting / shadows)
        adaptive = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 51, 11,
        )
        result = self._try_decode(adaptive)
        if result:
            return result

        # ④ Sharpened (useful for blurry scans)
        sharp_kernel = np.array([[0, -1, 0],
                                  [-1, 5, -1],
                                  [0, -1, 0]])
        sharpened = cv2.filter2D(gray, -1, sharp_kernel)
        result = self._try_decode(sharpened)
        if result:
            return result

        # ⑤ Inverted (white-on-black QR)
        result = self._try_decode(cv2.bitwise_not(gray))
        if result:
            return result

        return None

    # ── Core decoder ──────────────────────────────────────────────────────

    def _try_decode(self, cv_image: np.ndarray) -> Optional[InvoiceData]:
        """Attempt QR decode with both detectors."""
        try:
            # Primary: Aruco-based detector (better accuracy)
            if self._multi_detector is not None:
                ok, decoded_list = self._multi_detector.detectAndDecodeMulti(cv_image)[:2]
                if ok and decoded_list is not None:
                    for data in decoded_list:
                        if data:
                            parsed = self._parse_swiss_qr(data)
                            if parsed:
                                return parsed

            # Fallback: classic detector
            data, bbox, _ = self._detector.detectAndDecode(cv_image)
            if data:
                return self._parse_swiss_qr(data)

        except Exception as e:
            logger.debug(f"QR decode attempt failed: {e}")

        return None

    # ── Swiss QR-bill parsing (SIX standard v2.2) ─────────────────────────

    def _parse_swiss_qr(self, raw_data: str) -> Optional[InvoiceData]:
        """
        Swiss QR-bill payload — fixed line positions (0-indexed):

          0   SPC                    header
          1   0200                   version
          2   1                      coding (UTF-8)
          3   IBAN
          4   S / K                  creditor address type
          5   creditor name
          6   creditor street / addr line 1
          7   creditor building nr / addr line 2
          8   creditor postal code
          9   creditor city
          10  creditor country
          11-17                      ultimate creditor (usually all empty)
          18  amount
          19  currency
          20  S / K / empty          debtor address type
          21  debtor name
          22  debtor street / addr line 1
          23  debtor building nr / addr line 2
          24  debtor postal code
          25  debtor city
          26  debtor country
          27  QRR / SCOR / NON       reference type
          28  reference number
          29  additional message
          30  EPD
          31  trailer
        """
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

            # Creditor (lines 4–10)
            creditor = self._parse_entity(lines, start=4)

            # Amount + currency (lines 18–19)
            amount_str = get(18)
            currency   = get(19)

            # Debtor (lines 20–26)
            debtor = self._parse_entity(lines, start=20)

            # Reference (lines 27–29)
            ref_type  = get(27)
            reference = get(28)
            message   = get(29)

            total: Optional[float] = None
            if amount_str:
                try:
                    total = float(amount_str)
                except ValueError:
                    pass

            logger.info(
                "QR parsed | creditor=%s  debtor=%s  iban=%s  total=%s %s",
                creditor["name"], debtor["name"], iban, total, currency,
            )

            return InvoiceData(
                source_type=SourceType.QR_BILL,
                confidence_score=99.0,
                # Creditor
                vendor_name=creditor["name"],
                vendor_address=creditor["address"],
                vendor_iban=iban or None,
                # Debtor
                debtor_name=debtor["name"],
                debtor_address=debtor["address"],
                # Financials
                currency=currency or "CHF",
                total=total,
                # Reference
                reference_number=reference if ref_type == "QRR" else None,
                creditor_reference=reference if ref_type == "SCOR" else None,
                # Raw
                raw_text=raw_data,
            )

        except (IndexError, ValueError):
            return None

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _pil_to_cv(image: Image.Image) -> np.ndarray:
        """PIL Image → OpenCV BGR numpy array."""
        if image.mode == "L":
            return np.array(image)
        if image.mode != "RGB":
            image = image.convert("RGB")
        return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

    def _maybe_downscale(self, cv_image: np.ndarray) -> np.ndarray:
        """Downscale if larger than _MAX_DECODE_SIZE (faster decode)."""
        h, w = cv_image.shape[:2]
        max_dim = max(h, w)
        if max_dim > self._MAX_DECODE_SIZE:
            scale = self._MAX_DECODE_SIZE / max_dim
            new_w = int(w * scale)
            new_h = int(h * scale)
            return cv2.resize(cv_image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        return cv_image

    @staticmethod
    def _parse_entity(lines: list, start: int) -> dict:
        """
        Parse one creditor/debtor block.

        S (structured):  name | street | building nr | postal | city | country
        K (combined):    name | addr line 1 | addr line 2 | (empty) | (empty) | country
        """
        def get(i: int) -> str:
            return lines[i].strip() if i < len(lines) else ""

        addr_type = get(start)
        name      = get(start + 1) or None
        country   = get(start + 6)

        if addr_type == "S":
            street   = get(start + 2)
            building = get(start + 3)
            postal   = get(start + 4)
            city     = get(start + 5)
            parts = [
                f"{street} {building}".strip(),
                f"{postal} {city}".strip(),
                country,
            ]
        else:  # K (combined) or empty/unknown
            parts = [get(start + 2), get(start + 3), country]

        address = ", ".join(p for p in parts if p) or None
        return {"name": name, "address": address}