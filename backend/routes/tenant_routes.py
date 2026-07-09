from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import dns.resolver
import database as db_mod
from database import get_db, Tenant, User, GlobalSettings, QueueItem
import auth

router = APIRouter(prefix="/api/tenants", tags=["tenants"])

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
    return db.query(Tenant).all()

@router.get("/accessible")
def list_accessible_tenants(db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if current_user.role == "super_admin":
        return db.query(Tenant).all()
        
    if current_user.allowed_tenants:
        return db.query(Tenant).filter(Tenant.id.in_(current_user.allowed_tenants)).all()
        
    if current_user.tenant_id:
        return db.query(Tenant).filter(Tenant.id == current_user.tenant_id).all()
        
    return []

@router.post("")
def create_tenant(payload: dict = Body(...), db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Tenant name required")
        
    existing = db.query(Tenant).filter(Tenant.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Tenant name already exists")
        
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
        bounce_email=payload.get("bounce_email")
    )
    
    if payload.get("generate_dkim"):
        priv, pub = generate_dkim_keypair()
        tenant.dkim_private_key = priv
        tenant.dkim_public_key = pub
        
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant

# GLOBAL SETTINGS (Super Admin Only)

@router.get("/global-settings")
def get_global_settings(db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    settings = db.query(GlobalSettings).first()
    return settings

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
    settings.oidc_client_secret = payload.get("oidc_client_secret", settings.oidc_client_secret)
    settings.oidc_redirect_url = payload.get("oidc_redirect_url", settings.oidc_redirect_url)
    settings.allowed_domains = payload.get("allowed_domains", settings.allowed_domains)
    settings.auto_create_tenants = payload.get("auto_create_tenants", settings.auto_create_tenants)
    settings.local_login_enabled = new_local
    
    # Auto-updates and Backups API
    settings.auto_update = payload.get("auto_update", settings.auto_update)
    settings.update_channel = payload.get("update_channel", settings.update_channel)
    settings.backup_token = payload.get("backup_token", settings.backup_token)
    settings.external_backup_url = payload.get("external_backup_url", settings.external_backup_url)
    settings.external_backup_auth_header = payload.get("external_backup_auth_header", settings.external_backup_auth_header)
    
    db.commit()
    db.refresh(settings)
    return settings




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
        
    # Return everything except private key
    return {
        "id": tenant.id,
        "name": tenant.name,
        "logo_path": tenant.logo_path,
        "smtp_host": tenant.smtp_host,
        "smtp_port": tenant.smtp_port,
        "smtp_username": tenant.smtp_username,
        # Mask password
        "smtp_has_password": bool(tenant.smtp_password),
        "smtp_use_ssl": tenant.smtp_use_ssl,
        "smtp_use_tls": tenant.smtp_use_tls,
        "direct_send": tenant.direct_send,
        "dkim_domain": tenant.dkim_domain,
        "dkim_selector": tenant.dkim_selector,
        "dkim_public_key": tenant.dkim_public_key,
        "mta_from_prefix": tenant.mta_from_prefix,
        "imap_host": tenant.imap_host,
        "imap_port": tenant.imap_port,
        "imap_username": tenant.imap_username,
        "imap_has_password": bool(tenant.imap_password),
        "imap_use_ssl": tenant.imap_use_ssl,
        "imap_delete_processed": tenant.imap_delete_processed,
        "speed_emails_per_hour": tenant.speed_emails_per_hour,
        "bounce_email": tenant.bounce_email,
        "bounce_provider": tenant.bounce_provider,
        "bounce_webhook_token": tenant.bounce_webhook_token,
        "double_opt_in": tenant.double_opt_in,
        "retry_interval_minutes": tenant.retry_interval_minutes,
        "double_opt_in_subject": tenant.double_opt_in_subject,
        "double_opt_in_body_blocks": tenant.double_opt_in_body_blocks,
        "double_opt_in_body_html": tenant.double_opt_in_body_html,
        "double_opt_in_is_custom_html": tenant.double_opt_in_is_custom_html,
        "double_opt_in_custom_html": tenant.double_opt_in_custom_html,
        "email_footer_blocks": tenant.email_footer_blocks,
        "email_footer_html": tenant.email_footer_html,
        "email_footer_is_custom_html": tenant.email_footer_is_custom_html,
        "email_footer_custom_html": tenant.email_footer_custom_html,
        "sending_ip_override": tenant.sending_ip_override
    }

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
        try:
            import urllib.request
            public_ip = urllib.request.urlopen('https://api.ipify.org', timeout=2).read().decode('utf-8').strip()
        except Exception:
            pass

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
        
    import imaplib
    try:
        if use_ssl:
            client = imaplib.IMAP4_SSL(host, port or 993, timeout=10)
        else:
            client = imaplib.IMAP4(host, port or 143, timeout=10)
            
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
    
    # Temporarily override tenant SMTP/MTA settings from payload if provided (similar to test_smtp_settings)
    import copy
    mock_tenant = copy.copy(db_tenant)
    if "smtp_host" in payload: mock_tenant.smtp_host = payload["smtp_host"]
    if "smtp_port" in payload: mock_tenant.smtp_port = payload["smtp_port"]
    if "smtp_username" in payload: mock_tenant.smtp_username = payload["smtp_username"]
    if "smtp_password" in payload: mock_tenant.smtp_password = payload["smtp_password"]
    if "smtp_use_ssl" in payload: mock_tenant.smtp_use_ssl = payload["smtp_use_ssl"]
    if "smtp_use_tls" in payload: mock_tenant.smtp_use_tls = payload["smtp_use_tls"]
    if "direct_send" in payload: mock_tenant.direct_send = payload["direct_send"]
    if "mta_from_prefix" in payload: mock_tenant.mta_from_prefix = payload["mta_from_prefix"]
    if "dkim_domain" in payload: mock_tenant.dkim_domain = payload["dkim_domain"]
    
    if "bounce_email" in payload: mock_tenant.bounce_email = payload["bounce_email"]
    
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
        try:
            public_ip = urllib.request.urlopen('https://api.ipify.org', timeout=2).read().decode('utf-8').strip()
        except Exception:
            pass

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
            if err is None and records:
                for r in records:
                    r_clean = r.rstrip('.').lower()
                    if domain.lower() in r_clean or r_clean.endswith(domain.lower()):
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

    # 6. IP Blacklist Check
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
        
        dnsbl_results = {}
        for label, dnsbl in blacklists.items():
            query_host = f"{rev_ip}.{dnsbl}"
            listed_ips = []
            resolver_errors = []
            valid_queries = 0
            
            for ns_name, ns_srv in servers.items():
                res = resolve_dns(query_host, 'A', ns_srv)
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
def get_detected_ip(current_user: User = Depends(auth.require_tenant_admin)):
    import urllib.request
    try:
        ip = urllib.request.urlopen('https://api.ipify.org', timeout=2).read().decode('utf-8').strip()
        return {"public_ip": ip}
    except Exception:
        return {"public_ip": "unknown"}

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
        
    for field in ["smtp_host", "smtp_port", "smtp_username", "smtp_use_ssl", "smtp_use_tls", "dkim_selector", "mta_from_prefix", "imap_host", "imap_port", "imap_username", "imap_use_ssl", "imap_delete_processed", "speed_emails_per_hour", "bounce_email", "retry_interval_minutes", "double_opt_in_subject", "double_opt_in_body_blocks", "double_opt_in_body_html", "email_footer_blocks", "email_footer_html", "sending_ip_override"]:
        if field in payload:
            setattr(tenant, field, payload[field])
            
    if payload.get("smtp_password"):
        tenant.smtp_password = payload["smtp_password"]
    if payload.get("imap_password"):
        tenant.imap_password = payload["imap_password"]
        
    db.commit()
    db.refresh(tenant)
    return tenant

@router.delete("/{tenant_id}")
def delete_tenant(tenant_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
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
        # Delete in dependency order to respect foreign key constraints
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
