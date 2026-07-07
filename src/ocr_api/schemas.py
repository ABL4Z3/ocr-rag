from pydantic import BaseModel, Field


class OCRLine(BaseModel):
    text: str
    confidence: float | None = None
    bbox: list | None = None


class OCRPage(BaseModel):
    page_number: int
    source: str = Field(description="text-layer, ocr, docx, or image")
    text: str
    lines: list[OCRLine] = Field(default_factory=list)


class OCRResponse(BaseModel):
    filename: str
    content_type: str | None
    page_count: int
    text: str
    pages: list[OCRPage]

