# NOTE: docx2pdf (MS Word) will NOT work inside this Linux container. However, we enable
# LibreOffice-based conversion so /convert can succeed via LibreOffice headless.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps including LibreOffice and common fonts for better PDF fidelity
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libreoffice \
    libreoffice-writer \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-noto \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 80

# Use --reload for DX; remove in production
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "80", "--reload"]
