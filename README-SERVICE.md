# DOCX to PDF Converter - Service Setup

Service ini akan otomatis restart setiap hari jam 5 pagi menggunakan systemd timer.

## Instalasi Service

Jalankan script instalasi:
```bash
./install-service.sh
```

Script ini akan:
1. Menginstall service systemd untuk converter
2. Mengaktifkan timer untuk restart otomatis jam 5 pagi
3. Memulai service

## Status dan Monitoring

### Cek status service:
```bash
sudo systemctl status converter-service
```

### Cek status timer restart:
```bash
sudo systemctl status converter-restart.timer
```

### Lihat jadwal restart berikutnya:
```bash
sudo systemctl list-timers converter-restart.timer
```

### Lihat log service:
```bash
sudo journalctl -u converter-service -f
```

## Kontrol Manual

### Restart manual:
```bash
sudo systemctl restart converter-service
```

### Stop service:
```bash
sudo systemctl stop converter-service
```

### Start service:
```bash
sudo systemctl start converter-service
```

### Disable auto-restart (hanya stop timer):
```bash
sudo systemctl disable converter-restart.timer
sudo systemctl stop converter-restart.timer
```

### Enable kembali auto-restart:
```bash
sudo systemctl enable converter-restart.timer
sudo systemctl start converter-restart.timer
```

## Uninstall Service

Untuk menghapus service dan kembali ke mode manual:
```bash
./uninstall-service.sh
```

## Konfigurasi Timer

Timer dikonfigurasi untuk restart setiap hari jam 5:00 pagi. Untuk mengubah jadwal, edit file `/etc/systemd/system/converter-restart.timer` dan ubah baris:
```
OnCalendar=*-*-* 05:00:00
```

Contoh jadwal lain:
- `OnCalendar=*-*-* 03:00:00` - Jam 3 pagi
- `OnCalendar=*-*-* 02:30:00` - Jam 2:30 pagi
- `OnCalendar=Mon *-*-* 05:00:00` - Setiap Senin jam 5 pagi

Setelah mengubah, reload systemd:
```bash
sudo systemctl daemon-reload
sudo systemctl restart converter-restart.timer
```

## Troubleshooting

### Service tidak bisa start:
1. Cek log: `sudo journalctl -u converter-service -n 50`
2. Pastikan virtual environment ada: `ls -la .venv/`
3. Pastikan requirements.txt terinstall: `.venv/bin/pip list`

### Timer tidak berjalan:
1. Cek status: `sudo systemctl status converter-restart.timer`
2. Cek jadwal: `sudo systemctl list-timers converter-restart.timer`
3. Restart timer: `sudo systemctl restart converter-restart.timer`

### Port 80 sudah digunakan:
Edit file `/etc/systemd/system/converter-service.service` dan ubah port:
```
ExecStart=/home/zenner/Code/converter_docx_to_pdf/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080
```

Kemudian reload dan restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart converter-service
```
