# PowerShell script untuk menghapus Windows Service dan scheduled task
# Run as Administrator: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

param(
    [string]$ServiceName = "DocxToPdfConverter"
)

Write-Host "Uninstalling DOCX to PDF Converter Windows Service..." -ForegroundColor Green
Write-Host ""

# Check if running as administrator
if (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "ERROR: This script must be run as Administrator" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as administrator'" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

$CurrentDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$NssmPath = Join-Path $CurrentDir "nssm.exe"
$TaskName = "RestartDocxToPdfConverter"

# Stop and remove service
Write-Host "Stopping and removing service..." -ForegroundColor Yellow
$ExistingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($ExistingService) {
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    
    if (Test-Path $NssmPath) {
        & $NssmPath remove $ServiceName confirm
    } else {
        # Fallback to sc command
        & sc.exe delete $ServiceName
    }
    Write-Host "Service removed successfully" -ForegroundColor Green
} else {
    Write-Host "Service not found - already removed" -ForegroundColor Yellow
}

# Remove scheduled task
Write-Host "Removing scheduled task..." -ForegroundColor Yellow
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Scheduled task removed successfully" -ForegroundColor Green
} else {
    Write-Host "Scheduled task not found - already removed" -ForegroundColor Yellow
}

# Clean up NSSM
if (Test-Path $NssmPath) {
    Write-Host "Removing NSSM..." -ForegroundColor Yellow
    Remove-Item $NssmPath -Force
    Write-Host "NSSM removed successfully" -ForegroundColor Green
}

Write-Host ""
Write-Host "Uninstallation completed successfully!" -ForegroundColor Green
Write-Host "You can now run the service manually using: start_server.bat" -ForegroundColor Cyan
Write-Host ""

Read-Host "Press Enter to exit"
