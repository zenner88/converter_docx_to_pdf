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
import sys
import subprocess
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None
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

# Filter untuk menyembunyikan access log GET /queue/status dari uvicorn
class _QueueStatusAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        # Drop log yang berisi path /queue/status
        return "/queue/status" not in msg

def enable_queue_status_log_suppression():
    try:
        access_logger = logging.getLogger("uvicorn.access")
        access_logger.addFilter(_QueueStatusAccessLogFilter())
        log_print("INFO: Uvicorn access log for GET /queue/status is suppressed")
    except Exception as e:
        log_print(f"WARNING: Failed to add access log filter: {e}", "WARNING")

app = FastAPI(title="DOCX to PDF Converter", version="1.0.0")

# Aktifkan suppression untuk akses log /queue/status
enable_queue_status_log_suppression()

# Queue untuk menampung request konversi
conversion_queue = asyncio.Queue()
queue_status: Dict[str, Dict[str, Any]] = {}
queue_workers_running = 0
MAX_CONCURRENT_WORKERS = 10  # Increased workers for better throughput

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
                
                # Clean up hanging processes after failures
                try:
                    cleanup_hanging_processes()
                except Exception as cleanup_error:
                    log_print(f"WARNING: Process cleanup after error failed: {cleanup_error}", "WARNING")
            
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
    """Konversi DOCX ke PDF dengan timeout protection (docx2pdf) dengan improved COM handling."""
    def conversion_task():
        com_initialized = False
        try:
            # Initialize COM untuk thread ini (Windows only) dengan apartment threading
            import sys
            if sys.platform == "win32":
                try:
                    import pythoncom
                    # Use COINIT_APARTMENTTHREADED untuk better stability
                    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
                    com_initialized = True
                    log_print("DEBUG: COM initialized with apartment threading", "DEBUG")
                except ImportError:
                    log_print("WARNING: pythoncom not available, COM may not work properly", "WARNING")
                except Exception as e:
                    log_print(f"WARNING: COM initialization failed: {e}", "WARNING")
            
            # Lakukan konversi (menggunakan Microsoft Word/Automator tergantung platform)
            # Note: On some Windows environments, docx2pdf works more reliably when the output
            #      parameter is a DIRECTORY instead of a FILE path. We'll direct output to the
            #      target directory and then move/rename to the desired file path if needed.
            outdir = os.path.dirname(pdf_path) or os.getcwd()
            os.makedirs(outdir, exist_ok=True)
            convert(docx_path, outdir)

            # Ensure produced file exists; if target filename differs, move it
            produced_pdf = os.path.join(
                outdir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
            )
            if not os.path.exists(produced_pdf):
                raise Exception("docx2pdf did not produce expected PDF output")

            if os.path.abspath(produced_pdf) != os.path.abspath(pdf_path):
                try:
                    if os.path.exists(pdf_path):
                        os.remove(pdf_path)
                    shutil.move(produced_pdf, pdf_path)
                except Exception as move_err:
                    raise Exception(f"Failed to move docx2pdf output to target path: {move_err}")
            
            # Cleanup COM
            if sys.platform == "win32" and com_initialized:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                    log_print("DEBUG: COM uninitialized for conversion thread", "DEBUG")
                except Exception as e:
                    log_print(f"WARNING: COM cleanup failed: {e}", "WARNING")
            
            return True
        except Exception as e:
            error_msg = str(e)
            log_print(f"ERROR: Conversion failed: {error_msg}", "ERROR")
            
            # Check for specific COM errors
            if "-2147023170" in error_msg or "remote procedure call failed" in error_msg.lower():
                log_print("ERROR: COM/RPC failure detected - MS Word may be unavailable or hanging", "ERROR")
            elif "0x800706be" in error_msg:
                log_print("ERROR: RPC server unavailable - MS Word service may be down", "ERROR")
            
            # Cleanup COM jika error
            if sys.platform == "win32" and com_initialized:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
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
            log_print(f"ERROR: Conversion timeout after {timeout_seconds} seconds - likely MS Word hang", "ERROR")
            # Coba terminate proses yang hang
            try:
                future.cancel()
            except:
                pass
            return False
        except Exception as e:
            log_print(f"ERROR: Conversion executor error: {e}", "ERROR")
            return False


