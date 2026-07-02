from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse
import requests
from sqlalchemy.orm import Session
import database as db_mod
from database import get_db, User, GlobalSettings, Tenant
import auth
import urllib.parse
from routes.tenant_routes import generate_dkim_keypair

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.get("/setup/status")
def get_setup_status(db: Session = Depends(get_db)):
    num_users = db.query(User).count()
    return {"setup_completed": num_users > 0}

@router.post("/setup")
def run_setup(payload: dict, db: Session = Depends(get_db)):
    num_users = db.query(User).count()
    if num_users > 0:
        raise HTTPException(status_code=400, detail="Setup has already been completed")
        
    admin_name = payload.get("admin_name", "Administrator")
    admin_email = payload.get("admin_email")
    admin_password = payload.get("admin_password")
    app_name = payload.get("app_name", "PolyPress")
    
    if not admin_email or not admin_password:
        raise HTTPException(status_code=400, detail="Administrator email and password required")
        
    domain = admin_email.split("@")[-1]
    tenant_name = payload.get("tenant_name")
    if not tenant_name or not tenant_name.strip():
        tenant_name = domain.capitalize() if domain else "Primary Tenant"
    
    # Create Tenant
    tenant = Tenant(
        name=tenant_name,
        smtp_host=payload.get("smtp_host"),
        smtp_port=payload.get("smtp_port"),
        smtp_username=payload.get("smtp_username"),
        smtp_password=payload.get("smtp_password"),
        smtp_use_ssl=payload.get("smtp_use_ssl", False),
        smtp_use_tls=payload.get("smtp_use_tls", True),
        direct_send=payload.get("direct_send", False),
        dkim_domain=payload.get("dkim_domain") or domain,
        dkim_selector=payload.get("dkim_selector", "polypress"),
        mta_from_prefix=payload.get("mta_from_prefix", "noreply"),
        imap_host=payload.get("imap_host"),
        imap_port=payload.get("imap_port"),
        imap_username=payload.get("imap_username"),
        imap_password=payload.get("imap_password"),
        imap_use_ssl=payload.get("imap_use_ssl", True),
        speed_emails_per_hour=payload.get("speed_emails_per_hour", 500),
        bounce_email=payload.get("bounce_email")
    )
    
    if tenant.direct_send or payload.get("generate_dkim", True):
        priv, pub = generate_dkim_keypair()
        tenant.dkim_private_key = priv
        tenant.dkim_public_key = pub
        
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    
    # Update global settings
    settings = db.query(GlobalSettings).first()
    if not settings:
        settings = GlobalSettings(
            app_name=app_name,
            public_url=payload.get("public_url"),
            oidc_enabled=payload.get("oidc_enabled", False),
            oidc_issuer=payload.get("oidc_issuer"),
            oidc_client_id=payload.get("oidc_client_id"),
            oidc_client_secret=payload.get("oidc_client_secret"),
            oidc_redirect_url=payload.get("oidc_redirect_url")
        )
        db.add(settings)
    else:
        settings.app_name = app_name
        settings.public_url = payload.get("public_url")
        if "oidc_enabled" in payload:
            settings.oidc_enabled = payload["oidc_enabled"]
        if "oidc_issuer" in payload:
            settings.oidc_issuer = payload["oidc_issuer"]
        if "oidc_client_id" in payload:
            settings.oidc_client_id = payload["oidc_client_id"]
        if "oidc_client_secret" in payload:
            settings.oidc_client_secret = payload["oidc_client_secret"]
        if "oidc_redirect_url" in payload:
            settings.oidc_redirect_url = payload["oidc_redirect_url"]
    db.commit()
    
    # Create Super Admin User
    admin_pwd_hash = auth.hash_password(admin_password)
    admin = User(
        email=admin_email,
        name=admin_name,
        role="super_admin",
        password_hash=admin_pwd_hash,
        tenant_id=tenant.id,
        is_active=True
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    
    token = auth.create_access_token({"sub": admin.email})
    return {
        "status": "success",
        "access_token": token,
        "token_type": "bearer",
        "role": admin.role,
        "tenant_id": admin.tenant_id
    }

@router.post("/login")
def login(payload: dict, db: Session = Depends(get_db)):
    email = payload.get("email")
    password = payload.get("password")
    
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")
        
    user = db.query(User).filter(User.email == email, User.is_active == True).first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    if not auth.verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    if user.totp_enabled:
        return {"status": "totp_required", "email": user.email}
        
    token = auth.create_access_token({"sub": user.email})
    return {
        "status": "success",
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "tenant_id": user.tenant_id
    }

@router.post("/totp-verify")
def totp_verify(payload: dict, db: Session = Depends(get_db)):
    email = payload.get("email")
    code = payload.get("code")
    
    if not email or not code:
        raise HTTPException(status_code=400, detail="Email and TOTP code required")
        
    user = db.query(User).filter(User.email == email, User.is_active == True).first()
    if not user or not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="Invalid verification request")
        
    if not auth.verify_totp(user.totp_secret, code):
        raise HTTPException(status_code=401, detail="Invalid verification code")
        
    token = auth.create_access_token({"sub": user.email})
    return {
        "status": "success",
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "tenant_id": user.tenant_id
    }

