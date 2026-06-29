import time
import logging
import asyncio
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import re
import socket
import dns.resolver
try:
    import dkim
except ImportError:
    dkim = None
from sqlalchemy.orm import Session
from database import SessionLocal, QueueItem, Campaign, Tenant, Subscriber

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sending_worker")

def get_mx_records(domain: str) -> list:
    try:
        answers = dns.resolver.resolve(domain, 'MX')
        records = sorted([(ans.preference, str(ans.exchange).rstrip('.')) for ans in answers])
        return [r[1] for r in records]
    except Exception as e:
        logger.warning(f"Failed to find MX records for {domain}: {e}. Trying A record.")
        return [domain]

def generate_dkim_signature(msg_bytes: bytes, tenant: Tenant) -> bytes:
    if not dkim:
        logger.error("DKIM module not loaded. Cannot sign outbound mail.")
        return msg_bytes
        
    if not tenant.dkim_private_key or not tenant.dkim_domain or not tenant.dkim_selector:
        return msg_bytes
        
    try:
        sig = dkim.sign(
            message=msg_bytes,
            selector=tenant.dkim_selector.encode('utf-8'),
            domain=tenant.dkim_domain.encode('utf-8'),
            privkey=tenant.dkim_private_key.encode('utf-8'),
            include_headers=[b'To', b'From', b'Subject', b'Content-Type']
        )
        return sig + msg_bytes
    except Exception as e:
        logger.error(f"DKIM signing failed for tenant {tenant.name}: {e}")
        return msg_bytes

def parse_smtp_exception(e: Exception) -> tuple:
    """
    Parses SMTP exception and returns (is_transient, code, error_message)
    """
    is_transient = True
    code = 400
    msg = str(e)
    
    if hasattr(e, 'smtp_code'):
        code = getattr(e, 'smtp_code', 400)
        smtp_err = getattr(e, 'smtp_error', b'')
        msg = smtp_err.decode('utf-8', errors='ignore') if isinstance(smtp_err, bytes) else str(smtp_err)
        # If code is 5xx, it's permanent
        if 500 <= code < 600:
            is_transient = False
    elif hasattr(e, 'recipients'):
        refused = getattr(e, 'recipients', {})
        if refused:
            first_rec = list(refused.values())[0]
            code = first_rec[0]
            msg = first_rec[1].decode('utf-8', errors='ignore') if isinstance(first_rec[1], bytes) else str(first_rec[1])
            if 500 <= code < 600:
                is_transient = False
    elif isinstance(e, (socket.timeout, TimeoutError, ConnectionRefusedError, ConnectionResetError)):
        is_transient = True
        code = 408
        msg = f"Network Timeout / Connection Refused: {str(e)}"
        
    return is_transient, code, msg

def send_external_smtp(item: QueueItem, tenant: Tenant) -> tuple:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = item.subject
        msg["From"] = f"{tenant.name} <{tenant.bounce_email or f'noreply@{tenant.dkim_domain or tenant.smtp_host}'}>"
        msg["To"] = item.email
        
        # Add headers for tracking / bounce correlation
        msg["X-PolyPress-Campaign"] = str(item.campaign_id)
        msg["X-PolyPress-Subscriber"] = str(item.subscriber_id)
        msg["X-PolyPress-QueueItem"] = str(item.id)
        msg["Return-Path"] = tenant.bounce_email or f"bounce@{tenant.dkim_domain or tenant.smtp_host}"
        
        # List-Unsubscribe Header Extraction (RFC 8058)
        match = re.search(r'https?://[^/]+/api/embed/unsubscribe/\d+/\d+', item.body_html)
        if match:
            msg["List-Unsubscribe"] = f"<{match.group(0)}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
            
        part = MIMEText(item.body_html, "html", "utf-8")
        msg.attach(part)
        
        msg_bytes = msg.as_bytes()
        msg_bytes = generate_dkim_signature(msg_bytes, tenant)
        
        port = tenant.smtp_port or 587
        host = tenant.smtp_host
        username = tenant.smtp_username
        password = tenant.smtp_password
        
        if tenant.smtp_use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=15.0)
        else:
            server = smtplib.SMTP(host, port, timeout=15.0)
            if tenant.smtp_use_tls:
                server.ehlo()
                server.starttls()
                server.ehlo()
                
        if username and password:
            server.login(username, password)
            
        server.sendmail(tenant.bounce_email or f"bounce@{tenant.dkim_domain or tenant.smtp_host}", item.email, msg_bytes)
        server.quit()
        return True, True, 250, "Sent successfully"
    except Exception as e:
        logger.error(f"External SMTP failed for QueueItem {item.id}: {e}")
        is_transient, code, msg = parse_smtp_exception(e)
        return False, is_transient, code, msg

