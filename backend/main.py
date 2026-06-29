import os
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from acme_helper import active_challenges

from database import init_db, SessionLocal, User, Tenant, GlobalSettings
from auth import hash_password
from sending_worker import process_queue
from bounce_worker import bounce_worker_loop

# Import routers
from routes import auth_routes, tenant_routes, campaign_routes, list_routes, tracking_routes, embed_routes, ssl_routes, developer_routes, backup_routes

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
    
    yield
    
    # Shutdown actions
    logger.info("Shutting down background workers...")
    sending_task.cancel()
    bounce_task.cancel()
    try:
        await asyncio.gather(sending_task, bounce_task, return_exceptions=True)
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

# Mount branding folder for custom assets
branding_dir = "/home/tylerhats/Documents/GitHub/PolyPress/branding"
os.makedirs(branding_dir, exist_ok=True)
# Copy default logo if it is in place
logo_source = "/home/tylerhats/Documents/GitHub/PolyPress/PolyPressLogo.png"
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
static_path = "/home/tylerhats/Documents/GitHub/PolyPress/backend/static"
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

