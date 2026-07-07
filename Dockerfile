FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# CPU-only PyTorch + EasyOCR (avoids ~1.5GB CUDA deps from torch)
RUN pip install --no-cache-dir torch easyocr --index-url https://download.pytorch.org/whl/cpu

COPY . .
RUN python scripts/download_models.py

EXPOSE 8000
CMD ["uvicorn", "ocr_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

