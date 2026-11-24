import time
import threading
import concurrent.futures
import ipaddress
import socket
import urllib.request
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import dns.resolver
import database as db_mod
from database import get_db, Tenant, User, GlobalSettings, QueueItem, Subscriber
import auth
from security_utils import is_safe_mail_host, is_safe_outbound_url

router = APIRouter(prefix="/api/tenants", tags=["tenants"])

VALID_QUEUE_SEND_ORDERS = {"default", "random", "alphabetical", "alphabetical_desc", "domain_interleaved"}

_ip_cache_lock = threading.Lock()
_cached_public_ip = None
_cached_public_ip_at = 0.0


def get_cached_public_ip(force_refresh: bool = False) -> str:
    """Resolve outbound public IP via api.ipify.org at most once every 10 minutes."""
    global _cached_public_ip, _cached_public_ip_at
    now = time.monotonic()
    if not force_refresh and _cached_public_ip and (now - _cached_public_ip_at) < 600:
        return _cached_public_ip
    with _ip_cache_lock:
        now = time.monotonic()
        if not force_refresh and _cached_public_ip and (now - _cached_public_ip_at) < 600:
            return _cached_public_ip
        try:
            ip = urllib.request.urlopen("https://api.ipify.org", timeout=2).read().decode("utf-8").strip()
            if ip:
                _cached_public_ip = ip
                _cached_public_ip_at = now
                return ip
        except Exception:
            pass
    return _cached_public_ip or "unknown"


