import os
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from acme_helper import active_challenges

from database import init_db, SessionLocal, User, Tenant, GlobalSettings
from auth import hash_password
from sending_worker import process_queue
from bounce_worker import bounce_worker_loop
from update_worker import auto_update_worker_loop

# Import routers
from routes import auth_routes, tenant_routes, campaign_routes, list_routes, tracking_routes, embed_routes, ssl_routes, developer_routes, backup_routes, update_routes, user_routes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("polypress")

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
    
    yield
    
    # Shutdown actions
    logger.info("Shutting down background workers...")
    sending_task.cancel()
    bounce_task.cancel()
    update_task.cancel()
    try:
        await asyncio.gather(sending_task, bounce_task, update_task, return_exceptions=True)
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

@app.get("/")
def serve_home():
    index_file = os.path.join(static_path, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "PolyPress Backend API is running. Please create static/index.html to view frontend."}

@app.get("/{fallback_path:path}")
def serve_fallback(fallback_path: str):
    if fallback_path.startswith("api/") or fallback_path.startswith("branding/"):
        raise HTTPException(status_code=404)
    index_file = os.path.join(static_path, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    raise HTTPException(status_code=404)

