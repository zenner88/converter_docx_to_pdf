# PowerShell script untuk menginstall Windows Service dengan restart otomatis jam 5 pagi
# Run as Administrator: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

param(
    [string]$ServiceName = "DocxToPdfConverter",
    [string]$DisplayName = "DOCX to PDF Converter Service",
    [string]$RestartTime = "05:00"
)

Write-Host "Installing DOCX to PDF Converter Windows Service..." -ForegroundColor Green
Write-Host ""

# Check if running as administrator
if (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "ERROR: This script must be run as Administrator" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as administrator'" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

$CurrentDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$PythonExe = Join-Path $CurrentDir ".venv\Scripts\python.exe"
$LogDir = Join-Path $CurrentDir "logs"

Write-Host "Current directory: $CurrentDir" -ForegroundColor Cyan
Write-Host ""

# Create logs directory
if (!(Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    Write-Host "Created logs directory: $LogDir" -ForegroundColor Green
}

# Create virtual environment if not exists
$VenvDir = Join-Path $CurrentDir ".venv"
if (!(Test-Path $VenvDir)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
    & "$CurrentDir\.venv\Scripts\activate.ps1"
    pip install -r requirements.txt
    Write-Host "Virtual environment created successfully" -ForegroundColor Green
} else {
    Write-Host "Virtual environment already exists" -ForegroundColor Green
}

# Download and setup NSSM
$NssmPath = Join-Path $CurrentDir "nssm.exe"
if (!(Test-Path $NssmPath)) {
    Write-Host "Downloading NSSM (Non-Sucking Service Manager)..." -ForegroundColor Yellow
    $NssmZip = Join-Path $CurrentDir "nssm.zip"
    $TempDir = Join-Path $CurrentDir "temp"
    
    try {
        Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $NssmZip
        Expand-Archive -Path $NssmZip -DestinationPath $TempDir -Force
        Copy-Item "$TempDir\nssm-2.24\win64\nssm.exe" $NssmPath
        Remove-Item $TempDir -Recurse -Force
        Remove-Item $NssmZip -Force
        Write-Host "NSSM downloaded successfully" -ForegroundColor Green
    } catch {
        Write-Host "Failed to download NSSM: $_" -ForegroundColor Red
        exit 1
    }
}

# Stop existing service if it exists
$ExistingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($ExistingService) {
    Write-Host "Stopping existing service..." -ForegroundColor Yellow
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    & $NssmPath remove $ServiceName confirm
    Start-Sleep -Seconds 2
}

# Install service using NSSM
Write-Host "Installing Windows Service..." -ForegroundColor Yellow
& $NssmPath install $ServiceName $PythonExe
& $NssmPath set $ServiceName Arguments "-m uvicorn app:app --host 0.0.0.0 --port 80"
& $NssmPath set $ServiceName DisplayName $DisplayName
& $NssmPath set $ServiceName Description "FastAPI service for converting DOCX files to PDF"
& $NssmPath set $ServiceName Start SERVICE_AUTO_START
& $NssmPath set $ServiceName AppDirectory $CurrentDir
& $NssmPath set $ServiceName AppStdout "$LogDir\service.log"
& $NssmPath set $ServiceName AppStderr "$LogDir\service_error.log"
& $NssmPath set $ServiceName AppRotateFiles 1
& $NssmPath set $ServiceName AppRotateOnline 1
& $NssmPath set $ServiceName AppRotateBytes 1048576  # 1MB

# Start the service
Write-Host "Starting service..." -ForegroundColor Yellow
Start-Service -Name $ServiceName

# Create scheduled task for daily restart
Write-Host "Creating daily restart task..." -ForegroundColor Yellow
$TaskName = "RestartDocxToPdfConverter"

# Remove existing task if exists
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Create new scheduled task
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-Command `"Restart-Service -Name '$ServiceName' -Force`""
$Trigger = New-ScheduledTaskTrigger -Daily -At $RestartTime
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description "Daily restart for DOCX to PDF Converter Service at $RestartTime"

Write-Host ""
Write-Host "Installation completed successfully!" -ForegroundColor Green
Write-Host ""

# Show status
Write-Host "Service Status:" -ForegroundColor Cyan
Get-Service -Name $ServiceName | Format-Table -AutoSize

Write-Host "Scheduled Task Status:" -ForegroundColor Cyan
Get-ScheduledTask -TaskName $TaskName | Format-Table -AutoSize

Write-Host ""
Write-Host "Useful PowerShell commands:" -ForegroundColor Yellow
Write-Host "- Check service status: Get-Service -Name '$ServiceName'"
Write-Host "- Start service: Start-Service -Name '$ServiceName'"
Write-Host "- Stop service: Stop-Service -Name '$ServiceName'"
Write-Host "- Restart service: Restart-Service -Name '$ServiceName'"
Write-Host "- View logs: Get-Content '$LogDir\service.log' -Tail 50"
Write-Host "- Check scheduled task: Get-ScheduledTask -TaskName '$TaskName'"
Write-Host ""

Read-Host "Press Enter to exit"