def _find_soffice_executable() -> Optional[str]:
    """Cari executable LibreOffice (soffice) dengan beberapa strategi.
    Urutan: ENV var -> lokasi default Windows -> PATH.
    """
    # 1) Cek dari ENV var LIBREOFFICE_PATH (bisa file atau folder)
    env_path = os.getenv("LIBREOFFICE_PATH", "").strip().strip('"')
    if env_path:
        try:
            candidate_paths = []
            if os.path.isdir(env_path):
                # Di Windows, prefer soffice.com untuk non-GUI
                if sys.platform == "win32":
                    candidate_paths += [
                        os.path.join(env_path, "soffice.com"),
                        os.path.join(env_path, "soffice.exe"),
                    ]
                else:
                    candidate_paths.append(os.path.join(env_path, "soffice"))
            else:
                candidate_paths.append(env_path)

            for p in candidate_paths:
                if os.path.isfile(p):
                    log_print(f"INFO: Using LibreOffice from LIBREOFFICE_PATH: {p}")
                    return p
        except Exception:
            pass

    # 2) Cek lokasi default Windows
    if sys.platform == "win32":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        default_dirs = [
            os.path.join(program_files, "LibreOffice", "program"),
            os.path.join(program_files_x86, "LibreOffice", "program"),
        ]
        for d in default_dirs:
            for exe in ("soffice.com", "soffice.exe"):
                p = os.path.join(d, exe)
                if os.path.isfile(p):
                    log_print(f"INFO: Found LibreOffice at default Windows path: {p}")
                    return p

    # 3) Coba beberapa nama umum via PATH
    for name in ["soffice", "libreoffice", "soffice.com"]:
        path = shutil.which(name)
        if path:
            log_print(f"INFO: Found LibreOffice via PATH: {path}")
            return path

    return None


def check_conversion_engines() -> Dict[str, bool]:
    """Check availability of conversion engines."""
    engines = {
        "libreoffice": False,
        "ms_word": False
    }
    
    # Check LibreOffice
    soffice = _find_soffice_executable()
    if soffice:
        try:
            # Quick version check to verify LibreOffice is working
            result = subprocess.run(
                [soffice, "--version"],
                capture_output=True,
                timeout=10,
                text=True
            )
            if result.returncode == 0:
                engines["libreoffice"] = True
                log_print(f"INFO: LibreOffice available: {result.stdout.strip()[:100]}")
        except Exception as e:
            log_print(f"WARNING: LibreOffice version check failed: {e}", "WARNING")
    
    # Check MS Word (Windows/macOS only)
    if sys.platform in ("win32", "darwin"):
        try:
            if sys.platform == "win32":
                import pythoncom
                pythoncom.CoInitialize()
                try:
                    import win32com.client
                    word = win32com.client.Dispatch("Word.Application")
                    word.Visible = False
                    word.Quit()
                    engines["ms_word"] = True
                    log_print("INFO: MS Word COM interface available")
                except Exception:
                    pass
                finally:
                    pythoncom.CoUninitialize()
            else:  # macOS
                # Check if MS Word is installed via Automator
                engines["ms_word"] = True  # Assume available on macOS
        except Exception as e:
            log_print(f"DEBUG: MS Word check failed: {e}", "DEBUG")
    
    return engines


