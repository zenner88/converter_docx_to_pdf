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
import zipfile
import signal
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.responses import JSONResponse
from docx2pdf import convert
import httpx

# Setup logging untuk file
def setup_file_logging():
    """Setup file logging tanpa mengubah print statements"""
    # Buat direktori logs jika belum ada
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # Setup formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Setup file logger
    file_logger = logging.getLogger('converter_file')
    file_logger.setLevel(logging.INFO)
    
    # Clear existing handlers
    file_logger.handlers.clear()
    
    # File handler untuk semua logs (dengan rotation)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "converter.log"),
        maxBytes=10*1024*1024,  # 10MB per file
        backupCount=5  # Keep 5 backup files
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    file_logger.addHandler(file_handler)
    
    # Error file handler khusus untuk errors
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, "converter_errors.log"),
        maxBytes=5*1024*1024,  # 5MB per file
        backupCount=3
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    file_logger.addHandler(error_handler)
    
    return file_logger

# Initialize file logging
file_logger = setup_file_logging()

# Fungsi helper untuk print + log ke file
def log_print(message: str, level: str = "INFO"):
    """Print ke console dan simpan ke file log"""
    print(message)
    
    # Simpan juga ke file
    if level == "ERROR":
        file_logger.error(message.replace("ERROR: ", ""))
    elif level == "WARNING":
        file_logger.warning(message.replace("WARNING: ", ""))
    elif level == "DEBUG":
        file_logger.debug(message.replace("DEBUG: ", ""))
    else:
        file_logger.info(message.replace("INFO: ", ""))

app = FastAPI(title="DOCX to PDF Converter", version="1.0.0")

# Queue untuk menampung request konversi
conversion_queue = asyncio.Queue()
queue_status: Dict[str, Dict[str, Any]] = {}
queue_workers_running = 0
MAX_CONCURRENT_WORKERS = 10  # Reduced from 10 to avoid COM threading issues

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
    
    log_print(f"INFO: Conversion queue worker {worker_id} started")
    
    while True:
        try:
            # Ambil request dari queue (akan menunggu jika queue kosong)
            request: ConversionRequest = await conversion_queue.get()
            
            # Update status menjadi processing
            queue_status[request.request_id]["status"] = "processing"
            queue_status[request.request_id]["started_at"] = datetime.now()
            queue_status[request.request_id]["worker_id"] = worker_id
            
            log_print(f"INFO: Worker {worker_id} processing conversion request {request.request_id} for {request.nomor_urut}")
            
            try:
                # Proses konversi
                result = await process_single_conversion(request)
                
                # Update status menjadi completed
                queue_status[request.request_id]["status"] = "completed"
                queue_status[request.request_id]["completed_at"] = datetime.now()
                queue_status[request.request_id]["result"] = result
                
                log_print(f"INFO: Worker {worker_id} completed conversion request {request.request_id}")
                
            except Exception as e:
                # Update status menjadi error
                queue_status[request.request_id]["status"] = "error"
                queue_status[request.request_id]["error"] = str(e)
                queue_status[request.request_id]["completed_at"] = datetime.now()
                
                log_print(f"ERROR: Worker {worker_id} failed conversion request {request.request_id}: {e}", "ERROR")
            
            # Tandai task selesai di queue
            conversion_queue.task_done()
            
        except Exception as e:
            log_print(f"ERROR: Queue worker {worker_id} error: {e}", "ERROR")
            await asyncio.sleep(1)


