from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ocr import ocr_service
from .schemas import OCRResponse


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OCR locally on one file.")
    parser.add_argument("file", type=Path, help="PDF, DOCX, or image file")
    parser.add_argument("--json", action="store_true", help="Print full JSON output")
    args = parser.parse_args()

    response = extract_path(args.file)
    if args.json:
        print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2))
    else:
        print(response.text)


def extract_path(path: Path) -> OCRResponse:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pages = ocr_service.extract_pdf(path)
    elif suffix == ".docx":
        pages = ocr_service.extract_docx(path)
    else:
        pages = [ocr_service.extract_image(path, page_number=1)]

    return OCRResponse(
        filename=path.name,
        content_type=None,
        page_count=len(pages),
        text="\n\n".join(page.text for page in pages if page.text.strip()),
        pages=pages,
    )


if __name__ == "__main__":
    main()

