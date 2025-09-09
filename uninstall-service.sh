#!/bin/bash

# Script untuk menghapus service converter dan timer restart otomatis

echo "Uninstalling DOCX to PDF Converter Service..."

# Stop dan disable services
sudo systemctl stop converter-service.service
sudo systemctl disable converter-service.service

sudo systemctl stop converter-restart.timer
sudo systemctl disable converter-restart.timer

sudo systemctl stop converter-restart.service
sudo systemctl disable converter-restart.service

# Remove service files
sudo rm -f /etc/systemd/system/converter-service.service
sudo rm -f /etc/systemd/system/converter-restart.service
sudo rm -f /etc/systemd/system/converter-restart.timer

# Reload systemd daemon
sudo systemctl daemon-reload
sudo systemctl reset-failed

echo "Service uninstallation completed!"
echo "You can now run the service manually using: ./start_server.bat"
