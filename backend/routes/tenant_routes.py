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
        
    for field in ["smtp_host", "smtp_port", "smtp_username", "smtp_use_ssl", "smtp_use_tls", "dkim_selector", "mta_from_prefix", "imap_host", "imap_port", "imap_username", "imap_use_ssl", "speed_emails_per_hour", "bounce_email"]:
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



# TENANT ADMIN / USER SETTINGS (Scoped to Current Tenant)

@router.get("/my")
def get_my_tenant(db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User is not associated with any tenant")
        
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
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
        "speed_emails_per_hour": tenant.speed_emails_per_hour,
        "bounce_email": tenant.bounce_email,
        "double_opt_in": tenant.double_opt_in
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
    
    tenant.speed_emails_per_hour = payload.get("speed_emails_per_hour", tenant.speed_emails_per_hour)
    tenant.bounce_email = payload.get("bounce_email", tenant.bounce_email)
    tenant.double_opt_in = payload.get("double_opt_in", tenant.double_opt_in)
    
    db.commit()
    db.refresh(tenant)
    return {"detail": "Settings updated successfully"}

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
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    domain = tenant.dkim_domain
    if not domain:
        return {
            "mx": {"status": "missing", "records": [], "detail": "No domain configured for DKIM/MTA"},
            "spf": {"status": "missing", "records": []},
            "dkim": {"status": "missing", "records": []},
            "dmarc": {"status": "missing", "records": []}
        }
        
    results = {
        "mx": {"status": "missing", "records": []},
        "spf": {"status": "missing", "records": []},
        "dkim": {"status": "missing", "records": []},
        "dmarc": {"status": "missing", "records": []}
    }
    
    # 1. Test MX records
    try:
        answers = dns.resolver.resolve(domain, 'MX')
        results["mx"]["records"] = [str(ans.exchange).rstrip('.') for ans in answers]
        if results["mx"]["records"]:
            results["mx"]["status"] = "valid"
    except Exception:
        pass
        
    # 2. Test SPF records
    try:
        answers = dns.resolver.resolve(domain, 'TXT')
        for ans in answers:
            txt = "".join([t.decode('utf-8') for t in ans.strings])
            if txt.startswith("v=spf1"):
                results["spf"]["records"].append(txt)
                results["spf"]["status"] = "valid"
    except Exception:
        pass
        
    # 3. Test DKIM
    if tenant.dkim_selector:
        dkim_host = f"{tenant.dkim_selector}._domainkey.{domain}"
        try:
            answers = dns.resolver.resolve(dkim_host, 'TXT')
            for ans in answers:
                txt = "".join([t.decode('utf-8') for t in ans.strings])
                if txt.startswith("v=DKIM1"):
                    results["dkim"]["records"].append(txt)
                    results["dkim"]["status"] = "valid"
        except Exception:
            pass
            
    # 4. Test DMARC
    dmarc_host = f"_dmarc.{domain}"
    try:
        answers = dns.resolver.resolve(dmarc_host, 'TXT')
        for ans in answers:
            txt = "".join([t.decode('utf-8') for t in ans.strings])
            if txt.startswith("v=DMARC1"):
                results["dmarc"]["records"].append(txt)
                results["dmarc"]["status"] = "valid"
    except Exception:
        pass
        
    return results

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
