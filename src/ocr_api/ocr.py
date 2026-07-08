from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

import fitz
from docx import Document
from fastapi import HTTPException, UploadFile

from .config import settings
from .schemas import OCRLine, OCRPage, OCRResponse

OCR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}

# PaddleOCR devanagari model outputs romanized transliteration (not Unicode)
# EasyOCR handles Devanagari scripts correctly
DEVANAGARI_LANGS = {"hi", "mr", "ne", "sa"}

LANG_ALIASES = {
    "hindi": "hi",
    "marathi": "mr",
    "nepali": "ne",
    "sanskrit": "sa",
    "english": "en",
}

# ---------------------------------------------------------------------------
# Preserved tokens (URLs, emails, phones)
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
_PHONE_RE = re.compile(r"\+?[\d][\d\s\-\(\)]{6,}[\d]")


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def _has_devanagari(text: str) -> bool:
    return any("\u0900" <= c <= "\u097F" for c in text)


def _detect_language(text: str) -> str:
    """Detect language from Unicode text content."""
    deva_count = sum(1 for c in text if "\u0900" <= c <= "\u097F")
    latin_count = sum(1 for c in text if c.isascii() and c.isalpha())
    total = deva_count + latin_count
    if total == 0:
        return "en"
    deva_ratio = deva_count / total
    if deva_ratio > 0.7:
        return "hi"
    if deva_ratio > 0.1:
        return "hi,en"
    return "en"


def _looks_like_krutidev(text: str) -> bool:
    """Heuristic: is this text Kruti Dev font-encoded (not Unicode)?"""
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 1]
    if len(lines) < 2:
        return False
    kruti_lines = 0
    for line in lines:
        # Skip lines that are clearly URLs or emails
        if _URL_RE.search(line) or _EMAIL_RE.search(line):
            continue
        alpha = [c for c in line if c.isascii() and c.isalpha()]
        if not alpha:
            continue
        uppercase = sum(1 for c in alpha if c.isupper())
        ucase_ratio = uppercase / len(alpha)
        vowels = sum(1 for c in alpha if c.lower() in "aeiou")
        vowel_ratio = vowels / len(alpha)
        specials = sum(1 for c in line if c in "0/|'~#@;,`\\")
        extended = sum(1 for c in line if 127 < ord(c) < 256)

        # Kruti Dev signatures:
        # - very few vowels (consonant-heavy ASCII)
        # - lots of special chars used as vowel signs
        # - extended Latin-1 range (0x80-0xFF) for matras
        # - high uppercase ratio (ka/kha etc mapped to uppercase)
        score = 0
        if vowel_ratio < 0.18:
            score += 2
        if specials >= 2:
            score += 1
        if extended >= 1:
            score += 2
        if ucase_ratio > 0.25:
            score += 1
        if score >= 3:
            kruti_lines += 1

    return kruti_lines / max(len(lines), 1) > 0.15


def _normalize_lang(lang: str | None) -> str | None:
    if not lang or lang.strip().lower() in ("null", "undefined", "none", ""):
        return None
    parts = [LANG_ALIASES.get(p.strip(), p.strip()) for p in lang.split(",")]
    return ",".join(parts)


_COMMON_EN_WORDS = frozenset(
    "the and for are has was not but all any can you this that from with have been "
    "were also its their them about would could should into after other which where "
    "when what each both than then more some these those here there only over such "
    "very college university faculty institute school phone email website www com "
    "dr mr ms prof department".split()
)


def _is_english_line(line: str) -> bool:
    lower = line.strip().lower()
    if not lower:
        return True
    if _URL_RE.search(lower) or _EMAIL_RE.search(lower):
        return True
    words = re.findall(r"[A-Za-z]{3,}", lower)
    if len(words) >= 2 and sum(1 for w in words if w in _COMMON_EN_WORDS) >= 1:
        return True
    if re.search(r"\b[A-Z]\.", line):
        return True
    return False


# ---------------------------------------------------------------------------
# OCRService
# ---------------------------------------------------------------------------


