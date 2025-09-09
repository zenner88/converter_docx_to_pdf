@echo off
cd /d "C:\converter_docx_to_pdf"
.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 80