def send_direct_mta(item: QueueItem, tenant: Tenant) -> tuple:
    try:
        domain = item.email.split("@")[-1]
        mx_hosts = get_mx_records(domain)
        if not mx_hosts:
            raise Exception(f"Could not resolve mail servers for domain {domain}")
            
        msg = MIMEMultipart("alternative")
        msg["Subject"] = item.subject
        sender_domain = tenant.dkim_domain or "localhost"
        msg["From"] = f"{tenant.name} <{tenant.bounce_email or f'noreply@{sender_domain}'}>"
        msg["To"] = item.email
        
        msg["X-PolyPress-Campaign"] = str(item.campaign_id)
        msg["X-PolyPress-Subscriber"] = str(item.subscriber_id)
        msg["X-PolyPress-QueueItem"] = str(item.id)
        msg["Return-Path"] = tenant.bounce_email or f"bounce@{sender_domain}"
        
        # List-Unsubscribe Header Extraction (RFC 8058)
        match = re.search(r'https?://[^/]+/api/embed/unsubscribe/\d+/\d+', item.body_html)
        if match:
            msg["List-Unsubscribe"] = f"<{match.group(0)}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
            
        part = MIMEText(item.body_html, "html", "utf-8")
        msg.attach(part)
        
        msg_bytes = msg.as_bytes()
        msg_bytes = generate_dkim_signature(msg_bytes, tenant)
        
        connected = False
        last_err = None
        for mx_host in mx_hosts:
            try:
                server = smtplib.SMTP(mx_host, 25, timeout=15.0)
                server.ehlo(sender_domain)
                if server.has_extn('STARTTLS'):
                    server.starttls()
                    server.ehlo(sender_domain)
                server.sendmail(tenant.bounce_email or f"bounce@{sender_domain}", item.email, msg_bytes)
                server.quit()
                connected = True
                break
            except Exception as e:
                logger.warning(f"Connection to MX {mx_host} failed: {e}")
                last_err = e
                
        if not connected:
            raise last_err or Exception("All MX delivery attempts failed")
            
        return True, True, 250, "Sent successfully"
    except Exception as e:
        logger.error(f"Direct MTA delivery failed for QueueItem {item.id}: {e}")
        is_transient, code, msg = parse_smtp_exception(e)
        return False, is_transient, code, msg

def send_transactional_email(to_email: str, subject: str, body_html: str, tenant: Tenant):
    """
    Sends a transactional email immediately bypassing the standard outbox queue scheduling.
    """
    class MockItem:
        def __init__(self, to_email, subject, body_html):
            self.id = 0
            self.campaign_id = 0
            self.subscriber_id = 0
            self.email = to_email
            self.subject = subject
            self.body_html = body_html
            self.error_message = ""
            
    item = MockItem(to_email, subject, body_html)
    logger.info(f"Dispatching transactional email to {to_email} for tenant {tenant.name}...")
    
    if tenant.direct_send:
        success, is_transient, code, msg = send_direct_mta(item, tenant)
    else:
        success, is_transient, code, msg = send_external_smtp(item, tenant)
        
    if success:
        logger.info(f"Transactional email sent to {to_email} successfully.")
    else:
        logger.error(f"Transactional email failed to send to {to_email}: [{code}] {msg}")
    return success

