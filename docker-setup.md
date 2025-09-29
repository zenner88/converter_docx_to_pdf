# Gotenberg Setup Guide

## Prerequisites
- Docker installed on your system
- Port 3000 available

## Quick Start

### 1. Run Gotenberg Container
```bash
# Pull and run Gotenberg
docker run -d \
  --name gotenberg \
  --restart unless-stopped \
  -p 3000:3000 \
  gotenberg/gotenberg:7

# Verify it's running
docker ps | grep gotenberg
```

### 2. Test Gotenberg
```bash
# Test endpoint
curl http://localhost:3000/health

# Should return: {"status":"up"}
```

### 3. Configure Application
Set environment variables:
```bash
# Enable Gotenberg (default: true)
export USE_GOTENBERG=true

# Gotenberg URL (default: http://localhost:3000)
export GOTENBERG_URL=http://localhost:3000

# Conversion timeout (default: 90 seconds)
export CONVERSION_TIMEOUT=90
```

## Docker Compose Setup

Create `docker-compose.yml`:
```yaml
version: '3.8'

services:
  gotenberg:
    image: gotenberg/gotenberg:7
    container_name: gotenberg
    restart: unless-stopped
    ports:
      - "3000:3000"
    # Optional: Add resource limits
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '1.0'

  converter:
    # Your converter app
    build: .
    ports:
      - "80:80"
    environment:
      - USE_GOTENBERG=true
      - GOTENBERG_URL=http://gotenberg:3000
      - CONVERSION_TIMEOUT=90
    depends_on:
      - gotenberg
```

Run with:
```bash
docker-compose up -d
```

## Production Deployment

### Windows Server
```powershell
# Install Docker Desktop or Docker Engine
# Run Gotenberg
docker run -d --name gotenberg --restart unless-stopped -p 3000:3000 gotenberg/gotenberg:7

# Set environment variables
$env:USE_GOTENBERG="true"
$env:GOTENBERG_URL="http://localhost:3000"

# Start your converter application
python -m uvicorn app:app --host 0.0.0.0 --port 80
```

### Linux Server
```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Run Gotenberg
sudo docker run -d \
  --name gotenberg \
  --restart unless-stopped \
  -p 3000:3000 \
  gotenberg/gotenberg:7

# Set environment variables
export USE_GOTENBERG=true
export GOTENBERG_URL=http://localhost:3000

# Start your converter application
uvicorn app:app --host 0.0.0.0 --port 80
```

## Configuration Options

### Environment Variables
- `USE_GOTENBERG`: Enable/disable Gotenberg (true/false)
- `GOTENBERG_URL`: Gotenberg service URL
- `CONVERSION_TIMEOUT`: Timeout in seconds for conversions

### Fallback Behavior
1. **Primary**: Gotenberg (if enabled and available)
2. **Fallback 1**: LibreOffice (if Gotenberg disabled/failed)
3. **Fallback 2**: MS Word (if previous methods failed)

## Troubleshooting

### Gotenberg Not Accessible
```bash
# Check if container is running
docker ps | grep gotenberg

# Check container logs
docker logs gotenberg

# Test connectivity
curl http://localhost:3000/health
```

### Performance Tuning
```bash
# Run with more memory
docker run -d \
  --name gotenberg \
  --restart unless-stopped \
  -p 3000:3000 \
  --memory=2g \
  --cpus=2 \
  gotenberg/gotenberg:7
```

### Monitoring
```bash
# Monitor container stats
docker stats gotenberg

# View logs
docker logs -f gotenberg
```

## Benefits of Gotenberg Integration

1. **Stability**: No more hanging LibreOffice processes
2. **Performance**: Optimized conversion engine
3. **Scalability**: Easy to scale with multiple containers
4. **Maintenance**: No complex process management
5. **Reliability**: Production-tested solution

## Migration from LibreOffice

The application automatically detects Gotenberg availability:
- If `USE_GOTENBERG=true` and Gotenberg is accessible: Uses Gotenberg
- If Gotenberg fails: Falls back to MS Word
- If `USE_GOTENBERG=false`: Uses old LibreOffice → MS Word flow

This allows for gradual migration and easy rollback if needed.
