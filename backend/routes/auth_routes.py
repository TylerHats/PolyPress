from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Request, Response, BackgroundTasks
from fastapi.responses import RedirectResponse
import requests
import os
import secrets
import hmac
import jwt
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import database as db_mod
from database import get_db, User, GlobalSettings, Tenant
import auth
import urllib.parse
from routes.tenant_routes import generate_dkim_keypair
from security_utils import (
    login_rate_limiter,
    totp_rate_limiter,
    password_reset_rate_limiter,
    check_and_record_totp_step,
)

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
def login(payload: dict, request: Request, db: Session = Depends(get_db)):
    email = payload.get("email")
    password = payload.get("password")
    
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")

    client_ip = request.client.host if request.client else "unknown"
    email_norm = str(email).strip().lower()
    if (
        not login_rate_limiter.check_and_record(f"login:{client_ip}:{email_norm}", 15, 60)
        or not login_rate_limiter.check_and_record(f"login_ip:{client_ip}", 60, 60)
    ):
        raise HTTPException(status_code=429, detail="Too many login attempts. Please wait a minute and try again.")
        
    user = db.query(User).filter(User.email == email, User.is_active == True).first()
    if not user:
        from sqlalchemy import func
        user = db.query(User).filter(func.lower(User.email) == email_norm, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    settings = db.query(GlobalSettings).first()
    if settings and not settings.local_login_enabled and user.role != "super_admin":
        raise HTTPException(status_code=400, detail="Standard password login is disabled. Please use OIDC (SSO).")
        
    if user.auth_type == "oidc":
        raise HTTPException(status_code=400, detail="This account is configured for OIDC (SSO) authentication only")
        
    if not user.password_hash or not auth.verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    if user.totp_enabled:
        challenge_token = auth.create_totp_challenge_token(user.email)
        return {
            "status": "totp_required",
            "email": user.email,
            "challenge_token": challenge_token,
        }
        
    token = auth.create_access_token({"sub": user.email})
    return {
        "status": "success",
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "tenant_id": user.tenant_id
    }

@router.post("/totp-verify")
def totp_verify(payload: dict, request: Request, db: Session = Depends(get_db)):
    challenge_token = payload.get("challenge_token")
    code = payload.get("code")
    
    if not challenge_token or not code:
        raise HTTPException(status_code=400, detail="2FA challenge token and TOTP code required")

    verified_email = auth.verify_totp_challenge_token(challenge_token)
    if not verified_email:
        raise HTTPException(status_code=401, detail="Invalid or expired 2FA challenge")

    client_ip = request.client.host if request.client else "unknown"
    if not totp_rate_limiter.check_and_record(f"totp:{client_ip}:{verified_email.lower()}", 10, 60):
        raise HTTPException(status_code=429, detail="Too many verification attempts. Please wait a minute.")
        
    user = db.query(User).filter(User.email == verified_email, User.is_active == True).first()
    if not user or not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="Invalid verification request")
        
    matched_step = auth.verify_totp_with_step(user.totp_secret, code)
    if matched_step is None:
        raise HTTPException(status_code=401, detail="Invalid verification code")

    if not check_and_record_totp_step(user.id, matched_step):
        raise HTTPException(status_code=401, detail="TOTP code has already been used. Please wait for the next code.")
        
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
        
    matched_step = auth.verify_totp_with_step(secret, code)
    if matched_step is None:
        raise HTTPException(status_code=400, detail="Invalid verification code")
    if not check_and_record_totp_step(current_user.id, matched_step):
        raise HTTPException(status_code=400, detail="TOTP code already used. Wait for the next code.")
        
    current_user.totp_secret = secret
    current_user.totp_enabled = True
    db.commit()
    return {"detail": "TOTP 2FA enabled successfully"}

@router.post("/totp/disable")
def totp_disable(payload: dict, current_user: User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    code = payload.get("code")
    
    if not code:
        raise HTTPException(status_code=400, detail="Verification code required")
        
    matched_step = auth.verify_totp_with_step(current_user.totp_secret, code)
    if matched_step is None:
        raise HTTPException(status_code=400, detail="Invalid verification code")
    if not check_and_record_totp_step(current_user.id, matched_step):
        raise HTTPException(status_code=400, detail="TOTP code already used. Wait for the next code.")
        
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
            "oidc_enabled": False,
            "local_login_enabled": True
        }
    return {
        "app_name": settings.app_name,
        "app_logo": settings.app_logo,
        "oidc_enabled": settings.oidc_enabled,
        "local_login_enabled": settings.local_login_enabled
    }