def validate_docx_file(file_path: str) -> bool:
    """Validasi sederhana: pastikan file bisa dibuka sebagai ZIP dan punya struktur dasar DOCX.
    Tujuan: hanya mendeteksi file corrupt/tidak bisa dibuka. Sangat permisif."""
    try:
        with zipfile.ZipFile(file_path, 'r') as zip_file:
            # Test integritas ZIP (akan return nama file rusak jika ada)
            bad_file = zip_file.testzip()
            if bad_file is not None:
                log_print(f"ERROR: ZIP corruption detected in entry: {bad_file}", "ERROR")
                return False

            contents = zip_file.namelist()

            # Cek minimal struktur DOCX: folder word/ dan file utama document.xml
            if not any(name.startswith('word/') for name in contents):
                log_print("ERROR: Missing 'word/' folder in DOCX", "ERROR")
                return False

            if 'word/document.xml' not in contents:
                log_print("ERROR: Missing 'word/document.xml' in DOCX", "ERROR")
                return False

            # Coba baca sebagian kecil dari document.xml untuk memastikan bisa dibaca
            try:
                sample = zip_file.read('word/document.xml')[:100]
                _ = len(sample)  # trigger read
            except Exception as e:
                log_print(f"ERROR: Unable to read 'word/document.xml': {e}", "ERROR")
                return False

            log_print("INFO: Simple DOCX validation passed (file can be opened and basic structure present)")
            return True
    except zipfile.BadZipFile:
        log_print("ERROR: File is not a valid ZIP/DOCX (corrupt)", "ERROR")
        return False
    except Exception as e:
        # Permisif: jika error tak terduga, anggap gagal untuk keamanan
        log_print(f"ERROR: Simple DOCX validation error: {e}", "ERROR")
        return False


def validate_docx_content(file_content: bytes) -> tuple[bool, str]:
    """Validasi awal yang sederhana untuk memastikan file bukan corrupt.
    Hanya cek bisa dibuka sebagai ZIP dan memiliki struktur dasar DOCX."""
    try:
        # Buat temporary file lalu coba buka sebagai ZIP
        with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as temp_file:
            temp_file.write(file_content)
            temp_file.flush()

            try:
                with zipfile.ZipFile(temp_file.name, 'r') as zip_file:
                    names = zip_file.namelist()
                    if not any(n.startswith('word/') for n in names):
                        return False, "Folder 'word/' tidak ditemukan"
                    if 'word/document.xml' not in names:
                        return False, "File 'word/document.xml' tidak ditemukan"
                    # Coba baca sedikit untuk memastikan dapat diakses
                    _ = zip_file.read('word/document.xml')[:64]
                return True, "File dapat dibuka dan struktur dasar tersedia"
            except zipfile.BadZipFile:
                return False, "File corrupt/bukan ZIP DOCX yang valid"
            except Exception as e:
                return False, f"Gagal membuka konten DOCX: {e}"
            finally:
                try:
                    os.unlink(temp_file.name)
                except Exception:
                    pass
    except Exception as e:
        return False, f"Error validasi awal: {e}"


def convert_with_timeout(docx_path: str, pdf_path: str, timeout_seconds: int = 60) -> bool:
    """Konversi DOCX ke PDF dengan timeout protection (docx2pdf)."""
    def conversion_task():
        try:
            # Initialize COM untuk thread ini (Windows only)
            import sys
            if sys.platform == "win32":
                try:
                    import pythoncom
                    pythoncom.CoInitialize()
                    log_print("DEBUG: COM initialized for conversion thread", "DEBUG")
                except ImportError:
                    log_print("WARNING: pythoncom not available, COM may not work properly", "WARNING")
                except Exception as e:
                    log_print(f"WARNING: COM initialization failed: {e}", "WARNING")
            
            # Lakukan konversi (menggunakan Microsoft Word/Automator tergantung platform)
            convert(docx_path, pdf_path)
            
            # Cleanup COM
            if sys.platform == "win32":
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                    log_print("DEBUG: COM uninitialized for conversion thread", "DEBUG")
                except Exception:
                    pass
            
            return True
        except Exception as e:
            log_print(f"ERROR: Conversion failed: {e}", "ERROR")
            # Cleanup COM jika error
            try:
                import sys as _sys
                if _sys.platform == "win32":
                    import pythoncom as _pythoncom
                    _pythoncom.CoUninitialize()
            except Exception:
                pass
            return False
    
    # Gunakan ThreadPoolExecutor dengan timeout
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            future = executor.submit(conversion_task)
            result = future.result(timeout=timeout_seconds)
            return result
        except FutureTimeoutError:
            log_print(f"ERROR: Conversion timeout after {timeout_seconds} seconds", "ERROR")
            # Coba terminate proses yang hang
            try:
                future.cancel()
            except:
                pass
            return False
        except Exception as e:
            log_print(f"ERROR: Conversion executor error: {e}", "ERROR")
            return False


