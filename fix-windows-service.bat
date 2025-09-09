@echo off
REM Script untuk memperbaiki konfigurasi Windows Service

echo Fixing DOCX to PDF Converter Windows Service Configuration...
echo.

REM Check if running as administrator
net session >nul 2>&1
if %errorLevel% == 0 (
    echo Running as Administrator - OK
) else (
    echo ERROR: This script must be run as Administrator
    pause
    exit /b 1
)

set CURRENT_DIR=%~dp0
set SERVICE_NAME=DocxToPdfConverter

echo Current directory: %CURRENT_DIR%
echo.

REM Stop service if running
echo Stopping service if running
net stop "%SERVICE_NAME%" >nul 2>&1

REM Reconfigure service with absolute paths
echo Reconfiguring service with correct paths
"%CURRENT_DIR%nssm.exe" set "%SERVICE_NAME%" Application "%CURRENT_DIR%.venv\Scripts\python.exe"
"%CURRENT_DIR%nssm.exe" set "%SERVICE_NAME%" AppParameters "-m uvicorn app:app --host 0.0.0.0 --port 80"
"%CURRENT_DIR%nssm.exe" set "%SERVICE_NAME%" AppDirectory "%CURRENT_DIR%"
"%CURRENT_DIR%nssm.exe" set "%SERVICE_NAME%" AppStdout "%CURRENT_DIR%logs\service.log"
"%CURRENT_DIR%nssm.exe" set "%SERVICE_NAME%" AppStderr "%CURRENT_DIR%logs\service_error.log"

REM Ensure logs directory exists
if not exist "%CURRENT_DIR%logs" mkdir "%CURRENT_DIR%logs"

REM Start service
echo Starting service
net start "%SERVICE_NAME%"

echo.
echo Service Status:
sc query "%SERVICE_NAME%"

echo.
echo If service is running, check: http://localhost:80/health
pause
