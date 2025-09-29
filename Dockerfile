# DOCX to PDF Converter with Gotenberg Integration
# Supports Gotenberg (primary) and LibreOffice (fallback) conversion engines
# MS Word COM interface only available on Windows hosts

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    USE_GOTENBERG=true \
    GOTENBERG_URL=http://gotenberg:3000 \
    CONVERSION_TIMEOUT=90 \
    MAX_CONCURRENT_WORKERS=10

WORKDIR /app

# System dependencies including LibreOffice and fonts for better PDF fidelity
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libreoffice \
    libreoffice-writer \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-noto \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/document /app/logs

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:80/health || exit 1

EXPOSE 80

# Production command (remove --reload for production)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "80", "--workers", "1"]
