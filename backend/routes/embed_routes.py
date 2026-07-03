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
    
    # Check form_settings for name requirement
    name_required = False
    if sub_list.form_settings:
        name_required = sub_list.form_settings.get("name_required", False)
        
    # Generate form inputs dynamically for custom fields
    custom_inputs = ""
    if sub_list.custom_fields:
        for field in sub_list.custom_fields:
            key = field.get("key")
            label = field.get("label", key.capitalize())
            ftype = field.get("type", "text")
            required = field.get("required", False)
            
            req_attr = "required" if required else ""
            req_star = " *" if required else ""
            
            custom_inputs += f"""
            <div class="form-group">
                <label for="custom_{key}">{label}{req_star}</label>
                <input type="{ftype}" id="custom_{key}" name="custom_{key}" placeholder="Enter your {label.lower()}" {req_attr}>
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
                <div class="form-group">
                    <label for="email">Email Address *</label>
                    <input type="email" id="email" name="email" required placeholder="you@example.com">
                </div>
                <div class="form-group">
                    <label for="name">Name{" *" if name_required else ""}</label>
                    <input type="text" id="name" name="name" placeholder="Your Name" {"required" if name_required else ""}>
                </div>
                {custom_inputs}
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
        
    # Check form_settings for name requirement
    name_required = False
    if sub_list.form_settings:
        name_required = sub_list.form_settings.get("name_required", False)
        
    if name_required and not name:
        return HTMLResponse("<h2>Name is a required field</h2>", status_code=400)
        
    # Extract custom values
    custom_data = {}
    if sub_list.custom_fields:
        for field in sub_list.custom_fields:
            key = field.get("key")
            label = field.get("label", key.capitalize())
            required = field.get("required", False)
            form_val = form_data.get(f"custom_{key}")
            
            if required and not form_val:
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
def confirm_optin(token: str, db: Session = Depends(get_db)):
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
def post_unsubscribe(subscriber_id: int, campaign_id: int, db: Session = Depends(get_db)):
    subscriber = db.query(Subscriber).filter(Subscriber.id == subscriber_id).first()
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    
    if not subscriber or not campaign:
        raise HTTPException(status_code=400, detail="Invalid unsubscribe request parameters")
        
    if subscriber.status != "unsubscribed":
        subscriber.status = "unsubscribed"
        db.commit()
        
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
