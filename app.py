import os
import shutil
import tempfile
from typing import Optional, Dict, Any
import re
import asyncio
import uuid
from datetime import datetime
from dataclasses import dataclass
import logging
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.responses import JSONResponse
from docx2pdf import convert
import httpx

# Setup logging
def setup_logging():
    """Setup logging configuration dengan file rotation"""
    # Buat direktori logs jika belum ada
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # Setup formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [Worker-%(worker_id)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Setup root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # File handler untuk semua logs (dengan rotation)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "converter.log"),
        maxBytes=10*1024*1024,  # 10MB per file
        backupCount=5  # Keep 5 backup files
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Error file handler khusus untuk errors
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, "converter_errors.log"),
        maxBytes=5*1024*1024,  # 5MB per file
        backupCount=3
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)
    
    # Console handler (optional, untuk development)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))
    root_logger.addHandler(console_handler)
    
    return logging.getLogger(__name__)

# Initialize logging
logger = setup_logging()

app = FastAPI(title="DOCX to PDF Converter", version="1.0.0")

# Queue untuk menampung request konversi
conversion_queue = asyncio.Queue()
queue_status: Dict[str, Dict[str, Any]] = {}
queue_workers_running = 0
MAX_CONCURRENT_WORKERS = 7

@dataclass
class ConversionRequest:
    request_id: str
    file_content: bytes
    filename: str
    nomor_urut: str
    target_url: str
    endpoint_type: str  # "convert" atau "convertDua"
    created_at: datetime


async def process_conversion_queue(worker_id: int):
    """Background worker untuk memproses queue konversi dengan multiple worker concurrent"""
    global queue_workers_running
    queue_workers_running += 1
    
    # Setup worker-specific logger
    worker_logger = logging.getLogger(f"worker_{worker_id}")
    worker_logger = logging.LoggerAdapter(worker_logger, {'worker_id': worker_id})
    
    worker_logger.info(f"Conversion queue worker {worker_id} started")
    
    while True:
        try:
            # Ambil request dari queue (akan menunggu jika queue kosong)
            request: ConversionRequest = await conversion_queue.get()
            
            # Update status menjadi processing
            queue_status[request.request_id]["status"] = "processing"
            queue_status[request.request_id]["started_at"] = datetime.now()
            queue_status[request.request_id]["worker_id"] = worker_id
            
            worker_logger.info(f"Processing conversion request {request.request_id} for {request.nomor_urut}")
            
            try:
                # Proses konversi
                result = await process_single_conversion(request, worker_logger)
                
                # Update status menjadi completed
                queue_status[request.request_id]["status"] = "completed"
                queue_status[request.request_id]["completed_at"] = datetime.now()
                queue_status[request.request_id]["result"] = result
                
                worker_logger.info(f"Completed conversion request {request.request_id}")
                
            except Exception as e:
                # Update status menjadi error
                queue_status[request.request_id]["status"] = "error"
                queue_status[request.request_id]["error"] = str(e)
                queue_status[request.request_id]["completed_at"] = datetime.now()
                
                worker_logger.error(f"Failed conversion request {request.request_id}: {e}", exc_info=True)
            
            # Tandai task selesai di queue
            conversion_queue.task_done()
            
        except Exception as e:
            worker_logger.error(f"Queue worker {worker_id} error: {e}", exc_info=True)
            await asyncio.sleep(1)


