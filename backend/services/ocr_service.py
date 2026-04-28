# backend/services/ocr_service.py

import pytesseract
from PIL import Image
from pathlib import Path
from typing import Tuple, Optional

import logging

from backend.config import config
from backend.utils.image_preprocessing import (
    preprocess_for_ocr,
    preprocess_for_ocr_aggressive,
    pdf_to_images,
)

logger = logging.getLogger(__name__)

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


class OcrService:
    """
    OCR service for Swiss invoices.
    Uses grayscale pipeline (no binarization) — proven best by tests.
    """

    def __init__(self):
        self.languages = config.TESSERACT_LANGUAGES
        self.tesseract_config = config.TESSERACT_CONFIG
        self.confidence_threshold = config.OCR_CONFIDENCE_THRESHOLD
        self.fallback_psm_modes = config.OCR_FALLBACK_PSM_MODES
        self.min_width = config.OCR_MIN_WIDTH
        self.dpi = config.OCR_DPI
        self.debug = config.OCR_DEBUG
        self.debug_dir = config.BASE_DIR / "debug_ocr"

        logger.info(
            "OcrService init | lang=%s dpi=%d min_width=%d threshold=%.0f%%",
            self.languages, self.dpi, self.min_width, self.confidence_threshold,
        )

    # ── Public API ───────────────────────────

    def extract_text(self, file_path: Path) -> Tuple[str, float]:
        ext = file_path.suffix.lower()
        logger.info("Processing: %s (type=%s)", file_path.name, ext)

        if ext == ".pdf":
            return self._process_pdf(file_path)
        return self._process_image(file_path)

    # ── PDF ──────────────────────────────────

    def _process_pdf(self, pdf_path: Path) -> Tuple[str, float]:
        images = pdf_to_images(pdf_path, dpi=self.dpi)
        logger.info("PDF → %d page(s) at %d DPI", len(images), self.dpi)

        all_text = []
        total_conf = 0.0

        for i, page in enumerate(images):
            text, conf = self._ocr_with_fallback(page, tag=f"pdf_p{i+1}")
            all_text.append(f"--- Page {i + 1} ---\n{text}")
            total_conf += conf

        avg = total_conf / max(len(images), 1)
        logger.info("PDF done | avg_confidence=%.1f%%", avg)
        return "\n".join(all_text), avg

    # ── Image ────────────────────────────────

    def _process_image(self, image_path: Path) -> Tuple[str, float]:
        image = Image.open(image_path)
        text, conf = self._ocr_with_fallback(image, tag=image_path.stem)
        logger.info("Image done | file=%s confidence=%.1f%%", image_path.name, conf)
        return text, conf

    # ── Fallback strategy ────────────────────

    def _ocr_with_fallback(
        self, image: Image.Image, tag: str = "img"
    ) -> Tuple[str, float]:
        """
        Stage 1: Standard (upscale + grayscale + CLAHE)
        Stage 2: Aggressive (bigger upscale + sharpen)
        Stage 3: Try alternate PSM modes
        """

        # ── Stage 1 ──
        processed = preprocess_for_ocr(image, min_width=self.min_width)
        self._save_debug(image, processed, f"{tag}_1_standard")

        text, conf = self._run_tesseract(processed)
        logger.info("[%s] Stage 1 (standard): %.1f%%", tag, conf)

        if conf >= self.confidence_threshold:
            return text, conf

        # ── Stage 2 ──
        logger.info("[%s] Below threshold → aggressive preprocessing", tag)
        processed_agg = preprocess_for_ocr_aggressive(
            image, min_width=self.min_width + 500
        )
        self._save_debug(image, processed_agg, f"{tag}_2_aggressive")

        text_agg, conf_agg = self._run_tesseract(processed_agg)
        logger.info("[%s] Stage 2 (aggressive): %.1f%%", tag, conf_agg)

        # Track best so far
        best_text, best_conf = (
            (text_agg, conf_agg) if conf_agg > conf else (text, conf)
        )

        if best_conf >= self.confidence_threshold:
            return best_text, best_conf

        # ── Stage 3: PSM variations ──
        # Use whichever preprocessed image was better
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

    # ── Tesseract execution ──────────────────

    def _run_tesseract(
        self,
        image: Image.Image,
        custom_config: Optional[str] = None,
    ) -> Tuple[str, float]:
        tess_config = custom_config or self.tesseract_config

        try:
            text = pytesseract.image_to_string(
                image, lang=self.languages, config=tess_config,
            )
            data = pytesseract.image_to_data(
                image, lang=self.languages, config=tess_config,
                output_type=pytesseract.Output.DICT,
            )
            confidences = [int(c) for c in data["conf"] if int(c) > 0]
            avg = sum(confidences) / len(confidences) if confidences else 0.0
            return text.strip(), avg

        except pytesseract.TesseractError as exc:
            logger.error("Tesseract error: %s", exc)
            return "", 0.0

    # ── Debug helpers ────────────────────────

    def _save_debug(
        self, original: Image.Image, processed: Image.Image, name: str
    ) -> None:
        if not self.debug:
            return
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        original.save(self.debug_dir / f"{name}_original.png")
        processed.save(self.debug_dir / f"{name}_processed.png")

    @staticmethod
    def check_tesseract_installation() -> dict:
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
                capture_output=True, text=True, timeout=10,
            )
            status["tesseract_found"] = True
            status["version"] = ver.stdout.split("\n")[0].strip()

            langs = subprocess.run(
                [pytesseract.pytesseract.tesseract_cmd, "--list-langs"],
                capture_output=True, text=True, timeout=10,
            )
            installed = {
                l.strip() for l in langs.stdout.strip().split("\n")[1:] if l.strip()
            }
            status["installed_languages"] = sorted(installed)

            required = set(config.TESSERACT_LANGUAGES.split("+"))
            status["missing_languages"] = sorted(required - installed)
        except Exception as exc:
            logger.error("Tesseract check failed: %s", exc)

        return status