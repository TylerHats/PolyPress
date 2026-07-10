from fastapi import APIRouter, Depends, HTTPException, status, Form, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import database as db_mod
from database import get_db, SubscriberList, Subscriber, Campaign, Tenant, GlobalSettings
import json
import secrets

router = APIRouter(prefix="/api/embed", tags=["embed"])

def get_html_style(theme: str = "dark") -> str:
    if theme == "light":
        return """
<style>
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background-color: #f8fafc;
        color: #0f172a;
        margin: 0;
        padding: 20px;
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: 100vh;
    }
    .card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 30px;
        width: 100%;
        max-width: 400px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }
    h2 {
        margin-top: 0;
        font-size: 20px;
        font-weight: 700;
        color: #0f172a;
        text-align: center;
        margin-bottom: 20px;
    }
    .form-group {
        margin-bottom: 15px;
    }
    label {
        display: block;
        font-size: 13px;
        font-weight: 600;
        color: #475569;
        margin-bottom: 5px;
    }
    input[type="text"], input[type="email"], select {
        width: 100%;
        padding: 10px 12px;
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        color: #0f172a;
        font-size: 14px;
        box-sizing: border-box;
        transition: border-color 0.15s ease;
    }
    input:focus, select:focus {
        border-color: #3b82f6;
        outline: none;
    }
    .btn {
        width: 100%;
        padding: 11px;
        background: #2563eb;
        border: none;
        border-radius: 6px;
        color: #ffffff;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s ease;
        margin-top: 10px;
    }
    .btn:hover {
        background: #1d4ed8;
    }
    .success-msg {
        text-align: center;
        color: #059669;
        font-size: 15px;
        font-weight: 500;
    }
</style>
"""
    return """
<style>
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background-color: #0f172a;
        color: #f8fafc;
        margin: 0;
        padding: 20px;
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: 100vh;
    }
    .card {
        background: rgba(30, 41, 59, 0.7);
        backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 30px;
        width: 100%;
        max-width: 400px;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.3);
    }
    h2 {
        margin-top: 0;
        font-size: 20px;
        font-weight: 700;
        color: #f1f5f9;
        text-align: center;
        margin-bottom: 20px;
    }
    .form-group {
        margin-bottom: 15px;
    }
    label {
        display: block;
        font-size: 13px;
        font-weight: 600;
        color: #94a3b8;
        margin-bottom: 5px;
    }
    input[type="text"], input[type="email"], select {
        width: 100%;
        padding: 10px 12px;
        background: #0f172a;
        border: 1px solid #334155;
        border-radius: 6px;
        color: #f8fafc;
        font-size: 14px;
        box-sizing: border-box;
        transition: border-color 0.15s ease;
    }
    input:focus, select:focus {
        border-color: #3b82f6;
        outline: none;
    }
    .btn {
        width: 100%;
        padding: 11px;
        background: #2563eb;
        border: none;
        border-radius: 6px;
        color: #ffffff;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s ease;
        margin-top: 10px;
    }
    .btn:hover {
        background: #1d4ed8;
    }
    .success-msg {
        text-align: center;
        color: #10b981;
        font-size: 15px;
        font-weight: 500;
    }
</style>
"""
HTML_STYLE = get_html_style("dark")

# Premium responsive HTML template for Double Opt-in confirmation email
CONFIRMATION_EMAIL_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Confirm Your Subscription</title>
    <style>
        body {{
            background-color: #0b0f19;
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 0;
        }}
        .wrapper {{
            width: 100%;
            background-color: #0b0f19;
            padding: 40px 0;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
            overflow: hidden;
        }}
        .header {{
            padding: 40px 40px 20px 40px;
            text-align: center;
        }}
        .title {{
            font-size: 24px;
            font-weight: 800;
            margin: 0 0 10px 0;
            color: #ffffff;
        }}
        .subtitle {{
            font-size: 14px;
            color: #94a3b8;
            margin: 0;
        }}
        .content {{
            padding: 0 40px 40px 40px;
            text-align: center;
        }}
        .body-text {{
            font-size: 16px;
            color: #cbd5e1;
            line-height: 1.6;
            margin: 0 0 30px 0;
        }}
        .btn-wrapper {{
            margin-bottom: 30px;
        }}
        .btn {{
            display: inline-block;
            padding: 14px 32px;
            background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
            color: #ffffff !important;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            font-size: 15px;
        }}
        .footer {{
            padding: 20px 40px 40px 40px;
            border-top: 1px solid rgba(255,255,255,0.05);
            text-align: center;
            font-size: 12px;
            color: #64748b;
        }}
        .footer a {{
            color: #6366f1;
            text-decoration: none;
        }}
    </style>
