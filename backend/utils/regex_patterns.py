import re

# ------------------------------------------------------------------ #
#  DATE
# ------------------------------------------------------------------ #

DATE_PATTERNS = [
    r'\b(\d{1,2}\.\d{1,2}\.\d{4})\b',
    r'\b(\d{1,2}\.\d{1,2}\.\d{2})\b',
    r'\b(\d{4}-\d{2}-\d{2})\b',
]

DATE_KEYWORDS = {
    "de": [r"Rechnungsdatum", r"Datum", r"Rechnungs-Datum", r"Belegdatum"],
    "fr": [
        r"Date\s+de\s+(?:commande|facture)",
        r"Date\s+de\s+facture",
        r"Date",
        r"Factur.+le",
    ],
    "it": [r"Data\s+fattura", r"Data"],
    "en": [r"Invoice\s+date", r"Date"],
}

# ------------------------------------------------------------------ #
#  AMOUNTS
# ------------------------------------------------------------------ #

AMOUNT_PATTERN = r"(\d{1,3}(?:['\u2019,]\d{3})*\.\d{2})"

TOTAL_KEYWORDS = {
    "de": [
        r"Total", r"Gesamtbetrag", r"Gesamttotal", r"Rechnungsbetrag",
        r"Endbetrag", r"Bruttobetrag", r"Zu\s+zahlen",
    ],
    "fr": [
        r"Total\s+de\s+tous\s+les\s+services",
        r"Total\s+TTC", r"Montant\s+total", r"Total",
        r"Montant\s+d.", r".\s+payer", r"A\s+payer",
    ],
    "it": [
        r"Totale", r"Importo\s+totale", r"Totale\s+fattura",
        r"Da\s+pagare",
    ],
    "en": [
        r"Total", r"Grand\s+total", r"Amount\s+due",
        r"Total\s+amount", r"Balance\s+due",
    ],
}

SUBTOTAL_KEYWORDS = {
    "de": [r"Zwischensumme", r"Subtotal", r"Nettobetrag", r"Netto"],
    "fr": [r"Sous-total", r"Subtotal", r"Total\s+HT", r"Net", r"Valeur"],
    "it": [r"Subtotale", r"Netto"],
    "en": [r"Subtotal", r"Net\s+amount"],
}

# ------------------------------------------------------------------ #
#  VAT
# ------------------------------------------------------------------ #

VAT_RATE_PATTERN = r"(\d{1,2}[.,]\d{1,2})\s*%"

VAT_KEYWORDS = {
    "de": [r"MwSt", r"MWST", r"Mehrwertsteuer", r"USt"],
    "fr": [r"TVA", r"Taxe\s+sur\s+la\s+valeur"],
    "it": [r"IVA", r"Imposta\s+sul\s+valore"],
    "en": [r"VAT", r"Tax"],
}

VAT_UID_PATTERN = r"(CHE-?\d{3}\.?\d{3}\.?\d{3})\s*(?:MWST|TVA|IVA)?"

# ------------------------------------------------------------------ #
#  IBAN
# ------------------------------------------------------------------ #

IBAN_PATTERN = r"\b(CH\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{1})\b"
IBAN_PATTERN_LI = r"\b(LI\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{1})\b"

# ------------------------------------------------------------------ #
#  INVOICE NUMBER
# ------------------------------------------------------------------ #

INVOICE_NUMBER_KEYWORDS = {
    "de": [
        r"Rechnung\s*(?:No|Number|#)\s*:?",
        r"Rechnung",
        r"Beleg(?:-|\s)?Nr",
    ],
    "fr": [
        r"Facture\s*(?:N[°o.]?|No|Num[ée]ro)\s*:?",
        r"N[°o.]\s*(?:de\s+)?facture\s*:?",
        r"Ticket\s+de\s+caisse\s*/?\s*Facture",
        r"Facture",
    ],
    "it": [
        r"Fattura\s*(?:N[°o.]?|No|Numero)\s*:?",
        r"N[°o.]?\s*fattura\s*:?",
        r"Fattura",
    ],
    "en": [
        r"Invoice\s*(?:No|Number|#)\s*:?",
        r"Invoice\s*:?",
        r"Inv\s*(?:No|#)\s*:?",
    ],
}

INVOICE_NUMBER_VALUE = r"[:\s]*([A-Za-z0-9\-/\.]+\d[A-Za-z0-9\-/\.]*)"

# ------------------------------------------------------------------ #
#  CURRENCY & REFERENCES
# ------------------------------------------------------------------ #

CURRENCY_PATTERN = r"\b(CHF|EUR|USD|GBP|Fr\.)\b"
QR_REFERENCE_PATTERN = r"\b(\d{2}\s?\d{5}\s?\d{5}\s?\d{5}\s?\d{5}\s?\d{5}\s?\d{2})\b"

# ------------------------------------------------------------------ #
#  RECIPIENT keywords
# ------------------------------------------------------------------ #

RECIPIENT_KEYWORDS = {
    "de": [
        r"Kunde(?:n)?(?:\s*(?:Nr|Nummer|nummer))?",
        r"Rechnungsadresse", r"Lieferadresse",
        r"Empf.nger", r"Besteller",
    ],
    "fr": [
        r"Client", r"Num.ro\s+de\s+client",
        r"Adresse\s+de\s+(?:livraison|facturation)",
        r"Destinataire", r"Livr.\s+.",
        r"Commande\s+commerc",
    ],
    "it": [
        r"Cliente", r"Indirizzo\s+di\s+(?:consegna|fatturazione)",
        r"Destinatario",
    ],
    "en": [
        r"Customer", r"Bill\s+to", r"Ship\s+to",
        r"Recipient", r"Deliver\s+to",
    ],
}

COMPANY_CODE_KEYWORDS = {
    "de": [
        r"Kunden(?:\s*-?\s*)(?:Nr|Nummer|nummer|nr|code)",
        r"Kundennummer",
    ],
    "fr": [
        r"Num.ro\s+de\s+client",
        r"Code\s+client",
        r"N[°o.]\s*client",
    ],
    "it": [r"Codice\s+cliente", r"N[°o.]\s*cliente"],
    "en": [r"Customer\s*(?:No|Number|Code|ID)", r"Account\s*(?:No|Number)"],
}

# ------------------------------------------------------------------ #
#  Helper
# ------------------------------------------------------------------ #


def normalize_swiss_amount(amount_str: str) -> float:
    cleaned = amount_str.replace("'", "").replace("\u2019", "").replace(",", "")
    return float(cleaned)