import os
import re
import urllib.request
import shutil
import logging
import threading
import maxminddb

logger = logging.getLogger("location_helper")

BASE_DIR = os.path.realpath(os.path.dirname(__file__))
DATA_DIR = os.path.realpath(os.path.join(BASE_DIR, "..", "data"))

# Resolve correct persistent data dir matching database path
db_url = os.getenv("DATABASE_URL", "")
if db_url.startswith("sqlite:///"):
    sqlite_path = db_url.replace("sqlite:///", "")
    sqlite_dir = os.path.dirname(sqlite_path)
    if sqlite_dir:
        DATA_DIR = os.path.realpath(sqlite_dir)

GEOIP_DB_PATH = os.path.join(DATA_DIR, "geoip.mmdb")
GEOIP_MIRROR_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb"

_geoip_lock = threading.Lock()
_geoip_reader = None
_geoip_download_lock = threading.Lock()
_geoip_download_failed_at = 0.0


def close_geoip_reader():
    """Close the cached MaxMind DB reader cleanly during shutdown."""
    global _geoip_reader
    with _geoip_lock:
        if _geoip_reader is not None:
            try:
                _geoip_reader.close()
            except Exception:
                pass
            _geoip_reader = None


def _get_geoip_reader():
    global _geoip_reader
    if _geoip_reader is not None:
        return _geoip_reader
    if not os.path.exists(GEOIP_DB_PATH):
        return None
    with _geoip_lock:
        if _geoip_reader is None and os.path.exists(GEOIP_DB_PATH):
            try:
                _geoip_reader = maxminddb.open_database(GEOIP_DB_PATH)
            except Exception as e:
                logger.error(f"Failed to open GeoIP database: {e}")
                return None
    return _geoip_reader