def _serialize_tenant_safe(t: Tenant) -> dict:
    """Serialize Tenant omitting sensitive secrets (smtp_password, imap_password, dkim_private_key)."""
    return {
        "id": t.id,
        "name": t.name,
        "logo_path": t.logo_path,
        "smtp_host": t.smtp_host,
        "smtp_port": t.smtp_port,
        "smtp_username": t.smtp_username,
        "smtp_has_password": bool(t.smtp_password),
        "smtp_use_ssl": t.smtp_use_ssl,
        "smtp_use_tls": t.smtp_use_tls,
        "direct_send": t.direct_send,
        "dkim_domain": t.dkim_domain,
        "dkim_selector": t.dkim_selector,
        "dkim_public_key": t.dkim_public_key,
        "dkim_has_private_key": bool(t.dkim_private_key),
        "mta_from_prefix": t.mta_from_prefix,
        "imap_host": t.imap_host,
        "imap_port": t.imap_port,
        "imap_username": t.imap_username,
        "imap_has_password": bool(t.imap_password),
        "imap_use_ssl": t.imap_use_ssl,
        "imap_delete_processed": t.imap_delete_processed,
        "speed_emails_per_hour": t.speed_emails_per_hour,
        "max_sending_threads": t.max_sending_threads,
        "queue_send_order": getattr(t, "queue_send_order", None) or "default",
        "bounce_email": t.bounce_email,
        "bounce_provider": t.bounce_provider,
        "bounce_webhook_token": t.bounce_webhook_token,
        "double_opt_in": t.double_opt_in,
        "retry_interval_minutes": t.retry_interval_minutes,
        "double_opt_in_subject": t.double_opt_in_subject,
        "double_opt_in_body_blocks": t.double_opt_in_body_blocks,
        "double_opt_in_body_html": t.double_opt_in_body_html,
        "double_opt_in_is_custom_html": t.double_opt_in_is_custom_html,
        "double_opt_in_custom_html": t.double_opt_in_custom_html,
        "email_footer_blocks": t.email_footer_blocks,
        "email_footer_html": t.email_footer_html,
        "email_footer_is_custom_html": t.email_footer_is_custom_html,
        "email_footer_custom_html": t.email_footer_custom_html,
        "sending_ip_override": t.sending_ip_override,
        "subscription_confirmed_html": t.subscription_confirmed_html,
        "unsubscribed_html": t.unsubscribed_html,
        "history_retention_days": t.history_retention_days,
        "history_record_frequency_hours": t.history_record_frequency_hours,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _serialize_global_settings_safe(s: GlobalSettings) -> dict:
    """Serialize GlobalSettings while masking stored secrets."""
    if not s:
        return {}
    return {
        "id": s.id,
        "app_name": s.app_name,
        "app_logo": s.app_logo,
        "public_url": s.public_url,
        "mail_server_identity": s.mail_server_identity,
        "sending_ip_override": s.sending_ip_override,
        "oidc_enabled": s.oidc_enabled,
        "oidc_issuer": s.oidc_issuer,
        "oidc_client_id": s.oidc_client_id,
        "oidc_client_secret": "",
        "oidc_has_client_secret": bool(s.oidc_client_secret),
        "oidc_redirect_url": s.oidc_redirect_url,
        "allowed_domains": s.allowed_domains,
        "auto_create_tenants": s.auto_create_tenants,
        "local_login_enabled": s.local_login_enabled,
        "auto_update": s.auto_update,
        "update_channel": s.update_channel,
        "backup_token": s.backup_token,
        "external_backup_url": s.external_backup_url,
        "external_backup_auth_header": "",
        "external_backup_has_auth_header": bool(s.external_backup_auth_header),
        "oidc_role_claim": s.oidc_role_claim,
        "oidc_tenant_claim": s.oidc_tenant_claim,
        "oidc_super_admin_value": s.oidc_super_admin_value,
        "oidc_tenant_admin_value": s.oidc_tenant_admin_value,
        "oidc_tenant_user_value": s.oidc_tenant_user_value,
        "backup_interval_hours": s.backup_interval_hours,
        "backup_retention_count": s.backup_retention_count,
        "smtp_host": s.smtp_host,
        "smtp_port": s.smtp_port,
        "smtp_username": s.smtp_username,
        "smtp_password": "",
        "smtp_has_password": bool(s.smtp_password),
        "smtp_use_ssl": s.smtp_use_ssl,
        "smtp_use_tls": s.smtp_use_tls,
        "max_global_sending_threads": s.max_global_sending_threads,
        "max_domain_sending_threads": s.max_domain_sending_threads,
        "smtp_connection_reuse": s.smtp_connection_reuse,
        "history_retention_days": s.history_retention_days,
        "history_record_frequency_hours": s.history_record_frequency_hours,
    }


def generate_dkim_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')
    
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')
    
    # Extract base64 public key for TXT record
    lines = public_pem.split('\n')
    base64_pub = "".join([line.strip() for line in lines if "PUBLIC KEY" not in line and line.strip()])
    dns_record_value = f"v=DKIM1; k=rsa; p={base64_pub}"
    
    return private_pem, dns_record_value

# SUPER ADMIN ENDPOINTS

@router.get("")
def list_tenants(db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    tenants = db.query(Tenant).all()
    return [_serialize_tenant_safe(t) for t in tenants]

@router.get("/accessible")
def list_accessible_tenants(db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if current_user.role == "super_admin":
        tenants = db.query(Tenant).all()
    elif current_user.allowed_tenants:
        tenants = db.query(Tenant).filter(Tenant.id.in_(current_user.allowed_tenants)).all()
    elif current_user.tenant_id:
        tenants = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).all()
    else:
        tenants = []
    return [_serialize_tenant_safe(t) for t in tenants]

@router.post("")
def create_tenant(payload: dict = Body(...), db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Tenant name required")
        
    existing = db.query(Tenant).filter(Tenant.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Tenant name already exists")

    raw_order = (payload.get("queue_send_order") or "default").strip().lower()
    if raw_order not in VALID_QUEUE_SEND_ORDERS:
        raw_order = "default"
        
    tenant = Tenant(
        name=name,
        smtp_host=payload.get("smtp_host"),
        smtp_port=payload.get("smtp_port"),
        smtp_username=payload.get("smtp_username"),
        smtp_password=payload.get("smtp_password"),
        smtp_use_ssl=payload.get("smtp_use_ssl", False),
        smtp_use_tls=payload.get("smtp_use_tls", True),
        direct_send=payload.get("direct_send", False),
        dkim_domain=payload.get("dkim_domain"),
        dkim_selector=payload.get("dkim_selector", "polypress"),
        mta_from_prefix=payload.get("mta_from_prefix", "noreply"),
        imap_host=payload.get("imap_host"),
        imap_port=payload.get("imap_port"),
        imap_username=payload.get("imap_username"),
        imap_password=payload.get("imap_password"),
        imap_use_ssl=payload.get("imap_use_ssl", True),
        speed_emails_per_hour=payload.get("speed_emails_per_hour", 500),
        bounce_email=payload.get("bounce_email"),
        max_sending_threads=payload.get("max_sending_threads", 10),
        queue_send_order=raw_order,
    )
    
    if payload.get("generate_dkim"):
        priv, pub = generate_dkim_keypair()
        tenant.dkim_private_key = priv
        tenant.dkim_public_key = pub
        
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return _serialize_tenant_safe(tenant)

# GLOBAL SETTINGS (Super Admin Only)

@router.get("/global-settings")
def get_global_settings(db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    settings = db.query(GlobalSettings).first()
    return _serialize_global_settings_safe(settings)

@router.put("/global-settings")
def update_global_settings(payload: dict = Body(...), db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    settings = db.query(GlobalSettings).first()
    if not settings:
        settings = GlobalSettings()
        db.add(settings)
        
    new_oidc = payload.get("oidc_enabled", settings.oidc_enabled)
    new_local = payload.get("local_login_enabled", settings.local_login_enabled)
    
    # Safely force at least one to be enabled
    if not new_oidc and not new_local:
        new_local = True
        
    # Enforce having at least one active super admin of the selected authentication type
    if new_oidc and not new_local:
        oidc_admins = db.query(User).filter(User.role == "super_admin", User.auth_type == "oidc", User.is_active == True).count()
        if oidc_admins == 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot disable Local Auth: There are no active Global Admin accounts configured to use OIDC (SSO) login. You would be locked out."
            )
    elif new_local and not new_oidc:
        local_admins = db.query(User).filter(User.role == "super_admin", User.auth_type == "local", User.is_active == True).count()
        if local_admins == 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot disable OIDC: There are no active Global Admin accounts configured to use Local password login."
            )
            
    settings.app_name = payload.get("app_name", settings.app_name)
    settings.app_logo = payload.get("app_logo", settings.app_logo)
    settings.public_url = payload.get("public_url", settings.public_url)
    settings.mail_server_identity = payload.get("mail_server_identity", settings.mail_server_identity)
    if "sending_ip_override" in payload:
        settings.sending_ip_override = payload["sending_ip_override"].strip() if payload["sending_ip_override"] else None
    settings.oidc_enabled = new_oidc
    settings.oidc_issuer = payload.get("oidc_issuer", settings.oidc_issuer)
    settings.oidc_client_id = payload.get("oidc_client_id", settings.oidc_client_id)
    if payload.get("oidc_client_secret"):
        settings.oidc_client_secret = payload["oidc_client_secret"]
    settings.oidc_redirect_url = payload.get("oidc_redirect_url", settings.oidc_redirect_url)
    settings.allowed_domains = payload.get("allowed_domains", settings.allowed_domains)
    settings.auto_create_tenants = payload.get("auto_create_tenants", settings.auto_create_tenants)
    settings.local_login_enabled = new_local
    
    # Auto-updates and Backups API
    settings.auto_update = payload.get("auto_update", settings.auto_update)
    settings.update_channel = payload.get("update_channel", settings.update_channel)
    settings.backup_token = payload.get("backup_token", settings.backup_token)
    if "external_backup_url" in payload:
        ext_url = (payload.get("external_backup_url") or "").strip()
        if ext_url:
            is_safe, reason = is_safe_outbound_url(ext_url)
            if not is_safe:
                raise HTTPException(status_code=400, detail=f"External backup URL rejected: {reason}")
        settings.external_backup_url = ext_url or None
    if payload.get("external_backup_auth_header"):
        settings.external_backup_auth_header = payload["external_backup_auth_header"]
    
    # Custom OIDC Claim Mappings
    settings.oidc_role_claim = payload.get("oidc_role_claim", settings.oidc_role_claim)
    settings.oidc_tenant_claim = payload.get("oidc_tenant_claim", settings.oidc_tenant_claim)
    settings.oidc_super_admin_value = payload.get("oidc_super_admin_value", settings.oidc_super_admin_value)
    settings.oidc_tenant_admin_value = payload.get("oidc_tenant_admin_value", settings.oidc_tenant_admin_value)
    settings.oidc_tenant_user_value = payload.get("oidc_tenant_user_value", settings.oidc_tenant_user_value)
    
    # Auto Backup configuration
    settings.backup_interval_hours = int(payload.get("backup_interval_hours", settings.backup_interval_hours or 0))
    settings.backup_retention_count = int(payload.get("backup_retention_count", settings.backup_retention_count or 10))
    
    # Global SMTP relay fallback settings
    settings.smtp_host = payload.get("smtp_host", settings.smtp_host)
    if "smtp_port" in payload:
        settings.smtp_port = int(payload["smtp_port"]) if payload["smtp_port"] else None
    settings.smtp_username = payload.get("smtp_username", settings.smtp_username)
    if payload.get("smtp_password"):
        settings.smtp_password = payload["smtp_password"]
    settings.smtp_use_ssl = payload.get("smtp_use_ssl", settings.smtp_use_ssl)
    settings.smtp_use_tls = payload.get("smtp_use_tls", settings.smtp_use_tls)
    
    # Global Worker & Concurrency Scaling Settings
    if "max_global_sending_threads" in payload:
        settings.max_global_sending_threads = max(1, int(payload["max_global_sending_threads"]))
    if "max_domain_sending_threads" in payload:
        settings.max_domain_sending_threads = max(1, int(payload["max_domain_sending_threads"]))
    if "smtp_connection_reuse" in payload:
        settings.smtp_connection_reuse = bool(payload["smtp_connection_reuse"])
    
    db.commit()
    db.refresh(settings)
    return _serialize_global_settings_safe(settings)


# TENANT ADMIN / USER SETTINGS (Scoped to Current Tenant)

@router.get("/my")
def get_my_tenant(db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User is not associated with any tenant")
        
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    import secrets
    if not tenant.bounce_webhook_token:
        tenant.bounce_webhook_token = secrets.token_urlsafe(32)
        db.commit()
        db.refresh(tenant)
        
    return _serialize_tenant_safe(tenant)

@router.put("/my")
def update_my_tenant(payload: dict = Body(...), db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User is not associated with any tenant")
        
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    tenant.name = payload.get("name", tenant.name)
    tenant.logo_path = payload.get("logo_path", tenant.logo_path)
    
    tenant.smtp_host = payload.get("smtp_host", tenant.smtp_host)
    tenant.smtp_port = payload.get("smtp_port", tenant.smtp_port)
    tenant.smtp_username = payload.get("smtp_username", tenant.smtp_username)
    if payload.get("smtp_password"):
        tenant.smtp_password = payload.get("smtp_password")
    tenant.smtp_use_ssl = payload.get("smtp_use_ssl", tenant.smtp_use_ssl)
    tenant.smtp_use_tls = payload.get("smtp_use_tls", tenant.smtp_use_tls)
    
    tenant.direct_send = payload.get("direct_send", tenant.direct_send)
    tenant.dkim_domain = payload.get("dkim_domain", tenant.dkim_domain)
    tenant.dkim_selector = payload.get("dkim_selector", tenant.dkim_selector)
    tenant.mta_from_prefix = payload.get("mta_from_prefix", tenant.mta_from_prefix)
    
    tenant.imap_host = payload.get("imap_host", tenant.imap_host)
    tenant.imap_port = payload.get("imap_port", tenant.imap_port)
    tenant.imap_username = payload.get("imap_username", tenant.imap_username)
    if payload.get("imap_password"):
        tenant.imap_password = payload.get("imap_password")
    tenant.imap_use_ssl = payload.get("imap_use_ssl", tenant.imap_use_ssl)
    tenant.imap_delete_processed = payload.get("imap_delete_processed", tenant.imap_delete_processed)
    
    tenant.bounce_provider = payload.get("bounce_provider", tenant.bounce_provider)
    if "bounce_webhook_token" in payload and payload["bounce_webhook_token"]:
        tenant.bounce_webhook_token = payload["bounce_webhook_token"]
        
    tenant.speed_emails_per_hour = payload.get("speed_emails_per_hour", tenant.speed_emails_per_hour)
    if "max_sending_threads" in payload and payload["max_sending_threads"]:
        tenant.max_sending_threads = max(1, int(payload["max_sending_threads"]))
    if "queue_send_order" in payload:
        raw_order = (payload.get("queue_send_order") or "default").strip().lower()
        if raw_order in VALID_QUEUE_SEND_ORDERS:
            tenant.queue_send_order = raw_order
    tenant.bounce_email = payload.get("bounce_email", tenant.bounce_email)
    tenant.double_opt_in = payload.get("double_opt_in", tenant.double_opt_in)
    tenant.retry_interval_minutes = payload.get("retry_interval_minutes", tenant.retry_interval_minutes)
    
    if "sending_ip_override" in payload:
        tenant.sending_ip_override = payload["sending_ip_override"].strip() if payload["sending_ip_override"] else None
        
    if "double_opt_in_subject" in payload:
        tenant.double_opt_in_subject = payload["double_opt_in_subject"]
    if "double_opt_in_body_blocks" in payload:
        tenant.double_opt_in_body_blocks = payload["double_opt_in_body_blocks"]
    if "double_opt_in_body_html" in payload:
        tenant.double_opt_in_body_html = payload["double_opt_in_body_html"]
    if "double_opt_in_is_custom_html" in payload:
        tenant.double_opt_in_is_custom_html = payload["double_opt_in_is_custom_html"]
    if "double_opt_in_custom_html" in payload:
        tenant.double_opt_in_custom_html = payload["double_opt_in_custom_html"]
    if "email_footer_blocks" in payload:
        tenant.email_footer_blocks = payload["email_footer_blocks"]
    if "email_footer_html" in payload:
        tenant.email_footer_html = payload["email_footer_html"]
    if "email_footer_is_custom_html" in payload:
        tenant.email_footer_is_custom_html = payload["email_footer_is_custom_html"]
    if "email_footer_custom_html" in payload:
        tenant.email_footer_custom_html = payload["email_footer_custom_html"]
    if "subscription_confirmed_html" in payload:
        tenant.subscription_confirmed_html = payload["subscription_confirmed_html"]
    if "unsubscribed_html" in payload:
        tenant.unsubscribed_html = payload["unsubscribed_html"]
        
    db.commit()
    db.refresh(tenant)
    return {"detail": "Settings updated successfully"}

@router.post("/my/rotate-webhook-token")
def rotate_webhook_token(db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User is not associated with any tenant")
        
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    import secrets
    tenant.bounce_webhook_token = secrets.token_urlsafe(32)
    db.commit()
    db.refresh(tenant)
    return {"bounce_webhook_token": tenant.bounce_webhook_token}

@router.post("/test-smtp")
def test_smtp_settings(payload: dict = Body(...), db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    to_email = payload.get("test_email")
    if not to_email:
        raise HTTPException(status_code=400, detail="Test recipient email address is required")
        
    db_tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first() if current_user.tenant_id else None
    
    # Extract settings falling back to database
    smtp_host = payload.get("smtp_host") or (db_tenant.smtp_host if db_tenant else None)
    smtp_port = payload.get("smtp_port") or (db_tenant.smtp_port if db_tenant else None)
    smtp_username = payload.get("smtp_username") or (db_tenant.smtp_username if db_tenant else None)
    smtp_password = payload.get("smtp_password") or (db_tenant.smtp_password if db_tenant else None)
    smtp_use_ssl = payload.get("smtp_use_ssl", db_tenant.smtp_use_ssl if db_tenant else False)
    smtp_use_tls = payload.get("smtp_use_tls", db_tenant.smtp_use_tls if db_tenant else True)
    
    direct_send = payload.get("direct_send", db_tenant.direct_send if db_tenant else False)
    if not direct_send and smtp_host:
        is_safe, reason = is_safe_mail_host(smtp_host)
        if not is_safe:
            raise HTTPException(status_code=400, detail=f"Invalid SMTP host: {reason}")
    dkim_selector = payload.get("dkim_selector") or (db_tenant.dkim_selector if db_tenant else "polypress")
    dkim_domain = payload.get("dkim_domain") or (db_tenant.dkim_domain if db_tenant else None)
    dkim_private_key = payload.get("dkim_private_key") or (db_tenant.dkim_private_key if db_tenant else None)
    bounce_email = payload.get("bounce_email") or (db_tenant.bounce_email if db_tenant else None)
    sending_ip_override = payload.get("sending_ip_override") or (db_tenant.sending_ip_override if db_tenant else None)
    
    mock_tenant = Tenant(
        id=current_user.tenant_id or 0,
        name=payload.get("name") or (db_tenant.name if db_tenant else "PolyPress Test Tenant"),
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        smtp_use_ssl=smtp_use_ssl,
        smtp_use_tls=smtp_use_tls,
        direct_send=direct_send,
        dkim_selector=dkim_selector,
        dkim_domain=dkim_domain,
        dkim_private_key=dkim_private_key,
        bounce_email=bounce_email,
        sending_ip_override=sending_ip_override
    )
    
    # Resolve server public IP for direct sending diagnostics info
    public_ip = None
    db_settings = db.query(GlobalSettings).first()
    if mock_tenant.sending_ip_override:
        public_ip = mock_tenant.sending_ip_override.strip()
    elif db_settings and db_settings.sending_ip_override:
        public_ip = db_settings.sending_ip_override.strip()
    else:
        detected_ip = get_cached_public_ip()
        if detected_ip and detected_ip != "unknown":
            public_ip = detected_ip

    if mock_tenant.direct_send:
        test_subject = f"MTA Direct Send Test successful - {mock_tenant.name}"
        test_body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>PolyPress MTA Direct Send Test</title>
</head>
<body style="background-color: #0b0f19; color: #f1f5f9; font-family: sans-serif; padding: 40px 20px; text-align: center;">
    <div style="max-width: 550px; margin: 0 auto; background-color: #1e293b; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 30px; box-shadow: 0 10px 25px rgba(0,0,0,0.3); text-align: left;">
        <h1 style="color: #10b981; font-size: 22px; margin-bottom: 15px; text-align: center;">MTA Direct Send Test Successful!</h1>
        <p style="color: #cbd5e1; font-size: 15px; line-height: 1.6; margin-bottom: 25px;">
            This email confirms that your local MTA (Mail Transfer Agent) configuration is correct and PolyPress is successfully sending messages directly from your server's public IP address.
        </p>
        <div style="background-color: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 15px; font-size: 13px; color: #94a3b8; font-family: monospace; line-height: 1.5;">
            <strong>MTA Outbound Domain:</strong> {mock_tenant.dkim_domain}<br>
            <strong>DKIM Selector:</strong> {mock_tenant.dkim_selector}<br>
            <strong>Egress Public IP:</strong> {public_ip or 'unknown'}
        </div>
        <p style="font-size: 12px; color: #64748b; margin-top: 25px; text-align: center;">
            Sent via PolyPress Newsletter System.
        </p>
    </div>
</body>
</html>"""
    else:
        test_subject = f"SMTP Relay Test successful - {mock_tenant.name}"
        test_body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>PolyPress SMTP Relay Test</title>
</head>
<body style="background-color: #0b0f19; color: #f1f5f9; font-family: sans-serif; padding: 40px 20px; text-align: center;">
    <div style="max-width: 550px; margin: 0 auto; background-color: #1e293b; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 30px; box-shadow: 0 10px 25px rgba(0,0,0,0.3); text-align: left;">
        <h1 style="color: #6366f1; font-size: 22px; margin-bottom: 15px; text-align: center;">SMTP Relay Test Successful!</h1>
        <p style="color: #cbd5e1; font-size: 15px; line-height: 1.6; margin-bottom: 25px;">
            This email confirms that your outgoing mail server configuration is correct and PolyPress is successfully connected to your external SMTP provider.
        </p>
        <div style="background-color: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 15px; font-size: 13px; color: #94a3b8; font-family: monospace; line-height: 1.5;">
            <strong>SMTP Host:</strong> {mock_tenant.smtp_host}:{mock_tenant.smtp_port}<br>
            <strong>SMTP Username:</strong> {mock_tenant.smtp_username}
        </div>
        <p style="font-size: 12px; color: #64748b; margin-top: 25px; text-align: center;">
            Sent via PolyPress Newsletter System.
        </p>
    </div>
</body>
</html>"""

    # Append actual tenant footer and unsubscribe link (3e)
    footer_html = mock_tenant.email_footer_html or ""
    db_settings = db.query(GlobalSettings).first()
    tracking_domain = db_settings.public_url if (db_settings and db_settings.public_url) else "http://localhost:8000"
    if tracking_domain:
        tracking_domain = tracking_domain.rstrip("/")
    unsubscribe_url = f"{tracking_domain}/api/embed/unsubscribe/0/0"
    
    footer_html = footer_html.replace("{{unsubscribe_url}}", unsubscribe_url).replace("{unsubscribe_url}", unsubscribe_url)
    
    if "api/embed/unsubscribe/" not in footer_html:
        footer_html += f'<br><a href="{unsubscribe_url}" style="color: #6366f1; text-decoration: none;">Unsubscribe</a>'
        
    if "</body>" in test_body:
        test_body = test_body.replace("</body>", f"<div style='border-top:1px solid rgba(255,255,255,0.05); padding-top:20px; margin-top:20px;'>{footer_html}</div></body>")
    else:
        test_body += f"<div style='border-top:1px solid rgba(255,255,255,0.05); padding-top:20px; margin-top:20px;'>{footer_html}</div>"

    from sending_worker import send_direct_mta, send_external_smtp, QueueItem
    mock_item = QueueItem(
        id=0,
        tenant_id=current_user.tenant_id or 0,
        email=to_email,
        subject=test_subject,
        body_html=test_body
    )
    
    try:
        if mock_tenant.direct_send:
            success, is_transient, code, msg = send_direct_mta(mock_item, mock_tenant)
        else:
            success, is_transient, code, msg = send_external_smtp(mock_item, mock_tenant)
            
        if success:
            return {"success": True, "detail": "Test email dispatched successfully! Please check your inbox."}
        else:
            raise Exception(f"SMTP Error [{code}]: {msg}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Mail dispatch failed: {e}")

@router.post("/test-imap")
def test_imap_settings(payload: dict = Body(...), db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    host = payload.get("imap_host")
    port = payload.get("imap_port")
    username = payload.get("imap_username")
    password = payload.get("imap_password")
    use_ssl = payload.get("imap_use_ssl")
    
    db_tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first() if current_user.tenant_id else None
    if db_tenant:
        if not host:
            host = db_tenant.imap_host
        if port is None:
            port = db_tenant.imap_port
        if not username:
            username = db_tenant.imap_username
        if not password:
            password = db_tenant.imap_password
        if use_ssl is None:
            use_ssl = db_tenant.imap_use_ssl if db_tenant.imap_use_ssl is not None else True
            
    if not host or not username or not password:
        raise HTTPException(status_code=400, detail="imap_host, imap_username, and imap_password are required")

    is_safe, reason = is_safe_mail_host(host)
    if not is_safe:
        raise HTTPException(status_code=400, detail=f"Invalid IMAP host: {reason}")
        
    import imaplib
    try:
        if use_ssl:
            client = imaplib.IMAP4_SSL(host, port or 993, timeout=10)
        else:
            client = imaplib.IMAP4(host, port or 143, timeout=10)
            
        client._encoding = "utf-8"
        client.login(username, password)
        client.select("INBOX")
        client.close()
        client.logout()
        return {"success": True, "detail": "IMAP connection and authentication test successful! INBOX select OK."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"IMAP Test Failed: {e}")

@router.post("/test-imap/send")
def test_imap_loopback_send(payload: dict = Body(...), db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    db_tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not db_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    # Get IMAP email username to use as target address (unless bounce_email is explicitly set)
    target_email = payload.get("bounce_email") or db_tenant.bounce_email
    if not target_email:
        target_email = payload.get("imap_username") or db_tenant.imap_username
        
    if not target_email:
        raise HTTPException(status_code=400, detail="Bounce email or IMAP username is required to route the test email")
        
    # Generate unique loopback token
    import secrets
    token = secrets.token_hex(8)
    
    # We will send a simulated bounce email via SMTP/MTA
    db_settings = db.query(GlobalSettings).first()
    tracking_domain = db_settings.public_url if (db_settings and db_settings.public_url) else "http://localhost:8000"
    if tracking_domain:
        tracking_domain = tracking_domain.rstrip("/")
    unsubscribe_url = f"{tracking_domain}/api/embed/unsubscribe/0/0"
    
    footer_html = db_tenant.email_footer_html or ""
    footer_html = footer_html.replace("{{unsubscribe_url}}", unsubscribe_url).replace("{unsubscribe_url}", unsubscribe_url)
    if "api/embed/unsubscribe/" not in footer_html:
        footer_html += f'<br><a href="{unsubscribe_url}" style="color: #6366f1; text-decoration: none;">Unsubscribe</a>'

    test_body_html = f"""
    This is a PolyPress loopback bounce test.
    Token: {token}
    X-PolyPress-Campaign: 9999
    X-PolyPress-Subscriber: 8888
    X-PolyPress-QueueItem: 7777
    To: {target_email}
    Diagnostic-Code: smtp; 550 5.1.1 User Unknown (PolyPress Test)
    <div style='border-top:1px solid rgba(255,255,255,0.05); padding-top:20px; margin-top:20px;'>{footer_html}</div>
    """

    from sending_worker import send_direct_mta, send_external_smtp, QueueItem
    mock_item = QueueItem(
        id=7777,
        campaign_id=9999,
        subscriber_id=8888,
        email=target_email,
        subject=f"PolyPress Bounce Test - {token}",
        body_html=test_body_html
    )
    
    # Build an isolated detached Tenant snapshot with fallback to stored DB secrets
    smtp_host = payload.get("smtp_host") or db_tenant.smtp_host
    smtp_port = payload.get("smtp_port") or db_tenant.smtp_port
    smtp_username = payload.get("smtp_username") or db_tenant.smtp_username
    smtp_password = payload.get("smtp_password") or db_tenant.smtp_password
    smtp_use_ssl = payload.get("smtp_use_ssl", db_tenant.smtp_use_ssl)
    smtp_use_tls = payload.get("smtp_use_tls", db_tenant.smtp_use_tls)
    direct_send = payload.get("direct_send", db_tenant.direct_send)
    dkim_selector = payload.get("dkim_selector") or db_tenant.dkim_selector or "polypress"
    dkim_domain = payload.get("dkim_domain") or db_tenant.dkim_domain
    dkim_private_key = payload.get("dkim_private_key") or db_tenant.dkim_private_key
    mta_from_prefix = payload.get("mta_from_prefix") or db_tenant.mta_from_prefix or "noreply"
    bounce_email = payload.get("bounce_email") or db_tenant.bounce_email
    sending_ip_override = payload.get("sending_ip_override") or db_tenant.sending_ip_override

    mock_tenant = Tenant(
        id=db_tenant.id,
        name=payload.get("name") or db_tenant.name,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        smtp_use_ssl=smtp_use_ssl,
        smtp_use_tls=smtp_use_tls,
        direct_send=direct_send,
        mta_from_prefix=mta_from_prefix,
        dkim_selector=dkim_selector,
        dkim_domain=dkim_domain,
        dkim_private_key=dkim_private_key,
        bounce_email=bounce_email,
        sending_ip_override=sending_ip_override,
    )

    if not mock_tenant.direct_send and mock_tenant.smtp_host:
        is_safe, reason = is_safe_mail_host(mock_tenant.smtp_host)
        if not is_safe:
            raise HTTPException(status_code=400, detail=f"Invalid SMTP host: {reason}")
    
    try:
        if mock_tenant.direct_send:
            success, is_transient, code, msg = send_direct_mta(mock_item, mock_tenant)
        else:
            success, is_transient, code, msg = send_external_smtp(mock_item, mock_tenant)
            
        if success:
            return {"success": True, "token": token, "detail": f"Test email dispatched to {target_email}!"}
        else:
            raise Exception(f"SMTP Error [{code}]: {msg}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Mail dispatch failed: {e}")

@router.post("/test-imap/receive")
def test_imap_loopback_receive(payload: dict = Body(...), db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    db_tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not db_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    token = payload.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Token parameter is required")
        
    # Read IMAP settings from payload or db
    host = payload.get("imap_host") or db_tenant.imap_host
    port = payload.get("imap_port") or db_tenant.imap_port
    username = payload.get("imap_username") or db_tenant.imap_username
    password = payload.get("imap_password") or db_tenant.imap_password
    use_ssl = payload.get("imap_use_ssl")
    if use_ssl is None:
        use_ssl = db_tenant.imap_use_ssl if db_tenant.imap_use_ssl is not None else True
        
    if not host or not username or not password:
        raise HTTPException(status_code=400, detail="IMAP settings (host, username, password) are not fully configured")

    is_safe, reason = is_safe_mail_host(host)
    if not is_safe:
        raise HTTPException(status_code=400, detail=f"Invalid IMAP host: {reason}")
        
    import imaplib
    import time
    from bounce_worker import parse_bounce_report
    
    # We will search the INBOX with retry loops to wait for email arrival (up to 14 seconds)
    start_time = time.time()
    found_msg_id = None
    msg_bytes = None
    client = None
    
    try:
        while time.time() - start_time < 14:
            try:
                if use_ssl:
                    client = imaplib.IMAP4_SSL(host, port or 993, timeout=10)
                else:
                    client = imaplib.IMAP4(host, port or 143, timeout=10)
                    
                client._encoding = "utf-8"
                client.login(username, password)
                client.select("INBOX")
                
                # Search for emails containing the token in the subject
                search_term = f'SUBJECT "PolyPress Bounce Test - {token}"'
                status, messages = client.search(None, search_term)
                if status == "OK" and messages[0]:
                    msg_ids = messages[0].split()
                    if msg_ids:
                        found_msg_id = msg_ids[-1] # take the latest one
                        res, data = client.fetch(found_msg_id, "(RFC822)")
                        if res == "OK":
                            msg_bytes = data[0][1]
                            break
            except Exception:
                pass
            finally:
                if client:
                    try:
                        client.close()
                        client.logout()
                    except:
                        pass
                    client = None
            time.sleep(2)
            
        if not msg_bytes:
            raise Exception("Test email did not arrive in the bounce inbox within 14 seconds. Please try again or verify your settings.")
            
        # Parse tracking headers
        bounce_info = parse_bounce_report(msg_bytes)
        
        # Validate headers
        campaign_ok = bounce_info.get("campaign_id") == 9999
        subscriber_ok = bounce_info.get("subscriber_id") == 8888
        queue_item_ok = bounce_info.get("queue_item_id") == 7777
        
        # Clean up by permanently deleting the test message
        try:
            if use_ssl:
                client = imaplib.IMAP4_SSL(host, port or 993, timeout=10)
            else:
                client = imaplib.IMAP4(host, port or 143, timeout=10)
            client._encoding = "utf-8"
            client.login(username, password)
            client.select("INBOX")
            
            search_term = f'SUBJECT "PolyPress Bounce Test - {token}"'
            status, messages = client.search(None, search_term)
            if status == "OK" and messages[0]:
                for mid in messages[0].split():
                    client.store(mid, "+FLAGS", "\\Deleted")
                client.expunge()
        except Exception:
            pass
        finally:
            if client:
                try:
                    client.close()
                    client.logout()
                except:
                    pass
                    
        if not (campaign_ok and subscriber_ok and queue_item_ok):
            details = f"Campaign (9999): {'OK' if campaign_ok else 'Failed'}, Subscriber (8888): {'OK' if subscriber_ok else 'Failed'}, QueueItem (7777): {'OK' if queue_item_ok else 'Failed'}"
            raise Exception(f"Header verification failed! PolyPress could not parse tracking headers. details: {details}")
            
        return {"success": True, "detail": "Loopback processing test successful! All tracking headers parsed and verified."}
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/my/dkim")
def generate_my_dkim(db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User is not associated with any tenant")
        
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    priv, pub = generate_dkim_keypair()
    tenant.dkim_private_key = priv
    tenant.dkim_public_key = pub
    db.commit()
    
    return {"dkim_public_key": pub}

@router.get("/my/dns-test")
def test_my_dns(db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    import ipaddress
    import socket
    import urllib.request
    import concurrent.futures
    import dns.reversename
    
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    domain = tenant.dkim_domain
    if not domain:
        return {
            "mx": {"status": "missing", "sources": {"local": {"records": [], "error": None, "success": False}, "cloudflare": {"records": [], "error": None, "success": False}, "google": {"records": [], "error": None, "success": False}, "quad9": {"records": [], "error": None, "success": False}}},
            "spf": {"status": "missing", "sources": {"local": {"records": [], "error": None, "success": False}, "cloudflare": {"records": [], "error": None, "success": False}, "google": {"records": [], "error": None, "success": False}, "quad9": {"records": [], "error": None, "success": False}}, "spf_warning": ""},
            "dkim": {"status": "missing", "sources": {"local": {"records": [], "error": None, "success": False}, "cloudflare": {"records": [], "error": None, "success": False}, "google": {"records": [], "error": None, "success": False}, "quad9": {"records": [], "error": None, "success": False}}},
            "dmarc": {"status": "missing", "sources": {"local": {"records": [], "error": None, "success": False}, "cloudflare": {"records": [], "error": None, "success": False}, "google": {"records": [], "error": None, "success": False}, "quad9": {"records": [], "error": None, "success": False}}},
            "ptr": {"status": "missing", "sources": {"local": {"records": [], "error": None, "success": False}, "cloudflare": {"records": [], "error": None, "success": False}, "google": {"records": [], "error": None, "success": False}, "quad9": {"records": [], "error": None, "success": False}}},
            "blacklist": {"status": "missing", "sources": {"local": {"records": [], "error": None, "success": False}, "cloudflare": {"records": [], "error": None, "success": False}, "google": {"records": [], "error": None, "success": False}, "quad9": {"records": [], "error": None, "success": False}}}
        }

    # Fetch public IP of the PolyPress outbound server (or use override if provided)
    public_ip = None
    db_settings = db.query(GlobalSettings).first()
    if db_settings and db_settings.sending_ip_override:
        public_ip = db_settings.sending_ip_override.strip()
    elif tenant.sending_ip_override:
        public_ip = tenant.sending_ip_override.strip()
    else:
        detected = get_cached_public_ip()
        if detected and detected != "unknown":
            public_ip = detected

    servers = {
        "local": None,
        "cloudflare": "1.1.1.1",
        "google": "8.8.8.8",
        "quad9": "9.9.9.9"
    }

    def resolve_dns(host: str, rtype: str, server: str = None) -> dict:
        resolver = dns.resolver.Resolver()
        resolver.timeout = 2.0
        resolver.lifetime = 2.0
        if server:
            resolver.nameservers = [server]
        try:
            answers = resolver.resolve(host, rtype)
            if rtype == 'MX':
                return {"records": [str(ans.exchange).rstrip('.') for ans in answers], "error": None}
            elif rtype == 'PTR':
                return {"records": [str(ans.target).rstrip('.') for ans in answers], "error": None}
            else: # TXT / A
                records = []
                for ans in answers:
                    if rtype == 'TXT':
                        txt = "".join([t.decode('utf-8') for t in ans.strings])
                    else: # A
                        txt = str(ans)
                    records.append(txt)
                return {"records": records, "error": None}
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            return {"records": [], "error": None}
        except Exception as e:
            return {"records": [], "error": f"Resolver Error: {type(e).__name__}"}

    def check_dkim_key_match(dns_val: str, expected_val: str) -> bool:
        if not expected_val:
            return True
        clean_dns = "".join(dns_val.split()).rstrip(';').lower()
        clean_expected = "".join(expected_val.split()).rstrip(';').lower()
        return clean_dns == clean_expected

    def check_dmarc_policy_format(dns_val: str) -> bool:
        val = dns_val.lower()
        return val.startswith("v=dmarc1") and ("p=none" in val or "p=quarantine" in val or "p=reject" in val)

    def resolve_ip_matches_spf(ip_str: str, target_domain: str, spf_record: str, depth: int = 0) -> bool:
        if depth > 3:
            return False
        
        parts = spf_record.split()
        for part in parts:
            part = part.lower()
            if part.startswith("ip4:"):
                val = part[4:]
                try:
                    if "/" in val:
                        if ipaddress.IPv4Address(ip_str) in ipaddress.IPv4Network(val, strict=False):
                            return True
                    else:
                        if ipaddress.IPv4Address(ip_str) == ipaddress.IPv4Address(val):
                            return True
                except Exception:
                    pass
            elif part.startswith("ip6:"):
                val = part[6:]
                try:
                    if "/" in val:
                        if ipaddress.IPv6Address(ip_str) in ipaddress.IPv6Network(val, strict=False):
                            return True
                    else:
                        if ipaddress.IPv6Address(ip_str) == ipaddress.IPv6Address(val):
                            return True
                except Exception:
                    pass
            elif part == "a" or part.startswith("a:"):
                host = part[2:] if part.startswith("a:") else target_domain
                try:
                    for ip_info in socket.getaddrinfo(host, None):
                        if ip_info[4][0] == ip_str:
                            return True
                except Exception:
                    pass
            elif part == "mx" or part.startswith("mx:"):
                host = part[3:] if part.startswith("mx:") else target_domain
                try:
                    mx_res = resolve_dns(host, 'MX')
                    for mx in mx_res.get("records", []):
                        for ip_info in socket.getaddrinfo(mx, None):
                            if ip_info[4][0] == ip_str:
                                return True
                except Exception:
                    pass
            elif part.startswith("include:"):
                inc_domain = part[8:]
                try:
                    txt_res = resolve_dns(inc_domain, 'TXT')
                    for ans in txt_res.get("records", []):
                        if ans.startswith("v=spf1"):
                            if resolve_ip_matches_spf(ip_str, inc_domain, ans, depth + 1):
                                return True
                except Exception:
                    pass
        return False

    def calculate_status(sources: dict) -> str:
        total_valid = 0
        total_success = 0
        for s in sources.values():
            if s["error"] is None:
                total_valid += 1
                if s["success"]:
                    total_success += 1
        if total_valid == 0:
            return "missing"
        if total_success == total_valid:
            return "verified"
        if total_success == 0:
            return "missing"
        return "partial"

    results = {}

    def run_concurrently(func, *args):
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_server = {executor.submit(func, name, srv): name for name, srv in servers.items()}
            results_dict = {}
            for future in concurrent.futures.as_completed(future_to_server):
                name = future_to_server[future]
                results_dict[name] = future.result()
            return results_dict

    # 1. MX
    def get_mx_record(name, srv):
        res = resolve_dns(domain, 'MX', srv)
        return {
            "records": res["records"],
            "error": res["error"],
            "success": len(res["records"]) > 0 if res["error"] is None else False
        }
    mx_sources = run_concurrently(get_mx_record)
    results["mx"] = {"sources": mx_sources, "status": calculate_status(mx_sources)}

    # 2. SPF
    def get_spf_record(name, srv):
        res = resolve_dns(domain, 'TXT', srv)
        recs = res["records"]
        spf_recs = [r for r in recs if r.startswith("v=spf1")]
        return {
            "records": recs,
            "error": res["error"],
            "success": len(spf_recs) > 0 if res["error"] is None else False
        }
    spf_sources = run_concurrently(get_spf_record)
    results["spf"] = {"sources": spf_sources, "status": calculate_status(spf_sources), "spf_warning": ""}

    valid_spf_found_anywhere = any(s["success"] for s in spf_sources.values())
    if public_ip and valid_spf_found_anywhere:
        any_spf = None
        for name in ["local", "cloudflare", "google", "quad9"]:
            recs = spf_sources[name]["records"]
            spf_recs = [r for r in recs if r.startswith("v=spf1")]
            if spf_recs:
                any_spf = spf_recs[0]
                break
        if any_spf and not resolve_ip_matches_spf(public_ip, domain, any_spf):
            results["spf"]["spf_warning"] = f"Warning: Outbound public IP ({public_ip}) of the server is not authorized under the resolved SPF record."

    # 3. DKIM
    dkim_host = f"{tenant.dkim_selector}._domainkey.{domain}" if tenant.dkim_selector else None
    def get_dkim_record(name, srv):
        if not dkim_host: return {"records": [], "error": "No selector configured", "success": False}
        res = resolve_dns(dkim_host, 'TXT', srv)
        success = any(r.startswith("v=DKIM1") and check_dkim_key_match(r, tenant.dkim_public_key) for r in res["records"]) if res["error"] is None else False
        return {"records": res["records"], "error": res["error"], "success": success}
    dkim_sources = run_concurrently(get_dkim_record)
    results["dkim"] = {"sources": dkim_sources, "status": calculate_status(dkim_sources)}

    # 4. DMARC
    dmarc_host = f"_dmarc.{domain}"
    def get_dmarc_record(name, srv):
        res = resolve_dns(dmarc_host, 'TXT', srv)
        success = any(check_dmarc_policy_format(r) for r in res["records"]) if res["error"] is None else False
        return {"records": res["records"], "error": res["error"], "success": success}
    dmarc_sources = run_concurrently(get_dmarc_record)
    results["dmarc"] = {"sources": dmarc_sources, "status": calculate_status(dmarc_sources)}

    # 5. Reverse DNS (PTR) Check
    def get_ptr_record(name, srv):
        if not public_ip:
            return {"records": [], "error": "No sending IP detected/configured", "success": False}
        try:
            rev_name = dns.reversename.from_address(public_ip)
            res = resolve_dns(str(rev_name), 'PTR', srv)
            records = res["records"]
            err = res["error"]
            success = False
            
            # Match against mail_server_identity if direct send, else dkim domain
            if tenant.direct_send:
                expected_domain = (db_settings.mail_server_identity or "polypress.local").strip().lower()
            else:
                expected_domain = domain.lower()
                
            if err is None and records:
                for r in records:
                    r_clean = r.rstrip('.').lower()
                    if expected_domain in r_clean or r_clean.endswith(expected_domain):
                        success = True
            return {
                "records": records,
                "error": err,
                "success": success
            }
        except Exception as e:
            return {
                "records": [],
                "error": f"PTR Exception: {type(e).__name__}",
                "success": False
            }
    ptr_sources = run_concurrently(get_ptr_record)
    results["ptr"] = {"sources": ptr_sources, "status": calculate_status(ptr_sources)}

    # 6. IP Blacklist Check (executed concurrently across DNSBLs and resolvers)
    def get_blacklist_status_per_dnsbl():
        if not public_ip:
            empty_res = {"records": ["No sending IP detected/configured"], "error": None, "success": False}
            return {
                "Spamhaus (zen.spamhaus.org)": empty_res,
                "Spamcop (bl.spamcop.net)": empty_res,
                "SORBS (dnsbl.sorbs.net)": empty_res
            }
        
        try:
            ipaddress.IPv4Address(public_ip)
        except Exception:
            clean_res = {"records": ["Blacklist check only supported for IPv4"], "error": None, "success": True}
            return {
                "Spamhaus (zen.spamhaus.org)": clean_res,
                "Spamcop (bl.spamcop.net)": clean_res,
                "SORBS (dnsbl.sorbs.net)": clean_res
            }
            
        parts = public_ip.split('.')
        rev_ip = f"{parts[3]}.{parts[2]}.{parts[1]}.{parts[0]}"
        
        blacklists = {
            "Spamhaus (zen.spamhaus.org)": "zen.spamhaus.org",
            "Spamcop (bl.spamcop.net)": "bl.spamcop.net",
            "SORBS (dnsbl.sorbs.net)": "dnsbl.sorbs.net"
        }

        query_results = {label: {} for label in blacklists}
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            future_map = {}
            for label, dnsbl in blacklists.items():
                query_host = f"{rev_ip}.{dnsbl}"
                for ns_name, ns_srv in servers.items():
                    fut = pool.submit(resolve_dns, query_host, 'A', ns_srv)
                    future_map[fut] = (label, ns_name)
            for fut in concurrent.futures.as_completed(future_map):
                label, ns_name = future_map[fut]
                try:
                    query_results[label][ns_name] = fut.result()
                except Exception as exc:
                    query_results[label][ns_name] = {"records": [], "error": f"Resolver Error: {type(exc).__name__}"}
        
        dnsbl_results = {}
        for label in blacklists:
            listed_ips = []
            resolver_errors = []
            valid_queries = 0
            
            for ns_name in servers:
                res = query_results[label].get(ns_name, {"records": [], "error": "Missing"})
                if res["error"] is not None:
                    resolver_errors.append(f"{ns_name}: {res['error']}")
                else:
                    valid_queries += 1
                    for rec in res["records"]:
                        if rec.startswith("127.0.0."):
                            listed_ips.append(rec)
                            
            if listed_ips:
                dnsbl_results[label] = {
                    "records": [f"Listed (resolved: {', '.join(sorted(list(set(listed_ips))))})"],
                    "error": None,
                    "success": False
                }
            elif valid_queries > 0:
                dnsbl_results[label] = {
                    "records": ["Clean (not listed)"],
                    "error": None,
                    "success": True
                }
            else:
                dnsbl_results[label] = {
                    "records": [],
                    "error": "; ".join(resolver_errors) if resolver_errors else "Resolver Error",
                    "success": False
                }
        return dnsbl_results

    blacklist_sources = get_blacklist_status_per_dnsbl()
    results["blacklist"] = {"sources": blacklist_sources, "status": calculate_status(blacklist_sources)}

    return results

@router.get("/my/detected-ip")
def get_detected_ip(force: bool = False, current_user: User = Depends(auth.require_tenant_admin)):
    return {"public_ip": get_cached_public_ip(force_refresh=force)}

@router.get("/my/queue")
def get_my_queue(db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    items = db.query(QueueItem).filter(
        QueueItem.tenant_id == current_user.tenant_id,
        QueueItem.status.in_(["pending", "sending", "deferred"])
    ).order_by(QueueItem.created_at.desc()).all()
    
    return [
        {
            "id": i.id,
            "email": i.email,
            "subject": i.subject,
            "status": i.status,
            "retries": i.retries,
            "next_attempt": i.next_attempt,
            "error_message": i.error_message,
            "last_mx_response": i.last_mx_response,
            "error_code": i.error_code,
            "created_at": i.created_at,
            "updated_at": i.updated_at
        }
        for i in items
    ]

@router.delete("/my/queue/{queue_id}")
def delete_queue_item(queue_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    item = db.query(QueueItem).filter(
        QueueItem.id == queue_id,
        QueueItem.tenant_id == current_user.tenant_id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
        
    db.delete(item)
    db.commit()
    return {"detail": "Queue item removed successfully"}


@router.put("/{tenant_id}")
def update_tenant(tenant_id: int, payload: dict = Body(...), db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    name = payload.get("name")
    if name and name != tenant.name:
        existing = db.query(Tenant).filter(Tenant.name == name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Tenant name already exists")
        tenant.name = name
        
    if "dkim_domain" in payload:
        tenant.dkim_domain = payload["dkim_domain"]
    if "direct_send" in payload:
        tenant.direct_send = payload["direct_send"]
        
    for field in ["smtp_host", "smtp_port", "smtp_username", "smtp_use_ssl", "smtp_use_tls", "dkim_selector", "mta_from_prefix", "imap_host", "imap_port", "imap_username", "imap_use_ssl", "imap_delete_processed", "speed_emails_per_hour", "bounce_email", "retry_interval_minutes", "double_opt_in_subject", "double_opt_in_body_blocks", "double_opt_in_body_html", "email_footer_blocks", "email_footer_html", "sending_ip_override", "max_sending_threads"]:
        if field in payload:
            setattr(tenant, field, payload[field])
            
    if "queue_send_order" in payload:
        raw_order = (payload.get("queue_send_order") or "default").strip().lower()
        if raw_order in VALID_QUEUE_SEND_ORDERS:
            tenant.queue_send_order = raw_order
    if payload.get("smtp_password"):
        tenant.smtp_password = payload["smtp_password"]
    if payload.get("imap_password"):
        tenant.imap_password = payload["imap_password"]
        
    db.commit()
    db.refresh(tenant)
    return _serialize_tenant_safe(tenant)

@router.delete("/{tenant_id}")
def delete_tenant(tenant_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    from sqlalchemy.orm.attributes import flag_modified
    # Unlink users belonging to this tenant cleanly without deleting super admins
    for u in db.query(User).all():
        changed = False
        if u.tenant_id == tenant_id:
            u.tenant_id = None
            changed = True
        if isinstance(u.allowed_tenants, list) and tenant_id in u.allowed_tenants:
            u.allowed_tenants = [tid for tid in u.allowed_tenants if tid != tenant_id]
            flag_modified(u, "allowed_tenants")
            changed = True
        if changed and u.role != "super_admin" and u.tenant_id is None and u.allowed_tenants:
            u.tenant_id = u.allowed_tenants[0]

    # Delete all tenant-owned child records explicitly to leave no orphaned rows
    db.query(db_mod.AutomationLog).filter(db_mod.AutomationLog.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(db_mod.AutomationState).filter(db_mod.AutomationState.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(db_mod.AutomationFlow).filter(db_mod.AutomationFlow.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(db_mod.SubscriberActivity).filter(db_mod.SubscriberActivity.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(db_mod.TrackingLog).filter(db_mod.TrackingLog.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(db_mod.QueueItem).filter(db_mod.QueueItem.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(db_mod.Campaign).filter(db_mod.Campaign.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(db_mod.Subscriber).filter(db_mod.Subscriber.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(db_mod.SubscriberList).filter(db_mod.SubscriberList.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(db_mod.ApiKey).filter(db_mod.ApiKey.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(db_mod.WebhookSubscription).filter(db_mod.WebhookSubscription.tenant_id == tenant_id).delete(synchronize_session=False)

    db.delete(tenant)
    db.commit()
    return {"detail": "Tenant deleted"}

@router.post("/reset/history")
def reset_history_db(db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    import database as db_mod
    history_db = db_mod.HistorySessionLocal()
    try:
        history_db.query(db_mod.HistoricalMetric).delete()
        history_db.commit()
    except Exception as e:
        history_db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to reset history database: {e}")
    finally:
        history_db.close()
    return {"status": "success", "detail": "History metrics database reset successfully."}

@router.post("/reset/all")
def reset_all(db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    import os
    import database as db_mod
    
    # 1. Reset history DB
    history_db = db_mod.HistorySessionLocal()
    try:
        history_db.query(db_mod.HistoricalMetric).delete()
        history_db.commit()
    except Exception:
        history_db.rollback()
    finally:
        history_db.close()
        
    # 2. Reset main DB
    try:
        # Delete in dependency order across all tables
        db.query(db_mod.AutomationLog).delete()
        db.query(db_mod.AutomationState).delete()
        db.query(db_mod.AutomationFlow).delete()
        db.query(db_mod.SubscriberActivity).delete()
        db.query(db_mod.TrackingLog).delete()
        db.query(db_mod.QueueItem).delete()
        db.query(db_mod.Campaign).delete()
        db.query(db_mod.Subscriber).delete()
        db.query(db_mod.SubscriberList).delete()
        db.query(db_mod.ApiKey).delete()
        db.query(db_mod.WebhookSubscription).delete()
        db.query(db_mod.User).delete()
        db.query(db_mod.Tenant).delete()
        db.query(db_mod.GlobalSettings).delete()
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to reset database: {e}")
        
    # 3. Clean up custom logos
    BASE_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    branding_dir = os.path.join(BASE_DIR, "branding")
    if os.path.exists(branding_dir):
        for f in os.listdir(branding_dir):
            if f.startswith("custom_logo."):
                try:
                    os.remove(os.path.join(branding_dir, f))
                except Exception:
                    pass
                    
    # 4. Clean up backups
    backup_dir = os.path.join(BASE_DIR, "backups")
    if os.path.exists(backup_dir):
        for f in os.listdir(backup_dir):
            try:
                os.remove(os.path.join(backup_dir, f))
            except Exception:
                pass
                
    return {"status": "success", "detail": "Program has been fully reset. Returning to onboarding."}

@router.get("/my/delivery-diagnostics")
def get_delivery_diagnostics(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_user)
):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    tenant_id = current_user.tenant_id
    
    from datetime import datetime, timedelta
    from database import QueueItem, Tenant
    from sending_worker import get_active_threads_for_tenant
    
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    one_day_ago = datetime.utcnow() - timedelta(hours=24)
    
    active_threads = get_active_threads_for_tenant(tenant_id)
    pending_count = db.query(QueueItem).filter(QueueItem.tenant_id == tenant_id, QueueItem.status == "pending").count()
    sending_count = db.query(QueueItem).filter(QueueItem.tenant_id == tenant_id, QueueItem.status == "sending").count()
    sent_count = db.query(QueueItem).filter(QueueItem.tenant_id == tenant_id, QueueItem.status == "sent").count()
    failed_count = db.query(QueueItem).filter(QueueItem.tenant_id == tenant_id, QueueItem.status == "failed").count()
    deferred_count = db.query(QueueItem).filter(QueueItem.tenant_id == tenant_id, QueueItem.status == "deferred").count()
    
    sent_last_hour = db.query(QueueItem).filter(
        QueueItem.tenant_id == tenant_id,
        QueueItem.status == "sent",
        QueueItem.updated_at >= one_hour_ago
    ).count()
    
    sent_last_24h = db.query(QueueItem).filter(
        QueueItem.tenant_id == tenant_id,
        QueueItem.status == "sent",
        QueueItem.updated_at >= one_day_ago
    ).count()
    
    recent_failures = db.query(QueueItem).filter(
        QueueItem.tenant_id == tenant_id,
        QueueItem.status == "failed"
    ).order_by(QueueItem.updated_at.desc()).limit(10).all()
    
    failures_list = [{
        "email": f.email,
        "subject": f.subject,
        "error_message": f.error_message,
        "last_mx_response": f.last_mx_response,
        "error_code": f.error_code,
        "updated_at": f.updated_at.isoformat() if f.updated_at else None
    } for f in recent_failures]
    
    return {
        "active_threads": active_threads,
        "max_sending_threads": tenant.max_sending_threads,
        "speed_limit_per_hour": tenant.speed_emails_per_hour,
        "pending": pending_count,
        "sending": sending_count,
        "sent": sent_count,
        "failed": failed_count,
        "deferred": deferred_count,
        "sent_last_hour": sent_last_hour,
        "sent_last_24h": sent_last_24h,
        "recent_failures": failures_list
    }

@router.post("/my/clear-failed-logs")
def clear_failed_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.require_tenant_admin)
):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    db.query(QueueItem).filter(
        QueueItem.tenant_id == current_user.tenant_id,
        QueueItem.status == "failed"
    ).delete()
    db.commit()
    return {"detail": "Failed email diagnostics log cleared successfully"}

@router.post("/my/flush-queue")
def flush_tenant_queue(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.require_tenant_admin)
):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    now = datetime.utcnow()
    updated = db.query(QueueItem).filter(
        QueueItem.tenant_id == current_user.tenant_id,
        QueueItem.status.in_(["pending", "deferred"])
    ).update({
        QueueItem.next_attempt: now,
        QueueItem.status: "pending"
    }, synchronize_session=False)
    
    db.commit()
    return {"detail": f"Flushed queue: {updated} items reset to immediate dispatch."}

@router.post("/my/purge-queue")
def purge_tenant_queue(
    payload: dict = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.require_tenant_admin)
):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    mark_failed = False
    if payload and isinstance(payload, dict):
        mark_failed = bool(payload.get("mark_failed", False))
    tenant_id = current_user.tenant_id
    
    outbox_items = db.query(QueueItem).filter(
        QueueItem.tenant_id == tenant_id,
        QueueItem.status.in_(["pending", "sending", "deferred"])
    ).all()
    purged_count = len(outbox_items)
    
    if mark_failed and outbox_items:
        sub_ids = {item.subscriber_id for item in outbox_items if item.subscriber_id}
        if sub_ids:
            subs = db.query(Subscriber).filter(
                Subscriber.id.in_(sub_ids),
                Subscriber.tenant_id == tenant_id
            ).all()
            for sub in subs:
                if sub.status == "deferred":
                    sub.status = "failed"
                    sub.bounce_reason = "Consecutive Outbox Queue Purges by Admin"
                    sub.bounce_source_email = "System Outbox Queue Admin"
                elif sub.status in ["active", "pending"]:
                    sub.status = "deferred"
                    sub.bounce_reason = "Outbox Queue Purged by Admin"
                    sub.bounce_source_email = "System Outbox Queue Admin"
                    
    db.query(QueueItem).filter(
        QueueItem.tenant_id == tenant_id,
        QueueItem.status.in_(["pending", "sending", "deferred"])
    ).delete(synchronize_session=False)
    db.commit()
    return {"detail": f"Purged outbox queue ({purged_count} items cleared)."}
