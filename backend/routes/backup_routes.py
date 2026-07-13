import os
import sqlite3
import zipfile
import shutil
import glob
import requests
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, BackgroundTasks, Header
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import get_db, User, engine, GlobalSettings, DATABASE_URL, HISTORY_DATABASE_URL
import auth

router = APIRouter(prefix="/api/admin/backups", tags=["backups"])

BASE_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
BRANDING_DIR = os.path.join(BASE_DIR, "branding")

# Resolve database file paths dynamically supporting sqlite overrides
if DATABASE_URL.startswith("sqlite:///"):
    DB_PATH = DATABASE_URL.replace("sqlite:///", "")
else:
    DB_PATH = os.path.realpath(os.path.join(BASE_DIR, "backend", "polypress.db"))

if HISTORY_DATABASE_URL.startswith("sqlite:///"):
    HISTORY_DB_PATH = HISTORY_DATABASE_URL.replace("sqlite:///", "")
else:
    HISTORY_DB_PATH = os.path.realpath(os.path.join(BASE_DIR, "backend", "polypress_history.db"))

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
            "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
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

def perform_system_backup(db: Session, background_tasks: BackgroundTasks = None) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"polypress_backup_{timestamp}.zip"
    zip_path = os.path.join(BACKUP_DIR, zip_filename)
    
    # Force SQLite to write all WAL frames back to the main database file first
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception as e:
        print(f"Warning: Failed to checkpoint main DB WAL: {e}")
        
    # 1. Copy active SQLite DB using online backup copy
    temp_db = os.path.join(BACKUP_DIR, "temp_db_backup.db")
    if os.path.exists(temp_db):
        os.remove(temp_db)
        
    run_sqlite_backup(DB_PATH, temp_db)
    
    # History DB Checkpoint and Copy
    temp_history_db = os.path.join(BACKUP_DIR, "temp_history_backup.db")
    if os.path.exists(temp_history_db):
        os.remove(temp_history_db)
        
    history_exists = os.path.exists(HISTORY_DB_PATH)
    if history_exists:
        try:
            with sqlite3.connect(HISTORY_DB_PATH) as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except Exception as e:
            print(f"Warning: Failed to checkpoint history DB WAL: {e}")
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
        if background_tasks:
            background_tasks.add_task(
                push_backup_to_external, 
                zip_path, 
                settings.external_backup_url, 
                settings.external_backup_auth_header
            )
        else:
            try:
                push_backup_to_external(zip_path, settings.external_backup_url, settings.external_backup_auth_header)
            except Exception as push_err:
                print(f"Background external backup push failed: {push_err}")
                
    # Purge older backups if retention limit reached
    retention_count = 10
    if settings and settings.backup_retention_count is not None:
        retention_count = int(settings.backup_retention_count)
        
    if retention_count > 0:
        backups = glob.glob(os.path.join(BACKUP_DIR, "polypress_backup_*.zip"))
        backups.sort() # Sorts alphabetically (chronologically by timestamp)
        if len(backups) > retention_count:
            to_remove = backups[:-retention_count]
            for b_file in to_remove:
                try:
                    os.remove(b_file)
                except Exception as b_err:
                    print(f"Warning: Failed to purge old backup file {b_file}: {b_err}")
                    
    # Update last backup timestamp
    if settings:
        settings.last_backup_at = datetime.utcnow()
        db.commit()
        
    return zip_filename

@router.post("/create")
def create_backup(background_tasks: BackgroundTasks, current_user: User = Depends(auth.require_super_admin), db: Session = Depends(get_db)):
    try:
        zip_filename = perform_system_backup(db, background_tasks)
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
        
        # Force SQLite to write all WAL frames back to the main database file first
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except Exception as e:
            print(f"Warning: Failed to checkpoint main DB WAL: {e}")
            
        temp_db = os.path.join(BACKUP_DIR, "temp_db_backup.db")
        if os.path.exists(temp_db):
            os.remove(temp_db)
            
        run_sqlite_backup(DB_PATH, temp_db)
        
        temp_history_db = os.path.join(BACKUP_DIR, "temp_history_backup.db")
        if os.path.exists(temp_history_db):
            os.remove(temp_history_db)
            
        history_exists = os.path.exists(HISTORY_DB_PATH)
        if history_exists:
            try:
                with sqlite3.connect(HISTORY_DB_PATH) as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception as e:
                print(f"Warning: Failed to checkpoint history DB WAL: {e}")
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

