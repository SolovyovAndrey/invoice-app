# backend/config.py

import platform
from pathlib import Path
from dataclasses import dataclass, field
from typing import List


@dataclass
class AppConfig:
    BASE_DIR: Path = Path(__file__).parent
    TEMP_DIR: Path = BASE_DIR / "temp"
    DATA_DIR: Path = BASE_DIR / "data"
    FRONTEND_DIR: Path = BASE_DIR.parent / "frontend"
    DATABASE_NAME: str = "invoices.db"

    @property
    def DATABASE_URL(self) -> str:
        db_path = self.DATA_DIR / self.DATABASE_NAME
        return f"sqlite:///{db_path}"

    ALLOWED_EXTENSIONS: set = field(
        default_factory=lambda: {".pdf", ".png", ".jpg", ".jpeg", ".tiff"}
    )
    MAX_FILE_SIZE_MB: int = 20
    MAX_BATCH_SIZE: int = 50

    # ── Tesseract binary ─────────────────────
    @property
    def TESSERACT_CMD(self) -> str:
        """
        Path to the Tesseract executable.
        - Windows: full path to .exe
        - Linux/macOS: just "tesseract" (expects it in PATH)
        """
        if platform.system() == "Windows":
            return r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        return "tesseract"

    # ── OCR ──────────────────────────────────
    TESSERACT_LANGUAGES: str = "deu+fra+eng"
    OCR_DPI: int = 400
    OCR_MIN_WIDTH: int = 2500
    OCR_CONFIDENCE_THRESHOLD: float = 45.0
    OCR_DEBUG: bool = True  # turn off after testing
    OCR_FALLBACK_PSM_MODES: List[int] = field(
        default_factory=lambda: [4, 3]
    )

    @property
    def TESSERACT_CONFIG(self) -> str:
        """
        Simple config — no whitelist, no tricks.
        Proven best by diagnostic tests.
        """
        return "--oem 3 --psm 6 -c preserve_interword_spaces=1"

    # ── Swiss invoice ────────────────────────
    DEFAULT_CURRENCY: str = "CHF"
    SWISS_VAT_RATES: List[float] = field(
        default_factory=lambda: [8.1, 2.6, 3.8]
    )

    # ── Export ───────────────────────────────
    CSV_DELIMITER: str = ";"
    CSV_ENCODING: str = "utf-8-sig"
    DATE_FORMAT: str = "%d.%m.%Y"

    # ── Pagination ───────────────────────────
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    def __post_init__(self):
        self.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        if self.OCR_DEBUG:
            (self.BASE_DIR / "debug_ocr").mkdir(parents=True, exist_ok=True)


config = AppConfig()