import os
import shutil
import tempfile
from typing import Optional
import re

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.responses import JSONResponse
from docx2pdf import convert
import httpx

app = FastAPI(title="DOCX to PDF Converter", version="1.0.0")


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
    # Validasi
    filename = file.filename or "uploaded.docx"
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="File harus berformat .docx")
    # nomor_urut bisa string: sanitasi agar aman sebagai nama file
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", nomor_urut).strip()
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="nomor_urut tidak valid setelah sanitasi")

    # Folder penyimpanan lokal: ./document
    base_dir = os.getenv("DOC_LOCAL_DIR", os.path.join(os.path.dirname(__file__), "document"))
    os.makedirs(base_dir, exist_ok=True)

    path_docx = os.path.join(base_dir, f"{safe_name}.docx")
    path_pdf = os.path.join(base_dir, f"{safe_name}.pdf")

    # Simpan upload sebagai <nomor_urut>.docx
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

    # Konversi DOCX -> PDF ke path tujuan
    try:
        convert(path_docx, path_pdf)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Gagal konversi DOCX ke PDF. Pastikan menjalankan di Windows/Mac "
                "dengan Microsoft Word terpasang (docx2pdf membutuhkan Word). "
                f"Error: {str(e)}"
            ),
        )

    if not os.path.exists(path_pdf):
        raise HTTPException(status_code=500, detail="File PDF tidak ditemukan setelah konversi")
    
    # Check file size
    file_size = os.path.getsize(path_pdf)
    max_size = 5 * 1024 * 1024  # 5MB limit
    if file_size > max_size:
        print(f"WARNING: PDF file size {file_size} bytes exceeds recommended limit")
    
    print(f"INFO: PDF created successfully - Size: {file_size} bytes, Path: {path_pdf}")

    # Kirim ke target_url/check/responseBalikConvert
    post_url = f"{target_url.rstrip('/')}" + "/check/responseBalikConvert"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            with open(path_pdf, "rb") as fpdf:
                # Get file size for debugging
                file_size = os.path.getsize(path_pdf)
                print(f"DEBUG: Uploading PDF size: {file_size} bytes to {post_url}")
                
                # Target server expects 'docupload' field name
                files = {"docupload": (os.path.basename(path_pdf), fpdf, "application/pdf")}
                headers = {
                    "User-Agent": "FastAPI-DOCX-Converter/1.0",
                }
                resp = await client.post(post_url, files=files, headers=headers)
                
                print(f"DEBUG: Target response status: {resp.status_code}")
                print(f"DEBUG: Target response headers: {dict(resp.headers)}")
                
        resp_text = resp.text
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = None
            
        # Log response untuk debugging
        print(f"DEBUG: Target response text: {resp_text[:500]}")
        print(f"DEBUG: Full target response: {resp_text}")
        
        # Log file info yang dikirim
        print(f"DEBUG: Sent filename: {os.path.basename(path_pdf)}")
        print(f"DEBUG: Local file exists: {os.path.exists(path_pdf)}")
        print(f"DEBUG: Local file size: {os.path.getsize(path_pdf) if os.path.exists(path_pdf) else 'N/A'}")
        
    except httpx.HTTPError as e:
        print(f"DEBUG: HTTP Error: {e}")
        raise HTTPException(status_code=502, detail=f"Gagal upload ke target: {e}")

    # Cleanup files after successful upload
    try:
        if resp.status_code == 200 and resp_json and "upload_data" in resp_json:
            # Delete local files after successful upload
            if os.path.exists(path_docx):
                os.remove(path_docx)
                print(f"INFO: Deleted local DOCX file: {path_docx}")
            
            if os.path.exists(path_pdf):
                os.remove(path_pdf)
                print(f"INFO: Deleted local PDF file: {path_pdf}")
                
            print("INFO: Local files cleaned up successfully")
        else:
            print("INFO: Files retained due to upload error or unexpected response")
    except Exception as e:
        print(f"WARNING: Failed to cleanup local files: {e}")

    return JSONResponse(
        content={
            "status": "ok",
            "saved_docx": path_docx,
            "saved_pdf": path_pdf,
            "target_post": post_url,
            "target_status": resp.status_code,
            "target_response": resp_json if resp_json is not None else resp_text,
            "files_cleaned": resp.status_code == 200 and resp_json and "upload_data" in resp_json
        }
    )