class OCRService:
    def __init__(self) -> None:
        self._engine: Any | None = None
        self._lang: str | None = None
        self._engine_type: str | None = None

    def load(self, lang: str | None = None) -> None:
        target = _normalize_lang(lang) or _normalize_lang(settings.ocr_lang) or "en"
        if self._engine is not None and self._lang == target:
            return

        langs = [code.strip() for code in target.split(",")]
        use_easyocr = any(code in DEVANAGARI_LANGS for code in langs)

        if use_easyocr:
            from easyocr import Reader

            # Use only hi+en models regardless of specific Devanagari lang requested.
            # Hindi model covers the full Devanagari script (shared by mr/ne/sa).
            # Loading all 4 Devanagari models exceeds 512MB RAM on free-tier hosts.
            easyocr_langs = ["hi", "en"]
            self._engine = Reader(
                easyocr_langs,
                gpu=False,
                model_storage_directory="/root/.EasyOCR/model/",
            )
            self._engine_type = "easyocr"
        else:
            from paddleocr import PaddleOCR

            self._engine = PaddleOCR(
                lang=target,
                use_doc_orientation_classify=settings.ocr_use_doc_orientation_classify,
                use_doc_unwarping=settings.ocr_use_doc_unwarping,
                use_textline_orientation=settings.ocr_use_textline_orientation,
            )
            self._engine_type = "paddle"

        self._lang = target

    async def extract_upload(
        self, upload: UploadFile, lang: str | None = None
    ) -> OCRResponse:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in OCR_EXTENSIONS | PDF_EXTENSIONS | DOCX_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail="Supported files: PDF, DOCX, PNG, JPG, JPEG, BMP, TIFF, and WEBP.",
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await upload.read())
            path = Path(tmp.name)

        try:
            if suffix in PDF_EXTENSIONS:
                pages = self.extract_pdf(path, lang=lang)
            elif suffix in DOCX_EXTENSIONS:
                pages = self.extract_docx(path)
            else:
                pages = [self.extract_image(path, page_number=1, lang=lang)]
        finally:
            path.unlink(missing_ok=True)

        text = "\n\n".join(page.text for page in pages if page.text.strip())
        detected_lang = _detect_language(text)
        avg_conf = self._avg_confidence(pages)
        return OCRResponse(
            filename=upload.filename or path.name,
            content_type=upload.content_type,
            page_count=len(pages),
            language=detected_lang,
            avg_confidence=avg_conf,
            text=text,
            pages=pages,
        )

    def _avg_confidence(self, pages: list[OCRPage]) -> float | None:
        scores = [
            line.confidence
            for page in pages
            for line in page.lines
            if line.confidence is not None
        ]
        return round(sum(scores) / len(scores), 4) if scores else None

    def _make_text_page(self, page_number: int, text: str, source: str = "text-layer") -> OCRPage:
        return OCRPage(
            page_number=page_number,
            source=source,
            text=text,
            lines=[OCRLine(text=line) for line in text.splitlines() if line.strip()],
        )

    def extract_pdf(self, path: Path, lang: str | None = None) -> list[OCRPage]:
        pages: list[OCRPage] = []
        with fitz.open(path) as document:
            for index, page in enumerate(document, start=1):
                text = page.get_text("text").strip()
                if text:
                    if _has_devanagari(text):
                        # Unicode text layer — return as-is
                        pages.append(self._make_text_page(index, text))
                        continue

                    if _looks_like_krutidev(text):
                        # Legacy font encoding — render page and OCR with EasyOCR
                        # Font-mapping approach was unreliable (no authoritative mapping table)
                        pix = page.get_pixmap(dpi=settings.ocr_dpi, alpha=False)
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                            image_path = Path(tmp.name)
                        pix.save(image_path)
                        try:
                            pages.append(
                                self.extract_image(image_path, page_number=index, lang=lang)
                            )
                        finally:
                            image_path.unlink(missing_ok=True)
                        continue

                    # English or other script — return as-is
                    pages.append(self._make_text_page(index, text))
                    continue

                # Image-based page — use OCR
                pix = page.get_pixmap(dpi=settings.ocr_dpi, alpha=False)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    image_path = Path(tmp.name)
                pix.save(image_path)
                try:
                    pages.append(
                        self.extract_image(image_path, page_number=index, lang=lang)
                    )
                finally:
                    image_path.unlink(missing_ok=True)
        return pages

    def extract_docx(self, path: Path) -> list[OCRPage]:
        document = Document(path)
        paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs)
        return [
            OCRPage(
                page_number=1,
                source="docx",
                text=text,
                lines=[OCRLine(text=line) for line in paragraphs],
            )
        ]

    def extract_image(
        self, path: Path, page_number: int, lang: str | None = None
    ) -> OCRPage:
        self.load(lang)
        assert self._engine is not None

        if self._engine_type == "easyocr":
            results = self._engine.readtext(str(path))
            lines = []
            for bbox, text, confidence in results:
                text = str(text).strip()
                if not text:
                    continue
                if float(confidence) < 0.01:
                    continue
                lines.append(
                    OCRLine(
                        text=text,
                        confidence=float(confidence),
                        bbox=self._jsonable(bbox),
                    )
                )
        else:
            if hasattr(self._engine, "predict"):
                raw_results = self._engine.predict(str(path))
            else:
                raw_results = self._engine.ocr(str(path))
            lines = self._extract_lines(raw_results)

        return OCRPage(
            page_number=page_number,
            source="ocr" if path.suffix.lower() == ".png" else "image",
            text="\n".join(line.text for line in lines),
            lines=lines,
        )

    def _extract_lines(self, raw_results: Any) -> list[OCRLine]:
        lines: list[OCRLine] = []

        for result in raw_results or []:
            data = self._to_mapping(result)
            rec_texts = (
                data.get("rec_texts")
                if data.get("rec_texts") is not None
                else data.get("texts")
                if data.get("texts") is not None
                else []
            )
            rec_scores = (
                data.get("rec_scores")
                if data.get("rec_scores") is not None
                else data.get("scores")
                if data.get("scores") is not None
                else []
            )
            rec_boxes = (
                data.get("rec_boxes")
                if data.get("rec_boxes") is not None
                else data.get("rec_polys")
                if data.get("rec_polys") is not None
                else data.get("dt_polys")
                if data.get("dt_polys") is not None
                else []
            )

            for index, text in enumerate(rec_texts):
                if not str(text).strip():
                    continue
                lines.append(
                    OCRLine(
                        text=str(text),
                        confidence=self._safe_float(self._at(rec_scores, index)),
                        bbox=self._jsonable(self._at(rec_boxes, index)),
                    )
                )

            if lines:
                continue

            lines.extend(self._extract_legacy_lines(result))

        return lines

    def _to_mapping(self, result: Any) -> dict[str, Any]:
        if isinstance(result, dict):
            nested = result.get("res")
            return nested if isinstance(nested, dict) else result

        json_attr = getattr(result, "json", None)
        if isinstance(json_attr, dict):
            nested = json_attr.get("res")
            return nested if isinstance(nested, dict) else json_attr

        res_attr = getattr(result, "res", None)
        if isinstance(res_attr, dict):
            return res_attr

        return {}

    def _extract_legacy_lines(self, result: Any) -> list[OCRLine]:
        lines: list[OCRLine] = []
        for item in result or []:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            bbox, value = item[0], item[1]
            if isinstance(value, (list, tuple)) and value:
                text = str(value[0])
                score = self._safe_float(value[1] if len(value) > 1 else None)
                lines.append(OCRLine(text=text, confidence=score, bbox=self._jsonable(bbox)))
        return lines

    def _at(self, value: Any, index: int) -> Any:
        try:
            return value[index]
        except Exception:
            return None

    def _safe_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _jsonable(self, value: Any) -> list | None:
        if value is None:
            return None
        if hasattr(value, "tolist"):
            return value.tolist()
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, list):
            return value
        return None


ocr_service = OCRService()
