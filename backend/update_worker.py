import os
import sys
import signal
import subprocess
import logging
import asyncio
import threading
import time
import requests
from datetime import datetime
from sqlalchemy.orm import Session
from database import SessionLocal, GlobalSettings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("update_worker")

BASE_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
VERSION_FILE = os.path.join(BASE_DIR, "VERSION")
_UPDATE_CACHE_LOCK = threading.Lock()
_UPDATE_STATUS_CACHE = {}  # channel -> (ts, payload_dict)
UPDATE_CACHE_TTL_SECONDS = 600.0


def is_running_in_docker() -> bool:
    """Detect whether PolyPress is running inside a Docker/OCI container."""
    if os.getenv("POLYPRESS_DOCKER", "").strip().lower() in ("1", "true", "yes"):
        return True
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "rt", encoding="utf-8", errors="ignore") as f:
            cgroups = f.read()
            if "docker" in cgroups or "containerd" in cgroups or "kubepods" in cgroups:
                return True
    except Exception:
        pass
    return False


def read_baked_version() -> str:
    """Read application version from POLYPRESS_VERSION env var or repository VERSION file."""
    env_ver = (os.getenv("POLYPRESS_VERSION") or "").strip()
    if env_ver:
        return env_ver
    if os.path.exists(VERSION_FILE):
        try:
            with open(VERSION_FILE, "r", encoding="utf-8") as f:
                ver = f.read().strip()
                if ver:
                    return ver
        except Exception:
            pass
    return ""


def run_git_command(args, cwd=BASE_DIR):
    if not os.path.exists(os.path.join(cwd, ".git")):
        return None
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


