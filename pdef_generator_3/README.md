# pdef_generator_3 (LibreOffice)

FastAPI API untuk konversi DOCX/DOC → PDF menggunakan LibreOffice (soffice). Dapat berjalan di Linux/Ubuntu & Docker Linux (tanpa Microsoft Word).

## Endpoint
- GET `/health` → status
- POST `/convert` → upload `file` (multipart/form-data) dengan `.docx`/`.doc`, response: PDF

## Jalankan dengan Docker
```bash
# Dari folder pdef_generator_3/
docker compose up --build
# Akses
# Health: http://127.0.0.1:80/health
# Docs:   http://127.0.0.1:80/docs
```

## Jalankan lokal (tanpa Docker)
```bash
python -m venv .venv
# Windows PowerShell
# .\.venv\Scripts\Activate.ps1
# Linux/macOS
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn app:app --reload
```

## Catatan
- Memerlukan LibreOffice (perintah `soffice`) tersedia di PATH bila menjalankan tanpa Docker.
- Hasil konversi bisa berbeda dibanding Microsoft Word.
