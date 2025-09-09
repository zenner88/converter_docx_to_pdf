# DOCX to PDF Converter - Windows Service Setup

Untuk Windows, tersedia 2 metode instalasi service dengan restart otomatis jam 5 pagi:

## Metode 1: Batch Script (Sederhana)

### Instalasi:
1. **Jalankan sebagai Administrator**: Klik kanan Command Prompt → "Run as administrator"
2. Jalankan script instalasi:
```cmd
install-windows-service.bat
```

### Fitur:
- Menggunakan NSSM (Non-Sucking Service Manager)
- Otomatis download NSSM jika belum ada
- Membuat Windows Service
- Membuat Task Scheduler untuk restart jam 5 pagi
- Log tersimpan di folder `logs/`

## Metode 2: PowerShell Script (Advanced)

### Persiapan:
1. **Jalankan sebagai Administrator**: Klik kanan PowerShell → "Run as administrator"
2. Set execution policy (jika belum):
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Instalasi:
```powershell
.\install-windows-powershell.ps1
```

### Instalasi dengan custom waktu restart:
```powershell
.\install-windows-powershell.ps1 -RestartTime "03:00"
```

## Monitoring dan Kontrol

### Cek Status Service:
```cmd
sc query DocxToPdfConverter
```
atau
```powershell
Get-Service -Name DocxToPdfConverter
```

### Kontrol Service:
```cmd
# Start
net start DocxToPdfConverter

# Stop  
net stop DocxToPdfConverter

# Restart
net stop DocxToPdfConverter && net start DocxToPdfConverter
```

### PowerShell Commands:
```powershell
# Start
Start-Service -Name DocxToPdfConverter

# Stop
Stop-Service -Name DocxToPdfConverter

# Restart
Restart-Service -Name DocxToPdfConverter

# Status
Get-Service -Name DocxToPdfConverter | Format-Table -AutoSize
```

### Cek Scheduled Task:
```cmd
schtasks /query /tn "RestartDocxToPdfConverter"
```
atau
```powershell
Get-ScheduledTask -TaskName "RestartDocxToPdfConverter"
```

### View Logs:
```cmd
type logs\service.log
type logs\service_error.log
```
atau
```powershell
Get-Content logs\service.log -Tail 50
Get-Content logs\service_error.log -Tail 50
```

## Uninstall Service

### Batch Script:
```cmd
uninstall-windows-service.bat
```

### PowerShell:
```powershell
.\uninstall-windows-powershell.ps1
```

## Konfigurasi Restart Time

### Mengubah waktu restart (PowerShell):
```powershell
# Hapus task lama
Unregister-ScheduledTask -TaskName "RestartDocxToPdfConverter" -Confirm:$false

# Buat task baru dengan waktu berbeda
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-Command `"Restart-Service -Name 'DocxToPdfConverter' -Force`""
$Trigger = New-ScheduledTaskTrigger -Daily -At "03:00"  # Ubah ke jam 3 pagi
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "RestartDocxToPdfConverter" -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings
```

### Mengubah waktu restart (Command Prompt):
```cmd
schtasks /delete /tn "RestartDocxToPdfConverter" /f
schtasks /create /tn "RestartDocxToPdfConverter" /tr "net stop DocxToPdfConverter && timeout /t 5 && net start DocxToPdfConverter" /sc daily /st 03:00 /ru "SYSTEM" /f
```

## Troubleshooting

### Service tidak bisa start:
1. Cek apakah Python terinstall: `python --version`
2. Cek virtual environment: `dir .venv\Scripts\`
3. Cek logs: `type logs\service_error.log`
4. Cek port 80 tidak digunakan aplikasi lain

### Port 80 sudah digunakan:
Edit service untuk menggunakan port lain:
```cmd
nssm.exe set DocxToPdfConverter Arguments "-m uvicorn app:app --host 0.0.0.0 --port 8080"
net stop DocxToPdfConverter
net start DocxToPdfConverter
```

### Task Scheduler tidak berjalan:
1. Cek Task Scheduler service aktif: `sc query Schedule`
2. Cek task exists: `schtasks /query /tn "RestartDocxToPdfConverter"`
3. Test manual run: `schtasks /run /tn "RestartDocxToPdfConverter"`

### Permission Issues:
- Pastikan menjalankan sebagai Administrator
- Cek User Account Control (UAC) settings
- Pastikan user memiliki hak "Log on as a service"

## Keunggulan Windows Solution:

1. **Native Windows Integration**: Menggunakan Windows Service dan Task Scheduler
2. **Auto-Recovery**: Service otomatis restart jika crash
3. **Logging**: Log tersimpan di file dengan rotation
4. **Easy Management**: Bisa dikontrol via Services.msc dan Task Scheduler
5. **Flexible Scheduling**: Mudah mengubah jadwal restart
6. **No Dependencies**: Tidak perlu install software tambahan (kecuali NSSM yang otomatis didownload)