</head>
<body>
    <table class="wrapper" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
            <td align="center">
                <table class="container" width="100%" cellpadding="0" cellspacing="0" border="0">
                    <tr>
                        <td class="header">
                            <h1 class="title">Confirm Your Subscription</h1>
                            <p class="subtitle">Thank you for signing up!</p>
                        </td>
                    </tr>
                    <tr>
                        <td class="content">
                            <p class="body-text">
                                Please click the button below to confirm your subscription and start receiving newsletter updates from <strong>{tenant_name}</strong>.
                            </p>
                            <div class="btn-wrapper">
                                <a href="{confirm_url}" class="btn" target="_blank">Confirm Subscription</a>
                            </div>
                            <p style="font-size: 13px; color: #64748b; margin: 0;">
                                If you did not request this subscription, you can safely ignore this email.
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td class="footer">
                            Sent by {tenant_name} via PolyPress.<br>
                            If you have questions, reply directly to this mail.
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

@router.get("/subscribe/{list_id}", response_class=HTMLResponse)
def get_embed_subscribe(list_id: int, request: Request, tag: str = "iFrame Embed", theme: str = "dark", db: Session = Depends(get_db)):
    sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id).first()
    if not sub_list:
        return HTMLResponse("<h2>List not found</h2>", status_code=404)
        
    tenant = db.query(Tenant).filter(Tenant.id == sub_list.tenant_id).first()
    
    # Generate form inputs dynamically based on fields schema and ordering
    fields_to_render = []
    
    # 1. Email Field settings
    email_order = 0
    if sub_list.form_settings:
        email_order = sub_list.form_settings.get("email_form_order", 0)
    fields_to_render.append({
        "key": "email",
        "label": "Email Address",
        "type": "email",
        "required": True,
        "show_on_form": True,
        "form_order": email_order
    })
    
    # 2. Schema Fields settings (Name and custom fields)
    if sub_list.custom_fields:
        for field in sub_list.custom_fields:
            key = field.get("key")
            label = field.get("label", key.capitalize())
            ftype = field.get("type", "text")
            required = field.get("required", False)
            show = field.get("show_on_form", True)
            order = field.get("form_order", 1)
            
            if show:
                fields_to_render.append({
                    "key": key,
                    "label": label,
                    "type": ftype,
                    "required": required,
                    "show_on_form": True,
                    "form_order": order
                })
                
    # Sort fields by form_order
    fields_to_render.sort(key=lambda x: x["form_order"])
    
    # Generate fields inputs HTML
    inputs_html = ""
    for field in fields_to_render:
        key = field["key"]
        label = field["label"]
        ftype = field["type"]
        required = field["required"]
        req_attr = "required" if required else ""
        req_star = " *" if required else ""
        
        # Name and Email have special input names/IDs for database model compatibility
        input_name = key if key in ["email", "name"] else f"custom_{key}"
        input_id = key if key in ["email", "name"] else f"custom_{key}"
        
        inputs_html += f"""
        <div class="form-group">
            <label for="{input_id}">{label}{req_star}</label>
            <input type="{ftype}" id="{input_id}" name="{input_name}" placeholder="Enter your {label.lower()}" {req_attr}>
        </div>
        """
            
    submit_url = f"/api/embed/subscribe/{list_id}/submit?theme={theme}"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Subscribe to {sub_list.name}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        {get_html_style(theme)}
    </head>
    <body>
        <div class="card">
            <h2>Subscribe to {tenant.name if tenant else "Newsletter"}</h2>
            <form action="{submit_url}" method="POST">
                <input type="hidden" name="tag" value="{tag}">
                {inputs_html}
                <button type="submit" class="btn">Subscribe</button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@router.post("/subscribe/{list_id}/submit", response_class=HTMLResponse)
