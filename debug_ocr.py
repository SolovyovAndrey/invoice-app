# debug_ocr.py
# Run: python debug_ocr.py <path_to_invoice_image>

import sys
import subprocess
from pathlib import Path
from PIL import Image
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ─────────────────────────────────────────────
#  1. Check Tesseract installation
# ─────────────────────────────────────────────
print("=" * 60)
print("TESSERACT DIAGNOSTICS")
print("=" * 60)

# Version
result = subprocess.run(
    [pytesseract.pytesseract.tesseract_cmd, "--version"],
    capture_output=True, text=True
)
print(f"\nVersion: {result.stdout.split(chr(10))[0]}")

# Languages
result = subprocess.run(
    [pytesseract.pytesseract.tesseract_cmd, "--list-langs"],
    capture_output=True, text=True
)
installed_langs = [l.strip() for l in result.stdout.strip().split("\n")[1:] if l.strip()]
print(f"Installed languages: {installed_langs}")

required = ["deu", "fra", "ita", "eng"]
missing = [l for l in required if l not in installed_langs]
if missing:
    print(f"\n❌ MISSING LANGUAGES: {missing}")
    print("   This is likely your main problem!")
    print("   Download from: https://github.com/tesseract-ocr/tessdata_best")
    print(r"   Place in: C:\Program Files\Tesseract-OCR\tessdata")
else:
    print("✅ All required languages installed")

# Check tessdata quality (best vs fast)
tessdata_dir = Path(r"C:\Program Files\Tesseract-OCR\tessdata")
for lang in required:
    f = tessdata_dir / f"{lang}.traineddata"
    if f.exists():
        size_mb = f.stat().st_size / (1024 * 1024)
        quality = "tessdata_best ✅" if size_mb > 1 else "tessdata_fast ⚠️ (UPGRADE!)"
        print(f"   {lang}.traineddata: {size_mb:.1f} MB → {quality}")

# ─────────────────────────────────────────────
#  2. Test OCR on actual image
# ─────────────────────────────────────────────
if len(sys.argv) < 2:
    print("\nUsage: python debug_ocr.py <image_path>")
    print("Provide an invoice image to test OCR quality")
    sys.exit(0)

image_path = Path(sys.argv[1])
if not image_path.exists():
    print(f"\nFile not found: {image_path}")
    sys.exit(1)

print(f"\n{'=' * 60}")
print(f"TESTING OCR ON: {image_path.name}")
print(f"{'=' * 60}")

image = Image.open(image_path)
w, h = image.size
print(f"Image size: {w}x{h} pixels")
print(f"Image mode: {image.mode}")

# Create output directory
debug_dir = Path("debug_output")
debug_dir.mkdir(exist_ok=True)

import cv2
import numpy as np


def pil_to_cv2(img):
    if img.mode == "RGBA":
        img = img.convert("RGB")
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def cv2_to_pil(img):
    if len(img.shape) == 2:
        return Image.fromarray(img)
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def test_ocr(name, pil_image, tess_config):
    """Run OCR and print results."""
    print(f"\n--- {name} ---")
    print(f"    Config: {tess_config}")

    text = pytesseract.image_to_string(pil_image, lang="deu+fra+eng", config=tess_config)
    data = pytesseract.image_to_data(
        pil_image, lang="deu+fra+eng", config=tess_config,
        output_type=pytesseract.Output.DICT
    )
    confidences = [int(c) for c in data["conf"] if int(c) > 0]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0

    print(f"    Confidence: {avg_conf:.1f}%")
    print(f"    Text length: {len(text)} chars")
    print(f"    First 300 chars:")
    print(f"    {text[:300]}")
    print()
    return text, avg_conf


# ─────────────────────────────────────────────
#  Test A: Raw image, no preprocessing
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST A: RAW IMAGE (no preprocessing)")
print("=" * 60)
test_ocr("Raw --psm 6", image, "--oem 3 --psm 6")

# ─────────────────────────────────────────────
#  Test B: Just upscale + grayscale
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST B: UPSCALE + GRAYSCALE")
print("=" * 60)

img_cv = pil_to_cv2(image)
h_cv, w_cv = img_cv.shape[:2]
if w_cv < 2000:
    scale = 2000 / w_cv
    img_cv = cv2.resize(img_cv, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
pil_gray = cv2_to_pil(gray)
pil_gray.save(debug_dir / "B_grayscale.png")
test_ocr("Upscale+Gray --psm 6", pil_gray, "--oem 3 --psm 6")

# ─────────────────────────────────────────────
#  Test C: Adaptive threshold
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST C: ADAPTIVE THRESHOLD")
print("=" * 60)

denoised = cv2.bilateralFilter(gray, 9, 75, 75)
adaptive = cv2.adaptiveThreshold(
    denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
    cv2.THRESH_BINARY, 31, 10
)
adaptive = cv2.copyMakeBorder(adaptive, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
pil_adaptive = cv2_to_pil(adaptive)
pil_adaptive.save(debug_dir / "C_adaptive.png")
test_ocr("Adaptive --psm 6", pil_adaptive, "--oem 3 --psm 6")

# ─────────────────────────────────────────────
#  Test D: Otsu threshold
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST D: OTSU THRESHOLD")
print("=" * 60)

_, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
otsu = cv2.copyMakeBorder(otsu, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
pil_otsu = cv2_to_pil(otsu)
pil_otsu.save(debug_dir / "D_otsu.png")
test_ocr("Otsu --psm 6", pil_otsu, "--oem 3 --psm 6")

# ─────────────────────────────────────────────
#  Test E: Watermark removal + Otsu
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST E: WATERMARK REMOVAL + OTSU")
print("=" * 60)

kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (30, 30))
background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
no_watermark = cv2.subtract(background, gray)
no_watermark = cv2.normalize(no_watermark, None, 0, 255, cv2.NORM_MINMAX)
no_watermark = cv2.bitwise_not(no_watermark)
_, wm_otsu = cv2.threshold(no_watermark, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
wm_otsu = cv2.copyMakeBorder(wm_otsu, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
pil_wm = cv2_to_pil(wm_otsu)
pil_wm.save(debug_dir / "E_watermark_removed.png")
test_ocr("WatermarkRemoval+Otsu --psm 6", pil_wm, "--oem 3 --psm 6")

# ─────────────────────────────────────────────
#  Test F: Different PSM modes on best image
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST F: DIFFERENT PSM MODES (on grayscale)")
print("=" * 60)

for psm in [3, 4, 6, 11, 12]:
    test_ocr(f"Gray --psm {psm}", pil_gray, f"--oem 3 --psm {psm}")

# ─────────────────────────────────────────────
#  Test G: preserve_interword_spaces
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST G: PRESERVE INTERWORD SPACES")
print("=" * 60)
test_ocr(
    "Gray+Spaces --psm 6",
    pil_gray,
    "--oem 3 --psm 6 -c preserve_interword_spaces=1"
)

# ─────────────────────────────────────────────
#  Summary
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("DEBUG IMAGES SAVED TO: debug_output/")
print("Open them to visually check what Tesseract sees!")
print("=" * 60)
print("\nFiles:")
for f in sorted(debug_dir.glob("*.png")):
    print(f"  {f}")