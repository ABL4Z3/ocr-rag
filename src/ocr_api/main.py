from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .ocr import ocr_service
from .schemas import OCRResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Always pre-load EasyOCR at startup (hi+en models cover all Devanagari scripts).
    # Lazy loading causes OOM on first request on memory-constrained hosts; pre-loading
    # surfaces the OOM at startup (health check fails) and keeps the model resident.
    ocr_service.load("hi")
    yield


app = FastAPI(title=settings.project_name, version=settings.version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "running", "service": settings.project_name}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/extract", response_model=OCRResponse)
async def extract(file: UploadFile = File(...), lang: str | None = None) -> OCRResponse:
    return await ocr_service.extract_upload(file, lang=lang)

