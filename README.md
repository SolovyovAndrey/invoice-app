# 🧾 Swiss Invoice Processor

Upload invoices (PDF/images), extract data via QR-bill reader + OCR.

---

## 📌 Prerequisites

| Tool       | Version  | Purpose                          |
|------------|----------|----------------------------------|
| Python     | >= 3.9   | Runtime                          |
| Tesseract  | >= 5.0   | OCR engine                       |
| Poppler    | latest   | PDF to image conversion          |
| Git        | any      | Clone repository                 |
| pip        | latest   | Package manager                  |

---

## 🔧 System Dependencies (Install First)

### Windows

1. Tesseract OCR:
   - Download and install from: https://github.com/UB-Mannheim/tesseract/wiki
   - Note install path (e.g. C:\Program Files\Tesseract-OCR)
   - Add to System PATH

2. Poppler:
   - Download from: https://github.com/oschwartz10612/poppler-windows/releases
   - Extract to a folder (e.g. C:\poppler)
   - Add C:\poppler\Library\bin to System PATH

3. Verify both are in PATH:
   tesseract --version
   pdfinfo -v

### macOS

brew install tesseract tesseract-lang poppler zbar

### Linux (Ubuntu/Debian)

sudo apt update
sudo apt install tesseract-ocr tesseract-ocr-deu poppler-utils libzbar0

---

## 🌍 Verify Language Packs (FR + DE)

tesseract --list-langs

Expected output should include:
  eng
  fra
  deu

### Install missing languages:

macOS — already included with tesseract-lang

Linux:
  sudo apt install tesseract-ocr-fra tesseract-ocr-deu

Windows:
  1. Download:
     - https://github.com/tesseract-ocr/tessdata/raw/main/fra.traineddata
     - https://github.com/tesseract-ocr/tessdata/raw/main/deu.traineddata
  2. Copy to: C:\Program Files\Tesseract-OCR\tessdata\

---

## 🚀 Quick Start

### Step 1 — Clone the Repository

git clone https://github.com/YOUR_USERNAME/swiss-invoice-processor.git
cd swiss-invoice-processor

### Step 2 — Create Virtual Environment

macOS / Linux:
  python3 -m venv venv
  source venv/bin/activate

Windows:
  python -m venv venv
  venv\Scripts\activate

### Step 3 — Install Python Dependencies

pip install -r backend/requirements.txt

### Step 4 — Configure the App

Edit config.py if needed:

  # Windows
  TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

  # macOS / Linux (usually auto-detected)
  # TESSERACT_CMD = "/usr/local/bin/tesseract"

  TESSERACT_LANGUAGES = "fra+deu+eng"
  OCR_DPI = 300

### Step 5 — Run the Application

python -m uvicorn backend.main:app --reload --port 8000

### Step 6 — Open in Browser

http://localhost:8000

---

## 🧪 Run Tests

python -m pytest tests/ -v

---

## 🗂️ Project Structure

swiss-invoice-processor/
├── backend/
│   ├── main.py             # FastAPI entry point
│   ├── config.py           # Tesseract & OCR settings
│   ├── qr_service.py       # QR detection (OpenCV)
│   ├── ocr_service.py      # OCR extraction (Tesseract)
│   ├── invoice_data.py     # Unified data model
│   └── requirements.txt    # Python dependencies
├── tests/                  # Test suite
└── README.md               # This file

---

## 📊 How It Works

Invoice Image/PDF
       |
       v
  QrService (OpenCV)
       |
       |--- QR found? --- YES ---> InvoiceData (output)
       |
       |--- NO
       |
       v
  OcrService (Tesseract)
       |
       v
  InvoiceData (output)

- QrService: QRCodeDetector + Aruco, 5-step preprocessing, Swiss QR-bill parser
- OcrService: 3-stage fallback, FR + DE regex, PSM variations

---

## ❗ Troubleshooting

| Problem                      | Fix                                              |
|------------------------------|--------------------------------------------------|
| TesseractNotFoundError       | Set correct path in config.py or add to PATH     |
| ModuleNotFoundError: cv2     | pip install opencv-contrib-python                 |
| QR detection fails           | Use opencv-contrib-python (not opencv-python)     |
| OCR returns garbage          | Verify language packs: tesseract --list-langs     |
| PDF conversion fails         | Ensure Poppler is installed and in PATH           |
| pdfinfo not found (Windows)  | Add Poppler bin folder to System PATH             |

---

## 📄 License

MIT