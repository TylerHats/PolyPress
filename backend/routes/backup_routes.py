import os
import sqlite3
import zipfile
import shutil
import glob
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import get_db, User, engine
import auth

router = APIRouter(prefix="/api/admin/backups", tags=["backups"])

BASE_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
DB_PATH = os.path.join(BASE_DIR, "backend", "polypress.db")
BRANDING_DIR = os.path.join(BASE_DIR, "branding")

def run_sqlite_backup(src: str, dest: str):
    src_conn = sqlite3.connect(src)
    dest_conn = sqlite3.connect(dest)
    try:
        src_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        src_conn.close()

def get_backups_list():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    pattern = os.path.join(BACKUP_DIR, "polypress_backup_*.zip")
    files = glob.glob(pattern)
    backups = []
    for f in files:
        stat = os.stat(f)
        backups.append({
            "filename": os.path.basename(f),
            "size": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    # Sort by creation date desc
    backups.sort(key=lambda x: x["filename"], reverse=True)
    return backups

@router.get("")
def list_backups(current_user: User = Depends(auth.require_super_admin)):
    return get_backups_list()

@router.post("/create")
def create_backup(current_user: User = Depends(auth.require_super_admin)):
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"polypress_backup_{timestamp}.zip"
        zip_path = os.path.join(BACKUP_DIR, zip_filename)
        
        # 1. Copy active SQLite DB using online backup copy
        temp_db = os.path.join(BACKUP_DIR, "temp_db_backup.db")
        if os.path.exists(temp_db):
            os.remove(temp_db)
            
        run_sqlite_backup(DB_PATH, temp_db)
        
        # 2. Package database and branding files
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(temp_db, "polypress.db")
            if os.path.exists(BRANDING_DIR):
                for root, dirs, files in os.walk(BRANDING_DIR):
                    for file in files:
                        full_p = os.path.join(root, file)
                        rel_p = os.path.relpath(full_p, os.path.dirname(BRANDING_DIR))
                        zipf.write(full_p, rel_p)
                        
        if os.path.exists(temp_db):
            os.remove(temp_db)
            
        return {"detail": "Backup created successfully", "backups": get_backups_list()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create backup: {e}")

@router.get("/download/{filename}")
def download_backup(filename: str, current_user: User = Depends(auth.require_super_admin)):
    zip_path = os.path.join(BACKUP_DIR, filename)
    # Security check: ensure path sits under BACKUP_DIR
    real_path = os.path.realpath(zip_path)
    if not real_path.startswith(os.path.realpath(BACKUP_DIR)):
         raise HTTPException(status_code=403, detail="Access denied")
         
    if not os.path.exists(real_path):
        raise HTTPException(status_code=404, detail="Backup file not found")
        
    return FileResponse(real_path, media_type="application/zip", filename=filename)

@router.post("/restore")
async def restore_backup(file: UploadFile = File(...), current_user: User = Depends(auth.require_super_admin)):
    try:
        temp_zip = os.path.join(BACKUP_DIR, "temp_restore.zip")
        with open(temp_zip, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Extract files
        temp_extract = os.path.join(BACKUP_DIR, "temp_extract")
        if os.path.exists(temp_extract):
            shutil.rmtree(temp_extract)
        os.makedirs(temp_extract, exist_ok=True)
        
        with zipfile.ZipFile(temp_zip, 'r') as zipf:
            zipf.extractall(temp_extract)
            
        restored_db = os.path.join(temp_extract, "polypress.db")
        if not os.path.exists(restored_db):
            shutil.rmtree(temp_extract)
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
            raise HTTPException(status_code=400, detail="Invalid backup file: missing polypress.db")
            
        # Safely shut down database connection pool
        engine.dispose()
        
        # Replace files
        shutil.copy2(restored_db, DB_PATH)
        
        restored_branding = os.path.join(temp_extract, "branding")
        if os.path.exists(restored_branding):
            if os.path.exists(BRANDING_DIR):
                shutil.rmtree(BRANDING_DIR)
            shutil.copytree(restored_branding, BRANDING_DIR)
            
        # Cleanup
        shutil.rmtree(temp_extract)
        if os.path.exists(temp_zip):
            os.remove(temp_zip)
            
        return {"detail": "Database and assets restored successfully. Connection pool refreshed."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restore backup: {e}")

@router.post("/restore-local")
def restore_local_backup(filename: str, current_user: User = Depends(auth.require_super_admin)):
    zip_path = os.path.join(BACKUP_DIR, filename)
    real_path = os.path.realpath(zip_path)
    if not real_path.startswith(os.path.realpath(BACKUP_DIR)):
         raise HTTPException(status_code=403, detail="Access denied")
         
    if not os.path.exists(real_path):
        raise HTTPException(status_code=404, detail="Backup snapshot not found")
        
    try:
        # Extract files
        temp_extract = os.path.join(BACKUP_DIR, "temp_extract")
        if os.path.exists(temp_extract):
            shutil.rmtree(temp_extract)
        os.makedirs(temp_extract, exist_ok=True)
        
        with zipfile.ZipFile(real_path, 'r') as zipf:
            zipf.extractall(temp_extract)
            
        restored_db = os.path.join(temp_extract, "polypress.db")
        if not os.path.exists(restored_db):
            shutil.rmtree(temp_extract)
            raise HTTPException(status_code=400, detail="Invalid backup file: missing polypress.db")
            
        # Safely shut down database connection pool
        engine.dispose()
        
        # Replace files
        shutil.copy2(restored_db, DB_PATH)
        
        restored_branding = os.path.join(temp_extract, "branding")
        if os.path.exists(restored_branding):
            if os.path.exists(BRANDING_DIR):
                shutil.rmtree(BRANDING_DIR)
            shutil.copytree(restored_branding, BRANDING_DIR)
            
        # Cleanup
        shutil.rmtree(temp_extract)
        return {"detail": f"Database and assets restored from snapshot {filename}. Connection pool refreshed."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restore backup: {e}")

@router.delete("/{filename}")
def delete_backup(filename: str, current_user: User = Depends(auth.require_super_admin)):
    zip_path = os.path.join(BACKUP_DIR, filename)
    real_path = os.path.realpath(zip_path)
    if not real_path.startswith(os.path.realpath(BACKUP_DIR)):
         raise HTTPException(status_code=403, detail="Access denied")
         
    if os.path.exists(real_path):
        os.remove(real_path)
        
    return {"detail": "Backup file deleted", "backups": get_backups_list()}