async def process_single_conversion(request: ConversionRequest, worker_logger) -> Dict[str, Any]:
    """Memproses satu request konversi"""
    # Validasi nama file
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", request.nomor_urut).strip()
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="nomor_urut tidak valid setelah sanitasi")

    # Folder penyimpanan lokal
    base_dir = os.getenv("DOC_LOCAL_DIR", os.path.join(os.path.dirname(__file__), "document"))
    os.makedirs(base_dir, exist_ok=True)

    path_docx = os.path.join(base_dir, f"{safe_name}.docx")
    path_pdf = os.path.join(base_dir, f"{safe_name}.pdf")

    # Simpan file DOCX
    try:
        with open(path_docx, "wb") as f:
            f.write(request.file_content)
    except Exception as e:
        raise Exception(f"Gagal menyimpan file upload: {e}")

    # Hapus PDF lama jika ada
    try:
        if os.path.exists(path_pdf):
            os.remove(path_pdf)
    except Exception:
        pass

    # Konversi DOCX -> PDF
    try:
        convert(path_docx, path_pdf)
    except Exception as e:
        raise Exception(
            f"Gagal konversi DOCX ke PDF. Pastikan menjalankan di Windows/Mac "
            f"dengan Microsoft Word terpasang (docx2pdf membutuhkan Word). Error: {str(e)}"
        )

    if not os.path.exists(path_pdf):
        raise Exception("File PDF tidak ditemukan setelah konversi")
    
    # Check file size
    file_size = os.path.getsize(path_pdf)
    max_size = 5 * 1024 * 1024  # 5MB limit
    if file_size > max_size:
        worker_logger.warning(f"PDF file size {file_size} bytes exceeds recommended limit")
    
    worker_logger.info(f"PDF created successfully - Size: {file_size} bytes, Path: {path_pdf}")

    # Tentukan endpoint berdasarkan tipe
    if request.endpoint_type == "convertDua":
        post_url = f"{request.target_url.rstrip('/')}/check/responseBalikConvertDua"
        max_retries = 3
    else:
        post_url = f"{request.target_url.rstrip('/')}/check/responseBalikConvert"
        max_retries = 0
    
    # Kirim ke target server
    retry_delay = 1
    resp = None
    
    for attempt in range(max_retries + 1):
        try:
            timeout_config = httpx.Timeout(90.0, connect=15.0) if request.endpoint_type == "convertDua" else httpx.Timeout(60.0, connect=10.0)
            
            async with httpx.AsyncClient(timeout=timeout_config) as client:
                with open(path_pdf, "rb") as fpdf:
                    file_size = os.path.getsize(path_pdf)
                    worker_logger.info(f"Attempt {attempt + 1}/{max_retries + 1} - Uploading PDF size: {file_size} bytes to {post_url}")
                    
                    files = {"docupload": (os.path.basename(path_pdf), fpdf, "application/pdf")}
                    headers = {"User-Agent": "FastAPI-DOCX-Converter/1.0"}
                    resp = await client.post(post_url, files=files, headers=headers)
                    
                    # Jika sukses atau bukan server error, keluar dari retry loop
                    if resp.status_code < 500:
                        break
                        
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            worker_logger.warning(f"Attempt {attempt + 1} failed with error: {e}")
            if attempt < max_retries:
                worker_logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
                continue
            else:
                raise Exception(f"Gagal upload ke target setelah {max_retries + 1} percobaan: {e}")
    
    if resp is None:
        raise Exception("Tidak ada response dari target server")
    
    worker_logger.info(f"Target response status: {resp.status_code}")
    worker_logger.debug(f"Target response headers: {dict(resp.headers)}")
    
    resp_text = resp.text
    try:
        resp_json = resp.json()
    except Exception:
        resp_json = None
        
    worker_logger.debug(f"Target response text: {resp_text[:500]}")
    worker_logger.info(f"Sent filename: {os.path.basename(path_pdf)}")
    worker_logger.info(f"Local file size: {os.path.getsize(path_pdf)}")

    # Cleanup files setelah upload sukses
    files_cleaned = False
    try:
        if 200 <= resp.status_code < 300 and resp_json and "upload_data" in resp_json:
            if os.path.exists(path_docx):
                os.remove(path_docx)
                worker_logger.info(f"Deleted local DOCX file: {path_docx}")
            
            if os.path.exists(path_pdf):
                os.remove(path_pdf)
                worker_logger.info(f"Deleted local PDF file: {path_pdf}")
                
            files_cleaned = True
            worker_logger.info("Local files cleaned up successfully")
        else:
            worker_logger.info("Files retained due to upload error or unexpected response")
    except Exception as e:
        worker_logger.warning(f"Failed to cleanup local files: {e}")

    return {
        "status": "ok",
        "saved_docx": path_docx,
        "saved_pdf": path_pdf,
        "target_post": post_url,
        "target_status": resp.status_code,
        "target_response": resp_json if resp_json is not None else resp_text,
        "files_cleaned": files_cleaned
    }


@app.on_event("startup")
async def startup_event():
    """Start queue workers saat aplikasi dimulai"""
    for i in range(MAX_CONCURRENT_WORKERS):
        asyncio.create_task(process_conversion_queue(i + 1))
    logger.info(f"Started {MAX_CONCURRENT_WORKERS} conversion queue workers")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/queue/status")
