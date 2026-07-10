import os
import urllib.request
import shutil
import logging
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

def download_geoip_db():
    if os.path.exists(GEOIP_DB_PATH):
        return True
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        logger.info(f"Downloading offline GeoIP database from {GEOIP_MIRROR_URL}...")
        
        # Configure a custom User-Agent to avoid generic blocks
        req = urllib.request.Request(
            GEOIP_MIRROR_URL,
            headers={"User-Agent": "PolyPress-Offline-GeoIP/1.0"}
        )
        
        with urllib.request.urlopen(req, timeout=30) as response, open(GEOIP_DB_PATH, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
            
        logger.info("Offline GeoIP database downloaded successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to download offline GeoIP database: {e}")
        return False

# Initialize / try to download immediately on helper load
download_geoip_db()

def parse_user_agent(ua: str) -> tuple[str, str]:
    if not ua:
        return "Unknown Platform", "Unknown App"
    
    ua_lower = ua.lower()
    
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
        
    if not os.path.exists(GEOIP_DB_PATH):
        # Trigger download on-demand if it failed initially
        if not download_geoip_db():
            return "Unknown Location"
            
    try:
        with maxminddb.open_database(GEOIP_DB_PATH) as reader:
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