async def post_embed_subscribe(list_id: int, request: Request, background_tasks: BackgroundTasks, theme: str = "dark", db: Session = Depends(get_db)):
    form_data = await request.form()
    
    sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id).first()
    if not sub_list:
        return HTMLResponse("<h2>List not found</h2>", status_code=404)
        
    tenant = db.query(Tenant).filter(Tenant.id == sub_list.tenant_id).first()
    email = form_data.get("email")
    name = form_data.get("name")
    tag = form_data.get("tag", "iFrame Embed")
    
    if not email or "@" not in email:
        return HTMLResponse("<h2>Invalid email address</h2>", status_code=400)
        
    # Extract custom values and validate required fields
    custom_data = {}
    
    # Validate name field schema if present
    name_field = None
    if sub_list.custom_fields:
        for field in sub_list.custom_fields:
            key = field.get("key")
            required = field.get("required", False)
            show = field.get("show_on_form", True)
            
            if key == "name":
                name_field = field
                if show and required and not name:
                    return HTMLResponse("<h2>Name is a required field</h2>", status_code=400)
            else:
                form_val = form_data.get(f"custom_{key}")
                if show and required and not form_val:
                    label = field.get("label", key.capitalize())
                    return HTMLResponse(f"<h2>{label} is a required field</h2>", status_code=400)
                if form_val is not None:
                    custom_data[key] = form_val
                
    # Double Opt-In settings check
    is_double_optin = tenant.double_opt_in if tenant else False
    status_state = "pending" if is_double_optin else "active"
    token = secrets.token_hex(32) if is_double_optin else None
    
    existing = db.query(Subscriber).filter(
        Subscriber.list_id == list_id,
        Subscriber.email == email,
        Subscriber.tenant_id == sub_list.tenant_id
    ).first()
    
    if existing:
        existing.name = name or existing.name
        existing.status = status_state
        existing.double_opt_in_token = token
        existing.custom_data.update(custom_data)
        subscriber_id = existing.id
    else:
        sub = Subscriber(
            tenant_id=sub_list.tenant_id,
            list_id=list_id,
            email=email,
            name=name,
            status=status_state,
            double_opt_in_token=token,
            custom_data=custom_data,
            source_tag=tag
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
        subscriber_id = sub.id
        
    db.commit()
    
    sub_obj = existing if existing else sub
    if status_state == "active":
        from location_helper import log_subscriber_activity
        log_subscriber_activity(
            db=db,
            tenant_id=sub_list.tenant_id,
            subscriber_id=subscriber_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")
        )
        from automation_worker import trigger_automation_on_list_join
        trigger_automation_on_list_join(db, sub_obj, list_id)
    
    from webhook_dispatcher import trigger_webhook
    trigger_webhook(sub_list.tenant_id, "subscriber.subscribe", {
        "id": subscriber_id,
        "email": email,
        "name": name,
        "status": status_state,
        "list_id": list_id,
        "source": tag
    })
    
    # Send transactional confirmation email if pending (Double Opt-In)
    if is_double_optin:
        settings = db.query(GlobalSettings).first()
        base_url = settings.public_url if (settings and settings.public_url) else f"{request.base_url.scheme}://{request.base_url.netloc}"
        if base_url:
            base_url = base_url.rstrip("/")
        confirm_url = f"{base_url}/api/embed/confirm-optin/{token}"
        # Determine subject and body template
        subject = tenant.double_opt_in_subject or f"Confirm Your Subscription to {tenant.name}"
        if tenant.double_opt_in_body_html:
            email_body = tenant.double_opt_in_body_html.replace("{{confirm_url}}", confirm_url).replace("{confirm_url}", confirm_url)
        else:
            email_body = CONFIRMATION_EMAIL_TEMPLATE.format(
                tenant_name=tenant.name,
                confirm_url=confirm_url
            )
        
        # Import transactional sender to avoid circular import issues
        from sending_worker import send_transactional_email
        background_tasks.add_task(
            send_transactional_email,
            to_email=email,
            subject=subject,
            body_html=email_body,
            tenant=tenant
        )
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Verification Sent</title>
            {get_html_style(theme)}
        </head>
        <body>
            <div class="card" style="text-align: center;">
                <svg width="48" height="48" fill="none" stroke="#6366f1" viewBox="0 0 24 24" style="margin: 0 auto 15px; display: block;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>
                <h2>Check Your Inbox</h2>
                <p style="font-size: 14px; color: #94a3b8; line-height: 1.5; margin-bottom: 20px;">
                    We have sent a subscription verification link to <strong>{email}</strong>. Please check your email inbox and click the link to confirm subscription.
                </p>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html)
        
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Success</title>
        {get_html_style(theme)}
    </head>
    <body>
        <div class="card">
            <div class="success-msg">
                <svg width="48" height="48" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="margin: 0 auto 15px; display: block;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                Thank you! You have successfully subscribed.
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@router.get("/confirm-optin/{token}", response_class=HTMLResponse)
def confirm_optin(token: str, request: Request, db: Session = Depends(get_db)):
    subscriber = db.query(Subscriber).filter(Subscriber.double_opt_in_token == token).first()
    if not subscriber:
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Invalid Link</title>
            {HTML_STYLE}
        </head>
        <body>
            <div class="card" style="text-align: center;">
                <svg width="48" height="48" fill="none" stroke="#ef4444" viewBox="0 0 24 24" style="margin: 0 auto 15px; display: block;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                <h2>Verification Error</h2>
                <p style="font-size: 14px; color: #94a3b8; line-height: 1.5;">
                    The verification link is invalid, expired, or has already been used.
                </p>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html, status_code=400)
        
    subscriber.status = "active"
    subscriber.double_opt_in_token = None
    db.commit()

    from location_helper import log_subscriber_activity
    log_subscriber_activity(
        db=db,
        tenant_id=subscriber.tenant_id,
        subscriber_id=subscriber.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")
    )
    
    from automation_worker import trigger_automation_on_list_join
    trigger_automation_on_list_join(db, subscriber, subscriber.list_id)
    
    from webhook_dispatcher import trigger_webhook
    trigger_webhook(subscriber.tenant_id, "subscriber.active", {
        "id": subscriber.id,
        "email": subscriber.email,
        "name": subscriber.name,
        "status": subscriber.status,
        "list_id": subscriber.list_id
    })
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Confirmed</title>
        {HTML_STYLE}
    </head>
    <body>
        <div class="card" style="text-align: center;">
            <svg width="48" height="48" fill="none" stroke="#10b981" viewBox="0 0 24 24" style="margin: 0 auto 15px; display: block;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
            <h2>Subscription Confirmed!</h2>
            <p style="font-size: 14px; color: #94a3b8; line-height: 1.5;">
                Thank you! Your email subscription has been successfully verified. You are now active on our mailing list.
            </p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@router.get("/unsubscribe/{subscriber_id}/{campaign_id}", response_class=HTMLResponse)
