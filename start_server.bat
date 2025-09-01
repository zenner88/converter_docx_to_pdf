@echo off
echo Starting FastAPI DOCX to PDF Converter...
echo.

REM Activate virtual environment if exists
if exist .venv\Scripts\activate.bat (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
)

REM Start FastAPI server
echo Starting server on http://0.0.0.0:8000
echo Press Ctrl+C to stop
echo.
uvicorn app:app --host 0.0.0.0 --port 8000 --reload

pause
