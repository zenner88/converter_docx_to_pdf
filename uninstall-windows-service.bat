@echo off
REM Script untuk menghapus Windows Service dan Task Scheduler

echo Uninstalling DOCX to PDF Converter Windows Service...
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

set CURRENT_DIR=%~dp0
set SERVICE_NAME=DocxToPdfConverter

REM Stop and remove service
echo Stopping and removing service...
net stop "%SERVICE_NAME%" >nul 2>&1
if exist "%CURRENT_DIR%nssm.exe" (
    "%CURRENT_DIR%nssm.exe" remove "%SERVICE_NAME%" confirm >nul 2>&1
) else (
    sc delete "%SERVICE_NAME%" >nul 2>&1
)

REM Remove scheduled task
echo Removing scheduled task...
schtasks /delete /tn "RestartDocxToPdfConverter" /f >nul 2>&1

REM Clean up NSSM
if exist "%CURRENT_DIR%nssm.exe" (
    echo Removing NSSM...
    del "%CURRENT_DIR%nssm.exe"
)

echo.
echo Uninstallation completed!
echo You can now run the service manually using: start_server.bat
echo.
pause
