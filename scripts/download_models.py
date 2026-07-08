"""Pre-download all OCR models at build time so runtime doesn't fetch them."""

from ocr_api.ocr import ocr_service

# Pre-load EasyOCR with hi+en only.
# Hindi model covers full Devanagari script (mr/ne/sa share the same glyphs).
# Loading all 4 Devanagari langs (~800MB) OOMs on 512MB free-tier hosts.
from easyocr import Reader
Reader(["hi", "en"], gpu=False, model_storage_directory="/root/.EasyOCR/model/")

# Pre-load PaddleOCR for English (used for non-Devanagari documents)
ocr_service.load("en")
