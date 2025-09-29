# Server Deployment Guide - DOCX to PDF Converter

## 📋 Prerequisites

### Windows Server Requirements:
- Windows Server 2016/2019/2022
- Python 3.8+ 
- Microsoft Office/Word installed
- Administrative privileges
- Port 80 available
- Docker (optional, for Gotenberg)

### Linux Server Requirements:
- Ubuntu 18.04+ / CentOS 7+
- Python 3.8+
- LibreOffice installed
- Docker (for Gotenberg)
- Port 80 available

## 🔧 Step 1: Server Preparation

### Windows Server:
```powershell
# 1. Install Python 3.8+
# Download from python.org and install

# 2. Install Git
# Download from git-scm.com

# 3. Verify installations
python --version
git --version

# 4. Install Microsoft Office (if not installed)
# Install from Office installer

# 5. Optional: Install Docker Desktop
# Download from docker.com
```

### Linux Server:
```bash
# 1. Update system
sudo apt update && sudo apt upgrade -y

# 2. Install Python and dependencies
sudo apt install python3 python3-pip python3-venv git -y

# 3. Install LibreOffice
sudo apt install libreoffice -y

# 4. Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
```

## 📂 Step 2: Clone and Setup Project

```bash
# 1. Clone repository
git clone https://github.com/zenner88/converter_docx_to_pdf.git
cd converter_docx_to_pdf

# 2. Switch to Gotenberg branch
git checkout feature/gotenberg-integration

# 3. Create virtual environment
python3 -m venv .venv

# 4. Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux:
source .venv/bin/activate

# 5. Install dependencies
pip install -r requirements.txt
```

## 🐳 Step 3: Setup Gotenberg (Recommended)

### Option A: Docker Compose (Recommended)
```yaml
# Create docker-compose.yml
version: '3.8'

services:
  gotenberg:
    image: gotenberg/gotenberg:7
    container_name: gotenberg
    restart: unless-stopped
    ports:
      - "3000:3000"
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '2.0'
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  converter:
    build: .
    container_name: docx-converter
    restart: unless-stopped
    ports:
      - "80:80"
    environment:
      - USE_GOTENBERG=true
      - GOTENBERG_URL=http://gotenberg:3000
      - CONVERSION_TIMEOUT=90
      - MAX_CONCURRENT_WORKERS=10
    depends_on:
      - gotenberg
    volumes:
      - ./document:/app/document
      - ./logs:/app/logs
```

```bash
# Start services
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs -f
```

### Option B: Manual Docker Setup
```bash
# 1. Run Gotenberg
docker run -d \
  --name gotenberg \
  --restart unless-stopped \
  -p 3000:3000 \
  --memory=2g \
  --cpus=2 \
  gotenberg/gotenberg:7

# 2. Verify Gotenberg
curl http://localhost:3000/health
# Should return: {"status":"up"}
```

## ⚙️ Step 4: Environment Configuration

### Create .env file:
```bash
# Create .env file
cat > .env << EOF
# Gotenberg Configuration
USE_GOTENBERG=true
GOTENBERG_URL=http://localhost:3000
CONVERSION_TIMEOUT=90

# Worker Configuration
MAX_CONCURRENT_WORKERS=10

# Directory Configuration
DOC_LOCAL_DIR=./document

# Logging Configuration
LOG_LEVEL=INFO
EOF
```

### Windows Service Configuration:
```powershell
# Set environment variables (PowerShell)
$env:USE_GOTENBERG="true"
$env:GOTENBERG_URL="http://localhost:3000"
$env:CONVERSION_TIMEOUT="90"
$env:MAX_CONCURRENT_WORKERS="10"
```

### Linux Service Configuration:
```bash
# Set environment variables
export USE_GOTENBERG=true
export GOTENBERG_URL=http://localhost:3000
export CONVERSION_TIMEOUT=90
export MAX_CONCURRENT_WORKERS=10
```

## 🚀 Step 5: Application Deployment

### Option A: Direct Python Execution
```bash
# 1. Activate virtual environment
source .venv/bin/activate  # Linux
# .venv\Scripts\activate   # Windows

# 2. Start application
python -m uvicorn app:app --host 0.0.0.0 --port 80 --workers 1

# Or with more options:
uvicorn app:app \
  --host 0.0.0.0 \
  --port 80 \
  --workers 1 \
  --access-log \
  --log-level info
```

### Option B: Production with Gunicorn (Linux)
```bash
# 1. Install Gunicorn
pip install gunicorn

# 2. Create gunicorn config
cat > gunicorn.conf.py << EOF
bind = "0.0.0.0:80"
workers = 1
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 100
timeout = 300
keepalive = 2
preload_app = True
EOF

# 3. Start with Gunicorn
gunicorn app:app -c gunicorn.conf.py
```

