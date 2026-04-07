FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install poppler for PDF conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install dependencies, prioritizing PyTorch with CUDA support if running on GPU later or CPU basic
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu121

COPY ./app /app/app

EXPOSE 8082

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8082/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082"]