def cleanup_hanging_processes():
    """Clean up any hanging LibreOffice or Word processes."""
    if PSUTIL_AVAILABLE:
        try:
            cleaned = 0
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    name = proc.info['name'].lower()
                    cmdline = ' '.join(proc.info['cmdline'] or []).lower()
                    
                    # Check for LibreOffice processes - only kill if running too long
                    if ('soffice' in name or 'libreoffice' in name) and '--headless' in cmdline:
                        try:
                            create_time = proc.create_time()
                            # Only kill LibreOffice processes running longer than 5 minutes
                            if (datetime.now().timestamp() - create_time) > 300:  # 5 minutes
                                log_print(f"INFO: Terminating long-running LibreOffice process PID {proc.info['pid']} (running for {int((datetime.now().timestamp() - create_time)/60)} minutes)")
                                proc.terminate()
                                try:
                                    proc.wait(timeout=5)
                                except psutil.TimeoutExpired:
                                    proc.kill()
                                cleaned += 1
                            else:
                                # Don't kill recent LibreOffice processes - they might be actively converting
                                log_print(f"DEBUG: Skipping recent LibreOffice process PID {proc.info['pid']} (running for {int((datetime.now().timestamp() - create_time)/60)} minutes)", "DEBUG")
                        except Exception:
                            # If we can't get create time, don't kill the process
                            pass
                        
                    # Check for Word processes (Windows)
                    elif sys.platform == "win32" and 'winword' in name:
                        # Only kill if it's been running for a while without user interaction
                        try:
                            create_time = proc.create_time()
                            if (datetime.now().timestamp() - create_time) > 300:  # 5 minutes
                                log_print(f"INFO: Terminating old Word process PID {proc.info['pid']}")
                                proc.terminate()
                                cleaned += 1
                        except Exception:
                            pass
                            
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                    
            if cleaned > 0:
                log_print(f"INFO: Cleaned up {cleaned} hanging processes with psutil")
            else:
                log_print("INFO: No hanging processes found to cleanup")
            return
                
        except Exception as e:
            log_print(f"WARNING: psutil process cleanup failed: {e}, trying fallback", "WARNING")
    
    # Fallback: Basic process cleanup without psutil
    log_print("INFO: Using basic process cleanup (psutil not available)")
    if sys.platform == "win32":
        try:
            # Kill hanging soffice processes on Windows
            result1 = subprocess.run(["taskkill", "/f", "/im", "soffice.exe"], 
                         capture_output=True, timeout=10)
            result2 = subprocess.run(["taskkill", "/f", "/im", "soffice.bin"], 
                         capture_output=True, timeout=10)
            log_print("INFO: Attempted basic LibreOffice process cleanup")
            
            # Log results for debugging
            if result1.returncode == 0 or result2.returncode == 0:
                log_print("INFO: Successfully killed some LibreOffice processes")
            
        except Exception as e:
            log_print(f"DEBUG: Basic process cleanup failed: {e}", "DEBUG")
    else:
        try:
            # Kill hanging soffice processes on Linux/macOS
            subprocess.run(["pkill", "-f", "soffice.*--headless"], 
                         capture_output=True, timeout=10)
            log_print("INFO: Attempted basic LibreOffice process cleanup")
        except Exception as e:
            log_print(f"DEBUG: Basic process cleanup failed: {e}", "DEBUG")


