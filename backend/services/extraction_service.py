import re
from typing import Optional, Tuple, List

from backend.models.invoice import InvoiceData, SourceType
from backend.utils.regex_patterns import (
    DATE_PATTERNS, DATE_KEYWORDS,
    AMOUNT_PATTERN, TOTAL_KEYWORDS, SUBTOTAL_KEYWORDS,
    VAT_RATE_PATTERN, VAT_KEYWORDS, VAT_UID_PATTERN,
    IBAN_PATTERN, IBAN_PATTERN_LI,
    INVOICE_NUMBER_KEYWORDS, INVOICE_NUMBER_VALUE,
    CURRENCY_PATTERN, QR_REFERENCE_PATTERN,
    RECIPIENT_KEYWORDS, COMPANY_CODE_KEYWORDS,
    normalize_swiss_amount,
)

import logging

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
#  Swiss address patterns
# ------------------------------------------------------------------ #

SWISS_POSTAL_PATTERN = re.compile(
    r"\b(\d{4})\s+([A-ZÀ-Üa-zà-ü][a-zà-ü\-\']+(?:[\s\-][a-zà-ü\-\'A-ZÀ-Ü]+)*)\b"
)

SWISS_STREET_PATTERN = re.compile(
    r"(?:"
    r"[A-ZÀ-Üa-zà-ü\-\.]+(?:strasse|str\.|weg|gasse|platz|rain|matt|allee)"
    r"|(?:Rue|Route|Rte|Chemin|Ch\.|Avenue|Av\.|Place|Pl\.|Boulevard|Bd\.)"
    r"|(?:Via|Vicolo|Piazza|Viale)"
    r"|(?:Pfingstweids)"
    r")"
    r"[^,\n]*?\d+[a-zA-Z]?",
    re.IGNORECASE,
)

COMPANY_SUFFIX_PATTERN = re.compile(
    r"\b(?:AG|SA|GmbH|S[àa]rl|SARL|S\.à\.r\.l|Srl|Ltd|Inc|KG|OHG|SE|Co\.|Corp)\b",
    re.IGNORECASE,
)

SKIP_LINE_PATTERNS = [
    re.compile(r"^\s*$"),
    re.compile(r"^(Seite|Page|Pagina)\s+\d", re.IGNORECASE),
    re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$"),
    re.compile(r"^[\d\s\'\.,]+$"),
    re.compile(r"^-{3,}|^={3,}|^\*{3,}"),
    re.compile(r"^(Rechnung|Facture|Fattura|Invoice)\b", re.IGNORECASE),
    re.compile(r"^(Ticket\s+de\s+caisse)", re.IGNORECASE),
    re.compile(r"^(Bestellung|Commande|Ordine)\b", re.IGNORECASE),
    re.compile(r"^(No|Nr|Nummer|Numéro|N[°o])\.?\s*(de)?\s*(TVA|MWST|IVA)", re.IGNORECASE),
    re.compile(r"^(Kunden|Client|Customer)", re.IGNORECASE),
    re.compile(r"^(Tel|Fax|Email|E-Mail|www\.|http)", re.IGNORECASE),
    re.compile(r"^(IBAN|BIC|Swift|Konto|Compte)", re.IGNORECASE),
    re.compile(r"^CHE-\d{3}\.\d{3}\.\d{3}"),
    re.compile(r"^(Pour\s+les\s+questions|helpcenter)", re.IGNORECASE),
    re.compile(r"^[a-z\s\.\!\?\,]{1,5}$"),
    re.compile(r"^www\.|\.ch\b|\.com\b|\.de\b", re.IGNORECASE),
    re.compile(r"^\S+\.\w{2,3}$"),
    re.compile(r"^[^a-zA-Z0-9À-ÿ]*$"),
]