### Option C: Windows Service
```powershell
# 1. Install NSSM (Non-Sucking Service Manager)
# Download from nssm.cc

# 2. Create service
nssm install "DOCX-PDF-Converter" "C:\path\to\python.exe"
nssm set "DOCX-PDF-Converter" Arguments "-m uvicorn app:app --host 0.0.0.0 --port 80"
nssm set "DOCX-PDF-Converter" AppDirectory "C:\path\to\converter_docx_to_pdf"
nssm set "DOCX-PDF-Converter" DisplayName "DOCX to PDF Converter"
nssm set "DOCX-PDF-Converter" Description "DOCX to PDF Conversion Service"

# 3. Set environment variables for service
nssm set "DOCX-PDF-Converter" AppEnvironmentExtra "USE_GOTENBERG=true" "GOTENBERG_URL=http://localhost:3000"

# 4. Start service
nssm start "DOCX-PDF-Converter"
```

## 🔍 Step 6: Testing and Verification

### 1. Health Check:
```bash
# Test application health
curl http://localhost/health

# Expected response:
{
  "status": "ok",
  "service": "DOCX to PDF Converter",
  "conversion_engines": {
    "libreoffice": true,
    "ms_word": true
  },
  "workers_running": 10,
  "queue_size": 0
}
```

### 2. Queue Status:
```bash
curl http://localhost/queue/status
```

### 3. Test Conversion:
```bash
# Test with sample DOCX file
curl -X POST "http://localhost/convert" \
  -F "file=@sample.docx" \
  -F "nomor_urut=TEST001" \
  -F "target_url=http://your-target-server.com/api"
```

## 🔧 Step 7: Production Optimizations

### 1. Reverse Proxy (Nginx):
```nginx
# /etc/nginx/sites-available/docx-converter
server {
    listen 80;
    server_name your-domain.com;
    
    client_max_body_size 50M;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

### 2. Systemd Service (Linux):
```ini
# /etc/systemd/system/docx-converter.service
[Unit]
Description=DOCX to PDF Converter
After=network.target

[Service]
Type=exec
User=www-data
Group=www-data
WorkingDirectory=/path/to/converter_docx_to_pdf
Environment=PATH=/path/to/converter_docx_to_pdf/.venv/bin
Environment=USE_GOTENBERG=true
Environment=GOTENBERG_URL=http://localhost:3000
ExecStart=/path/to/converter_docx_to_pdf/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl enable docx-converter.service
sudo systemctl start docx-converter.service
sudo systemctl status docx-converter.service
```

## 📊 Step 8: Monitoring and Maintenance

### 1. Log Monitoring:
```bash
# Application logs
tail -f logs/app.log

# System logs (Linux)
journalctl -u docx-converter.service -f

# Docker logs
docker logs -f gotenberg
docker logs -f docx-converter
```

### 2. Performance Monitoring:
```bash
# Check resource usage
htop
docker stats

# Check disk space
df -h

# Check queue status
curl http://localhost/queue/status
```

### 3. Backup Strategy:~
```bash
# Backup configuration
tar -czf backup-$(date +%Y%m%d).tar.gz \
  app.py requirements.txt docker-compose.yml .env

# Backup logs (weekly)
tar -czf logs-backup-$(date +%Y%m%d).tar.gz logs/
```

## 🚨 Troubleshooting

### Common Issues:

1. **Gotenberg not accessible:**
   ```bash
   docker ps | grep gotenberg
   docker logs gotenberg
   curl http://localhost:3000/health
   ```

2. **MS Word COM errors (Windows):**
   ```powershell
   # Re-register MS Word
   cd "C:\Program Files\Microsoft Office\root\Office16"
   .\winword.exe /regserver
   ```

3. **LibreOffice hanging:**
   ```bash
   # Kill hanging processes
   pkill -f soffice
   # Or on Windows:
   taskkill /f /im soffice.exe
   ```

4. **Port conflicts:**
   ```bash
   # Check port usage
   netstat -tulpn | grep :80
   # Change port in configuration
   ```

## 🔐 Security Considerations

1. **Firewall Configuration:**
   ```bash
   # Allow only necessary ports
   ufw allow 80/tcp
   ufw allow 3000/tcp  # Only if Gotenberg needs external access
   ```

2. **File Permissions:**
   ```bash
   # Set proper permissions
   chmod 755 /path/to/converter_docx_to_pdf
   chmod 644 app.py requirements.txt
   chmod 600 .env  # Protect environment variables
   ```

3. **Resource Limits:**
   - Set memory limits for Docker containers
   - Configure worker limits
   - Implement rate limiting if needed

## 📈 Scaling Considerations

1. **Horizontal Scaling:**
   - Deploy multiple instances behind load balancer
   - Use shared Redis for queue management
   - Shared file storage (NFS/S3)

2. **Vertical Scaling:**
   - Increase MAX_CONCURRENT_WORKERS
   - Allocate more memory to Gotenberg
   - Use faster storage (SSD)

This guide provides comprehensive deployment instructions for production environments. Choose the appropriate options based on your server setup and requirements.
