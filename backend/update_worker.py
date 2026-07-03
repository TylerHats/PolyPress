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

def parse_semver(version_str: str):
    if not version_str:
        return (0, 0, 0)
    version_str = version_str.strip().lower()
    if version_str.startswith('v'):
        version_str = version_str[1:]
    parts = []
    for part in version_str.split('.'):
        digits = ''.join(c for c in part if c.isdigit())
        if digits:
            parts.append(int(digits))
        else:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])

def get_latest_github_tag_and_commit(channel: str):
    tags_url = "https://api.github.com/repos/TylerHats/PolyPress/tags"
    headers = {"User-Agent": "PolyPress-Updater"}
    tag_name = None
    commit_sha = ""
    
    try:
        tags_resp = requests.get(tags_url, headers=headers, timeout=10)
        if tags_resp.status_code == 200:
            tags_list = tags_resp.json()
            if tags_list:
                if channel == "stable":
                    rel_url = "https://api.github.com/repos/TylerHats/PolyPress/releases/latest"
                    rel_resp = requests.get(rel_url, headers=headers, timeout=10)
                    if rel_resp.status_code == 200:
                        rel_data = rel_resp.json()
                        tag_name = rel_data.get("tag_name")
                    
                    if tag_name:
                        for t in tags_list:
                            if t.get("name") == tag_name:
                                commit_sha = t.get("commit", {}).get("sha", "")[:7]
                                break
                
                if not tag_name:
                    valid_tags = [t for t in tags_list if t.get("name")]
                    if valid_tags:
                        valid_tags.sort(key=lambda t: parse_semver(t.get("name")), reverse=True)
                        tag_name = valid_tags[0].get("name")
                        commit_sha = valid_tags[0].get("commit", {}).get("sha", "")[:7]
    except Exception as e:
        logger.error(f"Error fetching GitHub tags/commits: {e}")
        
    return tag_name, commit_sha

def check_for_updates_internal(channel: str):
    # Fetch origin updates forcing tags to override rejection
    run_git_command(["fetch", "origin", "--tags", "--force"])
    
    current_tag = run_git_command(["describe", "--tags", "--abbrev=0"]) or "v0.0.0"
    current_semver = parse_semver(current_tag)
    
    latest_tag, latest_commit_sha = get_latest_github_tag_and_commit(channel)
            
    if not latest_tag:
        branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]) or "main"
        latest_tag = run_git_command(["describe", "--tags", "--abbrev=0", f"origin/{branch}"]) or current_tag
        latest_commit_sha = run_git_command(["rev-parse", "--short", latest_tag]) or ""
        
    latest_semver = parse_semver(latest_tag)
    update_available = latest_semver > current_semver
    
    return update_available, latest_tag, latest_commit_sha

def run_update_process(channel: str, target: str = None):
    try:
        # Stash local uncommitted changes
        run_git_command(["stash"])
        
        if target:
            run_git_command(["fetch", "origin", "--tags", "--force"])
            run_git_command(["checkout", f"tags/{target}"])
        elif channel == "beta":
            branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]) or "main"
            run_git_command(["checkout", branch])
            run_git_command(["pull", "origin", branch])
        else:
            run_git_command(["fetch", "origin", "--tags", "--force"])
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