def get_queue_status():
    """Endpoint untuk melihat status queue"""
    queue_size = conversion_queue.qsize()
    
    # Hitung status berdasarkan kategori
    status_counts = {"queued": 0, "processing": 0, "completed": 0, "error": 0}
    recent_requests = []
    
    for req_id, status_info in queue_status.items():
        status_counts[status_info["status"]] += 1
        recent_requests.append({
            "request_id": req_id,
            "nomor_urut": status_info.get("nomor_urut", "unknown"),
            "status": status_info["status"],
            "created_at": status_info["created_at"].isoformat(),
            "started_at": status_info.get("started_at").isoformat() if status_info.get("started_at") else None,
            "completed_at": status_info.get("completed_at").isoformat() if status_info.get("completed_at") else None,
            "error": status_info.get("error")
        })
    
    # Urutkan berdasarkan waktu pembuatan (terbaru dulu)
    recent_requests.sort(key=lambda x: x["created_at"], reverse=True)
    
    return {
        "queue_size": queue_size,
        "workers_running": queue_workers_running,
        "max_concurrent_workers": MAX_CONCURRENT_WORKERS,
        "status_counts": status_counts,
        "recent_requests": recent_requests[:20]  # Tampilkan 20 request terakhir
    }


@app.post("/convert")
async def convert_docx_to_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    nomor_urut: str = Form(...),
    target_url: str = Form(...),
):
    # Validasi
    filename = file.filename or "uploaded.docx"
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="File harus berformat .docx")
    
    # Baca file content
    try:
        file_content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal membaca file upload: {e}")
    
    # Generate unique request ID
    request_id = str(uuid.uuid4())
    
    # Buat conversion request
    conversion_request = ConversionRequest(
        request_id=request_id,
        file_content=file_content,
        filename=filename,
        nomor_urut=nomor_urut,
        target_url=target_url,
        endpoint_type="convert",
        created_at=datetime.now()
    )
    
    # Tambahkan ke queue status tracking
    queue_status[request_id] = {
        "status": "queued",
        "nomor_urut": nomor_urut,
        "filename": filename,
        "target_url": target_url,
        "endpoint_type": "convert",
        "created_at": conversion_request.created_at
    }
    
    # Tambahkan ke queue
    await conversion_queue.put(conversion_request)
    
    logger.info(f"Added conversion request {request_id} to queue for {nomor_urut}")
    
    return JSONResponse(
        content={
            "status": "queued",
            "request_id": request_id,
            "nomor_urut": nomor_urut,
            "queue_position": conversion_queue.qsize(),
            "message": "Request telah ditambahkan ke antrian. Gunakan /queue/status untuk melihat progress."
        }
    )


@app.post("/convertDua")
async def convert_docx_to_pdf_dua(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    nomor_urut: str = Form(...),
    target_url: str = Form(...),
):
    # Validasi
    filename = file.filename or "uploaded.docx"
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="File harus berformat .docx")
    
    # Baca file content
    try:
        file_content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal membaca file upload: {e}")
    
    # Generate unique request ID
    request_id = str(uuid.uuid4())
    
    # Buat conversion request
    conversion_request = ConversionRequest(
        request_id=request_id,
        file_content=file_content,
        filename=filename,
        nomor_urut=nomor_urut,
        target_url=target_url,
        endpoint_type="convertDua",
        created_at=datetime.now()
    )
    
    # Tambahkan ke queue status tracking
    queue_status[request_id] = {
        "status": "queued",
        "nomor_urut": nomor_urut,
        "filename": filename,
        "target_url": target_url,
        "endpoint_type": "convertDua",
        "created_at": conversion_request.created_at
    }
    
    # Tambahkan ke queue
    await conversion_queue.put(conversion_request)
    
    logger.info(f"Added conversion request {request_id} to queue for {nomor_urut}")
    
    return JSONResponse(
        content={
            "status": "queued",
            "request_id": request_id,
            "nomor_urut": nomor_urut,
            "queue_position": conversion_queue.qsize(),
            "message": "Request telah ditambahkan ke antrian. Gunakan /queue/status untuk melihat progress."
        }
    )
