import os
import sqlite3
import zipfile
import shutil
import glob
import requests
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, BackgroundTasks, Header
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import get_db, User, engine, GlobalSettings
import auth

router = APIRouter(prefix="/api/admin/backups", tags=["backups"])

BASE_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
DB_PATH = os.path.join(BASE_DIR, "backend", "polypress.db")
HISTORY_DB_PATH = os.path.join(BASE_DIR, "backend", "polypress_history.db")
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

def push_backup_to_external(zip_path: str, url: str, auth_header: str = None):
    try:
        headers = {}
        if auth_header:
            headers["Authorization"] = auth_header
        
        with open(zip_path, "rb") as f:
            files = {"file": (os.path.basename(zip_path), f, "application/zip")}
            response = requests.post(url, files=files, headers=headers, timeout=300)
            response.raise_for_status()
            print(f"Successfully pushed backup to external URL: {url}")
    except Exception as e:
        print(f"Failed to push backup to external URL: {e}")

@router.post("/create")
def create_backup(background_tasks: BackgroundTasks, current_user: User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
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
        
        # History DB Copy
        temp_history_db = os.path.join(BACKUP_DIR, "temp_history_backup.db")
        if os.path.exists(temp_history_db):
            os.remove(temp_history_db)
            
        history_exists = os.path.exists(HISTORY_DB_PATH)
        if history_exists:
            run_sqlite_backup(HISTORY_DB_PATH, temp_history_db)
        
        # 2. Package database and branding files
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(temp_db, "polypress.db")
            if history_exists:
                zipf.write(temp_history_db, "polypress_history.db")
            if os.path.exists(BRANDING_DIR):
                for root, dirs, files in os.walk(BRANDING_DIR):
                    for file in files:
                        full_p = os.path.join(root, file)
                        rel_p = os.path.relpath(full_p, os.path.dirname(BRANDING_DIR))
                        zipf.write(full_p, rel_p)
                        
        if os.path.exists(temp_db):
            os.remove(temp_db)
        if os.path.exists(temp_history_db):
            os.remove(temp_history_db)
            
        # Trigger external backup push if configured
        settings = db.query(GlobalSettings).first()
        if settings and settings.external_backup_url:
            background_tasks.add_task(
                push_backup_to_external, 
                zip_path, 
                settings.external_backup_url, 
                settings.external_backup_auth_header
            )
            
        return {"detail": "Backup created successfully", "backups": get_backups_list()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create backup: {e}")

@router.get("/export")
def export_backup(
    background_tasks: BackgroundTasks,
    token: str = None, 
    x_polypress_backup_token: str = Header(None), 
    db: Session = Depends(get_db)
):
    settings = db.query(GlobalSettings).first()
    configured_token = settings.backup_token if settings else None
    
    provided_token = token or x_polypress_backup_token
    if not configured_token or not provided_token or provided_token != configured_token:
        raise HTTPException(status_code=401, detail="Unauthorized backup token")
        
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"polypress_backup_{timestamp}.zip"
        zip_path = os.path.join(BACKUP_DIR, zip_filename)
        
        temp_db = os.path.join(BACKUP_DIR, "temp_db_backup.db")
        if os.path.exists(temp_db):
            os.remove(temp_db)
            
        run_sqlite_backup(DB_PATH, temp_db)
        
        temp_history_db = os.path.join(BACKUP_DIR, "temp_history_backup.db")
        if os.path.exists(temp_history_db):
            os.remove(temp_history_db)
            
        history_exists = os.path.exists(HISTORY_DB_PATH)
        if history_exists:
            run_sqlite_backup(HISTORY_DB_PATH, temp_history_db)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(temp_db, "polypress.db")
            if history_exists:
                zipf.write(temp_history_db, "polypress_history.db")
            if os.path.exists(BRANDING_DIR):
                for root, dirs, files in os.walk(BRANDING_DIR):
                    for file in files:
                        full_p = os.path.join(root, file)
                        rel_p = os.path.relpath(full_p, os.path.dirname(BRANDING_DIR))
                        zipf.write(full_p, rel_p)
                        
        if os.path.exists(temp_db):
            os.remove(temp_db)
        if os.path.exists(temp_history_db):
            os.remove(temp_history_db)
            
        # Trigger external backup push if configured
        if settings and settings.external_backup_url:
            background_tasks.add_task(
                push_backup_to_external, 
                zip_path, 
                settings.external_backup_url, 
                settings.external_backup_auth_header
            )
            
        return FileResponse(zip_path, media_type="application/zip", filename=zip_filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export backup: {e}")

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
        from database import history_engine
        history_engine.dispose()
        
        # Replace files
        shutil.copy2(restored_db, DB_PATH)
        
        restored_history_db = os.path.join(temp_extract, "polypress_history.db")
        if os.path.exists(restored_history_db):
            shutil.copy2(restored_history_db, HISTORY_DB_PATH)
        
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
        from database import history_engine
        history_engine.dispose()
        
        # Replace files
        shutil.copy2(restored_db, DB_PATH)
        
        restored_history_db = os.path.join(temp_extract, "polypress_history.db")
        if os.path.exists(restored_history_db):
            shutil.copy2(restored_history_db, HISTORY_DB_PATH)
        
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
