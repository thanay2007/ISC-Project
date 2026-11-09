FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
WORKDIR /opt/verifex
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr libgomp1 libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt backend/requirements-ocr.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/requirements-ocr.txt \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu 'torch>=2.8,<3'
COPY backend backend
COPY ml ml
RUN useradd --create-home --uid 10001 verifex && mkdir -p /opt/verifex/.verifex \
    && chown verifex:verifex /opt/verifex/.verifex
USER verifex
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.verifex.main:app", "--host", "0.0.0.0", "--port", "8000"]