def get_unsubscribe_confirm(subscriber_id: int, campaign_id: int, db: Session = Depends(get_db)):
    if subscriber_id == 0 and campaign_id == 0:
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Unsubscribe Test</title>
            {HTML_STYLE}
        </head>
        <body>
            <div class="card" style="text-align: center;">
                <h2>Unsubscribe Loopback Test</h2>
                <p style="font-size: 14px; color: #94a3b8; line-height: 1.5; margin-bottom: 20px;">
                    This is a mock unsubscribe page for system testing. If you were a real subscriber, clicking below would immediately remove you from our list.
                </p>
                <form action="/api/embed/unsubscribe/0/0" method="POST">
                    <button type="submit" class="btn" style="background-color: #dc2626;">Yes, Unsubscribe (Test)</button>
                </form>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html)

    subscriber = db.query(Subscriber).filter(Subscriber.id == subscriber_id).first()
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    
    if not subscriber or not campaign:
        return HTMLResponse("<h2>Invalid request</h2>", status_code=400)
        
    post_url = f"/api/embed/unsubscribe/{subscriber_id}/{campaign_id}"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Unsubscribe</title>
        {HTML_STYLE}
    </head>
    <body>
        <div class="card">
            <h2>Unsubscribe Confirmation</h2>
            <p style="text-align: center; font-size: 14px; color: #94a3b8; line-height: 1.5; margin-bottom: 20px;">
                Are you sure you want to unsubscribe <strong>{subscriber.email}</strong> from this newsletter?
            </p>
            <form action="{post_url}" method="POST">
                <button type="submit" class="btn" style="background-color: #dc2626;">Yes, Unsubscribe</button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@router.post("/unsubscribe/{subscriber_id}/{campaign_id}")