async def process_single_conversion(request: ConversionRequest) -> Dict[str, Any]:
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

    # Hapus file lama jika ada (DOCX dan PDF)
    try:
        if os.path.exists(path_docx):
            os.remove(path_docx)
            log_print(f"INFO: Removed existing DOCX file: {path_docx}")
    except Exception as e:
        log_print(f"WARNING: Failed to remove existing DOCX file: {e}", "WARNING")
    
    try:
        if os.path.exists(path_pdf):
            os.remove(path_pdf)
            log_print(f"INFO: Removed existing PDF file: {path_pdf}")
    except Exception as e:
        log_print(f"WARNING: Failed to remove existing PDF file: {e}", "WARNING")

    # Simpan file DOCX
    try:
        with open(path_docx, "wb") as f:
            f.write(request.file_content)
        log_print(f"INFO: Saved new DOCX file: {path_docx}")
    except Exception as e:
        raise Exception(f"Gagal menyimpan file upload: {e}")

    # Validasi file DOCX sebelum konversi (dinonaktifkan sementara sesuai permintaan)
    # log_print("INFO: Validating DOCX file structure...")
    # if not validate_docx_file(path_docx):
    #     # Cleanup file yang corrupt
    #     try:
    #         if os.path.exists(path_docx):
    #             os.remove(path_docx)
    #     except:
    #         pass
    #     raise Exception("File DOCX corrupt atau tidak valid. Silakan periksa file dan coba lagi.")
    log_print("INFO: Skipping DOCX validation (temporary)")

    # Konversi DOCX -> PDF dengan timeout protection
    log_print("INFO: Starting DOCX to PDF conversion with timeout protection (90s)...")
    conversion_timeout = 90  # 90 detik timeout
    
    conversion_success = await asyncio.get_event_loop().run_in_executor(
        None, convert_with_timeout, path_docx, path_pdf, conversion_timeout
    )
    
    if not conversion_success:
        # Cleanup files jika konversi gagal
        try:
            if os.path.exists(path_docx):
                os.remove(path_docx)
            if os.path.exists(path_pdf):
                os.remove(path_pdf)
        except:
            pass
        raise Exception(
            f"Gagal konversi DOCX ke PDF. Kemungkinan file corrupt, timeout, atau "
            f"Microsoft Word tidak tersedia. Pastikan menjalankan di Windows/Mac "
            f"dengan Microsoft Word terpasang."
        )

    if not os.path.exists(path_pdf):
        raise Exception("File PDF tidak ditemukan setelah konversi")
    
    # Check file size
    file_size = os.path.getsize(path_pdf)
    max_size = 5 * 1024 * 1024  # 5MB limit
    if file_size > max_size:
        log_print(f"WARNING: PDF file size {file_size} bytes exceeds recommended limit", "WARNING")
    
    log_print(f"INFO: PDF created successfully - Size: {file_size} bytes, Path: {path_pdf}")

    # Tentukan endpoint berdasarkan tipe
    if request.endpoint_type == "convertDua":
        post_url = f"{request.target_url.rstrip('/')}/check/responseBalikConvertDua"
        max_retries = 3
    else:
        post_url = f"{request.target_url.rstrip('/')}/check/responseBalikConvert"
        max_retries = 3
    
    # Kirim ke target server
    retry_delay = 1
    resp = None
    
    for attempt in range(max_retries + 1):
        try:
            timeout_config = httpx.Timeout(90.0, connect=15.0) if request.endpoint_type == "convertDua" else httpx.Timeout(60.0, connect=10.0)
            
            async with httpx.AsyncClient(timeout=timeout_config) as client:
                with open(path_pdf, "rb") as fpdf:
                    file_size = os.path.getsize(path_pdf)
                    log_print(f"DEBUG: Attempt {attempt + 1}/{max_retries + 1} - Uploading PDF size: {file_size} bytes to {post_url}", "DEBUG")
                    
                    files = {"docupload": (os.path.basename(path_pdf), fpdf, "application/pdf")}
                    headers = {"User-Agent": "FastAPI-DOCX-Converter/1.0"}
                    # Add data parameter to force overwrite existing files
                    data = {"overwrite": "true", "force_replace": "1"}
                    log_print(f"DEBUG: Sending overwrite parameters: {data}", "DEBUG")
                    log_print(f"DEBUG: Uploading file: {os.path.basename(path_pdf)}", "DEBUG")
                    resp = await client.post(post_url, files=files, headers=headers, data=data)
                    
                    # Jika sukses atau bukan server error, keluar dari retry loop
                    if resp.status_code < 500:
                        break
                        
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            log_print(f"DEBUG: Attempt {attempt + 1} failed with error: {e}", "DEBUG")
            if attempt < max_retries:
                log_print(f"DEBUG: Retrying in {retry_delay} seconds...", "DEBUG")
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
                continue
            else:
                raise Exception(f"Gagal upload ke target setelah {max_retries + 1} percobaan: {e}")
    
    if resp is None:
        raise Exception("Tidak ada response dari target server")
    
    log_print(f"DEBUG: Target response status: {resp.status_code}", "DEBUG")
    log_print(f"DEBUG: Target response headers: {dict(resp.headers)}", "DEBUG")
    
    resp_text = resp.text
    try:
        resp_json = resp.json()
    except Exception:
        resp_json = None
        
    log_print(f"DEBUG: Target response text: {resp_text[:500]}", "DEBUG")
    log_print(f"DEBUG: Full target response: {resp_text}", "DEBUG")
    
    # Log file info yang dikirim
    log_print(f"DEBUG: Sent filename: {os.path.basename(path_pdf)}", "DEBUG")
    log_print(f"DEBUG: Local file exists: {os.path.exists(path_pdf)}", "DEBUG")
    log_print(f"DEBUG: Local file size: {os.path.getsize(path_pdf) if os.path.exists(path_pdf) else 'N/A'}", "DEBUG")

    # Cleanup files setelah upload sukses
    files_cleaned = False
    try:
        if 200 <= resp.status_code < 300 and resp_json and "upload_data" in resp_json:
            # Delete local files after successful upload
            if os.path.exists(path_docx):
                os.remove(path_docx)
                log_print(f"INFO: Deleted local DOCX file: {path_docx}")
            
            if os.path.exists(path_pdf):
                os.remove(path_pdf)
                log_print(f"INFO: Deleted local PDF file: {path_pdf}")
                
            files_cleaned = True
            log_print("INFO: Local files cleaned up successfully")
        else:
            log_print("INFO: Files retained due to upload error or unexpected response")
    except Exception as e:
        log_print(f"WARNING: Failed to cleanup local files: {e}", "WARNING")

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
    log_print(f"INFO: Started {MAX_CONCURRENT_WORKERS} conversion queue workers")


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
    
    # Validasi awal dinonaktifkan sementara sesuai permintaan
    # is_valid, validation_message = validate_docx_content(file_content)
    # if not is_valid:
    #     raise HTTPException(status_code=400, detail=f"File DOCX tidak valid: {validation_message}")
    # log_print(f"INFO: Initial file validation passed for {nomor_urut}: {validation_message}")
    log_print(f"INFO: Skipping initial DOCX validation for {nomor_urut} (temporary)")
    
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
    
    log_print(f"INFO: Added conversion request {request_id} to queue for {nomor_urut}")
    
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
    
    # Validasi awal dinonaktifkan sementara sesuai permintaan
    # is_valid, validation_message = validate_docx_content(file_content)
    # if not is_valid:
    #     raise HTTPException(status_code=400, detail=f"File DOCX tidak valid: {validation_message}")
    # log_print(f"INFO: Initial file validation passed for {nomor_urut}: {validation_message}")
    log_print(f"INFO: Skipping initial DOCX validation for {nomor_urut} (temporary)")
    
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
    
    log_print(f"INFO: Added conversion request {request_id} to queue for {nomor_urut}")
    
    return JSONResponse(
        content={
            "status": "queued",
            "request_id": request_id,
            "nomor_urut": nomor_urut,
            "queue_position": conversion_queue.qsize(),
            "message": "Request telah ditambahkan ke antrian. Gunakan /queue/status untuk melihat progress."
        }
    )
