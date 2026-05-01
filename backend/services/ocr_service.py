# backend/services/ocr_service.py

import re
import pytesseract
from PIL import Image
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, List

import logging

from backend.config import config
from backend.models.invoice import InvoiceData, SourceType
from backend.services.qr_service import QrService, SwissEntity, SwissInvoiceEntities
from backend.utils.image_preprocessing import (
    preprocess_for_ocr,
    preprocess_for_ocr_aggressive,
    pdf_to_images,
)

logger = logging.getLogger(__name__)


class OcrService:
    """
    OCR service for Swiss invoices (hybrid QR + OCR extraction).

    Pipeline:
      1. Try QR decode → structured payment data
      2. Always run OCR → invoice details
      3. Merge both results (with smart recalculation)
    """

    def __init__(self):
        pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

        self.languages = config.TESSERACT_LANGUAGES
        self.tesseract_config = config.TESSERACT_CONFIG
        self.confidence_threshold = config.OCR_CONFIDENCE_THRESHOLD
        self.fallback_psm_modes = config.OCR_FALLBACK_PSM_MODES
        self.min_width = config.OCR_MIN_WIDTH
        self.dpi = config.OCR_DPI
        self.debug = config.OCR_DEBUG
        self.debug_dir = config.BASE_DIR / "debug_ocr"

        self._qr_service = QrService()

        logger.info(
            "OcrService init | lang=%s dpi=%d min_width=%d threshold=%.0f%%",
            self.languages, self.dpi, self.min_width, self.confidence_threshold,
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  PUBLIC API
    # ══════════════════════════════════════════════════════════════════════════

    def extract_text(self, file_path: Path) -> Tuple[str, float]:
        """Extract raw text + average confidence from a PDF or image file."""
        ext = file_path.suffix.lower()
        logger.info("Processing: %s (type=%s)", file_path.name, ext)

        if ext == ".pdf":
            return self._process_pdf(file_path)
        return self._process_image(file_path)

    def extract_invoice(self, file_path: Path) -> InvoiceData:
        """
        Full hybrid extraction:
          1. Try QR decode (payment data)
          2. Always run OCR (invoice details)
          3. Merge results with smart recalculation
        """

        # ── Step 1: QR extraction ────────────────────────────────────────
        qr_result = self._qr_service.try_extract(file_path)
        if qr_result:
            logger.info(
                "QR extracted | vendor=%s total=%s %s",
                qr_result.vendor_name, qr_result.total, qr_result.currency,
            )

        # ── Step 2: OCR extraction (always run) ─────────────────────────
        text, confidence = self.extract_text(file_path)
        ocr_fields = self._extract_fields_from_text(text)

        logger.info(
            "OCR extracted | invoice_no=%s date=%s subtotal=%s vat_rate=%s "
            "vat_amount=%s debtor=%s",
            ocr_fields.get("invoice_number"),
            ocr_fields.get("invoice_date"),
            ocr_fields.get("subtotal"),
            ocr_fields.get("vat_rate"),
            ocr_fields.get("vat_amount"),
            ocr_fields.get("debtor_name"),
        )

        # ── Step 3: Merge ───────────────────────────────────────────────
        if qr_result:
            return self._merge_qr_and_ocr(qr_result, ocr_fields, text, confidence)

        # No QR — build from OCR only
        return InvoiceData(
            source_type=SourceType.OCR,
            confidence_score=confidence,
            file_name=file_path.name,
            vendor_name=ocr_fields.get("vendor_name"),
            vendor_address=ocr_fields.get("vendor_address"),
            vendor_iban=ocr_fields.get("iban"),
            vendor_vat_uid=ocr_fields.get("vendor_vat_uid"),
            debtor_name=ocr_fields.get("debtor_name"),
            debtor_address=ocr_fields.get("debtor_address"),
            invoice_number=ocr_fields.get("invoice_number"),
            invoice_date=ocr_fields.get("invoice_date"),
            client_number=ocr_fields.get("client_number"),
            currency=ocr_fields.get("currency", "CHF"),
            subtotal=ocr_fields.get("subtotal"),
            vat_rate=ocr_fields.get("vat_rate"),
            vat_amount=ocr_fields.get("vat_amount"),
            total=ocr_fields.get("total"),
            reference_number=ocr_fields.get("reference_number"),
            raw_text=text,
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  MERGE QR + OCR
    # ══════════════════════════════════════════════════════════════════════════

    def _merge_qr_and_ocr(
        self,
        qr: InvoiceData,
        ocr: Dict[str, Any],
        raw_text: str,
        ocr_confidence: float,
    ) -> InvoiceData:
        """
        QR provides: IBAN, creditor, total, currency, reference
        OCR fills:   invoice details, debtor, VAT breakdown

        DEBTOR: OCR wins — QR has the "payer" which can differ from
        the invoice recipient shown in the address window.

        AMOUNTS: Recalculated after merge so QR total can help fill
        missing subtotal/vat_rate.
        """

        # ── Collect amounts from both sources ────────────────────────────
        total = qr.total or ocr.get("total")
        subtotal = ocr.get("subtotal")
        vat_amount = ocr.get("vat_amount")
        vat_rate = ocr.get("vat_rate")

        # ── Recalculate missing amounts using merged data ────────────────
        if total and vat_amount and not subtotal:
            subtotal = round(total - vat_amount, 2)
            logger.debug("Calculated subtotal: %.2f (total - vat)", subtotal)

        if total and subtotal and not vat_amount:
            vat_amount = round(total - subtotal, 2)
            logger.debug("Calculated vat_amount: %.2f (total - subtotal)", vat_amount)

        if subtotal and vat_amount and not total:
            total = round(subtotal + vat_amount, 2)
            logger.debug("Calculated total: %.2f (subtotal + vat)", total)

        if not vat_rate and subtotal and vat_amount and subtotal > 0:
            rate = round((vat_amount / subtotal) * 100, 2)
            swiss_rates = {8.1, 2.6, 3.8, 7.7, 2.5, 3.7}
            closest = min(swiss_rates, key=lambda r: abs(r - rate))
            if abs(closest - rate) < 0.5:
                rate = closest
            vat_rate = rate
            logger.debug("Calculated vat_rate: %.1f%%", vat_rate)

        return InvoiceData(
            source_type=SourceType.HYBRID,
            confidence_score=qr.confidence_score,
            file_name=qr.file_name,

            # Creditor — QR wins (structured, reliable)
            vendor_name=qr.vendor_name or ocr.get("vendor_name"),
            vendor_address=qr.vendor_address or ocr.get("vendor_address"),
            vendor_iban=qr.vendor_iban or ocr.get("iban"),
            vendor_vat_uid=ocr.get("vendor_vat_uid"),

            # Debtor — OCR wins (invoice body = billing recipient;
            # QR "debtor" = payer, which can be a different person)
            debtor_name=ocr.get("debtor_name") or qr.debtor_name,
            debtor_address=ocr.get("debtor_address") or qr.debtor_address,

            # Invoice details — OCR only (never in QR)
            invoice_number=ocr.get("invoice_number"),
            invoice_date=ocr.get("invoice_date"),
            client_number=ocr.get("client_number"),

            # Amounts — merged + recalculated
            currency=qr.currency or ocr.get("currency", "CHF"),
            subtotal=subtotal,
            vat_rate=vat_rate,
            vat_amount=vat_amount,
            total=total,

            # Reference — QR wins
            reference_number=qr.reference_number or ocr.get("reference_number"),
            creditor_reference=qr.creditor_reference,

            # Raw
            raw_text=raw_text,
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  OCR FIELD EXTRACTION (regex)
    # ══════════════════════════════════════════════════════════════════════════

    def _extract_fields_from_text(self, text: str) -> Dict[str, Any]:
        """Extract structured fields from OCR text using regex."""
        fields: Dict[str, Any] = {}

        # ── Invoice number ───────────────────────────────────────────────
        patterns_invoice_no = [
            # With N°/Nr/# separator
            r"(?:Bordereau|Facture|Invoice)\s*(?:N[°o.]?|Nr\.?|#)\s*[:.]?\s*(\d[\d\-/\.]+)",
            r"(?:Rechnung|Beleg)\s*(?:N[°o.]?|Nr\.?|#)\s*[:.]?\s*(\d[\d\-/\.]+)",
            r"(?:Rechnungs(?:nummer|nr)\.?)\s*[:.]?\s*(\d[\d\-/\.]+)",
            r"(?:N[°o]\.?\s*(?:de\s+)?(?:facture|bordereau))\s*[:.]?\s*(\d[\d\-/\.]+)",
            r"Affaire\s+N\s*[°ºo\.]?\s*:?\s*(\d[\d\-/\.]+)",
            r"Affaire\s+[Nn][ro°º]?\.?\s*:?\s*(\d[\d\-/\.]+)",
            r"(?i)notification\s*N[°ºo.]?\s*[:.]?\s*(\d+(?:\s+\d+)+)",
            r"(?i)Bulletin\s+AO\s*[:.]?\s*(\d+(?:\s+\d+)*)",
            # Without separator: "Facture 242736" or "Bordereau 509616"
            r"(?:Facture|Bordereau|Invoice|Rechnung)\s+(\d{5,})",
        ]
        fields["invoice_number"] = self._first_match(text, patterns_invoice_no)

        # ── Invoice date ─────────────────────────────────────────────────
        patterns_date = [
            r"(?:Factur[ée]\s+le|Date\s+(?:de\s+)?facture)\s*[:.]?\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
            r"(?:Rechnungsdatum|Belegdatum)\s*[:.]?\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
            r"(?:Invoice\s+date|Date)\s*[:.]?\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
        ]
        fields["invoice_date"] = self._first_match(text, patterns_date)

        # ── Due date ─────────────────────────────────────────────────────
        patterns_due = [
            r"[EÉeé]ch[ée]ance\s*(?:le)?\s*[:.]?\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
            r"(?:F[äa]llig(?:\s+am)?|Zahlbar\s+bis)\s*[:.]?\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
            r"(?:Due\s+date|Payment\s+due)\s*[:.]?\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
        ]
        fields["due_date"] = self._first_match(text, patterns_due)

        # ── Client number ────────────────────────────────────────────────
        patterns_client = [
            r"(?:N[°o]\.?\s*client|Client\s*(?:N[°o]\.?|Nr\.?))\s*[:.]?\s*(\d+)",
            r"(?:Kunden(?:nummer|nr)\.?|Kd\.?\s*Nr\.?)\s*[:.]?\s*(\d+)",
            r"(?:Customer\s*(?:No\.?|#|ID))\s*[:.]?\s*(\d+)",
        ]
        fields["client_number"] = self._first_match(text, patterns_client)

        # ── VAT UID ──────────────────────────────────────────────────────
        patterns_vat_uid = [
            r"(CHE[- ]?\d{3}[. ]?\d{3}[. ]?\d{3})\s*(?:MWST|TVA|IVA)",
            r"(?:N[°o]?\s*TVA|UID|MWST[- ]?Nr\.?)\s*:?\s*(CHE[- ]?\d{3}[. ]?\d{3}[. ]?\d{3})",
        ]
        uid = self._first_match(text, patterns_vat_uid)
        if uid:
            fields["vendor_vat_uid"] = re.sub(r"[.\s]", "", uid)

        # ── IBAN ─────────────────────────────────────────────────────────
        m = re.search(r"(CH\d{2}\s*[\d\s]{18,25})", text)
        if m:
            fields["iban"] = re.sub(r"\s", "", m.group(1))

        # ── Debtor ───────────────────────────────────────────────────────
        self._extract_debtor(text, fields)

        # ── Creditor ─────────────────────────────────────────────────────
        self._extract_creditor(text, fields)

        # ── Amounts ──────────────────────────────────────────────────────
        self._extract_amounts(text, fields)

                # ── Fallback: find any date pattern not already used ─────────────
        if not fields.get("invoice_date"):
            # Look for all dates in format DD.MM.YYYY
            all_dates = re.findall(r"(\d{2}\.\d{2}\.\d{4})", text)
            due = fields.get("due_date")
            period = fields.get("period", "")
            for d in all_dates:
                # Skip if it's the due date or part of period
                if d == due:
                    continue
                if period and d in period:
                    continue
                # Skip regulation dates (very old)
                year = int(d.split(".")[-1])
                if year < 2020:
                    continue
                fields["invoice_date"] = d
                logger.debug("Invoice date fallback: %s", d)
                break

        return fields

    # ══════════════════════════════════════════════════════════════════════════
    #  DEBTOR EXTRACTION
    # ══════════════════════════════════════════════════════════════════════════

    def _extract_debtor(self, text: str, fields: Dict[str, Any]) -> None:
        """
        Extract debtor/recipient. Priority order:
          1. Invoice body address window (who the invoice is addressed to)
          2. Payment slip "Zahlbar durch" / "Payable par" (LAST match)
          3. Labeled sections ("Rechnungsadresse" etc.)
        """

        vendor = fields.get("vendor_name", "").lower()

        # ── Strategy 1: Invoice body address block ───────────────────────
        # After "Frau/Herr/Firma" label → Name + Street + PostalCity
        body_patterns = [
            # After salutation: "Frau\nTETIANA SHEVCHENKO\nRue...\n1530 Payerne"
            (
                r"(?:Frau|Herr|Firma|Madame|Monsieur)\s*\n"
                r"\s*(.+?)\n"
                r"\s*(.+?\d{1,4}[A-Za-z]?)\s*\n"
                r"\s*(\d{4}\s+[A-Za-zÀ-ü\s\-]+)"
            ),
            # Company with legal form: "Novaris Solutions Sarl\nRue...\n1458 Montclair"
            (
                r"([A-ZÀ-Ü][A-Za-zÀ-ü\s\.\-&]+?"
                r"(?:Sàrl|Sarl|SARL|SA|AG|GmbH|S\.A\.|LLC|Srl|SRL))\s*\n"
                r"\s*([A-Za-zÀ-ü][\w\s\.\-\']+\s+\d{1,4}[A-Za-z]?)\s*\n"
                r"\s*(\d{4}\s+[A-Za-zÀ-ü\s\-]+)"
            ),
        ]

        for pattern in body_patterns:
            for m in re.finditer(pattern, text, re.MULTILINE):
                name = m.group(1).strip()
                # Skip if this IS the vendor
                if vendor and name.lower().startswith(vendor[:10]):
                    continue
                if len(name) < 3:
                    continue
                fields["debtor_name"] = name
                fields["debtor_address"] = (
                    f"{m.group(2).strip()}, {m.group(3).strip()}"
                )
                logger.debug(
                    "Debtor from invoice body: %s | %s",
                    name, fields["debtor_address"],
                )
                return

        # ── Strategy 2: Payment slip — LAST match ────────────────────────
        # Last = Zahlteil section (more reliable than Empfangsschein)
        slip_patterns = [
            r"Zahlbar\s+durch\s*\n\s*(.+?)\n\s*(.+?)\n\s*(\d{4}\s+.+?)(?:\n|$)",
            r"Payable\s+par\s*\n\s*(.+?)\n\s*(.+?)\n\s*(\d{4}\s+.+?)(?:\n|$)",
        ]

        last_match = None
        for pattern in slip_patterns:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                name = m.group(1).strip()
                if (
                    re.match(r"^[\d\s]+$", name)
                    or name.startswith("CH")
                    or len(name) < 3
                ):
                    continue
                # Skip vendor
                if vendor and name.lower().startswith(vendor[:10]):
                    continue
                last_match = m

        if last_match:
            fields["debtor_name"] = last_match.group(1).strip()
            street = last_match.group(2).strip()
            postal_city = last_match.group(3).strip()
            fields["debtor_address"] = f"{street}, {postal_city}"
            logger.debug(
                "Debtor from payment slip: %s", fields["debtor_name"]
            )
            return

        # ── Strategy 3: Labeled sections ─────────────────────────────────
        labeled_patterns = [
            (
                r"(?:Rechnungsadresse|Lieferadresse|Empf[äa]nger)\s*:?\s*\n"
                r"\s*(.+?)\n\s*(.+?)\n\s*(\d{4}\s+.+?)(?:\n|$)"
            ),
            (
                r"(?:Adresse\s+de\s+facturation|Destinataire)\s*:?\s*\n"
                r"\s*(.+?)\n\s*(.+?)\n\s*(\d{4}\s+.+?)(?:\n|$)"
            ),
        ]

        for pattern in labeled_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                if len(name) >= 3 and not name.startswith("CH"):
                    fields["debtor_name"] = name
                    fields["debtor_address"] = (
                        f"{m.group(2).strip()}, {m.group(3).strip()}"
                    )
                    logger.debug(
                        "Debtor from label: %s", fields["debtor_name"]
                    )
                    return

    # ══════════════════════════════════════════════════════════════════════════
    #  CREDITOR EXTRACTION
    # ══════════════════════════════════════════════════════════════════════════

    def _extract_creditor(self, text: str, fields: Dict[str, Any]) -> None:
        """Extract creditor from payment slip."""
        patterns = [
            (
                r"Compte\s*/\s*Payable\s+[àa]\s*\n"
                r"(?:CH[\d\s]{10,30}\n)?"
                r"(.+?)\n(\d{4}\s+.+?)(?:\n|$)"
            ),
            (
                r"Konto\s*/\s*Zahlbar\s+an\s*\n"
                r"(?:CH[\d\s]{10,30}\n)?"
                r"(.+?)\n(\d{4}\s+.+?)(?:\n|$)"
            ),
        ]

        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                fields.setdefault("vendor_name", m.group(1).strip())
                fields.setdefault("vendor_address", m.group(2).strip())
                return

    # ══════════════════════════════════════════════════════════════════════════
    #  AMOUNT EXTRACTION
    # ══════════════════════════════════════════════════════════════════════════

    def _extract_amounts(self, text: str, fields: Dict[str, Any]) -> None:
        """Extract subtotal, VAT rate, VAT amount, total."""

        # ── Currency ─────────────────────────────────────────────────────
        fields["currency"] = "EUR" if re.search(r"\bEUR\b", text) else "CHF"

        # ── Total (same-line only) ───────────────────────────────────────
        total_patterns = [
            r"Total\s+(?:bordereau|TTC|facture|[àa]\s+payer|g[ée]n[ée]ral)[^\n]*?([\d']+\.\d{2})",
            r"Total\s+bordereau[^\n]*?([\d']+\.\d{2})",
            r"Endbetrag[^\n]*?([\d']+\.\d{2})",
            r"(?:Gesamtbetrag|Rechnungsbetrag)[^\n]*?([\d']+\.\d{2})",
            r"Montant\s+CHF\s+incl\.?[^\n]+([\d']+\.\d{2})",
            # "A payer ... 496.75" (on same line)
            r"[àaA]\s+payer[^\n]*?([\d']+\.\d{2})",
        ]
        fields["total"] = self._first_amount(text, total_patterns)

        # ── Subtotal (same-line only) ────────────────────────────────────
        subtotal_patterns = [
            r"(?:Montant\s+(?:HT|hors\s+taxe)|Total\s+HT|Sous[- ]total|Subtotal)[^\n]*?([\d']+\.\d{2})",
            r"Summe\s+Netto[^\n]*?([\d']+\.\d{2})",
            r"(?:Nettobetrag|Betrag\s+(?:exkl|ohne\s+MwSt)\.?)[^\n]*?([\d']+\.\d{2})",
            r"Montant\s+CHF\s+excl\.?[^\n]+([\d']+\.\d{2})",
            # "Valeur 459.54"
            r"\bValeur\b[^\n]*?([\d']+\.\d{2})",
        ]
        fields["subtotal"] = self._first_amount(text, subtotal_patterns)

        # ── VAT rate ─────────────────────────────────────────────────────
        vat_rate_patterns = [
            r"(?:Taux\s+(?:TVA|T\.V\.A\.?))\s*[:.]?\s*(\d{1,2}[.,]\d{1,2})\s*%?",
            r"(?:MwSt\.?|MWST)\s*[:.]?\s*(\d{1,2}[.,]\d{1,2})\s*%",
            r"CHF\s+(\d{1,2}[.,]\d{1,2})\s*%",
            r"Steuersatz[^\n]*\n\s*(\d{1,2}[.,]\d{1,2})\s*%",
            r"(?:TVA|T\.V\.A\.?)\s*[:.]?\s*(\d{1,2}[.,]\d{1,2})\s*%",
            # "8.10%" standalone at start of recap line
            r"^\s*(\d{1,2}[.,]\d{1,2})%\s+[\d']+\.\d{2}\s+CHF",
        ]
        rate_str = self._first_match(text, vat_rate_patterns)
        if rate_str:
            fields["vat_rate"] = self._parse_float(rate_str)

        # ── VAT amount (same-line only) ──────────────────────────────────
        vat_amount_patterns = [
            r"(?:TVA|T\.V\.A\.?)\s+CHF[^\n]*?([\d']+\.\d{2})",
            r"(?:Montant\s+(?:TVA|T\.V\.A\.?))[^\n]*?([\d']+\.\d{2})",
            r"Summe\s+MwSt[^\n]*?([\d']+\.\d{2})",
            r"(?:MwSt\.?|MWST)\s*(?:CHF)?[^\n]*?([\d']+\.\d{2})",
            # "TVA 37.21" (bare TVA followed by amount)
            r"\bTVA\b\s+(\d[\d']*\.\d{2})",
        ]
        fields["vat_amount"] = self._first_amount(text, vat_amount_patterns)

        # ── Recap table parser ───────────────────────────────────────────
        self._parse_recap_table(text, fields)

        # ── Smart fallback ───────────────────────────────────────────────
        self._calculate_missing_amounts(fields)

    def _calculate_missing_amounts(self, fields: Dict[str, Any]) -> None:
        """If 2 of 3 (subtotal, vat_amount, total) exist, calculate the third."""
        subtotal = fields.get("subtotal")
        vat_amount = fields.get("vat_amount")
        total = fields.get("total")

        if subtotal and vat_amount and not total:
            fields["total"] = round(subtotal + vat_amount, 2)
            logger.debug("Calculated total: %s", fields["total"])

        if total and vat_amount and not subtotal:
            fields["subtotal"] = round(total - vat_amount, 2)
            logger.debug("Calculated subtotal: %s", fields["subtotal"])

        if total and subtotal and not vat_amount:
            fields["vat_amount"] = round(total - subtotal, 2)
            logger.debug("Calculated vat_amount: %s", fields["vat_amount"])

        # Calculate VAT rate from amounts
        subtotal = fields.get("subtotal")
        vat_amount = fields.get("vat_amount")
        if not fields.get("vat_rate") and subtotal and vat_amount and subtotal > 0:
            rate = round((vat_amount / subtotal) * 100, 2)
            swiss_rates = {8.1, 2.6, 3.8, 7.7, 2.5, 3.7}
            closest = min(swiss_rates, key=lambda r: abs(r - rate))
            if abs(closest - rate) < 0.5:
                rate = closest
            fields["vat_rate"] = rate
            logger.debug("Calculated vat_rate: %.1f%%", rate)

    # ══════════════════════════════════════════════════════════════════════════
    #  REGEX HELPERS
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _first_match(text: str, patterns: list) -> Optional[str]:
        """Return first regex match from a list of patterns, or None."""
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if m:
                return m.group(1).strip()
        return None

    @staticmethod
    def _parse_float(value: str) -> Optional[float]:
        """Parse "129.50" or "1'234.50" or "129,50" to float."""
        if not value:
            return None
        try:
            cleaned = re.sub(r"[\s']", "", value).replace(",", ".")
            return float(cleaned)
        except ValueError:
            return None

    def _first_amount(self, text: str, patterns: list) -> Optional[float]:
        """Return first matched amount as float."""
        raw = self._first_match(text, patterns)
        return self._parse_float(raw)

    # ══════════════════════════════════════════════════════════════════════════
    #  PDF / IMAGE PROCESSING
    # ══════════════════════════════════════════════════════════════════════════

    def _process_pdf(self, pdf_path: Path) -> Tuple[str, float]:
        """Convert PDF to images and OCR each page."""
        images = pdf_to_images(pdf_path, dpi=self.dpi)
        logger.info("PDF → %d page(s) at %d DPI", len(images), self.dpi)

        all_text: List[str] = []
        total_conf = 0.0

        for i, page in enumerate(images):
            text, conf = self._ocr_with_fallback(page, tag=f"pdf_p{i+1}")
            all_text.append(f"--- Page {i + 1} ---\n{text}")
            total_conf += conf

        avg = total_conf / max(len(images), 1)
        logger.info("PDF done | avg_confidence=%.1f%%", avg)
        return "\n".join(all_text), avg

    def _process_image(self, image_path: Path) -> Tuple[str, float]:
        """OCR a single image file."""
        image = Image.open(image_path)
        text, conf = self._ocr_with_fallback(image, tag=image_path.stem)
        logger.info(
            "Image done | file=%s confidence=%.1f%%", image_path.name, conf
        )
        return text, conf

    # ══════════════════════════════════════════════════════════════════════════
    #  OCR FALLBACK STRATEGY
    # ══════════════════════════════════════════════════════════════════════════

    def _ocr_with_fallback(
        self, image: Image.Image, tag: str = "img"
    ) -> Tuple[str, float]:
        """
        Stage 1: Standard preprocessing (upscale + grayscale + CLAHE)
        Stage 2: Aggressive preprocessing (bigger upscale + sharpen)
        Stage 3: Alternate PSM modes
        """

        # ── Stage 1: Standard ────────────────────────────────────────────
        processed = preprocess_for_ocr(image, min_width=self.min_width)
        self._save_debug(image, processed, f"{tag}_1_standard")

        text, conf = self._run_tesseract(processed)
        logger.info("[%s] Stage 1 (standard): %.1f%%", tag, conf)

        if conf >= self.confidence_threshold:
            return text, conf

        # ── Stage 2: Aggressive ──────────────────────────────────────────
        logger.info("[%s] Below threshold → aggressive preprocessing", tag)
        processed_agg = preprocess_for_ocr_aggressive(
            image, min_width=self.min_width + 500
        )
        self._save_debug(image, processed_agg, f"{tag}_2_aggressive")

        text_agg, conf_agg = self._run_tesseract(processed_agg)
        logger.info("[%s] Stage 2 (aggressive): %.1f%%", tag, conf_agg)

        best_text, best_conf = (
            (text_agg, conf_agg) if conf_agg > conf else (text, conf)
        )

        if best_conf >= self.confidence_threshold:
            return best_text, best_conf

        # ── Stage 3: PSM variations ──────────────────────────────────────
        best_img = processed_agg if conf_agg >= conf else processed

        for psm in self.fallback_psm_modes:
            alt_config = self.tesseract_config.replace("--psm 6", f"--psm {psm}")
            text_alt, conf_alt = self._run_tesseract(best_img, alt_config)
            logger.info("[%s] Stage 3 (psm=%d): %.1f%%", tag, psm, conf_alt)

            if conf_alt > best_conf:
                best_text, best_conf = text_alt, conf_alt

            if best_conf >= self.confidence_threshold:
                break

        logger.info("[%s] Final best: %.1f%%", tag, best_conf)
        return best_text, best_conf

    # ══════════════════════════════════════════════════════════════════════════
    #  TESSERACT EXECUTION
    # ══════════════════════════════════════════════════════════════════════════

    def _run_tesseract(
        self,
        image: Image.Image,
        custom_config: Optional[str] = None,
    ) -> Tuple[str, float]:
        """Single Tesseract call — returns (text, avg_confidence)."""
        tess_config = custom_config or self.tesseract_config

        try:
            data = pytesseract.image_to_data(
                image,
                lang=self.languages,
                config=tess_config,
                output_type=pytesseract.Output.DICT,
            )

            lines: List[str] = []
            current_line_key = None
            current_words: List[str] = []

            for i in range(len(data["text"])):
                conf = int(data["conf"][i])
                word = data["text"][i]
                if conf <= 0 or not word.strip():
                    continue
                line_key = (
                    data["block_num"][i],
                    data["par_num"][i],
                    data["line_num"][i],
                )
                if line_key != current_line_key:
                    if current_words:
                        lines.append(" ".join(current_words))
                    current_words = [word]
                    current_line_key = line_key
                else:
                    current_words.append(word)

            if current_words:
                lines.append(" ".join(current_words))

            text = "\n".join(lines)

            confidences = [int(c) for c in data["conf"] if int(c) > 0]
            avg = sum(confidences) / len(confidences) if confidences else 0.0

            return text.strip(), avg

        except pytesseract.TesseractError as exc:
            logger.error("Tesseract error: %s", exc)
            return "", 0.0

    # ══════════════════════════════════════════════════════════════════════════
    #  DEBUG & INSTALL CHECK
    # ══════════════════════════════════════════════════════════════════════════

    def _save_debug(
        self, original: Image.Image, processed: Image.Image, name: str
    ) -> None:
        """Save original + processed images for debugging."""
        if not self.debug:
            return
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        original.save(self.debug_dir / f"{name}_original.png")
        processed.save(self.debug_dir / f"{name}_processed.png")

    @staticmethod
    def check_tesseract_installation() -> dict:
        """Verify Tesseract is installed and has required languages."""
        import subprocess

        status = {
            "tesseract_found": False,
            "version": "",
            "installed_languages": [],
            "missing_languages": [],
        }
        try:
            ver = subprocess.run(
                [pytesseract.pytesseract.tesseract_cmd, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            status["tesseract_found"] = True
            status["version"] = ver.stdout.split("\n")[0].strip()

            langs = subprocess.run(
                [pytesseract.pytesseract.tesseract_cmd, "--list-langs"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            installed = {
                ln.strip()
                for ln in langs.stdout.strip().split("\n")[1:]
                if ln.strip()
            }
            status["installed_languages"] = sorted(installed)

            required = set(config.TESSERACT_LANGUAGES.split("+"))
            status["missing_languages"] = sorted(required - installed)

        except Exception as exc:
            logger.error("Tesseract check failed: %s", exc)

        return status
    
    def _parse_recap_table(self, text: str, fields: Dict[str, Any]) -> None:
        """
        Parse TVA/MwSt recap tables. Handles two common Swiss formats:

        Format A (excl, TVA, incl):
            Récapitulatif TVA  Taux  Montant CHF excl.  TVA CHF  Montant CHF incl.
                           8.10  129.50              10.50    140.00

        Format B (TTC, HT, TVA):
            Taux TVA  T.T.C.      H.T.       TVA
            8.10%     496.75 CHF  459.54 CHF  37.21 CHF
        """

        # ── Format A: after "Récapitulatif" — rate, subtotal, vat, total ──
        recap_a = re.search(
            r"(?:R[ée]capitulatif|Zusammenfassung)"
            r".*?"
            r"(\d{1,2}[.,]\d{1,2})%?\s+"
            r"([\d']+\.\d{2})\s+"
            r"([\d']+\.\d{2})\s+"
            r"([\d']+\.\d{2})",
            text, re.IGNORECASE | re.DOTALL,
        )

        if recap_a:
            rate = self._parse_float(recap_a.group(1))
            subtotal = self._parse_float(recap_a.group(2))
            vat = self._parse_float(recap_a.group(3))
            total = self._parse_float(recap_a.group(4))

            # Validate: subtotal + vat ≈ total
            if subtotal and vat and total and abs((subtotal + vat) - total) < 0.10:
                logger.debug("Recap A: sub=%.2f vat=%.2f total=%.2f", subtotal, vat, total)
                if rate and not fields.get("vat_rate"):
                    fields["vat_rate"] = rate
                if not fields.get("subtotal"):
                    fields["subtotal"] = subtotal
                if not fields.get("vat_amount"):
                    fields["vat_amount"] = vat
                if not fields.get("total"):
                    fields["total"] = total
                return

        # ── Format B: "Taux TVA  T.T.C.  H.T.  TVA" — rate, total, subtotal, vat ──
        recap_b = re.search(
            r"(?:Taux\s+TVA|T\.T\.C\.)"
            r".*?"
            r"(\d{1,2}[.,]\d{1,2})%?\s+"
            r"([\d']+\.\d{2})\s+(?:CHF\s+)?"
            r"([\d']+\.\d{2})\s+(?:CHF\s+)?"
            r"([\d']+\.\d{2})",
            text, re.IGNORECASE | re.DOTALL,
        )

        if recap_b:
            rate = self._parse_float(recap_b.group(1))
            amt1 = self._parse_float(recap_b.group(2))  # T.T.C. (total)
            amt2 = self._parse_float(recap_b.group(3))  # H.T. (subtotal)
            amt3 = self._parse_float(recap_b.group(4))  # TVA (vat)

            # Validate: amt2 + amt3 ≈ amt1
            if amt1 and amt2 and amt3 and abs((amt2 + amt3) - amt1) < 0.10:
                logger.debug("Recap B: total=%.2f sub=%.2f vat=%.2f", amt1, amt2, amt3)
                if rate and not fields.get("vat_rate"):
                    fields["vat_rate"] = rate
                if not fields.get("total"):
                    fields["total"] = amt1
                if not fields.get("subtotal"):
                    fields["subtotal"] = amt2
                if not fields.get("vat_amount"):
                    fields["vat_amount"] = amt3
                return

        # ── Fallback: "Total  129.50  10.50  140.00" (3 amounts) ─────────
        total_line = re.search(
            r"\bTotal\s+"
            r"([\d']+\.\d{2})\s+"
            r"([\d']+\.\d{2})\s+"
            r"([\d']+\.\d{2})",
            text,
        )

        if total_line:
            a = self._parse_float(total_line.group(1))
            b = self._parse_float(total_line.group(2))
            c = self._parse_float(total_line.group(3))

            if a and b and c and abs((a + b) - c) < 0.10:
                logger.debug("Total line: sub=%.2f vat=%.2f total=%.2f", a, b, c)
                if not fields.get("subtotal"):
                    fields["subtotal"] = a
                if not fields.get("vat_amount"):
                    fields["vat_amount"] = b
                if not fields.get("total"):
                    fields["total"] = c
                return