@router.get("/oidc/url")
def get_oidc_url(request: Request, response: Response, db: Session = Depends(get_db)):
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

        state_nonce = secrets.token_urlsafe(24)
        state_token = auth.create_access_token(
            {"nonce": state_nonce},
            expires_delta=timedelta(minutes=10),
            purpose="oidc_state",
        )
        is_https = (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto") == "https")
        response.set_cookie(
            key="polypress_oidc_state",
            value=state_nonce,
            max_age=600,
            path="/",
            httponly=True,
            samesite="lax",
            secure=is_https,
        )
        
        login_url = (
            f"{auth_endpoint}?"
            f"client_id={urllib.parse.quote(settings.oidc_client_id or '', safe='')}&"
            f"redirect_uri={urllib.parse.quote(redirect_uri, safe='')}&"
            f"response_type=code&"
            f"scope=openid%20profile%20email&"
            f"state={urllib.parse.quote(state_token, safe='')}"
        )
        return {"url": login_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch OIDC configuration: {str(e)}")

@router.get("/oidc/callback")
def oidc_callback(request: Request, code: str = Query(...), state: str = Query(None), db: Session = Depends(get_db)):
    settings = db.query(GlobalSettings).first()
    if not settings or not settings.oidc_enabled:
        return RedirectResponse(url="/#/login?error=OIDC_disabled")

    cookie_nonce = request.cookies.get("polypress_oidc_state")
    if not state or not cookie_nonce:
        return RedirectResponse(url="/#/login?error=invalid_oidc_state")

    try:
        state_payload = jwt.decode(state, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        token_nonce = state_payload.get("nonce")
        if state_payload.get("purpose") != "oidc_state" or not token_nonce or not hmac.compare_digest(str(cookie_nonce), str(token_nonce)):
            return RedirectResponse(url="/#/login?error=invalid_oidc_state")
    except jwt.PyJWTError:
        return RedirectResponse(url="/#/login?error=invalid_oidc_state")
        
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

        if userinfo.get("email_verified") is False or str(userinfo.get("email_verified", "true")).lower() == "false":
            resp = RedirectResponse(url="/#/login?error=email_not_verified")
            resp.delete_cookie("polypress_oidc_state")
            return resp
        
        email = userinfo.get("email")
        if not email:
            resp = RedirectResponse(url="/#/login?error=no_email_claim")
            resp.delete_cookie("polypress_oidc_state")
            return resp

        name = userinfo.get("name", email.split("@")[0])
        user = auth.process_oidc_user(db, email, name, userinfo)
        session_token = auth.create_access_token({"sub": user.email})
        resp = RedirectResponse(url=f"/#/login?token={urllib.parse.quote(session_token, safe='')}")
        resp.delete_cookie("polypress_oidc_state")
        return resp
        
    except Exception as e:
        print(f"OIDC callback error: {e}")
        resp = RedirectResponse(url=f"/#/login?error={urllib.parse.quote(str(e), safe='')}")
        resp.delete_cookie("polypress_oidc_state")
        return resp

@router.get("/me")
def get_me(current_user: User = Depends(auth.get_authenticated_user), db: Session = Depends(get_db)):
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
        "auth_type": current_user.auth_type,
        "allowed_tenants": current_user.allowed_tenants or []
    }

@router.put("/me")
def update_me(payload: dict, current_user: User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    if "name" in payload and str(payload.get("name") or "").strip():
        current_user.name = str(payload["name"]).strip()

    new_password = payload.get("password")
    if new_password:
        if current_user.auth_type != "local":
            raise HTTPException(status_code=400, detail="Password changes are only supported for local accounts")
        current_password = payload.get("current_password")
        if not current_password or not current_user.password_hash or not auth.verify_password(current_password, current_user.password_hash):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        if len(str(new_password)) < 8:
            raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
        current_user.password_hash = auth.hash_password(str(new_password))

    db.commit()
    db.refresh(current_user)
    return {
        "detail": "Profile updated successfully",
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "role": current_user.role,
        "tenant_id": current_user.tenant_id,
        "totp_enabled": current_user.totp_enabled,
        "auth_type": current_user.auth_type,
        "allowed_tenants": current_user.allowed_tenants or []
    }

@router.post("/branding/logo")
def upload_branding_logo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.require_super_admin)
):
    import shutil
    # Validate extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".png", ".jpg", ".jpeg", ".gif"]:
        raise HTTPException(status_code=400, detail="Only PNG, JPG, JPEG, and GIF formats are allowed")
    
    # Target path
    BASE_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    branding_dir = os.path.join(BASE_DIR, "branding")
    os.makedirs(branding_dir, exist_ok=True)
    
    # Cleanup any existing custom logos
    for existing_file in os.listdir(branding_dir):
        if existing_file.startswith("custom_logo."):
            try:
                os.remove(os.path.join(branding_dir, existing_file))
            except Exception:
                pass
                
    logo_filename = f"custom_logo{ext}"
    logo_path = os.path.join(branding_dir, logo_filename)
    logo_url = f"/branding/{logo_filename}"
    
    try:
        with open(logo_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Persist path to GlobalSettings
        settings = db.query(GlobalSettings).first()
        if not settings:
            settings = GlobalSettings(app_logo=logo_url)
            db.add(settings)
        else:
            settings.app_logo = logo_url
        db.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save logo file: {e}")
        
    return {"status": "success", "logo_url": logo_url}

@router.post("/branding/logo/reset")
def reset_branding_logo(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.require_super_admin)
):
    # Target path
    BASE_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    branding_dir = os.path.join(BASE_DIR, "branding")
    
    # Cleanup custom logos
    if os.path.exists(branding_dir):
        for existing_file in os.listdir(branding_dir):
            if existing_file.startswith("custom_logo."):
                try:
                    os.remove(os.path.join(branding_dir, existing_file))
                except Exception:
                    pass
                    
    # Clear app_logo in settings
    settings = db.query(GlobalSettings).first()
    if settings:
        settings.app_logo = None
        db.commit()
        
    return {"status": "success", "logo_url": "/branding/logo.png"}

@router.post("/forgot-password")
def forgot_password(payload: dict, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    email = payload.get("email", "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    client_ip = request.client.host if request.client else "unknown"
    if not password_reset_rate_limiter.check_and_record(f"forgot:{client_ip}:{email}", 10, 60):
        raise HTTPException(status_code=429, detail="Too many password reset requests. Please try again later.")
        
    user = db.query(User).filter(User.email == email, User.auth_type == "local").first()
    if not user:
        from sqlalchemy import func
        user = db.query(User).filter(func.lower(User.email) == email, User.auth_type == "local").first()
    if not user:
        # Prevent user enumeration
        return {"detail": "If the email is registered for a local account, a reset link will be sent shortly."}
        
    token = secrets.token_urlsafe(32)
    user.password_reset_token = token
    user.password_reset_expires_at = datetime.utcnow() + timedelta(hours=1)
    db.commit()
    
    settings = db.query(GlobalSettings).first()
    base_url = settings.public_url if (settings and settings.public_url) else ""
    if not base_url:
        base_url = "http://localhost:8000"
    base_url = base_url.rstrip("/")
    
    reset_url = f"{base_url}/#/reset-password?token={token}"
    
    tenant = None
    if user.tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    if not tenant:
        tenant = db.query(Tenant).filter((Tenant.smtp_host != None) | (Tenant.direct_send == True)).first()
    if not tenant:
        tenant = db.query(Tenant).first()
        
    if not tenant:
        # If no tenant exists to send, we can't send
        return {"detail": "If the email is registered for a local account, a reset link will be sent shortly."}
        
    subject = f"Reset Your {settings.app_name if settings else 'PolyPress'} Password"
    body_html = f"""
    <div style="font-family: sans-serif; max-width: 500px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px; background-color: #0f172a; color: #f8fafc;">
        <h2 style="color: #6366f1; margin-top: 0;">Password Recovery Request</h2>
        <p>You requested a password reset for your local account on PolyPress.</p>
        <p>Please click the button below to choose a new password. This link is active for 1 hour.</p>
        <div style="text-align: center; margin: 25px 0;">
            <a href="{reset_url}" style="background-color: #6366f1; color: #ffffff; padding: 12px 24px; text-decoration: none; font-weight: bold; border-radius: 6px; display: inline-block;">Reset Password</a>
        </div>
        <p style="font-size: 12px; color: #64748b;">If you did not request this, you can safely ignore this email. Your password will remain unchanged.</p>
    </div>
    """
    
    from sending_worker import send_transactional_email_by_tenant_id
    background_tasks.add_task(
        send_transactional_email_by_tenant_id,
        to_email=user.email,
        subject=subject,
        body_html=body_html,
        tenant_id=tenant.id,
    )
    
    return {"detail": "If the email is registered for a local account, a reset link will be sent shortly."}

@router.post("/reset-password")
def reset_password(payload: dict, db: Session = Depends(get_db)):
    token = payload.get("token")
    new_password = payload.get("password")
    
    if not token or not new_password:
        raise HTTPException(status_code=400, detail="Token and password are required")
    if len(str(new_password)) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long")
        
    user = db.query(User).filter(
        User.password_reset_token == token,
        User.password_reset_expires_at > datetime.utcnow()
    ).first()
    
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
        
    user.password_hash = auth.hash_password(str(new_password))
    user.password_reset_token = None
    user.password_reset_expires_at = None
    db.commit()
    
    return {"detail": "Password reset successfully. You can now login with your new credentials."}

