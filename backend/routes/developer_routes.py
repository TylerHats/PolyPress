from fastapi import APIRouter, Depends, HTTPException, status, Header, Request, BackgroundTasks
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
def developer_add_subscriber(payload: dict, request: Request, background_tasks: BackgroundTasks, x_polypress_key: str = Header(None), db: Session = Depends(get_db)):
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
    
    if sub.status == "active":
        from automation_worker import trigger_automation_on_list_join
        trigger_automation_on_list_join(db, sub, list_id)
    
    # Secure Webhook Dispatch
    trigger_webhook(tenant.id, "subscriber.subscribe", {
        "id": sub.id,
        "email": sub.email,
        "name": sub.name,
        "status": sub.status,
        "list_id": sub.list_id,
        "source": sub.source_tag
    })

    # Send transactional confirmation email if pending (Double Opt-In)
    if is_double_optin:
        from database import GlobalSettings
        settings = db.query(GlobalSettings).first()
        base_url = settings.public_url if (settings and settings.public_url) else f"{request.base_url.scheme}://{request.base_url.netloc}"
        if base_url:
            base_url = base_url.rstrip("/")
        confirm_url = f"{base_url}/api/embed/confirm-optin/{token}"
        
        from routes.embed_routes import CONFIRMATION_EMAIL_TEMPLATE
        subject = tenant.double_opt_in_subject or f"Confirm Your Subscription to {tenant.name}"
        if tenant.double_opt_in_body_html:
            email_body = tenant.double_opt_in_body_html.replace("{{confirm_url}}", confirm_url).replace("{confirm_url}", confirm_url)
        else:
            email_body = CONFIRMATION_EMAIL_TEMPLATE.format(
                tenant_name=tenant.name,
                confirm_url=confirm_url
            )
            
        from sending_worker import send_transactional_email
        background_tasks.add_task(
            send_transactional_email,
            to_email=email,
            subject=subject,
            body_html=email_body,
            tenant=tenant
        )
        
    return {
        "id": sub.id,
        "status": sub.status,
        "detail": "Subscriber added successfully via Developer API. Verification sent if required."
    }

@router.post("/v1/send")
def developer_direct_send(
    payload: dict,
    request: Request,
    x_polypress_key: str = Header(None),
    db: Session = Depends(get_db)
):
    tenant = get_tenant_by_api_key(db, x_polypress_key)
    
    to_email = payload.get("to_email")
    subject = payload.get("subject")
    body_html = payload.get("body_html")
    smtp_fallback = payload.get("smtp_fallback", False)
    
    if not to_email or not subject or not body_html:
        raise HTTPException(status_code=400, detail="to_email, subject, and body_html are required fields")
        
    # Resolve or create special tracking list
    list_name = "API Direct Sends"
    sub_list = db.query(SubscriberList).filter(SubscriberList.name == list_name, SubscriberList.tenant_id == tenant.id).first()
    if not sub_list:
        sub_list = SubscriberList(
            tenant_id=tenant.id,
            name=list_name,
            description="Default subscriber tracking list for Direct Send API"
        )
        db.add(sub_list)
        db.commit()
        db.refresh(sub_list)
        
    # Resolve or create subscriber
    subscriber = db.query(Subscriber).filter(Subscriber.email == to_email, Subscriber.tenant_id == tenant.id).first()
    if not subscriber:
        subscriber = Subscriber(
            tenant_id=tenant.id,
            list_id=sub_list.id,
            email=to_email,
            name=to_email.split("@")[0],
            status="active",
            source_tag="Direct Send API"
        )
        db.add(subscriber)
        db.commit()
        db.refresh(subscriber)
        
    # Create campaign log record
    campaign = Campaign(
        tenant_id=tenant.id,
        list_id=sub_list.id,
        list_ids=[sub_list.id],
        name=f"API Send: {subject[:50]}",
        subject=subject,
        body_html=body_html,
        is_custom_html=True,
        custom_html=body_html,
        status="sent",
        total_recipients=1,
        sent_count=1,
        sent_at=datetime.utcnow()
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    
    # Compile trackers and replace templates
    from database import GlobalSettings
    settings = db.query(GlobalSettings).first()
    base_url = settings.public_url if (settings and settings.public_url) else f"{request.base_url.scheme}://{request.base_url.netloc}"
    if base_url:
        base_url = base_url.rstrip("/")
        
    from routes.campaign_routes import render_email_template
    final_html = render_email_template(
        body_html=body_html,
        subscriber=subscriber,
        tracking_domain=base_url,
        campaign_id=campaign.id,
        subscriber_id=subscriber.id
    )
    
    # We send using the sending worker helper functions
    from sending_worker import send_direct_mta, send_external_smtp
    
    success = False
    error_msg = "Unknown error"
    
    if tenant.direct_send:
        class MockItem:
            def __init__(self, to, subj, html, c_id, s_id):
                self.id = 0
                self.campaign_id = c_id
                self.subscriber_id = s_id
                self.email = to
                self.subject = subj
                self.body_html = html
        item = MockItem(to_email, subject, final_html, campaign.id, subscriber.id)
        success, is_transient, code, msg = send_direct_mta(item, tenant)
        if not success:
            error_msg = f"Direct send failed: {msg}"
            
    if not success and (not tenant.direct_send or smtp_fallback):
        if tenant.smtp_host:
            class MockItem:
                def __init__(self, to, subj, html, c_id, s_id):
                    self.id = 0
                    self.campaign_id = c_id
                    self.subscriber_id = s_id
                    self.email = to
                    self.subject = subj
                    self.body_html = html
            item = MockItem(to_email, subject, final_html, campaign.id, subscriber.id)
            success, is_transient, code, msg = send_external_smtp(item, tenant)
            if not success:
                error_msg = f"SMTP fallback failed: {msg}"
        else:
            if tenant.direct_send:
                error_msg += " (No SMTP fallback server configured)"
            else:
                error_msg = "No SMTP server configured"
                
    if success:
        campaign.sent_count = 1
        campaign.failed_count = 0
        db.commit()
        return {"status": "success", "detail": "Email dispatched successfully", "campaign_id": campaign.id}
    else:
        campaign.sent_count = 0
        campaign.failed_count = 1
        db.commit()
        raise HTTPException(status_code=502, detail=f"Failed to dispatch email: {error_msg}")