async def process_queue():
    last_expiry_check = 0
    
    while True:
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            
            # Periodically check for expired queue items (once every 60 seconds)
            if time.time() - last_expiry_check > 60:
                last_expiry_check = time.time()
                cutoff_date = now - timedelta(days=3)
                expired_items = db.query(QueueItem).filter(
                    QueueItem.status.in_(["pending", "deferred"]),
                    QueueItem.created_at < cutoff_date
                ).all()
                
                for exp_item in expired_items:
                    exp_item.status = "failed"
                    exp_item.error_message = "Queue item expired after 3 days of delivery attempts."
                    exp_item.error_code = 408
                    
                    # Update campaign failures if possible
                    camp = db.query(Campaign).filter(Campaign.id == exp_item.campaign_id).first()
                    if camp:
                        camp.failed_count += 1
                        
                    # Progress subscriber status
                    sub = db.query(Subscriber).filter(Subscriber.id == exp_item.subscriber_id).first()
                    if sub:
                        if sub.status == "deferred":
                            sub.status = "failed"
                            sub.bounce_reason = "Consecutive email queue timeouts of 3 days."
                            sub.bounce_source_email = "System Outbox Queue Monitor"
                        else:
                            sub.status = "deferred"
                            sub.bounce_reason = "Email queue delivery timeout of 3 days."
                            sub.bounce_source_email = "System Outbox Queue Monitor"
                    db.commit()
            
            # Fetch a pending or deferred item
            item = db.query(QueueItem).filter(
                QueueItem.status.in_(["pending", "deferred"]),
                QueueItem.next_attempt <= now
            ).order_by(QueueItem.created_at.asc()).first()
            
            if not item:
                # Sleep briefly if nothing to send
                await asyncio.sleep(2)
                continue
                
            tenant = db.query(Tenant).filter(Tenant.id == item.tenant_id).first()
            campaign = db.query(Campaign).filter(Campaign.id == item.campaign_id).first()
            subscriber = db.query(Subscriber).filter(Subscriber.id == item.subscriber_id).first()
            
            # Exclude blocked subscriber statuses
            if not tenant or not campaign or not subscriber or subscriber.status not in ["active", "deferred"]:
                item.status = "failed"
                item.error_message = "Tenant, Campaign, or active/deferred Subscriber not found"
                item.error_code = 400
                db.commit()
                continue
                
            logger.info(f"Sending QueueItem {item.id} to {item.email}")
            
            # Record start time to implement rate limits
            start_time = time.time()
            
            # Send
            success = False
            if tenant.direct_send:
                success, is_transient, code, msg = send_direct_mta(item, tenant)
            else:
                success, is_transient, code, msg = send_external_smtp(item, tenant)
                
            # Update item status
            if success:
                item.status = "sent"
                item.error_code = 250
                item.last_mx_response = "Sent successfully"
                campaign.sent_count += 1
            else:
                item.error_code = code
                item.last_mx_response = msg
                item.error_message = msg
                
                if is_transient:
                    # Reschedule temporary failures without marking subscriber bad
                    item.status = "deferred"
                    item.next_attempt = datetime.utcnow() + timedelta(minutes=15)
                else:
                    # Permanent failure: immediately mark failed and block subscriber
                    item.status = "failed"
                    campaign.failed_count += 1
                    
                    subscriber.status = "bounced"
                    subscriber.bounce_reason = f"[{code}] {msg}"
                    subscriber.bounce_source_email = f"SMTP/MX: {item.email.split('@')[-1]}"
                    
            db.commit()
            
            # Dispatch Webhook Delivery notifications
            from webhook_dispatcher import trigger_webhook
            if success:
                trigger_webhook(tenant.id, "email.sent", {
                    "campaign_id": campaign.id,
                    "subscriber_id": subscriber.id,
                    "email": subscriber.email
                })
            else:
                if is_transient:
                    trigger_webhook(tenant.id, "email.deferred", {
                        "campaign_id": campaign.id,
                        "subscriber_id": subscriber.id,
                        "email": subscriber.email,
                        "code": code,
                        "reason": msg
                    })
                else:
                    trigger_webhook(tenant.id, "subscriber.bounce", {
                        "id": subscriber.id,
                        "email": subscriber.email,
                        "name": subscriber.name,
                        "status": subscriber.status,
                        "reason": f"[{code}] {msg}",
                        "campaign_id": campaign.id
                    })
            
            # Calculate next delay for this tenant's items to respect speed limit
            if tenant.speed_emails_per_hour > 0:
                delay = 3600.0 / tenant.speed_emails_per_hour
                other_pending = db.query(QueueItem).filter(
                    QueueItem.tenant_id == tenant.id,
                    QueueItem.status.in_(["pending", "deferred"])
                ).all()
                
                next_time = datetime.utcnow() + timedelta(seconds=delay)
                for other_item in other_pending:
                    if other_item.next_attempt < next_time:
                        other_item.next_attempt = next_time
                        next_time += timedelta(seconds=delay)
                db.commit()
                
                elapsed = time.time() - start_time
                wait_time = max(0.0, delay - elapsed)
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
            else:
                await asyncio.sleep(0.05)
                
            # Check if campaign is finished
            total_pending = db.query(QueueItem).filter(
                QueueItem.campaign_id == campaign.id,
                QueueItem.status.in_(["pending", "deferred"])
            ).count()
            if total_pending == 0:
                campaign.status = "sent"
                db.commit()
                
        except Exception as e:
            logger.exception(f"Error in sending worker loop: {e}")
            await asyncio.sleep(5)
        finally:
            db.close()

def start_sending_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(process_queue())