class ExtractionService:
    def extract(self, raw_text: str, confidence: float = 0.0) -> InvoiceData:
        invoice = InvoiceData(
            source_type=SourceType.OCR,
            confidence_score=confidence,
            raw_text=raw_text,
        )

        # Invoice details
        invoice.invoice_date = self._extract_date(raw_text, DATE_KEYWORDS)
        invoice.invoice_number = self._extract_invoice_number(raw_text)
        invoice.currency = self._extract_currency(raw_text)
        invoice.total = self._extract_total(raw_text)
        invoice.subtotal = self._extract_subtotal(raw_text)
        invoice.vat_rate = self._extract_vat_rate(raw_text)
        invoice.vat_amount = self._extract_vat_amount(raw_text)
        invoice.vendor_iban = self._extract_iban(raw_text)
        invoice.vendor_vat_uid = self._extract_vat_uid(raw_text)
        invoice.reference_number = self._extract_qr_reference(raw_text)

        # Vendor (seller)
        vendor_name, vendor_address = self._extract_vendor_block(raw_text)
        invoice.vendor_name = vendor_name
        invoice.vendor_address = vendor_address

        # Recipient (buyer)
        recipient = self._extract_recipient_block(raw_text, vendor_name)
        invoice.recipient_name = recipient.get("name")
        invoice.recipient_address = recipient.get("address")
        invoice.recipient_vat_uid = recipient.get("vat_uid")
        invoice.recipient_company_code = self._extract_company_code(raw_text)

        invoice.confidence_score = self._calculate_confidence(invoice)

        logger.info(
            "Extracted: vendor=%s | vendor_addr=%s | recipient=%s | "
            "recipient_addr=%s | invoice_no=%s | total=%s | date=%s",
            invoice.vendor_name, invoice.vendor_address,
            invoice.recipient_name, invoice.recipient_address,
            invoice.invoice_number, invoice.total, invoice.invoice_date,
        )
        return invoice

    # ================================================================ #
    #  VENDOR NAME + ADDRESS
    # ================================================================ #

    def _extract_vendor_block(
        self, text: str
    ) -> Tuple[Optional[str], Optional[str]]:
        lines = text.strip().split("\n")
        clean_lines = [(i, line.strip()) for i, line in enumerate(lines)]

        result = self._find_address_by_company_suffix(clean_lines)
        if result and result[1]:
            return result

        result = self._find_address_by_postal_code(clean_lines)
        if result:
            return result

        result = self._find_address_by_street(clean_lines)
        if result:
            return result

        vendor_name = self._extract_vendor_name_fallback(lines)
        return vendor_name, None

    def _find_address_by_company_suffix(
        self, lines: List[Tuple[int, str]]
    ) -> Optional[Tuple[str, str]]:
        for idx, (line_num, line_text) in enumerate(lines):
            if idx > 15:
                break
            if not COMPANY_SUFFIX_PATTERN.search(line_text):
                continue
            if self._is_skip_line(line_text):
                continue
            if len(line_text.replace(" ", "")) < 3:
                continue

            vendor_name = line_text
            address_parts = []

            for lookahead in range(1, 4):
                if idx + lookahead >= len(lines):
                    break
                _, next_text = lines[idx + lookahead]
                if not next_text or len(next_text) < 2:
                    continue
                if re.match(
                    r"^(Rechnung|Facture|Fattura|Invoice|Bestellung|"
                    r"Datum|Date|Ticket|Pour\s+les|www\.)",
                    next_text, re.IGNORECASE,
                ):
                    break
                if (
                    SWISS_STREET_PATTERN.search(next_text)
                    or SWISS_POSTAL_PATTERN.search(next_text)
                ):
                    address_parts.append(next_text)
                elif (
                    len(next_text) < 50
                    and not self._is_skip_line(next_text)
                    and not next_text.startswith("www")
                ):
                    address_parts.append(next_text)

            address = ", ".join(address_parts) if address_parts else None
            return vendor_name, address

        return None

    def _find_address_by_postal_code(
        self, lines: List[Tuple[int, str]]
    ) -> Optional[Tuple[str, str]]:
        for idx, (line_num, line_text) in enumerate(lines):
            if idx > 20:
                break
            match = SWISS_POSTAL_PATTERN.search(line_text)
            if not match:
                continue

            postal_line = line_text
            block_lines = [postal_line]
            vendor_name = None

            for lookback in range(1, 5):
                if idx - lookback < 0:
                    break
                _, prev_text = lines[idx - lookback]
                if not prev_text or len(prev_text) < 2:
                    continue
                if self._is_skip_line(prev_text):
                    continue
                if SWISS_STREET_PATTERN.search(prev_text):
                    block_lines.insert(0, prev_text)
                    continue
                if COMPANY_SUFFIX_PATTERN.search(prev_text):
                    vendor_name = prev_text
                    break
                if len(prev_text) < 60 and not vendor_name:
                    vendor_name = prev_text
                    break

            address = ", ".join(block_lines)
            if vendor_name or address:
                return vendor_name, address

        return None

    def _find_address_by_street(
        self, lines: List[Tuple[int, str]]
    ) -> Optional[Tuple[str, str]]:
        for idx, (line_num, line_text) in enumerate(lines):
            if idx > 20:
                break
            if not SWISS_STREET_PATTERN.search(line_text):
                continue

            vendor_name = None
            postal_line = None

            if idx > 0:
                _, prev_text = lines[idx - 1]
                if prev_text and not self._is_skip_line(prev_text):
                    vendor_name = prev_text

            if idx + 1 < len(lines):
                _, next_text = lines[idx + 1]
                if SWISS_POSTAL_PATTERN.search(next_text):
                    postal_line = next_text

            parts = [line_text]
            if postal_line:
                parts.append(postal_line)
            return vendor_name, ", ".join(parts)

        return None

    def _extract_vendor_name_fallback(self, lines: list) -> Optional[str]:
        for line in lines[:10]:
            cleaned = line.strip()
            if len(cleaned) < 3:
                continue
            if self._is_skip_line(cleaned):
                continue
            if not re.search(r"[a-zA-ZÀ-ÿ]{2,}", cleaned):
                continue
            return cleaned
        return None

    def _is_skip_line(self, text: str) -> bool:
        for pattern in SKIP_LINE_PATTERNS:
            if pattern.search(text):
                return True
        return False

    # ================================================================ #
    #  RECIPIENT (BUYER)
    # ================================================================ #

    def _extract_recipient_block(
        self, text: str, vendor_name: Optional[str] = None
    ) -> dict:
        result = {"name": None, "address": None, "vat_uid": None}
        lines = text.strip().split("\n")

        # Strategy 1: Keyword-based
        kw_result = self._find_recipient_by_keyword(lines, vendor_name)
        if kw_result["name"]:
            result.update(kw_result)
            return result

        # Strategy 2: Labeled person name + address
        label_result = self._find_recipient_by_labels(lines, vendor_name)
        if label_result["name"]:
            result.update(label_result)
            return result

        # Strategy 3: Second address block
        block_result = self._find_second_address_block(lines, vendor_name)
        if block_result["name"]:
            result.update(block_result)

        return result

    def _find_recipient_by_keyword(
        self, lines: list, vendor_name: Optional[str]
    ) -> dict:
        result = {"name": None, "address": None, "vat_uid": None}
        text_joined = "\n".join(lines)

        for lang, kw_list in RECIPIENT_KEYWORDS.items():
            for kw in kw_list:
                pattern = rf"{kw}[\s:]*(.+?)(?:\n|$)"
                match = re.search(pattern, text_joined, re.IGNORECASE)
                if not match:
                    continue

                value = match.group(1).strip()

                # Comma-separated full address on one line
                if "," in value and len(value) > 20:
                    parts = [p.strip() for p in value.split(",")]
                    result["name"] = parts[0]
                    result["address"] = ", ".join(parts[1:])
                    if result["address"]:
                        result["address"] = re.sub(
                            r"CH-(\d{4})", r"\1", result["address"]
                        )
                    return result

                # Name on this line → look below for address
                if value and not self._is_skip_line(value):
                    line_idx = None
                    for i, line in enumerate(lines):
                        if value in line:
                            line_idx = i
                            break

                    if line_idx is not None:
                        name, address = self._collect_address_from(
                            lines, line_idx + 1, vendor_name
                        )
                        if name:
                            result["name"] = name
                            result["address"] = address
                            return result

        return result

    def _find_recipient_by_labels(
        self, lines: list, vendor_name: Optional[str]
    ) -> dict:
        result = {"name": None, "address": None, "vat_uid": None}

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Person name: "Firstname Lastname" pattern
            if i < 25 and re.match(
                r"^[A-ZÀ-Ü][a-zà-ü]+\s+(?:[A-ZÀ-Ü][a-zà-ü]+\s*){1,3}$",
                stripped,
            ):
                if vendor_name and stripped.lower() in vendor_name.lower():
                    continue

                address_parts = []
                for j in range(i + 1, min(i + 4, len(lines))):
                    next_line = lines[j].strip()
                    if not next_line:
                        continue
                    if SWISS_STREET_PATTERN.search(next_line):
                        address_parts.append(next_line)
                    elif SWISS_POSTAL_PATTERN.search(next_line):
                        address_parts.append(next_line)
                    elif next_line.lower() in (
                        "suisse", "schweiz", "svizzera", "ch",
                    ):
                        address_parts.append(next_line)
                    else:
                        break

                if address_parts:
                    result["name"] = stripped
                    result["address"] = ", ".join(address_parts)
                    return result

        return result

    def _find_second_address_block(
        self, lines: list, vendor_name: Optional[str]
    ) -> dict:
        result = {"name": None, "address": None, "vat_uid": None}
        found_first = False

        for i, line in enumerate(lines):
            if i > 30:
                break
            stripped = line.strip()

            if SWISS_POSTAL_PATTERN.search(stripped):
                if not found_first:
                    found_first = True
                    continue

                address_parts = [stripped]
                name = None

                for lookback in range(1, 4):
                    if i - lookback < 0:
                        break
                    prev = lines[i - lookback].strip()
                    if not prev:
                        continue
                    if SWISS_STREET_PATTERN.search(prev):
                        address_parts.insert(0, prev)
                    elif (
                        len(prev) > 3
                        and not self._is_skip_line(prev)
                        and (
                            not vendor_name
                            or prev.lower() != vendor_name.lower()
                        )
                    ):
                        name = prev
                        break

                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line.lower() in (
                        "suisse", "schweiz", "svizzera", "switzerland", "ch",
                    ):
                        address_parts.append(next_line)

                result["name"] = name
                result["address"] = ", ".join(address_parts)
                return result

        return result

    def _collect_address_from(
        self, lines: list, start_idx: int, vendor_name: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        name = None
        address_parts = []

        for i in range(start_idx, min(start_idx + 5, len(lines))):
            stripped = lines[i].strip()
            if not stripped:
                continue
            if self._is_skip_line(stripped):
                continue

            if not name:
                if vendor_name and stripped.lower() == vendor_name.lower():
                    continue
                name = stripped
                continue

            if (
                SWISS_STREET_PATTERN.search(stripped)
                or SWISS_POSTAL_PATTERN.search(stripped)
                or stripped.lower() in ("suisse", "schweiz", "svizzera", "ch")
            ):
                address_parts.append(stripped)
            elif len(stripped) < 50:
                address_parts.append(stripped)
            else:
                break

        address = ", ".join(address_parts) if address_parts else None
        return name, address

    # ================================================================ #
    #  COMPANY CODE
    # ================================================================ #

    def _extract_company_code(self, text: str) -> Optional[str]:
        for lang, kw_list in COMPANY_CODE_KEYWORDS.items():
            for kw in kw_list:
                pattern = rf"{kw}[\s:]*(\d{{3,10}})"
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1).strip()

        match = re.search(
            r"Soci[ée]t[ée][\s:]*(\d{3,10})", text, re.IGNORECASE
        )
        if match:
            return match.group(1).strip()

        return None

    # ================================================================ #
    #  INVOICE NUMBER
    # ================================================================ #

    def _extract_invoice_number(self, text):
        for lang, kw_list in INVOICE_NUMBER_KEYWORDS.items():
            for kw in kw_list:
                pattern = kw + INVOICE_NUMBER_VALUE
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    value = match.group(1).strip()
                    if len(value) >= 2 and re.search(r"\d", value):
                        return value
        return None

    # ================================================================ #
    #  DATE
    # ================================================================ #

    def _extract_date(self, text, keywords):
        for lang, kw_list in keywords.items():
            for kw in kw_list:
                for date_pat in DATE_PATTERNS:
                    pattern = rf"{kw}[\s:]*{date_pat}"
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        return (
                            match.group(1)
                            if match.lastindex
                            else match.group()
                        )
        for date_pat in DATE_PATTERNS:
            match = re.search(date_pat, text)
            if match:
                return match.group(1)
        return None

    # ================================================================ #
    #  CURRENCY, AMOUNTS, VAT, IBAN, REFERENCES
    # ================================================================ #

    def _extract_currency(self, text):
        match = re.search(CURRENCY_PATTERN, text)
        if match:
            currency = match.group(1)
            return "CHF" if currency == "Fr." else currency.upper()
        return "CHF"

    def _extract_total(self, text):
        return self._extract_amount_near_keywords(text, TOTAL_KEYWORDS)

    def _extract_subtotal(self, text):
        return self._extract_amount_near_keywords(text, SUBTOTAL_KEYWORDS)

    def _extract_amount_near_keywords(self, text, keywords):
        for lang, kw_list in keywords.items():
            for kw in kw_list:
                pattern = rf"{kw}[\s:]*(?:CHF|EUR|Fr\.?)?\s*{AMOUNT_PATTERN}"
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return normalize_swiss_amount(match.group(1))
        for lang, kw_list in keywords.items():
            for kw in kw_list:
                pattern = rf"(?:CHF|EUR|Fr\.?)?\s*{AMOUNT_PATTERN}\s*{kw}"
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return normalize_swiss_amount(match.group(1))
        return None

    def _extract_vat_rate(self, text):
        for lang, kw_list in VAT_KEYWORDS.items():
            for kw in kw_list:
                pattern = rf"{kw}[\s:]*{VAT_RATE_PATTERN}"
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return float(match.group(1).replace(",", "."))
        pattern = rf"{VAT_RATE_PATTERN}\s*(?:MwSt|MWST|TVA|IVA|VAT)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", "."))
        return None

    def _extract_vat_amount(self, text):
        for lang, kw_list in VAT_KEYWORDS.items():
            for kw in kw_list:
                pattern = (
                    rf"{kw}[\s:]*(?:\d{{1,2}}[.,]\d{{1,2}}\s*%?\s*)?"
                    rf"(?:CHF|EUR|Fr\.?)?\s*{AMOUNT_PATTERN}"
                )
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return normalize_swiss_amount(match.group(1))
        return self._extract_amount_near_keywords(text, VAT_KEYWORDS)

    def _extract_iban(self, text):
        for pattern in [IBAN_PATTERN, IBAN_PATTERN_LI]:
            match = re.search(pattern, text)
            if match:
                iban = match.group(1).replace(" ", "")
                if len(iban) == 21:
                    return iban
        return None

    def _extract_vat_uid(self, text):
        match = re.search(VAT_UID_PATTERN, text)
        return match.group(1) if match else None

    def _extract_qr_reference(self, text):
        match = re.search(QR_REFERENCE_PATTERN, text)
        return match.group(1).replace(" ", "") if match else None

    # ================================================================ #
    #  CONFIDENCE
    # ================================================================ #

    def _calculate_confidence(self, invoice):
        base = invoice.confidence_score
        critical = [invoice.total, invoice.invoice_date, invoice.vendor_name]
        important = [
            invoice.currency, invoice.vendor_iban, invoice.vat_rate,
            invoice.invoice_number, invoice.vendor_address,
            invoice.recipient_name,
        ]
        critical_found = sum(1 for f in critical if f is not None)
        important_found = sum(1 for f in important if f is not None)
        field_score = (critical_found / 3) * 50 + (important_found / 6) * 30
        final = (base * 0.4) + (field_score * 0.6)
        return round(min(final, 99.0), 1)