def convert_with_libreoffice(docx_path: str, pdf_path: str, timeout_seconds: int = 60) -> bool:
    """
    Konversi DOCX ke PDF menggunakan LibreOffice (headless) dengan improved timeout dan error handling.
    Menghindari hang dengan menjalankan proses dan mematikan jika timeout.
    """
    soffice = _find_soffice_executable()
    if not soffice:
        log_print("WARNING: LibreOffice (soffice) not found via ENV/default/PATH", "WARNING")
        return False

    outdir = os.path.dirname(pdf_path) or os.getcwd()
    
    # Ensure output directory exists
    os.makedirs(outdir, exist_ok=True)

    cmd = [
        soffice,
        "--headless",
        "--norestore",
        "--nolockcheck",
        "--nodefault",
        "--nofirststartwizard",
        "--invisible",  # Additional flag for better headless operation
        "--convert-to",
        "pdf:writer_pdf_Export",
        "--outdir",
        outdir,
        docx_path,
    ]

    log_print(f"INFO: Trying conversion via LibreOffice: {' '.join(cmd)}")
    proc = None
    try:
        # Enhanced process creation with better isolation
        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "stdin": subprocess.DEVNULL,  # Prevent hanging on input
        }
        
        if sys.platform == "win32":
            try:
                # Use CREATE_NEW_PROCESS_GROUP for better process isolation
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            except Exception:
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            # POSIX: create new session for better process isolation
            kwargs["preexec_fn"] = os.setsid if hasattr(os, "setsid") else None

        proc = subprocess.Popen(cmd, **kwargs)
        
        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            log_print(f"ERROR: LibreOffice conversion timeout after {timeout_seconds} seconds", "ERROR")
            try:
                # Try graceful termination first
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Force kill if terminate doesn't work
                    proc.kill()
                    proc.wait()
            except Exception as e:
                log_print(f"WARNING: Failed to terminate LibreOffice process: {e}", "WARNING")
            return False

        out_txt = (stdout or b"").decode(errors="ignore")
        err_txt = (stderr or b"").decode(errors="ignore")
        
        if out_txt.strip():
            log_print(f"DEBUG: LibreOffice stdout: {out_txt[:500]}", "DEBUG")
        if err_txt.strip():
            log_print(f"DEBUG: LibreOffice stderr: {err_txt[:500]}", "DEBUG")

        if proc.returncode != 0:
            log_print(f"ERROR: LibreOffice exited with code {proc.returncode}", "ERROR")
            if err_txt:
                # Log specific error patterns
                if "Error:" in err_txt or "Exception:" in err_txt:
                    log_print(f"ERROR: LibreOffice specific error: {err_txt[:200]}", "ERROR")
                if "locked" in err_txt.lower():
                    log_print("ERROR: LibreOffice file lock detected - may need cleanup", "ERROR")
            return False

        # Check if PDF was produced
        expected_name = os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
        produced_pdf = os.path.join(outdir, expected_name)
        
        if not os.path.exists(produced_pdf):
            log_print(f"ERROR: LibreOffice did not produce expected PDF file: {produced_pdf}", "ERROR")
            # List files in output directory for debugging
            try:
                files_in_dir = os.listdir(outdir)
                log_print(f"DEBUG: Files in output directory: {files_in_dir}", "DEBUG")
            except Exception:
                pass
            return False

        # Move to target path if different
        if os.path.abspath(produced_pdf) != os.path.abspath(pdf_path):
            try:
                if os.path.exists(pdf_path):
                    os.remove(pdf_path)
                shutil.move(produced_pdf, pdf_path)
                log_print(f"INFO: Moved PDF from {produced_pdf} to {pdf_path}")
            except Exception as e:
                log_print(f"ERROR: Failed to move produced PDF to target path: {e}", "ERROR")
                return False

        # Verify final PDF exists and has reasonable size
        if not os.path.exists(pdf_path):
            log_print(f"ERROR: Final PDF not found at {pdf_path}", "ERROR")
            return False
            
        pdf_size = os.path.getsize(pdf_path)
        if pdf_size < 100:  # PDF should be at least 100 bytes
            log_print(f"ERROR: Generated PDF is too small ({pdf_size} bytes) - likely corrupt", "ERROR")
            return False
            
        log_print(f"INFO: LibreOffice conversion successful - PDF size: {pdf_size} bytes")
        return True
        
    except FileNotFoundError:
        log_print("ERROR: LibreOffice executable not found when starting process", "ERROR")
        return False
    except Exception as e:
        log_print(f"ERROR: LibreOffice conversion failed: {e}", "ERROR")
        return False
    finally:
        # Ensure process is cleaned up
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


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

    # Hapus file lama jika ada (DOCX dan PDF) dengan cleanup proses hanging
    try:
        if os.path.exists(path_docx):
            # Cleanup hanging processes before removing file
            cleanup_hanging_processes()
            # Wait a bit for processes to terminate
            import time
            time.sleep(0.5)
            os.remove(path_docx)
            log_print(f"INFO: Removed existing DOCX file: {path_docx}")
    except Exception as e:
        log_print(f"WARNING: Failed to remove existing DOCX file: {e}", "WARNING")
        # Force cleanup and try again
        try:
            cleanup_hanging_processes()
            import time
            time.sleep(1)
            if os.path.exists(path_docx):
                os.remove(path_docx)
                log_print(f"INFO: Force removed DOCX file after cleanup: {path_docx}")
        except Exception as e2:
            log_print(f"ERROR: Could not remove DOCX file even after cleanup: {e2}", "ERROR")
            # Last resort: try to find and kill specific processes using the file
            try:
                if sys.platform == "win32":
                    # Use handle.exe if available, or force kill all soffice processes
                    subprocess.run(["taskkill", "/f", "/im", "soffice.exe"], 
                                 capture_output=True, timeout=5)
                    subprocess.run(["taskkill", "/f", "/im", "soffice.bin"], 
                                 capture_output=True, timeout=5)
                    import time
                    time.sleep(2)
                    if os.path.exists(path_docx):
                        os.remove(path_docx)
                        log_print(f"INFO: Successfully removed DOCX after force kill: {path_docx}")
                    else:
                        log_print(f"WARNING: DOCX file no longer exists: {path_docx}", "WARNING")
                else:
                    raise Exception(f"Gagal menghapus file DOCX yang sedang digunakan: {e2}")
            except Exception as e3:
                log_print(f"ERROR: Final attempt to remove DOCX failed: {e3}", "ERROR")
                raise Exception(f"Gagal menghapus file DOCX yang sedang digunakan: {e3}")
    
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

    # Check engine availability first
    engines = check_conversion_engines()
    log_print(f"INFO: Available conversion engines: {engines}")
    
    # Konversi DOCX -> PDF: coba LibreOffice dulu, jika gagal baru fallback ke MS Word (docx2pdf) pada Windows/macOS
    conversion_timeout = int(os.getenv("CONVERSION_TIMEOUT", "90"))
    log_print(f"INFO: Starting DOCX to PDF conversion (timeout {conversion_timeout}s). First try LibreOffice...")

    loop = asyncio.get_event_loop()
    conversion_success = False
    fallback_used = False
    
    # Try LibreOffice first if available
    if engines["libreoffice"]:
        lo_success = await loop.run_in_executor(None, convert_with_libreoffice, path_docx, path_pdf, conversion_timeout)
        conversion_success = lo_success
        
        if lo_success:
            log_print("INFO: LibreOffice conversion successful")
        else:
            log_print("WARNING: LibreOffice conversion failed, will try fallback", "WARNING")
    else:
        log_print("WARNING: LibreOffice not available, skipping to fallback", "WARNING")

    # Try MS Word fallback if LibreOffice failed and MS Word is available
    if not conversion_success and engines["ms_word"]:
        log_print("INFO: Trying fallback via MS Word/Automator (docx2pdf)...")
        try:
            conversion_success = await loop.run_in_executor(
                None, convert_with_timeout, path_docx, path_pdf, conversion_timeout
            )
            fallback_used = True
            if conversion_success:
                log_print("INFO: MS Word fallback conversion successful")
            else:
                log_print("ERROR: MS Word fallback conversion failed", "ERROR")
        except Exception as e:
            log_print(f"ERROR: MS Word fallback failed with exception: {e}", "ERROR")
    elif not conversion_success:
        log_print("ERROR: No conversion engines available or all failed", "ERROR")

    if not conversion_success:
        # Cleanup files jika konversi gagal
        try:
            if os.path.exists(path_docx):
                os.remove(path_docx)
            if os.path.exists(path_pdf):
                os.remove(path_pdf)
        except Exception:
            pass
        # Provide more specific error messages based on what was tried
        error_parts = []
        if engines["libreoffice"]:
            error_parts.append("LibreOffice conversion failed")
        else:
            error_parts.append("LibreOffice not available")
            
        if engines["ms_word"]:
            if fallback_used:
                error_parts.append("MS Word fallback also failed")
            else:
                error_parts.append("MS Word fallback not attempted")
        else:
            error_parts.append("MS Word not available")
            
        error_msg = f"Conversion failed: {', '.join(error_parts)}. "
        
        if not any(engines.values()):
            error_msg += "No conversion engines are available. Please install LibreOffice or MS Word."
        else:
            error_msg += "Please check if the DOCX file is valid and not corrupted."
            
        raise Exception(error_msg)

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
    """Enhanced health check with conversion engine status."""
    try:
        engines = check_conversion_engines()
        return {
            "status": "ok",
            "conversion_engines": engines,
            "workers_running": queue_workers_running,
            "max_workers": MAX_CONCURRENT_WORKERS,
            "queue_size": conversion_queue.qsize()
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "workers_running": queue_workers_running,
            "max_workers": MAX_CONCURRENT_WORKERS
        }


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
