#!/bin/bash

# Script untuk menginstall dan mengaktifkan service converter dengan restart otomatis jam 5 pagi

echo "Installing DOCX to PDF Converter Service..."

# Copy service files ke systemd directory
sudo cp converter-service.service /etc/systemd/system/
sudo cp converter-restart.service /etc/systemd/system/
sudo cp converter-restart.timer /etc/systemd/system/

# Set permissions
sudo chmod 644 /etc/systemd/system/converter-service.service
sudo chmod 644 /etc/systemd/system/converter-restart.service
sudo chmod 644 /etc/systemd/system/converter-restart.timer

# Reload systemd daemon
sudo systemctl daemon-reload

# Enable dan start main service
sudo systemctl enable converter-service.service
sudo systemctl start converter-service.service

# Enable dan start timer untuk restart otomatis
sudo systemctl enable converter-restart.timer
sudo systemctl start converter-restart.timer

echo "Service installation completed!"
echo ""
echo "Status check:"
sudo systemctl status converter-service.service --no-pager -l
echo ""
echo "Timer status:"
sudo systemctl status converter-restart.timer --no-pager -l
echo ""
echo "Next scheduled restart:"
sudo systemctl list-timers converter-restart.timer --no-pager

echo ""
echo "Useful commands:"
echo "- Check service status: sudo systemctl status converter-service"
echo "- Check timer status: sudo systemctl status converter-restart.timer"
echo "- View logs: sudo journalctl -u converter-service -f"
echo "- Manual restart: sudo systemctl restart converter-service"
echo "- Stop service: sudo systemctl stop converter-service"
echo "- Disable auto-restart: sudo systemctl disable converter-restart.timer"
