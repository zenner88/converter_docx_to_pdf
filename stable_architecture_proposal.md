# Stable Architecture Proposal

## Current Issues:
1. Multiple conversion engines causing complexity
2. Process spawning overhead and cleanup issues
3. File lock conflicts with concurrent workers
4. COM/RPC errors in Windows environment
5. Memory leaks and hanging processes

## Proposed Solution: Containerized Single-Engine Approach

### Architecture:
```
Client Request → FastAPI → Redis Queue → Docker Container (LibreOffice) → Response
```

### Benefits:
1. **Isolated Environment**: Each conversion in clean container
2. **No Process Cleanup**: Container dies after conversion
3. **No File Locks**: Each container has own filesystem
4. **Scalable**: Can spin up multiple containers
5. **Predictable**: Same environment every time

### Implementation:
```python
import docker
import redis
from celery import Celery

# Use Celery + Redis for queue management
# Use Docker containers for conversion
# No more process management headaches
```

### Docker Container:
```dockerfile
FROM ubuntu:20.04
RUN apt-get update && apt-get install -y libreoffice
COPY convert.py /app/
ENTRYPOINT ["python", "/app/convert.py"]
```

### Conversion Script:
```python
# Simple, single-purpose conversion
# Input: DOCX file path
# Output: PDF file path
# Exit: Container terminates (auto-cleanup)
```

## Alternative: Use Gotenberg
- Production-ready Docker service
- HTTP API for document conversion
- Handles LibreOffice internally
- No process management needed

```yaml
version: '3'
services:
  gotenberg:
    image: gotenberg/gotenberg:7
    ports:
      - "3000:3000"
```

```python
# Simple HTTP call to Gotenberg
async with httpx.AsyncClient() as client:
    files = {"files": open("document.docx", "rb")}
    response = await client.post("http://gotenberg:3000/forms/libreoffice/convert", files=files)
    pdf_content = response.content
```

## Recommendation:
**Switch to Gotenberg** for immediate stability, or implement containerized approach for custom control.