@router.post("/totp/setup")
def totp_setup(current_user: User = Depends(auth.get_current_user)):
    secret = auth.generate_totp_secret()
    label = f"PolyPress:{current_user.email}"
    uri = f"otpauth://totp/{urllib.parse.quote(label)}?secret={secret}&issuer=PolyPress"
    return {"secret": secret, "uri": uri}

@router.post("/totp/enable")
def totp_enable(payload: dict, current_user: User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    secret = payload.get("secret")
    code = payload.get("code")
    
    if not secret or not code:
        raise HTTPException(status_code=400, detail="Secret and verification code required")
        
    if not auth.verify_totp(secret, code):
        raise HTTPException(status_code=400, detail="Invalid verification code")
        
    current_user.totp_secret = secret
    current_user.totp_enabled = True
    db.commit()
    return {"detail": "TOTP 2FA enabled successfully"}

@router.post("/totp/disable")
def totp_disable(payload: dict, current_user: User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    code = payload.get("code")
    
    if not code:
        raise HTTPException(status_code=400, detail="Verification code required")
        
    if not auth.verify_totp(current_user.totp_secret, code):
        raise HTTPException(status_code=400, detail="Invalid verification code")
        
    current_user.totp_secret = None
    current_user.totp_enabled = False
    db.commit()
    return {"detail": "TOTP 2FA disabled successfully"}

@router.get("/public-settings")
def get_public_settings(db: Session = Depends(get_db)):
    settings = db.query(GlobalSettings).first()
    if not settings:
        return {
            "app_name": "PolyPress",
            "app_logo": None,
            "oidc_enabled": False
        }
    return {
        "app_name": settings.app_name,
        "app_logo": settings.app_logo,
        "oidc_enabled": settings.oidc_enabled
    }

@router.get("/oidc/url")
def get_oidc_url(db: Session = Depends(get_db)):
    settings = db.query(GlobalSettings).first()
    if not settings or not settings.oidc_enabled:
        raise HTTPException(status_code=400, detail="OIDC login is disabled")
        
    try:
        config_url = f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
        res = requests.get(config_url, timeout=5)
        res.raise_for_status()
        openid_config = res.json()
        auth_endpoint = openid_config["authorization_endpoint"]
        
        public_url = settings.public_url or "http://localhost:8000"
        redirect_uri = settings.oidc_redirect_url or f"{public_url.rstrip('/')}/api/auth/oidc/callback"
        
        login_url = (
            f"{auth_endpoint}?"
            f"client_id={settings.oidc_client_id}&"
            f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
            f"response_type=code&"
            f"scope=openid%20profile%20email&"
            f"state=polypress_auth"
        )
        return {"url": login_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch OIDC configuration: {str(e)}")

@router.get("/oidc/callback")
def oidc_callback(code: str = Query(...), state: str = None, db: Session = Depends(get_db)):
    settings = db.query(GlobalSettings).first()
    if not settings or not settings.oidc_enabled:
        return RedirectResponse(url="/#/login?error=OIDC_disabled")
        
    try:
        config_url = f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
        openid_config = requests.get(config_url, timeout=5).json()
        token_endpoint = openid_config["token_endpoint"]
        userinfo_endpoint = openid_config["userinfo_endpoint"]
        
        public_url = settings.public_url or "http://localhost:8000"
        redirect_uri = settings.oidc_redirect_url or f"{public_url.rstrip('/')}/api/auth/oidc/callback"
        
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": settings.oidc_client_id,
            "client_secret": settings.oidc_client_secret
        }
        token_res = requests.post(token_endpoint, data=token_data, timeout=5)
        token_res.raise_for_status()
        tokens = token_res.json()
        
        access_token = tokens["access_token"]
        
        headers = {"Authorization": f"Bearer {access_token}"}
        userinfo_res = requests.get(userinfo_endpoint, headers=headers, timeout=5)
        userinfo_res.raise_for_status()
        userinfo = userinfo_res.json()
        
        email = userinfo.get("email")
        name = userinfo.get("name", email.split("@")[0])
        
        if not email:
            return RedirectResponse(url="/#/login?error=no_email_claim")
            
        user = auth.process_oidc_user(db, email, name)
        session_token = auth.create_access_token({"sub": user.email})
        return RedirectResponse(url=f"/#/login?token={session_token}")
        
    except Exception as e:
        print(f"OIDC callback error: {e}")
        return RedirectResponse(url=f"/#/login?error={requests.utils.quote(str(e))}")

@router.get("/me")
def get_me(current_user: User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    tenant_name = None
    if current_user.tenant_id:
        tenant = db.query(db_mod.Tenant).filter(db_mod.Tenant.id == current_user.tenant_id).first()
        if tenant:
            tenant_name = tenant.name
            
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "role": current_user.role,
        "tenant_id": current_user.tenant_id,
        "tenant_name": tenant_name,
        "totp_enabled": current_user.totp_enabled,
        "allowed_tenants": current_user.allowed_tenants or []
    }
