from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import fitz
from docx import Document
from fastapi import HTTPException, UploadFile

from .config import settings
from .schemas import OCRLine, OCRPage, OCRResponse

DEVANAGARI_LANGS = frozenset({"hi", "mr", "ne", "sa", "bh", "mai"})

OCR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}


class OCRService:
    def __init__(self) -> None:
        self._engine: Any | None = None

    def load(self) -> None:
        if self._engine is not None:
            return

        from paddleocr import PaddleOCR

        self._engine = PaddleOCR(
            lang=settings.ocr_lang,
            use_doc_orientation_classify=settings.ocr_use_doc_orientation_classify,
            use_doc_unwarping=settings.ocr_use_doc_unwarping,
            use_textline_orientation=settings.ocr_use_textline_orientation,
        )

    async def extract_upload(self, upload: UploadFile) -> OCRResponse:
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
                pages = self.extract_pdf(path)
            elif suffix in DOCX_EXTENSIONS:
                pages = self.extract_docx(path)
            else:
                pages = [self.extract_image(path, page_number=1)]
        finally:
            path.unlink(missing_ok=True)

        text = "\n\n".join(page.text for page in pages if page.text.strip())
        return OCRResponse(
            filename=upload.filename or path.name,
            content_type=upload.content_type,
            page_count=len(pages),
            text=text,
            pages=pages,
        )

    def extract_pdf(self, path: Path) -> list[OCRPage]:
        pages: list[OCRPage] = []
        force_ocr = settings.ocr_lang in DEVANAGARI_LANGS
        with fitz.open(path) as document:
            for index, page in enumerate(document, start=1):
                if not force_ocr:
                    text = page.get_text("text").strip()
                    if text:
                        pages.append(
                            OCRPage(
                                page_number=index,
                                source="text-layer",
                                text=text,
                                lines=[OCRLine(text=line) for line in text.splitlines() if line.strip()],
                            )
                        )
                        continue

                pix = page.get_pixmap(dpi=settings.ocr_dpi, alpha=False)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    image_path = Path(tmp.name)
                pix.save(image_path)
                try:
                    pages.append(self.extract_image(image_path, page_number=index))
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

    def extract_image(self, path: Path, page_number: int) -> OCRPage:
        self.load()
        assert self._engine is not None

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
            rec_texts = data.get("rec_texts") if data.get("rec_texts") is not None else data.get("texts") if data.get("texts") is not None else []
            rec_scores = data.get("rec_scores") if data.get("rec_scores") is not None else data.get("scores") if data.get("scores") is not None else []
            rec_boxes = data.get("rec_boxes") if data.get("rec_boxes") is not None else data.get("rec_polys") if data.get("rec_polys") is not None else data.get("dt_polys") if data.get("dt_polys") is not None else []

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

