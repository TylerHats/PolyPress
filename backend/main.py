import os
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse, HTMLResponse
from acme_helper import active_challenges

from database import init_db, SessionLocal, User, Tenant, GlobalSettings
from auth import hash_password
from sending_worker import process_queue
from bounce_worker import bounce_worker_loop
from update_worker import auto_update_worker_loop

# Import routers
from routes import auth_routes, tenant_routes, campaign_routes, list_routes, tracking_routes, embed_routes, ssl_routes, developer_routes, backup_routes, update_routes, user_routes, report_routes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("polypress")

# Get running version from git tag to append query params for browser cache invalidation
APP_VERSION = "1.0.0"
try:
    import subprocess
    res = subprocess.run(["git", "describe", "--tags", "--abbrev=0"], capture_output=True, text=True, check=True)
    APP_VERSION = res.stdout.strip()
except Exception:
    pass

def seed_bootstrap_data():
    db = SessionLocal()
    try:
        # Create default GlobalSettings
        settings = db.query(GlobalSettings).first()
        if not settings:
            settings = GlobalSettings(
                app_name="PolyPress",
                oidc_enabled=False
            )
            db.add(settings)
            db.commit()
            logger.info("Initialized default Global Settings.")
    except Exception as e:
        logger.error(f"Error seeding bootstrap data: {e}")
    finally:
        db.close()

def record_historical_metrics():
    from database import SessionLocal, HistorySessionLocal, Tenant, GlobalSettings, HistoricalMetric, Subscriber, Campaign
    from datetime import datetime, timedelta
    
    db = SessionLocal()
    history_db = HistorySessionLocal()
    
    try:
        global_settings = db.query(GlobalSettings).first()
        global_freq = global_settings.history_record_frequency_hours if global_settings else 24
        global_ret = global_settings.history_retention_days if global_settings else 30
        
        # 1. Record Global Metrics
        now = datetime.utcnow()
        latest_global = history_db.query(HistoricalMetric).filter(HistoricalMetric.tenant_id == None).order_by(HistoricalMetric.recorded_at.desc()).first()
        
        if not latest_global or (now - latest_global.recorded_at) >= timedelta(hours=global_freq):
            # Calculate global metrics
            sub_count = db.query(Subscriber).filter(Subscriber.status == "active").count()
            # Campaigns metrics
            campaigns = db.query(Campaign).all()
            sent = sum(c.total_recipients for c in campaigns if c.total_recipients)
            opens = sum(c.open_count for c in campaigns if c.open_count)
            clicks = sum(c.click_count for c in campaigns if c.click_count)
            bounces = sum(c.bounce_count for c in campaigns if c.bounce_count)
            
            metric = HistoricalMetric(
                tenant_id=None,
                recorded_at=now,
                subscriber_count=sub_count,
                emails_sent=sent,
                email_opens=opens,
                link_clicks=clicks,
                bounces=bounces
            )
            history_db.add(metric)
            
            # Clean up global metrics older than global_ret
            cutoff = now - timedelta(days=global_ret)
            history_db.query(HistoricalMetric).filter(HistoricalMetric.tenant_id == None, HistoricalMetric.recorded_at < cutoff).delete()
            history_db.commit()
            
        # 2. Record Tenant Metrics
        tenants = db.query(Tenant).all()
        for tenant in tenants:
            tenant_freq = tenant.history_record_frequency_hours or 24
            tenant_ret = tenant.history_retention_days or 30
            
            latest_tenant = history_db.query(HistoricalMetric).filter(HistoricalMetric.tenant_id == tenant.id).order_by(HistoricalMetric.recorded_at.desc()).first()
            
            if not latest_tenant or (now - latest_tenant.recorded_at) >= timedelta(hours=tenant_freq):
                # Calculate tenant metrics
                sub_count = db.query(Subscriber).filter(Subscriber.tenant_id == tenant.id, Subscriber.status == "active").count()
                campaigns = db.query(Campaign).filter(Campaign.tenant_id == tenant.id).all()
                sent = sum(c.total_recipients for c in campaigns if c.total_recipients)
                opens = sum(c.open_count for c in campaigns if c.open_count)
                clicks = sum(c.click_count for c in campaigns if c.click_count)
                bounces = sum(c.bounce_count for c in campaigns if c.bounce_count)
                
                metric = HistoricalMetric(
                    tenant_id=tenant.id,
                    recorded_at=now,
                    subscriber_count=sub_count,
                    emails_sent=sent,
                    email_opens=opens,
                    link_clicks=clicks,
                    bounces=bounces
                )
                history_db.add(metric)
                
                # Clean up tenant metrics older than tenant_ret
                cutoff = now - timedelta(days=tenant_ret)
                history_db.query(HistoricalMetric).filter(HistoricalMetric.tenant_id == tenant.id, HistoricalMetric.recorded_at < cutoff).delete()
                history_db.commit()
                
    except Exception as e:
        logger.error(f"Error in record_historical_metrics: {e}")
    finally:
        db.close()
        history_db.close()

