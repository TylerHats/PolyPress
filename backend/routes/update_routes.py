import os
import signal
import asyncio
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Response
from sqlalchemy.orm import Session
from database import get_db, User, GlobalSettings
import auth
from update_worker import (
    is_running_in_docker,
    check_for_updates_internal,
    get_cached_update_status,
    run_update_process,
)

router = APIRouter(prefix="/api/admin/update", tags=["update"])


async def schedule_restart():
    # Delay slightly to allow HTTP response to flush
    await asyncio.sleep(2)
    print("Restarting PolyPress process to apply updates...")
    os.kill(os.getpid(), signal.SIGTERM)


def _build_status_payload(db: Session, force: bool = False) -> dict:
    import database
    settings = db.query(GlobalSettings).first()
    channel = settings.update_channel if settings else "stable"
    auto_update = settings.auto_update if settings else False
    payload = get_cached_update_status(channel=channel, auto_update=auto_update, force=force)
    payload["db_schema_version"] = database.DB_SCHEMA_VERSION
    payload["db_history_schema_version"] = database.DB_HISTORY_SCHEMA_VERSION
    return payload


@router.get("/status")
def get_update_status(
    response: Response,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.require_super_admin),
):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return _build_status_payload(db, force=force)


@router.post("/check")
def check_updates(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.require_super_admin),
):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    try:
        return _build_status_payload(db, force=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check for updates: {e}")


@router.post("/install")
def install_updates(background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    if is_running_in_docker():
        raise HTTPException(
            status_code=400,
            detail="In-container git updates are disabled for Docker deployments. Run 'docker compose pull && docker compose up -d' on the host.",
        )

    settings = db.query(GlobalSettings).first()
    channel = settings.update_channel if settings else "stable"
    
    # 1. Verify update is available
    update_available, target_ver, _, _ = check_for_updates_internal(channel, fetch_remote=True)
    if not update_available and not target_ver:
        raise HTTPException(status_code=400, detail="No update target available.")
        
    # 2. Run update process
    success = run_update_process(channel, target_ver)
    if not success:
        raise HTTPException(status_code=500, detail="Update failed during git pulls or requirement setup. Check logs.")
        
    # 3. Schedule restart
    background_tasks.add_task(schedule_restart)
    return {"detail": "Update applied successfully. Server is restarting..."}


@router.post("/force-beta")
def force_beta_update(background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    if is_running_in_docker():
        raise HTTPException(
            status_code=400,
            detail="In-container git updates are disabled for Docker deployments. Pull the latest container image instead.",
        )

    # Force updating: switch to beta and pull the latest commits on active branch
    success = run_update_process("beta")
    if not success:
        raise HTTPException(status_code=500, detail="Force update failed. Check logs.")
        
    background_tasks.add_task(schedule_restart)
    return {"detail": "Force pull successful. Server is restarting..."}

@router.get("/schema-status")
def get_schema_status():
    import database
    return {
        "schema_mismatch": database.SCHEMA_MISMATCH,
        "current_code_version": database.CURRENT_SCHEMA_VERSION,
        "db_schema_version": database.DB_SCHEMA_VERSION,
        "current_history_code_version": database.CURRENT_HISTORY_SCHEMA_VERSION,
        "db_history_schema_version": database.DB_HISTORY_SCHEMA_VERSION
    }

@router.post("/bypass-schema-check")
def bypass_schema_check(payload: dict, background_tasks: BackgroundTasks):
    import database
    from sqlalchemy import text
    from auth import verify_password
    
    email = payload.get("email")
    password = payload.get("password")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")
        
    db = database.SessionLocal()
    try:
        user = db.query(database.User).filter(
            database.User.email == email,
            database.User.role == "super_admin"
        ).first()
        
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid admin credentials")
            
        with database.engine.begin() as conn:
            conn.execute(text(f"UPDATE global_settings SET schema_version = {database.CURRENT_SCHEMA_VERSION}"))
            
        database.SCHEMA_MISMATCH = False
        background_tasks.add_task(schedule_restart)
        return {"detail": "Schema version bypass applied. Rebooting server..."}
    finally:
        db.close()