def post_unsubscribe(subscriber_id: int, campaign_id: int, request: Request, db: Session = Depends(get_db)):
    if subscriber_id == 0 and campaign_id == 0:
        return {"unsubscribed": True, "detail": "Test unsubscribe request processed successfully (no subscriber was modified)."}

    subscriber = db.query(Subscriber).filter(Subscriber.id == subscriber_id).first()
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    
    if not subscriber or not campaign:
        raise HTTPException(status_code=400, detail="Invalid unsubscribe request parameters")
        
    if subscriber.status != "unsubscribed":
        subscriber.status = "unsubscribed"
        db.commit()

        from location_helper import log_subscriber_activity
        log_subscriber_activity(
            db=db,
            tenant_id=subscriber.tenant_id,
            subscriber_id=subscriber.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")
        )
        
        from webhook_dispatcher import trigger_webhook
        trigger_webhook(subscriber.tenant_id, "subscriber.unsubscribe", {
            "id": subscriber.id,
            "email": subscriber.email,
            "name": subscriber.name,
            "status": subscriber.status,
            "list_id": subscriber.list_id,
            "campaign_id": campaign_id
        })
        
    return {"unsubscribed": True, "detail": f"Subscriber {subscriber.email} has been unsubscribed."}

def extract_ses_metadata(msg_data: dict):
    campaign_id = None
    subscriber_id = None
    mail_obj = msg_data.get("mail", {})
    
    # 1. Search headers
    headers = mail_obj.get("headers", [])
    if isinstance(headers, list):
        for h in headers:
            if not isinstance(h, dict):
                continue
            name = str(h.get("name", "")).lower()
            value = h.get("value")
            if name == "x-polypress-subscriber":
                subscriber_id = value
            elif name == "x-polypress-campaign":
                campaign_id = value
                
    # 2. Search tags
    tags = mail_obj.get("tags", {})
    if isinstance(tags, dict):
        if "X-PolyPress-Subscriber" in tags:
            subscriber_id = tags["X-PolyPress-Subscriber"]
        if "X-PolyPress-Campaign" in tags:
            campaign_id = tags["X-PolyPress-Campaign"]
    elif isinstance(tags, list):
        for t in tags:
            if not isinstance(t, dict):
                continue
            name = str(t.get("name", "")).lower()
            value = t.get("value")
            if name == "x-polypress-subscriber":
                subscriber_id = value
            elif name == "x-polypress-campaign":
                campaign_id = value
                
    return campaign_id, subscriber_id

