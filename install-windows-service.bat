@echo off
REM Script untuk menginstall Windows Service dan Task Scheduler untuk restart otomatis jam 5 pagi

echo Installing DOCX to PDF Converter Windows Service...
echo.

REM Check if running as administrator
net session >nul 2>&1
if %errorLevel% == 0 (
    echo Running as Administrator - OK
) else (
    echo ERROR: This script must be run as Administrator
    echo Right-click and select "Run as administrator"
    pause
    exit /b 1
)

REM Get current directory
set CURRENT_DIR=%~dp0
set SERVICE_NAME=DocxToPdfConverter
set SERVICE_DISPLAY_NAME=DOCX to PDF Converter Service

echo Current directory: %CURRENT_DIR%
echo.

REM Create Windows Service using NSSM (Non-Sucking Service Manager)
REM Download NSSM if not exists
if not exist "%CURRENT_DIR%nssm.exe" (
    echo Downloading NSSM (Non-Sucking Service Manager)
    powershell -Command "Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile '%CURRENT_DIR%nssm.zip'"
    powershell -Command "Expand-Archive -Path '%CURRENT_DIR%nssm.zip' -DestinationPath '%CURRENT_DIR%temp'"
    copy "%CURRENT_DIR%temp\nssm-2.24\win64\nssm.exe" "%CURRENT_DIR%nssm.exe"
    rmdir /s /q "%CURRENT_DIR%temp"
    del "%CURRENT_DIR%nssm.zip"
)

REM Stop service if exists
sc query "%SERVICE_NAME%" >nul 2>&1
if %errorLevel% == 0 (
    echo Stopping existing service
    net stop "%SERVICE_NAME%" >nul 2>&1
    "%CURRENT_DIR%nssm.exe" remove "%SERVICE_NAME%" confirm >nul 2>&1
)

REM Create virtual environment if not exists
if not exist "%CURRENT_DIR%.venv" (
    echo Creating virtual environment
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    echo Virtual environment already exists
)

REM Install service using NSSM
echo Installing Windows Service
"%CURRENT_DIR%nssm.exe" install "%SERVICE_NAME%" "%CURRENT_DIR%.venv\Scripts\python.exe"
"%CURRENT_DIR%nssm.exe" set "%SERVICE_NAME%" Arguments "-m uvicorn app:app --host 0.0.0.0 --port 80"
"%CURRENT_DIR%nssm.exe" set "%SERVICE_NAME%" DisplayName "%SERVICE_DISPLAY_NAME%"
"%CURRENT_DIR%nssm.exe" set "%SERVICE_NAME%" Description "FastAPI service for converting DOCX files to PDF"
"%CURRENT_DIR%nssm.exe" set "%SERVICE_NAME%" Start SERVICE_AUTO_START
"%CURRENT_DIR%nssm.exe" set "%SERVICE_NAME%" AppDirectory "%CURRENT_DIR%"
"%CURRENT_DIR%nssm.exe" set "%SERVICE_NAME%" AppStdout "%CURRENT_DIR%logs\service.log"
"%CURRENT_DIR%nssm.exe" set "%SERVICE_NAME%" AppStderr "%CURRENT_DIR%logs\service_error.log"

REM Create logs directory
if not exist "%CURRENT_DIR%logs" mkdir "%CURRENT_DIR%logs"

REM Start the service
echo Starting service
net start "%SERVICE_NAME%"

REM Create Task Scheduler for daily restart at 5 AM
echo Creating daily restart task
schtasks /delete /tn "RestartDocxToPdfConverter" /f >nul 2>&1

schtasks /create /tn "RestartDocxToPdfConverter" /tr "net stop \"%SERVICE_NAME%\" && timeout /t 5 && net start \"%SERVICE_NAME%\"" /sc daily /st 05:00 /ru "SYSTEM" /f

echo.
echo Installation completed!
echo.
echo Service Status:
sc query "%SERVICE_NAME%"
echo.
echo Scheduled Task Status:
schtasks /query /tn "RestartDocxToPdfConverter"
echo.
echo Useful commands:
echo - Check service status: sc query "%SERVICE_NAME%"
echo - Start service: net start "%SERVICE_NAME%"
echo - Stop service: net stop "%SERVICE_NAME%"
echo - Restart service: net stop "%SERVICE_NAME%" ^&^& net start "%SERVICE_NAME%"
echo - View logs: type logs\service.log
echo - View scheduled tasks: schtasks /query /tn "RestartDocxToPdfConverter"
echo.
pause