def download_geoip_db():
    global _geoip_download_failed_at
    if os.path.exists(GEOIP_DB_PATH):
        return True
    import time
    if _geoip_download_failed_at and (time.monotonic() - _geoip_download_failed_at < 3600):
        return False
    if not _geoip_download_lock.acquire(blocking=False):
        return os.path.exists(GEOIP_DB_PATH)
    try:
        if os.path.exists(GEOIP_DB_PATH):
            return True
        os.makedirs(DATA_DIR, exist_ok=True)
        logger.info(f"Downloading offline GeoIP database from {GEOIP_MIRROR_URL}...")

        req = urllib.request.Request(
            GEOIP_MIRROR_URL,
            headers={"User-Agent": "PolyPress-Offline-GeoIP/1.0"}
        )
        tmp_path = f"{GEOIP_DB_PATH}.tmp"
        with urllib.request.urlopen(req, timeout=20) as response, open(tmp_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        os.replace(tmp_path, GEOIP_DB_PATH)
        _geoip_download_failed_at = 0.0
        logger.info("Offline GeoIP database downloaded successfully.")
        return True
    except Exception as e:
        _geoip_download_failed_at = time.monotonic()
        logger.error(f"Failed to download offline GeoIP database: {e}")
        return False
    finally:
        _geoip_download_lock.release()


BOT_UA_PATTERNS = [
    "googleimageproxy", "via ggpht.com",
    "outlook-express", "outlook.office", "office365",
    "apple-mailshare", "apple-pubsub", "apple image proxy",
    "yandex", "baidu", "yahoomailproxy", "yahooslurp",
    "bot", "crawler", "spider", "prefetch", "preview", "validator", "fetcher",
    "scanner", "urlscan", "virusscan", "security", "mimecast", "barracuda", "proofpoint", "cisco",
    "trendmicro", "fireeye", "kaspersky", "avast", "sophos", "zscaler", "cyren",
    "mailguard", "cloudmark", "symantec", "mcafee", "checkpoint", "fortinet",
    "spamhaus", "curl", "python", "go-http-client", "wget", "urllib",
    "httpx", "axios", "postman", "phantom", "selenium", "puppeteer", "playwright"
]


def is_bot_or_proxy(user_agent: str) -> bool:
    if not user_agent or not user_agent.strip():
        return True

    ua_lower = user_agent.lower()

    for pattern in BOT_UA_PATTERNS:
        if pattern in ua_lower:
            return True

    if re.search(r"(?:^|\s)head/", ua_lower) or ua_lower.strip() == "head":
        return True
    if "outlook" in ua_lower and ("via" in ua_lower or "caching" in ua_lower or "proxy" in ua_lower):
        return True
    if "yahoo" in ua_lower and ("via" in ua_lower or "proxy" in ua_lower or "slurp" in ua_lower):
        return True

    return False

def parse_user_agent(ua: str) -> tuple[str, str]:
    if not ua:
        return "Unknown Platform", "Unknown App"
    
    ua_lower = ua.lower()
    
    if is_bot_or_proxy(ua):
        return "Cloud Proxy", "Proxy / Image Prefetcher"
    
    # Platform Detection
    platform = "Unknown Platform"
    if "android" in ua_lower:
        platform = "Android"
    elif "iphone" in ua_lower or "ipad" in ua_lower or "ipod" in ua_lower:
        platform = "iOS"
    elif "windows phone" in ua_lower:
        platform = "Windows Phone"
    elif "windows" in ua_lower:
        platform = "Windows"
    elif "macintosh" in ua_lower or "mac os x" in ua_lower:
        platform = "macOS"
    elif "linux" in ua_lower:
        platform = "Linux"
        
    # App / Browser Detection
    app = "Unknown App"
    if "gmail" in ua_lower:
        app = "Gmail App"
    elif "yahoo" in ua_lower:
        app = "Yahoo Mail"
    elif "outlook" in ua_lower:
        app = "Outlook App"
    elif "applemail" in ua_lower or "microsoft office" in ua_lower or "thunderbird" in ua_lower:
        app = "Desktop Email Client"
    elif "chrome" in ua_lower and "safari" in ua_lower and "edge" not in ua_lower and "opr" not in ua_lower:
        app = "Chrome Browser"
    elif "safari" in ua_lower and "chrome" not in ua_lower:
        app = "Safari Browser"
    elif "firefox" in ua_lower:
        app = "Firefox Browser"
    elif "edge" in ua_lower or "edg/" in ua_lower:
        app = "Edge Browser"
    elif "opera" in ua_lower or "opr" in ua_lower:
        app = "Opera Browser"
    elif "mozilla" in ua_lower:
        app = "Web Browser / Mail Client"
        
    return platform, app

def estimate_ip_location(ip: str) -> str:
    if not ip or ip in ["127.0.0.1", "localhost", "::1"]:
        return "Local Loopback"

    reader = _get_geoip_reader()
    if reader is None:
        return "Unknown"

    try:
        record = reader.get(ip)
        if record:
            city = record.get("city", {}).get("names", {}).get("en")
            country = record.get("country", {}).get("names", {}).get("en") or \
                      record.get("registered_country", {}).get("names", {}).get("en")
            if city and country:
                return f"{city}, {country}"
            elif country:
                return country
    except Exception as e:
        logger.error(f"Error resolving IP location: {e}")

    return "Unknown"

def log_subscriber_activity(db, tenant_id: int, subscriber_id: int, ip_address: str, user_agent: str):
    from database import Subscriber, SubscriberActivity
    try:
        platform, app = parse_user_agent(user_agent)
        location = estimate_ip_location(ip_address)
        
        # 1. Create activity entry
        activity = SubscriberActivity(
            tenant_id=tenant_id,
            subscriber_id=subscriber_id,
            ip_address=ip_address,
            user_agent=user_agent,
            platform=platform,
            app=app,
            location=location
        )
        db.add(activity)
        db.commit()
        
        # 2. Update subscriber most recent location
        sub = db.query(Subscriber).filter(Subscriber.id == subscriber_id).first()
        if sub:
            sub.ip_location = location
            db.commit()
            
        # 3. Clean up records beyond the last 15
        records = db.query(SubscriberActivity)\
            .filter(SubscriberActivity.subscriber_id == subscriber_id)\
            .order_by(SubscriberActivity.created_at.desc())\
            .all()
            
        if len(records) > 15:
            boundary_time = records[14].created_at
            db.query(SubscriberActivity)\
                .filter(
                    SubscriberActivity.subscriber_id == subscriber_id,
                    SubscriberActivity.created_at < boundary_time
                )\
                .delete()
            db.commit()
            
    except Exception as e:
        logger.error(f"Error logging subscriber activity: {e}")