def process_webhook_event(db: Session, tenant: Tenant, email: str, event_type: str, reason: str, campaign_id=None, subscriber_id=None):
    subscriber = None
    if subscriber_id:
        try:
            subscriber = db.query(Subscriber).filter(
                Subscriber.id == int(subscriber_id),
                Subscriber.tenant_id == tenant.id
            ).first()
        except (ValueError, TypeError):
            pass
            
    if not subscriber and email:
        subscriber = db.query(Subscriber).filter(
            Subscriber.email == email,
            Subscriber.tenant_id == tenant.id
        ).first()
        
    if subscriber:
        new_status = "spam" if event_type == "spam" else "bounced"
        if subscriber.status != new_status:
            subscriber.status = new_status
            if event_type == "spam":
                subscriber.complaint_reason = reason
            else:
                subscriber.bounce_reason = reason
            subscriber.bounce_source_email = f"Webhook ({tenant.bounce_provider})"
            
            # Increment campaign statistics if resolved
            resolved_campaign_id = None
            if campaign_id:
                try:
                    resolved_campaign_id = int(campaign_id)
                except (ValueError, TypeError):
                    pass
            if resolved_campaign_id:
                campaign = db.query(Campaign).filter(
                    Campaign.id == resolved_campaign_id,
                    Campaign.tenant_id == tenant.id
                ).first()
                if campaign:
                    campaign.bounce_count += 1
                    
            db.commit()
            
            # Trigger outbound webhook
            try:
                from webhook_dispatcher import trigger_webhook
                trigger_webhook(tenant.id, f"subscriber.{new_status}", {
                    "id": subscriber.id,
                    "email": subscriber.email,
                    "name": subscriber.name,
                    "status": subscriber.status,
                    "reason": reason,
                    "source": f"Webhook ({tenant.bounce_provider})",
                    "campaign_id": resolved_campaign_id
                })
            except Exception as e:
                print(f"Error triggering outbound webhook for {subscriber.email}: {e}")

