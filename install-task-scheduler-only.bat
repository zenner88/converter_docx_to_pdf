@echo off
REM Script untuk setup menggunakan Task Scheduler saja (tanpa Windows Service)

echo Setting up DOCX to PDF Converter using Task Scheduler only...
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
set TASK_NAME=DocxToPdfConverterService
set RESTART_TASK_NAME=RestartDocxToPdfConverter

echo Current directory: %CURRENT_DIR%
echo.

REM Remove existing tasks
echo Removing existing tasks if any
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
schtasks /delete /tn "%RESTART_TASK_NAME%" /f >nul 2>&1

REM Create task to run service at startup and keep it running
echo Creating main service task
schtasks /create /tn "%TASK_NAME%" /tr "cmd /c cd /d \"%CURRENT_DIR%\" && .venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 80" /sc onstart /ru "SYSTEM" /f

REM Create task for daily restart at 5 AM
echo Creating daily restart task
schtasks /create /tn "%RESTART_TASK_NAME%" /tr "schtasks /end /tn \"%TASK_NAME%\" && timeout /t 5 && schtasks /run /tn \"%TASK_NAME%\"" /sc daily /st 05:00 /ru "SYSTEM" /f

REM Start the main task now
echo Starting service task
schtasks /run /tn "%TASK_NAME%"

echo.
echo Setup completed!
echo.
echo Task Status:
schtasks /query /tn "%TASK_NAME%"
echo.
echo Restart Task Status:
schtasks /query /tn "%RESTART_TASK_NAME%"
echo.
echo Service should be running on: http://localhost:80/health
echo.
echo Useful commands:
echo - Start service: schtasks /run /tn "%TASK_NAME%"
echo - Stop service: schtasks /end /tn "%TASK_NAME%"
echo - Check status: schtasks /query /tn "%TASK_NAME%"
pause