def get_installed_version_info() -> tuple[str, str, str]:
    """Return (current_tag, current_commit, active_branch) reliably on source and Docker installs."""
    is_docker = is_running_in_docker()
    has_git = os.path.exists(os.path.join(BASE_DIR, ".git"))

    baked_tag = read_baked_version()
    baked_commit = (os.getenv("POLYPRESS_COMMIT") or "").strip()

    if is_docker or not has_git:
        tag = baked_tag or (run_git_command(["describe", "--tags", "--abbrev=0"]) if has_git else "") or "v0.0.0"
        commit = baked_commit or (run_git_command(["rev-parse", "--short", "HEAD"]) if has_git else "") or "docker"
        return tag, commit, "docker"

    git_tag = run_git_command(["describe", "--tags", "--abbrev=0"]) or baked_tag or "v0.0.0"
    git_commit = run_git_command(["rev-parse", "--short", "HEAD"]) or baked_commit or "unknown"
    branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]) or "main"
    if branch == "HEAD":
        sym = run_git_command(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
        branch = sym.split("/", 1)[-1] if sym and "/" in sym else "main"
    return git_tag, git_commit, branch


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
    tags_url = "https://api.github.com/repos/TylerHats/PolyPress/tags?per_page=100"
    headers = {"User-Agent": "PolyPress-Updater"}
    tag_name = None
    commit_sha = ""
    
    try:
        tags_resp = requests.get(tags_url, headers=headers, timeout=10)
        tags_list = tags_resp.json() if tags_resp.status_code == 200 else []
        if channel == "stable":
            rel_data = get_latest_github_release()
            if rel_data:
                tag_name = rel_data.get("tag_name")
            if tag_name and tags_list:
                for t in tags_list:
                    if t.get("name") == tag_name:
                        commit_sha = t.get("commit", {}).get("sha", "")[:7]
                        break
            if tag_name and not commit_sha:
                try:
                    ref_resp = requests.get(
                        f"https://api.github.com/repos/TylerHats/PolyPress/git/ref/tags/{tag_name}",
                        headers=headers,
                        timeout=10,
                    )
                    if ref_resp.status_code == 200:
                        commit_sha = ref_resp.json().get("object", {}).get("sha", "")[:7]
                except Exception:
                    pass

        if not tag_name and tags_list:
            valid_tags = [t for t in tags_list if t.get("name")]
            if valid_tags:
                valid_tags.sort(key=lambda t: parse_semver(t.get("name")), reverse=True)
                tag_name = valid_tags[0].get("name")
                commit_sha = valid_tags[0].get("commit", {}).get("sha", "")[:7]
    except Exception as e:
        logger.error(f"Error fetching GitHub tags/commits: {e}")
        
    return tag_name, commit_sha


def check_for_updates_internal(channel: str, fetch_remote: bool = True):
    is_docker = is_running_in_docker()
    has_git = os.path.exists(os.path.join(BASE_DIR, ".git"))
    current_tag, current_commit, branch = get_installed_version_info()
    current_semver = parse_semver(current_tag)

    latest_tag, latest_commit_sha = get_latest_github_tag_and_commit(channel)
    latest_main_commit = ""

    if not is_docker and has_git:
        if fetch_remote:
            run_git_command(["fetch", "origin", "--tags", "--force"])
        latest_main_commit = run_git_command(["rev-parse", "--short", f"origin/{branch}"]) or ""
        if not latest_tag:
            latest_tag = run_git_command(["describe", "--tags", "--abbrev=0", f"origin/{branch}"]) or current_tag
            latest_commit_sha = run_git_command(["rev-parse", "--short", latest_tag]) or ""

    latest_semver = parse_semver(latest_tag) if latest_tag else current_semver

    if is_docker or not has_git:
        update_available = bool(latest_tag and latest_semver > current_semver)
        return update_available, latest_tag or current_tag, latest_commit_sha or current_commit, latest_main_commit

    # Check if local HEAD is equal to or ahead of the remote release tag/commit
    is_ahead_or_equal = False
    if latest_tag:
        try:
            res = subprocess.run(
                ["git", "merge-base", "--is-ancestor", latest_tag, "HEAD"],
                cwd=BASE_DIR,
                capture_output=True
            )
            if res.returncode == 0:
                is_ahead_or_equal = True
        except Exception:
            pass
            
    if not is_ahead_or_equal and latest_commit_sha:
        try:
            res = subprocess.run(
                ["git", "merge-base", "--is-ancestor", latest_commit_sha, "HEAD"],
                cwd=BASE_DIR,
                capture_output=True
            )
            if res.returncode == 0:
                is_ahead_or_equal = True
        except Exception:
            pass
            
    if is_ahead_or_equal:
        update_available = False
    else:
        update_available = latest_semver > current_semver
    
    return update_available, latest_tag, latest_commit_sha, latest_main_commit


def get_cached_update_status(channel: str, auto_update: bool, force: bool = False) -> dict:
    """Return update status with 10-minute TTL caching so dashboard loads never stampede GitHub/git."""
    is_docker = is_running_in_docker()
    current_tag, current_commit, _branch = get_installed_version_info()
    cache_key = f"{channel}:{is_docker}:{current_tag}:{current_commit}"
    now_mono = time.monotonic()

    if not force:
        with _UPDATE_CACHE_LOCK:
            cached = _UPDATE_STATUS_CACHE.get(cache_key)
            if cached and (now_mono - cached[0]) < UPDATE_CACHE_TTL_SECONDS:
                res = dict(cached[1])
                res["auto_update"] = auto_update
                res["update_channel"] = channel
                return res

    update_available, latest_tag, latest_commit_sha, latest_main_commit = check_for_updates_internal(
        channel,
        fetch_remote=(not is_docker),
    )

    payload = {
        "current_commit": current_commit,
        "current_tag": current_tag,
        "latest_commit": latest_commit_sha or latest_main_commit,
        "latest_tag": latest_tag or "",
        "latest_main_commit": latest_main_commit,
        "update_available": update_available,
        "update_channel": channel,
        "auto_update": auto_update,
        "is_systemd": "INVOCATION_ID" in os.environ,
        "is_docker": is_docker,
    }
    with _UPDATE_CACHE_LOCK:
        _UPDATE_STATUS_CACHE[cache_key] = (time.monotonic(), dict(payload))
    return payload


def run_update_process(channel: str, target: str = None):
    if is_running_in_docker() or not os.path.exists(os.path.join(BASE_DIR, ".git")):
        logger.warning("In-container git update skipped: Docker installs must pull the latest image.")
        return False

    try:
        # Stash local uncommitted changes
        run_git_command(["stash"])
        
        if target:
            run_git_command(["fetch", "origin", "--tags", "--force"])
            run_git_command(["checkout", f"tags/{target}"])
        elif channel == "beta":
            _, _, branch = get_installed_version_info()
            run_git_command(["fetch", "origin", "--tags", "--force"])
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


def _run_auto_update_cycle():
    db = SessionLocal()
    try:
        settings = db.query(GlobalSettings).first()
        if not settings or not settings.auto_update:
            return False
        logger.info("Auto-update check in progress...")
        update_available, target_ver, _, _ = check_for_updates_internal(settings.update_channel, fetch_remote=True)
        if update_available:
            logger.info(f"Auto-update: installing new version {target_ver}")
            return run_update_process(settings.update_channel, target_ver)
    finally:
        db.close()
    return False


async def auto_update_worker_loop():
    if is_running_in_docker():
        logger.info("Running in Docker container; background git auto-update loop is disabled.")
        return

    # Initial sleep to avoid conflicts during startup
    await asyncio.sleep(60)
    while True:
        try:
            updated = await asyncio.to_thread(_run_auto_update_cycle)
            if updated:
                logger.info("Auto-update succeeded. Restarting server...")
                await asyncio.sleep(2)
                os.kill(os.getpid(), signal.SIGTERM)
        except Exception as e:
            logger.error(f"Error in auto-update worker: {e}")
        
        # Sleep for 12 hours
        await asyncio.sleep(43200)