@router.post("/bounces/webhook/{provider}/{tenant_id}")
async def incoming_bounce_webhook(
    provider: str,
    tenant_id: int,
    request: Request,
    token: str = None,
    db: Session = Depends(get_db)
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    import hmac
    if not token or not hmac.compare_digest(tenant.bounce_webhook_token or "", token):
        raise HTTPException(status_code=401, detail="Invalid bounce webhook token")
        
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
        
    p_lower = provider.lower()
    
    if p_lower == "ses":
        sns_type = payload.get("Type")
        if sns_type == "SubscriptionConfirmation":
            subscribe_url = payload.get("SubscribeURL")
            if subscribe_url:
                import urllib.request
                import urllib.parse
                try:
                    parsed_url = urllib.parse.urlparse(subscribe_url)
                    if parsed_url.scheme != "https" or not (parsed_url.netloc.endswith(".amazonaws.com") or parsed_url.netloc.endswith(".amazonaws.com.cn")):
                        raise HTTPException(status_code=400, detail="Invalid SNS subscription confirmation URL domain")
                    # AWS SNS requires confirmation by fetching the URL
                    urllib.request.urlopen(subscribe_url, timeout=10)
                    return {"success": True, "detail": "Subscription confirmed successfully."}
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Failed to confirm subscription: {e}")
                    
        if sns_type == "Notification":
            msg_str = payload.get("Message", "")
            try:
                import json
                msg_data = json.loads(msg_str)
            except Exception:
                msg_data = {}
        else:
            msg_data = payload
            
        event_type = msg_data.get("eventType") or msg_data.get("notificationType")
        if event_type == "Bounce":
            bounce_obj = msg_data.get("bounce", {})
            recipients = bounce_obj.get("bouncedRecipients") or []
            for rec in recipients:
                if not isinstance(rec, dict):
                    continue
                email = rec.get("emailAddress")
                diag = rec.get("diagnosticCode") or bounce_obj.get("bounceSubType") or "AWS SES Permanent Bounce"
                campaign_id, subscriber_id = extract_ses_metadata(msg_data)
                process_webhook_event(db, tenant, email, "bounce", diag, campaign_id, subscriber_id)
        elif event_type == "Complaint":
            complaint_obj = msg_data.get("complaint", {})
            recipients = complaint_obj.get("complainedRecipients") or []
            for rec in recipients:
                if not isinstance(rec, dict):
                    continue
                email = rec.get("emailAddress")
                feedback = complaint_obj.get("complaintFeedbackType") or "AWS SES Spam Complaint"
                campaign_id, subscriber_id = extract_ses_metadata(msg_data)
                process_webhook_event(db, tenant, email, "spam", feedback, campaign_id, subscriber_id)
                
    elif p_lower == "sendgrid":
        if not isinstance(payload, list):
            payload = [payload]
        for event in payload:
            event_type = event.get("event")
            email = event.get("email")
            if not email:
                continue
                
            subscriber_id = event.get("subscriber_id") or event.get("x-polypress-subscriber") or event.get("X-PolyPress-Subscriber")
            campaign_id = event.get("campaign_id") or event.get("x-polypress-campaign") or event.get("X-PolyPress-Campaign")
            
            unique_args = event.get("unique_args", {})
            if isinstance(unique_args, dict):
                if not subscriber_id:
                    subscriber_id = unique_args.get("X-PolyPress-Subscriber") or unique_args.get("subscriber_id") or unique_args.get("x-polypress-subscriber")
                if not campaign_id:
                    campaign_id = unique_args.get("X-PolyPress-Campaign") or unique_args.get("campaign_id") or unique_args.get("x-polypress-campaign")
                    
            if event_type == "bounce":
                reason = event.get("reason") or event.get("status") or "SendGrid Bounce"
                process_webhook_event(db, tenant, email, "bounce", reason, campaign_id, subscriber_id)
            elif event_type == "spamreport":
                reason = "SendGrid Spam Complaint"
                process_webhook_event(db, tenant, email, "spam", reason, campaign_id, subscriber_id)
                
    elif p_lower == "mailgun":
        event_data = payload.get("event-data", {})
        event_type = event_data.get("event")
        recipient = event_data.get("recipient")
        if recipient:
            user_vars = event_data.get("user-variables", {})
            subscriber_id = None
            campaign_id = None
            if isinstance(user_vars, dict):
                subscriber_id = user_vars.get("X-PolyPress-Subscriber") or user_vars.get("subscriber_id") or user_vars.get("x-polypress-subscriber")
                campaign_id = user_vars.get("X-PolyPress-Campaign") or user_vars.get("campaign_id") or user_vars.get("x-polypress-campaign")
                
            if event_type in ("failed", "bounced"):
                severity = event_data.get("severity")
                if severity != "temporary":
                    reason = event_data.get("delivery-status", {}).get("message") or event_data.get("reason") or "Mailgun Permanent Bounce"
                    process_webhook_event(db, tenant, recipient, "bounce", reason, campaign_id, subscriber_id)
            elif event_type == "complained":
                reason = "Mailgun Spam Complaint"
                process_webhook_event(db, tenant, recipient, "spam", reason, campaign_id, subscriber_id)
                
    elif p_lower == "postmark":
        record_type = payload.get("RecordType")
        email = payload.get("Email")
        if email:
            metadata = payload.get("Metadata", {})
            subscriber_id = None
            campaign_id = None
            if isinstance(metadata, dict):
                subscriber_id = metadata.get("X-PolyPress-Subscriber") or metadata.get("subscriber_id") or metadata.get("x-polypress-subscriber")
                campaign_id = metadata.get("X-PolyPress-Campaign") or metadata.get("campaign_id") or metadata.get("x-polypress-campaign")
                
            if record_type == "Bounce":
                reason = payload.get("Description") or payload.get("Details") or "Postmark Bounce"
                process_webhook_event(db, tenant, email, "bounce", reason, campaign_id, subscriber_id)
            elif record_type == "SpamComplaint":
                reason = payload.get("Description") or "Postmark Spam Complaint"
                process_webhook_event(db, tenant, email, "spam", reason, campaign_id, subscriber_id)
                
    return {"success": True}
