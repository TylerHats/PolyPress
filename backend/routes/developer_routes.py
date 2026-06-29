from fastapi import APIRouter, Depends, HTTPException, status, Header, Request
from sqlalchemy.orm import Session
import hashlib
import secrets
from datetime import datetime
from database import get_db, User, ApiKey, WebhookSubscription, Tenant, Subscriber, SubscriberList
import auth
from webhook_dispatcher import trigger_webhook

router = APIRouter(prefix="/api/developer", tags=["developer"])

def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode('utf-8')).hexdigest()

def get_tenant_by_api_key(db: Session, x_polypress_key: str) -> Tenant:
    if not x_polypress_key:
        raise HTTPException(status_code=401, detail="X-PolyPress-Key header is missing")
        
    hashed = hash_key(x_polypress_key)
    api_key_record = db.query(ApiKey).filter(ApiKey.key_hash == hashed).first()
    if not api_key_record:
        raise HTTPException(status_code=401, detail="Invalid API Key")
        
    # Update last used
    api_key_record.last_used_at = datetime.utcnow()
    db.commit()
    
    tenant = db.query(Tenant).filter(Tenant.id == api_key_record.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Associated tenant not found")
        
    return tenant

# API KEYS MANAGEMENT

@router.get("/keys")
def list_api_keys(db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User is not associated with a tenant")
        
    keys = db.query(ApiKey).filter(ApiKey.tenant_id == current_user.tenant_id).order_by(ApiKey.created_at.desc()).all()
    return [
        {
            "id": k.id,
            "name": k.name,
            "prefix": k.prefix,
            "created_at": k.created_at,
            "last_used_at": k.last_used_at
        }
        for k in keys
    ]

@router.post("/keys")
def create_api_key(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User is not associated with a tenant")
        
    name = payload.get("name", "Unnamed Key").strip()
    # Generate secure token
    raw_token = secrets.token_urlsafe(32)
    full_key = f"pp_live_{raw_token}"
    prefix = f"pp_live_{raw_token[:8]}"
    hashed = hash_key(full_key)
    
    api_key = ApiKey(
        tenant_id=current_user.tenant_id,
        name=name,
        prefix=prefix,
        key_hash=hashed
    )
    db.add(api_key)
    db.commit()
    
    return {
        "id": api_key.id,
        "name": api_key.name,
        "prefix": api_key.prefix,
        "key": full_key, # Returned only once
        "created_at": api_key.created_at
    }

@router.delete("/keys/{key_id}")
def delete_api_key(key_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User is not associated with a tenant")
        
    api_key = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.tenant_id == current_user.tenant_id).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API Key not found")
        
    db.delete(api_key)
    db.commit()
    return {"detail": "API Key revoked successfully"}

# WEBHOOKS MANAGEMENT

@router.get("/webhooks")
def list_webhooks(db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User is not associated with a tenant")
        
    subs = db.query(WebhookSubscription).filter(WebhookSubscription.tenant_id == current_user.tenant_id).all()
    return subs

@router.post("/webhooks")
def create_webhook(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User is not associated with a tenant")
        
    url = payload.get("url")
    events = payload.get("events", ["*"])
    
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Valid target destination URL required")
        
    secret = secrets.token_hex(16)
    sub = WebhookSubscription(
        tenant_id=current_user.tenant_id,
        url=url,
        secret=secret,
        events=events,
        active=True
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub

@router.put("/webhooks/{hook_id}")
def update_webhook(hook_id: int, payload: dict, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User is not associated with a tenant")
        
    sub = db.query(WebhookSubscription).filter(WebhookSubscription.id == hook_id, WebhookSubscription.tenant_id == current_user.tenant_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Webhook subscription not found")
        
    sub.url = payload.get("url", sub.url)
    sub.events = payload.get("events", sub.events)
    sub.active = payload.get("active", sub.active)
    
    db.commit()
    db.refresh(sub)
    return sub

@router.delete("/webhooks/{hook_id}")
def delete_webhook(hook_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User is not associated with a tenant")
        
    sub = db.query(WebhookSubscription).filter(WebhookSubscription.id == hook_id, WebhookSubscription.tenant_id == current_user.tenant_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Webhook subscription not found")
        
    db.delete(sub)
    db.commit()
    return {"detail": "Webhook subscription deleted"}

# PUBLIC DEVELOPER V1 REST API

@router.post("/v1/subscribers")
def developer_add_subscriber(payload: dict, x_polypress_key: str = Header(None), db: Session = Depends(get_db)):
    # Validate API key and retrieve associated tenant
    tenant = get_tenant_by_api_key(db, x_polypress_key)
    
    list_id = payload.get("list_id")
    email = payload.get("email")
    name = payload.get("name")
    custom_data = payload.get("custom_data", {})
    source_tag = payload.get("source_tag", "Developer API")
    
    if not list_id or not email:
        raise HTTPException(status_code=400, detail="list_id and email are required parameters")
        
    sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == tenant.id).first()
    if not sub_list:
        raise HTTPException(status_code=404, detail="Mailing list not found")
        
    # Check if subscriber exists
    existing = db.query(Subscriber).filter(
        Subscriber.list_id == list_id,
        Subscriber.email == email,
        Subscriber.tenant_id == tenant.id
    ).first()
    
    # Save opt-in setup status
    is_double_optin = tenant.double_opt_in
    status_state = "pending" if is_double_optin else "active"
    token = secrets.token_hex(32) if is_double_optin else None
    
    if existing:
        existing.name = name or existing.name
        existing.status = status_state
        existing.double_opt_in_token = token
        existing.custom_data.update(custom_data)
        sub = existing
    else:
        sub = Subscriber(
            tenant_id=tenant.id,
            list_id=list_id,
            email=email,
            name=name,
            status=status_state,
            double_opt_in_token=token,
            custom_data=custom_data,
            source_tag=source_tag
        )
        db.add(sub)
        
    db.commit()
    db.refresh(sub)
    
    # Secure Webhook Dispatch
    trigger_webhook(tenant.id, "subscriber.subscribe", {
        "id": sub.id,
        "email": sub.email,
        "name": sub.name,
        "status": sub.status,
        "list_id": sub.list_id,
        "source": sub.source_tag
    })
    
    return {
        "id": sub.id,
        "status": sub.status,
        "detail": "Subscriber added successfully via Developer API."
    }
