# backend/utils/image_preprocessing.py

import cv2
import numpy as np
from PIL import Image
from typing import List
from pathlib import Path

import logging

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Conversion helpers
# ------------------------------------------------------------------ #

def pil_to_cv2(image: Image.Image) -> np.ndarray:
    """Convert PIL → OpenCV, handling RGBA transparency."""
    if image.mode == "RGBA":
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[3])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def cv2_to_pil(image: np.ndarray) -> Image.Image:
    if len(image.shape) == 2:
        return Image.fromarray(image)
    return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


# ------------------------------------------------------------------ #
#  Building blocks
# ------------------------------------------------------------------ #

def smart_upscale(img: np.ndarray, target_width: int = 2500) -> np.ndarray:
    """
    Upscale to target width with appropriate interpolation
    and post-upscale sharpening.
    """
    h, w = img.shape[:2]
    if w >= target_width:
        return img

    scale = target_width / w
    logger.info(
        "Upscaling %.1fx: %dx%d → %dx%d",
        scale, w, h, int(w * scale), int(h * scale),
    )

    # INTER_CUBIC for small upscale, LANCZOS4 for large
    interp = cv2.INTER_CUBIC if scale <= 2.0 else cv2.INTER_LANCZOS4
    upscaled = cv2.resize(img, None, fx=scale, fy=scale, interpolation=interp)

    # Unsharp mask to recover edges after upscale
    if scale > 1.5:
        gaussian = cv2.GaussianBlur(upscaled, (0, 0), 2)
        upscaled = cv2.addWeighted(upscaled, 1.3, gaussian, -0.3, 0)

    return upscaled


def deskew(gray: np.ndarray) -> np.ndarray:
    """Fix slight rotation in scanned documents."""
    coords = np.column_stack(np.where(gray < 128))
    if len(coords) < 100:
        return gray

    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    if abs(angle) > 10 or abs(angle) < 0.1:
        return gray

    h, w = gray.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        gray, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    logger.debug("Deskewed by %.2f°", angle)
    return rotated


def add_border(img: np.ndarray, size: int = 30) -> np.ndarray:
    """Add white padding — Tesseract needs breathing room."""
    return cv2.copyMakeBorder(
        img, size, size, size, size,
        cv2.BORDER_CONSTANT, value=255,
    )


# ------------------------------------------------------------------ #
#  STANDARD pipeline  (proven best for your invoices)
#
#  The key insight: do NOT binarize.
#  Tesseract's LSTM engine (oem 3) handles grayscale better
#  than thresholded images for low-resolution inputs.
# ------------------------------------------------------------------ #

def preprocess_for_ocr(
    image: Image.Image, min_width: int = 2500
) -> Image.Image:
    """
    Standard pipeline: upscale → gray → light denoise → border.
    No thresholding — LSTM works better on grayscale.
    """
    img = pil_to_cv2(image)

    # 1. Upscale to target width
    img = smart_upscale(img, target_width=min_width)

    # 2. Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 3. Deskew
    gray = deskew(gray)

    # 4. Light denoise — preserve text edges
    #    Small kernel bilateral filter is gentle enough
    gray = cv2.bilateralFilter(gray, 5, 40, 40)

    # 5. CLAHE for local contrast (helps faded text)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # 6. White border
    gray = add_border(gray)

    return cv2_to_pil(gray)


# ------------------------------------------------------------------ #
#  AGGRESSIVE pipeline  (fallback for very bad images)
#
#  Tries harder upscale + stronger sharpening.
#  Still avoids thresholding.
# ------------------------------------------------------------------ #

def preprocess_for_ocr_aggressive(
    image: Image.Image, min_width: int = 3000
) -> Image.Image:
    """
    Aggressive pipeline: bigger upscale, stronger sharpening,
    still grayscale (no binarization).
    """
    img = pil_to_cv2(image)

    # 1. Bigger upscale target
    img = smart_upscale(img, target_width=min_width)

    # 2. Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 3. Deskew
    gray = deskew(gray)

    # 4. Stronger CLAHE
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # 5. Denoise
    gray = cv2.bilateralFilter(gray, 7, 50, 50)

    # 6. Sharpen text
    sharpen_kernel = np.array([[0, -1, 0],
                                [-1,  5, -1],
                                [0, -1, 0]])
    gray = cv2.filter2D(gray, -1, sharpen_kernel)

    # 7. Border
    gray = add_border(gray)

    return cv2_to_pil(gray)


# ------------------------------------------------------------------ #
#  QR code region extraction
# ------------------------------------------------------------------ #

def extract_qr_region(image: Image.Image) -> Image.Image:
    """
    Extract QR code region from Swiss QR-bill invoice.
    Tries contour detection, falls back to bottom-left crop.
    """
    img = pil_to_cv2(image)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    _, thresh = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(
        thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    h, w = img.shape[:2]
    min_qr_size = min(h, w) * 0.05
    max_qr_size = min(h, w) * 0.40

    best_candidate = None
    best_score = 0

    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)

        aspect_ratio = cw / ch if ch > 0 else 0
        if not (0.7 < aspect_ratio < 1.3):
            continue
        if not (min_qr_size < cw < max_qr_size):
            continue

        position_score = y / h
        size_score = cw * ch
        score = position_score * size_score

        if score > best_score:
            best_score = score
            padding = int(cw * 0.15)
            x1 = max(0, x - padding)
            y1 = max(0, y - padding)
            x2 = min(w, x + cw + padding)
            y2 = min(h, y + ch + padding)
            best_candidate = (x1, y1, x2, y2)

    if best_candidate:
        x1, y1, x2, y2 = best_candidate
        cropped = img[y1:y2, x1:x2]
        logger.debug("QR region found: (%d,%d)-(%d,%d)", x1, y1, x2, y2)
        return cv2_to_pil(cropped)

    bottom_left = img[int(h * 0.55):h, 0:int(w * 0.5)]
    logger.debug("QR region not detected, using bottom-left fallback")
    return cv2_to_pil(bottom_left)


# ------------------------------------------------------------------ #
#  PDF → images
# ------------------------------------------------------------------ #

POPPLER_PATH = r"C:\powercoder\AlpineDocs\poppler\poppler-24.08.0\Library\bin"


def pdf_to_images(pdf_path: Path, dpi: int = 300) -> List[Image.Image]:
    """Convert PDF pages to PIL Images."""
    try:
        from pdf2image import convert_from_path
    except ImportError:
        raise ImportError("pdf2image is required. Install: pip install pdf2image")

    # Verify poppler exists
    poppler_bin = Path(POPPLER_PATH)
    pdftoppm = poppler_bin / "pdftoppm.exe"

    if not pdftoppm.exists():
        raise RuntimeError(
            f"pdftoppm.exe not found at: {pdftoppm}\n"
            f"Download Poppler from: "
            f"https://github.com/oschwartz10612/poppler-windows/releases"
        )

    logger.info("Using Poppler at: %s", POPPLER_PATH)
    logger.info("Converting PDF: %s at %d DPI", pdf_path, dpi)

    try:
        images = convert_from_path(
            str(pdf_path),
            dpi=dpi,
            fmt="png",
            grayscale=False,
            thread_count=2,
            poppler_path=POPPLER_PATH,
        )
        logger.info("PDF converted: %d pages", len(images))
        return images

    except Exception as e:
        logger.error("PDF conversion failed: %s", e)
        raise RuntimeError(
            f"Failed to convert PDF: {e}\n"
            f"Poppler path: {POPPLER_PATH}\n"
            f"pdftoppm exists: {pdftoppm.exists()}"
        ) from e