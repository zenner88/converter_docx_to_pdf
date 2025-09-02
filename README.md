# PDEF Generator API (DOCX → PDF + Forward)

FastAPI service to:
- Accept a DOCX upload along with `nomor_urut` (string) and `target_url`.
- Save DOCX/PDF to local `document/` as `<nomor_urut>.docx|.pdf`.
- Convert DOCX → PDF using `docx2pdf` (requires Microsoft Word on Windows/Mac).
- Forward the PDF to `target_url/check/responseBalikConvert` as form field `docupload`.

## Project Structure
- `app.py`: Main FastAPI endpoint at the project root.
- `document/`: Output folder for saved DOCX/PDF files (gitignored).
- `requirements.txt`: Python dependencies.
- `pdef_generator_3/`: Alternative implementation using LibreOffice (Linux-friendly).

## Requirements
- Python 3.9+
- Windows/Mac with Microsoft Word (required by `docx2pdf`).
  - For Linux, use the service in `pdef_generator_3/app.py` (LibreOffice/soffice) or run on a Windows host.

## Installation
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows PowerShell
python -m pip install -r requirements.txt
```

## Run the Server
```bash
uvicorn app:app --reload --host 0.0.0.0 --port 80
```

Health check:
```bash
curl http://localhost:80/health
```

## Endpoint
### POST /convert
Form-data fields:
- `file`: `.docx` file
- `nomor_urut`: Arbitrary string (sanitized to `[A-Za-z0-9._-]`) used as the filename
- `target_url`: Base URL to receive the PDF (the PDF will be posted to `target_url/check/responseBalikConvert`)

Response (JSON):
```json
{
  "status": "ok",
  "saved_docx": "c:/.../document/ABC-123.docx",
  "saved_pdf": "c:/.../document/ABC-123.pdf",
  "target_post": "https://app.example.com/check/responseBalikConvert",
  "target_status": 200,
  "target_response": {"example": "response atau teks mentah"}
}
```

Example cURL (Windows PowerShell):
```powershell
curl -Method POST http://localhost:80/convert `
  -Form file=@"C:\path\to\file.docx" `
  -Form nomor_urut="ABC-123" `
  -Form target_url="https://app.example.com"
```
Example cURL (bash):
```bash
curl -X POST http://localhost:80/convert \
  -F "file=@/path/to/file.docx" \
  -F "nomor_urut=ABC-123" \
  -F "target_url=https://app.example.com"
```

## Configuration
- `DOC_LOCAL_DIR`: (optional) override the output folder path. Default: `<repo>/document`.

For the LibreOffice (Linux) implementation in `pdef_generator_3/app.py`, additional envs are available:
- `DOC_BASE_DIR` (default: `/var/www/service.sidinarbnn.my.id/html`)
- `DOC_SUB_DIR` (default: `dokumen`)
- `CONVERT_TIMEOUT` (seconds, default: `120`)
- `TARGET_ENDPOINT_SUFFIX` (default: `/check/responseBalikConvert`)

## Notes & Troubleshooting
- "Failed to convert DOCX to PDF" on Windows/Mac usually means Microsoft Word is not available. Ensure Word is installed and accessible.
- For a Linux server, use `pdef_generator_3/app.py` (LibreOffice/soffice) or run a Windows host.
- The `document/` folder is created automatically if missing. Ensure the process has write permissions.
- `target_url` must be reachable from the host running this server.

## License
Internal/Private.
