from fastapi import APIRouter, Depends, HTTPException, status, Form, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
import html as html_lib
import re
import urllib.parse
import database as db_mod
from database import get_db, SubscriberList, Subscriber, Campaign, Tenant, GlobalSettings
import auth
import json
import secrets
from security_utils import embed_rate_limiter

router = APIRouter(prefix="/api/embed", tags=["embed"])

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _sanitize_css_color(value: str, fallback: str) -> str:
    v = (value or "").strip()
    if v.lower() == "transparent" or _HEX_COLOR_RE.match(v):
        return v
    return fallback


def _darken_hex(hex_color: str, fallback: str = "#1d4ed8") -> str:
    c = (hex_color or "").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6 or not all(ch in "0123456789abcdefABCDEF" for ch in c):
        return fallback
    r = max(0, int(c[0:2], 16) - 22)
    g = max(0, int(c[2:4], 16) - 22)
    b = max(0, int(c[4:6], 16) - 22)
    return f"#{r:02x}{g:02x}{b:02x}"


def get_autoresize_script() -> str:
    """Emit ResizeObserver height updates to parent window for seamless auto-sizing iFrames."""
    return """
<script>
(function() {
    var lastH = 0;
    function sendHeight() {
        try {
            var card = document.querySelector('.card');
            var h = card ? Math.ceil(document.body.scrollHeight) : Math.ceil(document.documentElement.scrollHeight);
            if (h > 0 && h !== lastH && window.parent && window.parent !== window) {
                lastH = h;
                window.parent.postMessage({ type: 'polypress-embed-resize', height: h }, '*');
            }
        } catch (e) {}
    }
    window.addEventListener('load', sendHeight);
    window.addEventListener('resize', sendHeight);
    if (typeof ResizeObserver !== 'undefined') {
        var ro = new ResizeObserver(sendHeight);
        ro.observe(document.documentElement);
    }
    setTimeout(sendHeight, 50);
})();
</script>
"""


def get_html_style(
    theme: str = "dark",
    accent: str = "",
    bg: str = "",
    text_color: str = "",
    card: bool = True,
    compact: bool = False,
    align: str = "center",
    full_page: bool = False,
) -> str:
    theme_clean = (theme or "dark").strip().lower()
    if theme_clean not in ("dark", "light", "transparent"):
        theme_clean = "dark"

    is_light = theme_clean == "light"
    is_transparent = theme_clean == "transparent"

    default_bg = "transparent" if is_transparent else ("#f8fafc" if is_light else "#0f172a")
    default_text = "#0f172a" if is_light else "#f8fafc"
    default_accent = "#2563eb"

    body_bg = _sanitize_css_color(bg, default_bg)
    fg = _sanitize_css_color(text_color, default_text)
    btn_bg = _sanitize_css_color(accent, default_accent)
    btn_hover = _darken_hex(btn_bg, "#1d4ed8")

    label_color = "#475569" if (is_light or is_transparent) else "#94a3b8"
    input_bg = "#ffffff" if is_light else ("rgba(15, 23, 42, 0.85)" if is_transparent else "#0f172a")
    input_border = "#cbd5e1" if is_light else "#334155"
    input_fg = "#0f172a" if is_light else "#f8fafc"

    card_bg = "#ffffff" if is_light else "rgba(30, 41, 59, 0.78)"
    card_border = "1px solid #e2e8f0" if is_light else "1px solid rgba(255, 255, 255, 0.1)"
    card_shadow = "0 4px 6px -1px rgba(0,0,0,0.1)" if is_light else "0 10px 25px -5px rgba(0,0,0,0.3)"
    card_pad = "16px" if compact else "24px"
    body_pad = "8px" if (compact or not card) else "12px"

    justify = "flex-start" if align == "left" else "center"
    full_page_css = "min-height: 100vh; align-items: center;" if full_page else "align-items: flex-start;"

    if not card:
        card_css = f"background: transparent; border: none; border-radius: 0; padding: 4px 0; width: 100%; max-width: 440px; box-shadow: none;"
    else:
        card_css = f"background: {card_bg}; backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border: {card_border}; border-radius: 12px; padding: {card_pad}; width: 100%; max-width: 420px; box-shadow: {card_shadow};"

    title_align = "left" if align == "left" else "center"
    gap_bottom = "10px" if compact else "14px"

    return f"""
<style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    html {{ margin: 0; padding: 0; overflow-x: hidden; background: {body_bg}; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background-color: {body_bg};
        color: {fg};
        margin: 0;
        padding: {body_pad};
        display: flex;
        justify-content: {justify};
        {full_page_css}
        overflow-x: hidden;
    }}
    .card {{
        {card_css}
    }}
    h2 {{
        margin-top: 0;
        font-size: 19px;
        font-weight: 700;
        color: {fg};
        text-align: {title_align};
        margin-bottom: {gap_bottom};
    }}
    .form-group {{
        margin-bottom: {gap_bottom};
    }}
    label {{
        display: block;
        font-size: 13px;
        font-weight: 600;
        color: {label_color};
        margin-bottom: 5px;
    }}
    input[type="text"], input[type="email"], select {{
        width: 100%;
        padding: 10px 12px;
        background: {input_bg};
        border: 1px solid {input_border};
        border-radius: 6px;
        color: {input_fg};
        font-size: 14px;
        box-sizing: border-box;
        transition: border-color 0.15s ease;
    }}
    input:focus, select:focus {{
        border-color: {btn_bg};
        outline: none;
    }}
    .btn {{
        width: 100%;
        padding: 11px;
        background: {btn_bg};
        border: none;
        border-radius: 6px;
        color: #ffffff;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s ease;
        margin-top: 6px;
    }}
    .btn:hover {{
        background: {btn_hover};
    }}
    .success-msg {{
        text-align: center;
        color: #10b981;
        font-size: 15px;
        font-weight: 500;
    }}
</style>
"""


