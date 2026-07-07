"""Pre-download all OCR models at build time so runtime doesn't fetch them."""

from ocr_api.ocr import ocr_service

# Pre-load EasyOCR for all Devanagari languages (hi, mr, ne, sa)
# This caches detection + recognition models in ~/.EasyOCR/model/
from easyocr import Reader
Reader(["hi", "mr", "ne", "sa"], gpu=False, model_storage_directory="/root/.EasyOCR/model/")

# Pre-load PaddleOCR for English (used for non-Devanagari documents)
ocr_service.load("en")
