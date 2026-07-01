import os
import signal
import asyncio
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from database import get_db, User, GlobalSettings
import auth
from update_worker import (
    run_git_command,
    get_latest_github_release,
    check_for_updates_internal,
    run_update_process
)

router = APIRouter(prefix="/api/admin/update", tags=["update"])

async def schedule_restart():
    # Delay slightly to allow HTTP response to flush
    await asyncio.sleep(2)
    print("Restarting PolyPress process to apply updates...")
    os.kill(os.getpid(), signal.SIGTERM)

@router.get("/status")
def get_update_status(db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    settings = db.query(GlobalSettings).first()
    channel = settings.update_channel if settings else "stable"
    auto_update = settings.auto_update if settings else False
    
    current_commit = run_git_command(["rev-parse", "--short", "HEAD"]) or "unknown"
    current_tag = run_git_command(["describe", "--tags", "--abbrev=0"]) or ""
    
    latest_commit = ""
    latest_tag = ""
    update_available = False
    
    if channel == "beta":
        branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]) or "main"
        latest_commit = run_git_command(["rev-parse", "--short", f"origin/{branch}"]) or ""
        if latest_commit and latest_commit != current_commit:
            update_available = True
    else:
        release = get_latest_github_release()
        if release:
            latest_tag = release.get("tag_name", "")
            if latest_tag and latest_tag != current_tag:
                update_available = True
                
    is_systemd = "INVOCATION_ID" in os.environ
    
    return {
        "current_commit": current_commit,
        "current_tag": current_tag,
        "latest_commit": latest_commit,
        "latest_tag": latest_tag,
        "update_available": update_available,
        "update_channel": channel,
        "auto_update": auto_update,
        "is_systemd": is_systemd
    }

@router.post("/check")
def check_updates(db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    settings = db.query(GlobalSettings).first()
    channel = settings.update_channel if settings else "stable"
    try:
        check_for_updates_internal(channel)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check for updates: {e}")
    return get_update_status(db, current_user)

@router.post("/install")
def install_updates(background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    settings = db.query(GlobalSettings).first()
    channel = settings.update_channel if settings else "stable"
    
    # 1. Verify update is available
    update_available, target_ver = check_for_updates_internal(channel)
    if not update_available:
        # Check if we can still try to pull
        pass
        
    # 2. Run update process
    success = run_update_process(channel, target_ver)
    if not success:
        raise HTTPException(status_code=500, detail="Update failed during git pulls or requirement setup. Check logs.")
        
    # 3. Schedule restart
    background_tasks.add_task(schedule_restart)
    return {"detail": "Update applied successfully. Server is restarting..."}

@router.post("/force-beta")
def force_beta_update(background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    # Force updating: switch to beta and pull the latest commits on active branch
    success = run_update_process("beta")
    if not success:
        raise HTTPException(status_code=500, detail="Force update failed. Check logs.")
        
    background_tasks.add_task(schedule_restart)
    return {"detail": "Force pull successful. Server is restarting..."}