HTML_STYLE = get_html_style("dark", full_page=True)

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
def get_embed_subscribe(
    list_id: int,
    request: Request,
    tag: str = "iFrame Embed",
    theme: str = "dark",
    accent: str = "",
    bg: str = "",
    text_color: str = "",
    card: bool = True,
    compact: bool = False,
    align: str = "center",
    title: str = "",
    button_text: str = "Subscribe",
    show_title: bool = True,
    db: Session = Depends(get_db),
):
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
    
    # Generate fields inputs HTML safely escaped
    inputs_html = ""
    for field in fields_to_render:
        key = str(field["key"] or "")
        label = str(field["label"] or key)
        ftype = str(field["type"] or "text")
        if ftype not in ("text", "email", "number", "tel", "url", "date"):
            ftype = "text"
        required = field["required"]
        req_attr = "required" if required else ""
        req_star = " *" if required else ""
        
        input_name = html_lib.escape(key if key in ["email", "name"] else f"custom_{key}", quote=True)
        label_esc = html_lib.escape(label)
        placeholder_esc = html_lib.escape(f"Enter your {label.lower()}", quote=True)
        
        inputs_html += f"""
        <div class="form-group">
            <label for="{input_name}">{label_esc}{req_star}</label>
            <input type="{ftype}" id="{input_name}" name="{input_name}" placeholder="{placeholder_esc}" {req_attr}>
        </div>
        """

    import urllib.parse
    submit_params = urllib.parse.urlencode({
        "theme": theme,
        "accent": accent,
        "bg": bg,
        "text_color": text_color,
        "card": "true" if card else "false",
        "compact": "true" if compact else "false",
        "align": align,
    })
    submit_url = f"/api/embed/subscribe/{list_id}/submit?{submit_params}"
    style_block = get_html_style(
        theme=theme,
        accent=accent,
        bg=bg,
        text_color=text_color,
        card=card,
        compact=compact,
        align=align,
    )
    list_name_esc = html_lib.escape(sub_list.name or "Newsletter")
    heading_raw = title.strip() if title and title.strip() else f"Subscribe to {tenant.name if tenant else 'Newsletter'}"
    heading_html = f"<h2>{html_lib.escape(heading_raw)}</h2>" if show_title else ""
    button_esc = html_lib.escape(button_text.strip() if button_text and button_text.strip() else "Subscribe")
    tag_esc = html_lib.escape(tag or "iFrame Embed", quote=True)
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Subscribe to {list_name_esc}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        {style_block}
    </head>
    <body>
        <div class="card">
            {heading_html}
            <form action="{submit_url}" method="POST">
                <input type="hidden" name="tag" value="{tag_esc}">
                {inputs_html}
                <button type="submit" class="btn">{button_esc}</button>
            </form>
        </div>
        {get_autoresize_script()}
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.post("/subscribe/{list_id}/submit", response_class=HTMLResponse)
async def post_embed_subscribe(
    list_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    theme: str = "dark",
    accent: str = "",
    bg: str = "",
    text_color: str = "",
    card: bool = True,
    compact: bool = False,
    align: str = "center",
    db: Session = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    if not embed_rate_limiter.check_and_record(f"embed:{client_ip}:{list_id}", 20, 60):
        return HTMLResponse("<h2>Too many subscription attempts. Please try again shortly.</h2>", status_code=429)

    form_data = await request.form()
    
    sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id).first()
    if not sub_list:
        return HTMLResponse("<h2>List not found</h2>", status_code=404)
        
    tenant = db.query(Tenant).filter(Tenant.id == sub_list.tenant_id).first()
    email = str(form_data.get("email") or "").strip()
    name = str(form_data.get("name") or "").strip() or None
    tag = str(form_data.get("tag") or "iFrame Embed")[:128]
    
    if not email or "@" not in email:
        return HTMLResponse("<h2>Invalid email address</h2>", status_code=400)
        
    # Extract custom values and validate required fields
    custom_data = {}
    
    if sub_list.custom_fields:
        for field in sub_list.custom_fields:
            key = field.get("key")
            required = field.get("required", False)
            show = field.get("show_on_form", True)
            
            if key == "name":
                if show and required and not name:
                    return HTMLResponse("<h2>Name is a required field</h2>", status_code=400)
            else:
                form_val = form_data.get(f"custom_{key}")
                if show and required and not form_val:
                    label = html_lib.escape(str(field.get("label", key.capitalize())))
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
        merged_custom = dict(existing.custom_data or {})
        merged_custom.update(custom_data)
        existing.custom_data = merged_custom
        flag_modified(existing, "custom_data")
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

    style_block = get_html_style(
        theme=theme,
        accent=accent,
        bg=bg,
        text_color=text_color,
        card=card,
        compact=compact,
        align=align,
    )
    email_esc = html_lib.escape(email)
    
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
                tenant_name=html_lib.escape(tenant.name or "PolyPress"),
                confirm_url=confirm_url
            )
        
        from sending_worker import send_transactional_email_by_tenant_id
        background_tasks.add_task(
            send_transactional_email_by_tenant_id,
            to_email=email,
            subject=subject,
            body_html=email_body,
            tenant_id=tenant.id,
        )
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Verification Sent</title>
            {style_block}
        </head>
        <body>
            <div class="card" style="text-align: center;">
                <svg width="48" height="48" fill="none" stroke="#6366f1" viewBox="0 0 24 24" style="margin: 0 auto 15px; display: block;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>
                <h2>Check Your Inbox</h2>
                <p style="font-size: 14px; color: #94a3b8; line-height: 1.5; margin-bottom: 10px;">
                    We have sent a subscription verification link to <strong>{email_esc}</strong>. Please check your email inbox and click the link to confirm subscription.
                </p>
            </div>
            {get_autoresize_script()}
        </body>
        </html>
        """
        return HTMLResponse(content=html)
        
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Success</title>
        {style_block}
    </head>
    <body>
        <div class="card">
            <div class="success-msg">
                <svg width="48" height="48" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="margin: 0 auto 15px; display: block;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                Thank you! You have successfully subscribed.
            </div>
        </div>
        {get_autoresize_script()}
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
    
    tenant = db.query(Tenant).filter(Tenant.id == subscriber.tenant_id).first()
    if tenant and tenant.subscription_confirmed_html:
        custom_html = tenant.subscription_confirmed_html
        custom_html = custom_html.replace("{email}", html_lib.escape(subscriber.email or ""))
        custom_html = custom_html.replace("{name}", html_lib.escape(subscriber.name or ""))
        custom_html = custom_html.replace("{tenant_name}", html_lib.escape(tenant.name or ""))
        return HTMLResponse(content=custom_html)

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

def _mask_email(email: str) -> str:
    """Mask email local-part for legacy unsigned confirmation views without leaking PII."""
    if not email or "@" not in email:
        return "subscriber"
    local, domain = email.split("@", 1)
    if len(local) <= 1:
        masked_local = "*"
    elif len(local) == 2:
        masked_local = f"{local[0]}*"
    else:
        masked_local = f"{local[:2]}***"
    return f"{masked_local}@{domain}"


def _is_legacy_unsub_allowed(db: Session, campaign_id: int) -> bool:
    """Allow legacy unsigned unsubscribes strictly for campaigns sent prior to HMAC enforcement."""
    settings = db.query(GlobalSettings).first()
    cutoff = getattr(settings, "legacy_unsub_cutoff_campaign_id", 0) if settings else 0
    return bool(cutoff and int(campaign_id) <= int(cutoff))


@router.get("/unsubscribe/{subscriber_id}/{campaign_id}", response_class=HTMLResponse)
def get_unsubscribe_confirm(
    subscriber_id: int,
    campaign_id: int,
    sig: str = None,
    db: Session = Depends(get_db),
):
    if subscriber_id == 0:
        sig_esc = html_lib.escape(sig or "", quote=True)
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
                <form action="/api/embed/unsubscribe/0/{campaign_id}" method="POST">
                    <input type="hidden" name="sig" value="{sig_esc}">
                    <button type="submit" class="btn" style="background-color: #dc2626;">Yes, Unsubscribe (Test)</button>
                </form>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html)

    subscriber = db.query(Subscriber).filter(Subscriber.id == subscriber_id).first()
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    
    if not subscriber or not campaign or (subscriber.tenant_id and campaign.tenant_id and subscriber.tenant_id != campaign.tenant_id):
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Invalid Link</title>
            {HTML_STYLE}
        </head>
        <body>
            <div class="card" style="text-align: center;">
                <h2 style="color: #ef4444;">Invalid Request</h2>
                <p style="font-size: 14px; color: #94a3b8; line-height: 1.5;">
                    The subscription management link is invalid or no longer active.
                </p>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html, status_code=400)

    if sig is not None:
        if not auth.verify_url_token(f"unsub:{subscriber_id}:{campaign_id}", sig):
            return HTMLResponse(
                f"""<!DOCTYPE html><html><head><title>Forbidden</title>{HTML_STYLE}</head><body><div class="card" style="text-align:center;"><h2 style="color:#ef4444;">Unauthorized Link</h2><p style="font-size:14px;color:#94a3b8;">This subscription management link has an invalid or missing signature.</p></div></body></html>""",
                status_code=403,
            )
    elif _is_legacy_unsub_allowed(db, campaign_id):
        masked_email_esc = html_lib.escape(_mask_email(subscriber.email or ""))
        legacy_sig = auth.sign_url_token(f"unsub:{subscriber_id}:{campaign_id}")
        post_legacy_url = f"/api/embed/unsubscribe/{subscriber_id}/{campaign_id}?sig={urllib.parse.quote(legacy_sig, safe='')}"
        html = f"""<!DOCTYPE html><html><head><title>Unsubscribe</title>{HTML_STYLE}</head><body><div class="card" style="max-width:460px;width:100%;box-sizing:border-box;background:rgba(30,41,59,0.7);border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:30px;text-align:center;"><h2 style="margin-bottom:10px;font-size:22px;color:#fff;">Confirm Unsubscribe</h2><p style="font-size:14px;color:#94a3b8;line-height:1.5;margin-bottom:22px;">Unsubscribe <strong>{masked_email_esc}</strong> from all mailing lists in this workspace?</p><form action="{post_legacy_url}" method="POST"><input type="hidden" name="action" value="unsubscribe_all"><input type="hidden" name="sig" value="{html_lib.escape(legacy_sig, quote=True)}"><button type="submit" class="btn" style="background:#dc2626;width:100%;">Confirm Unsubscribe</button></form></div></body></html>"""
        return HTMLResponse(content=html)
    else:
        return HTMLResponse(
            f"""<!DOCTYPE html><html><head><title>Forbidden</title>{HTML_STYLE}</head><body><div class="card" style="text-align:center;"><h2 style="color:#ef4444;">Unauthorized Link</h2><p style="font-size:14px;color:#94a3b8;">This subscription management link has an invalid or missing signature.</p></div></body></html>""",
            status_code=403,
        )
        
    tenant_id = campaign.tenant_id
    
    from sqlalchemy import func
    # Join SubscriberList to resolve memberships correctly even if tenant_id is Null on Subscriber
    subs = db.query(Subscriber).join(SubscriberList).filter(
        SubscriberList.tenant_id == tenant_id,
        func.lower(Subscriber.email) == subscriber.email.lower()
    ).all()
    
    subscribed_list_ids = {s.list_id for s in subs}
    active_list_ids = {s.list_id for s in subs if s.status == "active"}
    
    # Filter the shown lists to only the ones they are already subscribed to
    lists = db.query(SubscriberList).filter(
        SubscriberList.tenant_id == tenant_id,
        SubscriberList.id.in_(subscribed_list_ids)
    ).all()
    
    list_items_html = ""
    for l in lists:
        is_checked = "checked" if l.id in active_list_ids else ""
        list_name_esc = html_lib.escape(l.name or "")
        list_desc_esc = html_lib.escape(l.description or "Mailing list")
        list_items_html += f"""
        <div style="display: flex; align-items: flex-start; gap: 10px; padding: 12px; background: rgba(255,255,255,0.03); border-radius: 8px; border: 1px solid rgba(255,255,255,0.08); margin-bottom: 12px; text-align: left;">
            <input type="checkbox" name="lists" value="{l.id}" {is_checked} style="width: 18px; height: 18px; margin-top: 2px; cursor: pointer;">
            <div>
                <div style="font-weight: 600; font-size: 14px; color: #fff;">{list_name_esc}</div>
                <div style="font-size: 12px; color: #94a3b8; margin-top: 2px;">{list_desc_esc}</div>
            </div>
        </div>
        """

    post_url = f"/api/embed/unsubscribe/{subscriber_id}/{campaign_id}?sig={urllib.parse.quote(sig or '', safe='')}"
    email_esc = html_lib.escape(subscriber.email or "")
    sig_esc = html_lib.escape(sig or "", quote=True)
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Manage Subscription</title>
        {HTML_STYLE}
    </head>
    <body>
        <div class="card" style="max-width: 480px; width: 100%; box-sizing: border-box; background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 16px; padding: 30px;">
            <h2 style="margin-bottom: 10px; font-size: 22px; color: #fff; text-align: center;">Subscription Preferences Center</h2>
            <p style="text-align: center; font-size: 14px; color: #94a3b8; line-height: 1.5; margin-bottom: 25px;">
                Manage your subscriptions for <strong>{email_esc}</strong>. Check the lists you want to subscribe to, or unsubscribe from everything.
            </p>
            <form action="{post_url}" method="POST" style="display: flex; flex-direction: column; gap: 15px;">
                <input type="hidden" name="action" id="preference_action" value="update_preferences">
                <input type="hidden" name="sig" value="{sig_esc}">
                <div>
                    {list_items_html}
                </div>
                
                <div style="display: flex; flex-direction: column; gap: 10px; margin-top: 15px;">
                    <button type="submit" class="btn" style="background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%); margin: 0; box-shadow: 0 4px 10px rgba(59, 130, 246, 0.3);">Save Preferences</button>
                    <button type="submit" onclick="document.getElementById('preference_action').value='unsubscribe_all';" class="btn" style="background: #dc2626; margin: 0; box-shadow: 0 4px 10px rgba(220, 38, 38, 0.2);">Unsubscribe from All</button>
                </div>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.post("/unsubscribe/{subscriber_id}/{campaign_id}", response_class=HTMLResponse)
async def post_unsubscribe(
    subscriber_id: int,
    campaign_id: int,
    request: Request,
    sig: str = None,
    db: Session = Depends(get_db),
):
    form_data = await request.form()
    sig_val = sig or form_data.get("sig")

    if subscriber_id == 0:
        action = html_lib.escape(str(form_data.get("action", "unsubscribe_all")))
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Unsubscribed</title>
            {HTML_STYLE}
        </head>
        <body>
            <div class="card" style="text-align: center;">
                <h2 style="color: #10b981;">✓ Success</h2>
                <p style="font-size: 14px; color: #94a3b8; line-height: 1.5; margin-bottom: 20px;">
                    Test mock action '{action}' processed successfully.
                </p>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html)

    subscriber = db.query(Subscriber).filter(Subscriber.id == subscriber_id).first()
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    
    if not subscriber or not campaign or (subscriber.tenant_id and campaign.tenant_id and subscriber.tenant_id != campaign.tenant_id):
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Invalid Link</title>
            {HTML_STYLE}
        </head>
        <body>
            <div class="card" style="text-align: center;">
                <h2 style="color: #ef4444;">Invalid Request</h2>
                <p style="font-size: 14px; color: #94a3b8; line-height: 1.5;">
                    The subscription management link is invalid or no longer active.
                </p>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html, status_code=400)

    action = str(form_data.get("action", "unsubscribe_all"))
    if sig_val is not None:
        if not auth.verify_url_token(f"unsub:{subscriber_id}:{campaign_id}", sig_val):
            return HTMLResponse(
                f"""<!DOCTYPE html><html><head><title>Forbidden</title>{HTML_STYLE}</head><body><div class="card" style="text-align:center;"><h2 style="color:#ef4444;">Unauthorized Request</h2><p style="font-size:14px;color:#94a3b8;">Invalid or missing unsubscribe signature.</p></div></body></html>""",
                status_code=403,
            )
    elif _is_legacy_unsub_allowed(db, campaign_id) and action == "unsubscribe_all":
        pass
    else:
        return HTMLResponse(
            f"""<!DOCTYPE html><html><head><title>Forbidden</title>{HTML_STYLE}</head><body><div class="card" style="text-align:center;"><h2 style="color:#ef4444;">Unauthorized Request</h2><p style="font-size:14px;color:#94a3b8;">Invalid or missing unsubscribe signature.</p></div></body></html>""",
            status_code=403,
        )

    tenant = db.query(Tenant).filter(Tenant.id == subscriber.tenant_id).first()
    
    from sqlalchemy import func
    
    if action == "unsubscribe_all":
        subs = db.query(Subscriber).filter(
            Subscriber.tenant_id == subscriber.tenant_id,
            func.lower(Subscriber.email) == subscriber.email.lower()
        ).all()
        for s in subs:
            if s.status != "unsubscribed":
                s.status = "unsubscribed"
                db.commit()
                
                from location_helper import log_subscriber_activity
                log_subscriber_activity(
                    db=db,
                    tenant_id=s.tenant_id,
                    subscriber_id=s.id,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent", "")
                )
                
                from webhook_dispatcher import trigger_webhook
                trigger_webhook(s.tenant_id, "subscriber.unsubscribe", {
                    "id": s.id,
                    "email": s.email,
                    "name": s.name,
                    "status": s.status,
                    "list_id": s.list_id,
                    "campaign_id": campaign_id
                })
        db.commit()
        
        if tenant and tenant.unsubscribed_html:
            custom_html = tenant.unsubscribed_html
            custom_html = custom_html.replace("{email}", html_lib.escape(subscriber.email or ""))
            custom_html = custom_html.replace("{name}", html_lib.escape(subscriber.name or ""))
            custom_html = custom_html.replace("{tenant_name}", html_lib.escape(tenant.name or ""))
            return HTMLResponse(content=custom_html)
            
        success_title = "✓ Unsubscribed"
        success_desc = "You have been successfully unsubscribed from all mailing lists."
        
    else:
        # Update preferences
        selected_list_ids = []
        for lid in form_data.getlist("lists"):
            try:
                selected_list_ids.append(int(lid))
            except (TypeError, ValueError):
                pass
        tenant_id = campaign.tenant_id
        tenant_lists = db.query(SubscriberList).filter(SubscriberList.tenant_id == tenant_id).all()
        
        for list_obj in tenant_lists:
            # Query existing subscriber record without matching tenant_id directly, as list_id is unique enough
            sub_entry = db.query(Subscriber).filter(
                Subscriber.list_id == list_obj.id,
                func.lower(Subscriber.email) == subscriber.email.lower()
            ).first()
            
            should_be_subscribed = list_obj.id in selected_list_ids
            
            if should_be_subscribed:
                if not sub_entry:
                    new_sub = Subscriber(
                        tenant_id=tenant_id,
                        list_id=list_obj.id,
                        email=subscriber.email,
                        name=subscriber.name,
                        status="active",
                        custom_data={},
                        source_tag="Preferences Screen"
                    )
                    db.add(new_sub)
                    db.commit()
                elif sub_entry.status != "active":
                    sub_entry.status = "active"
                    db.commit()
                    
                    from location_helper import log_subscriber_activity
                    log_subscriber_activity(
                        db=db,
                        tenant_id=subscriber.tenant_id,
                        subscriber_id=sub_entry.id,
                        ip_address=request.client.host if request.client else None,
                        user_agent=request.headers.get("user-agent", "")
                    )
            else:
                if sub_entry and sub_entry.status != "unsubscribed":
                    sub_entry.status = "unsubscribed"
                    db.commit()
                    
                    from location_helper import log_subscriber_activity
                    log_subscriber_activity(
                        db=db,
                        tenant_id=subscriber.tenant_id,
                        subscriber_id=sub_entry.id,
                        ip_address=request.client.host if request.client else None,
                        user_agent=request.headers.get("user-agent", "")
                    )
                    
                    from webhook_dispatcher import trigger_webhook
                    trigger_webhook(subscriber.tenant_id, "subscriber.unsubscribe", {
                        "id": sub_entry.id,
                        "email": sub_entry.email,
                        "name": sub_entry.name,
                        "status": sub_entry.status,
                        "list_id": sub_entry.list_id,
                        "campaign_id": campaign_id
                    })
        db.commit()
        
        success_title = "✓ Preferences Saved"
        success_desc = "Your subscription preferences have been updated successfully."
        
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{success_title}</title>
        {HTML_STYLE}
    </head>
    <body>
        <div class="card" style="text-align: center;">
            <svg width="48" height="48" fill="none" stroke="#10b981" viewBox="0 0 24 24" style="margin: 0 auto 15px; display: block;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
            <h2 style="color: #10b981;">{success_title}</h2>
            <p style="font-size: 14px; color: #94a3b8; line-height: 1.5;">
                {success_desc}
            </p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

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
                from sqlalchemy import func
                db.query(Campaign).filter(
                    Campaign.id == resolved_campaign_id,
                    Campaign.tenant_id == tenant.id
                ).update(
                    {Campaign.bounce_count: func.coalesce(Campaign.bounce_count, 0) + 1},
                    synchronize_session=False,
                )
                    
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
                import requests
                import urllib.parse
                try:
                    parsed_url = urllib.parse.urlparse(subscribe_url)
                    sns_host = (parsed_url.hostname or "").lower()
                    if parsed_url.scheme != "https" or not (
                        sns_host == "amazonaws.com"
                        or sns_host.endswith(".amazonaws.com")
                        or sns_host.endswith(".amazonaws.com.cn")
                    ):
                        raise HTTPException(status_code=400, detail="Invalid SNS subscription confirmation URL domain")
                    # AWS SNS requires confirmation by fetching the URL without following untrusted redirects
                    res = requests.get(subscribe_url, timeout=10, allow_redirects=False)
                    if res.status_code >= 400:
                        raise HTTPException(status_code=400, detail=f"SNS confirmation returned status {res.status_code}")
                    return {"success": True, "detail": "Subscription confirmed successfully."}
                except HTTPException:
                    raise
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