def restart_server():
    import time
    import os
    import signal
    time.sleep(1.5)
    print("Out-of-band restore initiated. Stopping server process to apply backup...")
    os.kill(os.getpid(), signal.SIGTERM)

@router.post("/restore")
async def restore_backup(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...), 
    current_user: User = Depends(auth.require_super_admin)
):
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        restore_zip_path = os.path.join(BACKUP_DIR, "restore.zip")
        with open(restore_zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        background_tasks.add_task(restart_server)
        return {"detail": "System is restarting to apply the restore backup. This will take a moment."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initiate restore: {e}")

@router.post("/restore-local")
def restore_local_backup(
    background_tasks: BackgroundTasks,
    filename: str, 
    current_user: User = Depends(auth.require_super_admin)
):
    zip_path = os.path.join(BACKUP_DIR, filename)
    real_path = os.path.realpath(zip_path)
    if not real_path.startswith(os.path.realpath(BACKUP_DIR)):
         raise HTTPException(status_code=403, detail="Access denied")
         
    if not os.path.exists(real_path):
        raise HTTPException(status_code=404, detail="Backup snapshot not found")
        
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        restore_zip_path = os.path.join(BACKUP_DIR, "restore.zip")
        shutil.copy2(real_path, restore_zip_path)
        
        background_tasks.add_task(restart_server)
        return {"detail": "System is restarting to apply the local restore backup. This will take a moment."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initiate local restore: {e}")

@router.delete("/{filename}")
def delete_backup(filename: str, current_user: User = Depends(auth.require_super_admin)):
    zip_path = os.path.join(BACKUP_DIR, filename)
    real_path = os.path.realpath(zip_path)
    if not real_path.startswith(os.path.realpath(BACKUP_DIR)):
         raise HTTPException(status_code=403, detail="Access denied")
         
    if os.path.exists(real_path):
        os.remove(real_path)
        
    return {"detail": "Backup file deleted", "backups": get_backups_list()}

@router.get("/system-stats")
def get_system_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.require_super_admin)
):
    db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    history_db_size = os.path.getsize(HISTORY_DB_PATH) if os.path.exists(HISTORY_DB_PATH) else 0
    
    assets_size = 0
    assets_count = 0
    if os.path.exists(BRANDING_DIR):
        for root, dirs, files in os.walk(BRANDING_DIR):
            for file in files:
                filepath = os.path.join(root, file)
                try:
                    assets_size += os.path.getsize(filepath)
                    assets_count += 1
                except Exception:
                    pass
                    
    from database import Tenant, Subscriber, SubscriberList, Campaign, User, QueueItem
    tenants = db.query(Tenant).all()
    tenant_stats = []
    for t in tenants:
        sub_count = db.query(Subscriber).join(SubscriberList).filter(SubscriberList.tenant_id == t.id).count()
        list_count = db.query(SubscriberList).filter(SubscriberList.tenant_id == t.id).count()
        campaign_count = db.query(Campaign).filter(Campaign.tenant_id == t.id).count()
        user_count = db.query(User).filter(User.tenant_id == t.id).count()
        tenant_stats.append({
            "id": t.id,
            "name": t.name,
            "subscribers": sub_count,
            "lists": list_count,
            "campaigns": campaign_count,
            "users": user_count
        })
        
    # Calculate estimated max emails per hour based on recent sending data
    recent_sent = db.query(QueueItem).filter(
        QueueItem.status == "sent"
    ).order_by(QueueItem.updated_at.desc()).limit(100).all()
    recent_sent = [r for r in recent_sent if r.updated_at]
    
    est_max_per_hour = 36000 # default
    if len(recent_sent) >= 5:
        recent_sent.sort(key=lambda x: x.updated_at)
        max_rate = 0.0
        # Check window size of 10 consecutive sends to find peak speed under load
        window_size = min(10, len(recent_sent))
        for i in range(len(recent_sent) - window_size + 1):
            t1 = recent_sent[i].updated_at
            t2 = recent_sent[i + window_size - 1].updated_at
            delta = (t2 - t1).total_seconds()
            if delta > 0.1:
                rate = (window_size - 1) / delta
                if rate > max_rate:
                    max_rate = rate
        if max_rate > 0.0:
            est_max_per_hour = int(max_rate * 3600)
        
    return {
        "db_size": db_size,
        "history_db_size": history_db_size,
        "assets_size": assets_size,
        "assets_count": assets_count,
        "tenant_stats": tenant_stats,
        "est_max_per_hour": est_max_per_hour
    }
