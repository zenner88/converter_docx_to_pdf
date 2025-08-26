import os
import shutil
import subprocess
import tempfile
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.responses import StreamingResponse, JSONResponse
import httpx

app = FastAPI(title="DOCX to PDF Converter (LibreOffice)", version="1.0.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/convert")
async def convert_docx_to_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    nomor_urut: str = Form(...),
    target_url: str = Form(...),
):
    # Validasi file
    filename = file.filename or "uploaded.docx"
    if not filename.lower().endswith((".docx", ".doc")):
        raise HTTPException(status_code=400, detail="File harus .docx atau .doc")

    # Validasi nomor_urut hanya digit
    if not nomor_urut.isdigit():
        raise HTTPException(status_code=400, detail="nomor_urut tidak valid (hanya digit)")

    # Siapkan direktori tujuan seperti di PHP: /var/www/.../dokumen/
    base_dir = os.getenv("DOC_BASE_DIR", "/var/www/service.sidinarbnn.my.id/html")
    dir_upload = os.getenv("DOC_SUB_DIR", "dokumen")
    fullpath = os.path.join(base_dir, dir_upload)
    os.makedirs(fullpath, exist_ok=True)

    path_docx = os.path.join(fullpath, f"{nomor_urut}.docx")
    path_pdf = os.path.join(fullpath, f"{nomor_urut}.pdf")

    # Timeout konversi
    try:
        convert_timeout = int(os.getenv("CONVERT_TIMEOUT", "120"))
    except ValueError:
        convert_timeout = 120

    # Simpan upload langsung ke folder tujuan (meniru PHP)
    try:
        with open(path_docx, "wb") as f:
            content = await file.read()
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal menyimpan file upload: {e}")

    # Hapus PDF lama jika ada
    try:
        if os.path.exists(path_pdf):
            os.remove(path_pdf)
    except Exception:
        pass

    # Konversi via LibreOffice (soffice) dengan outdir ke folder tujuan
    cmd = [
        "soffice",
        "--headless",
        "--nologo",
        "--norestore",
        "--nodefault",
        "--nolockcheck",
        "--convert-to",
        "pdf",
        "--outdir",
        fullpath,
        path_docx,
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=convert_timeout,
            env={**os.environ, "HOME": "/tmp"},
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=(
                "LibreOffice (soffice) tidak ditemukan. Pastikan sudah terinstall dan ada di PATH."
            ),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Konversi timeout setelah {convert_timeout} detik. "
                "Anda bisa menaikkan nilai dengan environment variable CONVERT_TIMEOUT."
            ),
        )

    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Gagal konversi. stderr: {proc.stderr.strip()} | stdout: {proc.stdout.strip()}",
        )

    if not os.path.exists(path_pdf):
        # Fallback: cari *.pdf dengan prefix nomor_urut jika dinamai berbeda
        candidates = [p for p in os.listdir(fullpath) if p.lower().endswith(".pdf")]
        if candidates:
            # Pilih yang paling baru
            newest = max(
                (os.path.join(fullpath, p) for p in candidates),
                key=lambda p: os.path.getmtime(p),
            )
            path_pdf = newest
        else:
            raise HTTPException(status_code=500, detail="File PDF tidak ditemukan setelah konversi")

    # Kirim PDF ke target_url seperti PHP
    target_url = (target_url or "").rstrip("/")
    endpoint_suffix = os.getenv("TARGET_ENDPOINT_SUFFIX", "/check/responseBalikConvert")
    post_url = f"{target_url}{endpoint_suffix}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            with open(path_pdf, "rb") as fpdf:
                files = {"docupload": (os.path.basename(path_pdf), fpdf, "application/pdf")}
                resp = await client.post(post_url, files=files)
        resp_text = resp.text
        # Coba parse JSON
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = None
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Gagal upload ke target: {e}")

    result = {
        "status": "ok",
        "saved_docx": path_docx,
        "saved_pdf": path_pdf,
        "target_post": post_url,
        "target_status": resp.status_code,
        "target_response": resp_json if resp_json is not None else resp_text,
    }

    return JSONResponse(content=result)