async def historical_metrics_worker_loop():
    logger.info("Starting historical metrics worker...")
    # Initial run on startup
    try:
        record_historical_metrics()
    except Exception as e:
        logger.error(f"Error doing initial historical metrics check: {e}")
        
    while True:
        try:
            # Sleep 1 hour between checks
            await asyncio.sleep(3600)
            record_historical_metrics()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in historical metrics loop: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    logger.info("Initializing Database...")
    init_db()
    
    logger.info("Seeding bootstrap data...")
    seed_bootstrap_data()
    
    logger.info("Launching background sending queue worker...")
    sending_task = asyncio.create_task(process_queue())
    
    logger.info("Launching background IMAP bounce processing worker...")
    bounce_task = asyncio.create_task(bounce_worker_loop())
    
    logger.info("Launching background auto-update worker...")
    update_task = asyncio.create_task(auto_update_worker_loop())
    
    logger.info("Launching background historical metrics worker...")
    metrics_task = asyncio.create_task(historical_metrics_worker_loop())
    
    yield
    
    # Shutdown actions
    logger.info("Shutting down background workers...")
    sending_task.cancel()
    bounce_task.cancel()
    update_task.cancel()
    metrics_task.cancel()
    try:
        await asyncio.gather(sending_task, bounce_task, update_task, metrics_task, return_exceptions=True)
    except Exception as e:
        logger.warning(f"Error while cleaning background tasks: {e}")
    logger.info("Shutdown complete.")

app = FastAPI(
    title="PolyPress API",
    description="Multitenant email newsletter management system",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def check_schema_mismatch(request: Request, call_next):
    import database
    if database.SCHEMA_MISMATCH:
        allowed_paths = [
            "/api/admin/update/schema-status",
            "/api/admin/update/bypass-schema-check",
            "/static/",
            "/branding/"
        ]
        path = request.url.path
        is_allowed = any(path.startswith(p) for p in allowed_paths) or path == "/"
        if not is_allowed and path.startswith("/api/"):
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Database schema is newer than the running code. Administration required.",
                    "schema_mismatch": True,
                    "code_version": database.CURRENT_SCHEMA_VERSION,
                    "db_version": database.DB_SCHEMA_VERSION
                }
            )
    return await call_next(request)

# Include routers
app.include_router(auth_routes.router)
app.include_router(tenant_routes.router)
app.include_router(campaign_routes.router)
app.include_router(list_routes.router)
app.include_router(tracking_routes.router)
app.include_router(embed_routes.router)
app.include_router(ssl_routes.router)
app.include_router(developer_routes.router)
app.include_router(backup_routes.router)
app.include_router(update_routes.router)
app.include_router(user_routes.router)
app.include_router(report_routes.router)

# Mount branding folder for custom assets
BASE_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
branding_dir = os.path.join(BASE_DIR, "branding")
os.makedirs(branding_dir, exist_ok=True)
# Copy default logo if it is in place
logo_source = os.path.join(BASE_DIR, "PolyPressLogo.png")
logo_dest = os.path.join(branding_dir, "logo.png")
if os.path.exists(logo_source) and not os.path.exists(logo_dest):
    try:
        import shutil
        shutil.copy(logo_source, logo_dest)
        logger.info("Copied logo to branding folder.")
    except Exception as e:
        logger.warning(f"Could not copy logo to branding: {e}")

app.mount("/branding", StaticFiles(directory=branding_dir), name="branding")

# Serve Static Frontend
static_path = os.path.join(BASE_DIR, "backend", "static")
os.makedirs(static_path, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")

@app.get("/.well-known/acme-challenge/{token}")
def serve_acme_challenge(token: str):
    if token in active_challenges:
        return Response(content=active_challenges[token], media_type="text/plain")
    raise HTTPException(status_code=404, detail="Challenge token not found")

def get_index_html_response() -> HTMLResponse:
    index_file = os.path.join(static_path, "index.html")
    if os.path.exists(index_file):
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                html = f.read()
            # Replace scripts and links to force cache busting
            html = html.replace('href="/static/style.css"', f'href="/static/style.css?v={APP_VERSION}"')
            html = html.replace('src="/static/app.js"', f'src="/static/app.js?v={APP_VERSION}"')
            return HTMLResponse(
                content=html,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
        except Exception as e:
            return HTMLResponse(content=f"Error loading index.html: {str(e)}", status_code=500)
    return HTMLResponse(content="<h3>PolyPress static index.html not found</h3>", status_code=404)

@app.get("/")
def serve_home():
    return get_index_html_response()

@app.get("/{fallback_path:path}")
def serve_fallback(fallback_path: str):
    if fallback_path.startswith("api/") or fallback_path.startswith("branding/"):
        raise HTTPException(status_code=404)
    return get_index_html_response()

