# Swiss Invoice Processor

Upload invoices (PDF/images), extract data via QR-bill reader + OCR.

## Quick Start

    pip install -r backend/requirements.txt
    python -m uvicorn backend.main:app --reload --port 8000

Open http://localhost:8000

## System Dependencies (install first)

Windows: Install Tesseract from https://github.com/UB-Mannheim/tesseract/wiki
         Install poppler from https://github.com/oschwartz10612/poppler-windows/releases
         Add both to PATH.

Mac:     brew install tesseract tesseract-lang poppler zbar

Linux:   sudo apt install tesseract-ocr tesseract-ocr-deu poppler-utils libzbar0

## Run Tests

    python -m pytest tests/ -v
