import os
import sys
import signal
import subprocess
import logging
import asyncio
import requests
from datetime import datetime
from sqlalchemy.orm import Session
from database import SessionLocal, GlobalSettings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("update_worker")

BASE_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))

def run_git_command(args, cwd=BASE_DIR):
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "true"
    try:
        res = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            env=env
        )
        return res.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Git command 'git {' '.join(args)}' failed: {e.stderr}")
        return None

def get_latest_github_release():
    url = "https://api.github.com/repos/TylerHats/PolyPress/releases/latest"
    headers = {"User-Agent": "PolyPress-Updater"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"Error fetching GitHub release: {e}")
    return None

def check_for_updates_internal(channel: str):
    # Fetch origin updates rate-limit free
    run_git_command(["fetch", "origin"])
    
    current_commit = run_git_command(["rev-parse", "HEAD"])
    current_tag = run_git_command(["describe", "--tags", "--abbrev=0"])
    
    if channel == "beta":
        branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]) or "main"
        remote_commit = run_git_command(["rev-parse", f"origin/{branch}"])
        if remote_commit and remote_commit != current_commit:
            return True, remote_commit
    else:
        latest_release = get_latest_github_release()
        if latest_release:
            tag_name = latest_release.get("tag_name")
            # If current tag is not the latest release tag (or no tag on current commit)
            if tag_name and tag_name != current_tag:
                return True, tag_name
                
    return False, None

def run_update_process(channel: str, target: str = None):
    try:
        # Stash local uncommitted changes
        run_git_command(["stash"])
        
        if channel == "beta":
            branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]) or "main"
            run_git_command(["checkout", branch])
            run_git_command(["pull", "origin", branch])
        else:
            run_git_command(["fetch", "origin", "--tags"])
            if target:
                run_git_command(["checkout", f"tags/{target}"])
            else:
                latest_release = get_latest_github_release()
                if latest_release:
                    tag_name = latest_release.get("tag_name")
                    run_git_command(["checkout", f"tags/{tag_name}"])
                else:
                    logger.error("No GitHub release target found.")
                    return False
        
        # Upgrade python dependencies inside the same venv
        requirements_path = os.path.join(BASE_DIR, "backend", "requirements.txt")
        if os.path.exists(requirements_path):
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", requirements_path],
                cwd=BASE_DIR,
                check=True,
                capture_output=True
            )
        return True
    except Exception as e:
        logger.error(f"Failed to perform update: {e}")
        return False

async def auto_update_worker_loop():
    # Initial sleep to avoid conflicts during startup
    await asyncio.sleep(60)
    while True:
        db = SessionLocal()
        try:
            settings = db.query(GlobalSettings).first()
            if settings and settings.auto_update:
                logger.info("Auto-update check in progress...")
                update_available, target_ver = check_for_updates_internal(settings.update_channel)
                if update_available:
                    logger.info(f"Auto-update: installing new version {target_ver}")
                    success = run_update_process(settings.update_channel, target_ver)
                    if success:
                        logger.info("Auto-update succeeded. Restarting server...")
                        # Delay slightly and restart
                        await asyncio.sleep(2)
                        os.kill(os.getpid(), signal.SIGTERM)
        except Exception as e:
            logger.error(f"Error in auto-update worker: {e}")
        finally:
            db.close()
        
        # Sleep for 12 hours
        await asyncio.sleep(43200)
