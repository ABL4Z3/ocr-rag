# OCR API

Local OCR service for Marathi, Hindi, and English documents using PaddleOCR.

## Local Setup

```powershell
uv venv
uv sync --extra dev
$env:PYTHONPATH="src"
uv run uvicorn ocr_api.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/docs
```

## OCR A File From The Terminal

```powershell
$env:PYTHONPATH="src"
uv run python -m ocr_api.cli path\to\document.pdf
uv run python -m ocr_api.cli path\to\image.jpg --json
```

## API

```http
GET /health
POST /extract
```

`POST /extract` accepts PDF, DOCX, PNG, JPG, JPEG, BMP, TIFF, and WEBP files.
Searchable PDFs use their embedded text layer. Scanned PDF pages and images run through PaddleOCR.

## Language Setting

The default `OCR_LANG=devanagari` is intended for Hindi, Marathi, and English mixed documents. For English-only documents, set:

```powershell
$env:OCR_LANG="en"
```

## Railway

This repo includes a `Dockerfile` and `railway.json`. The Docker build installs the CPU PaddleOCR stack and runs `scripts/download_models.py` so models are cached in the image instead of being fetched on first request.

