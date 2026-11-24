import time
import logging
import asyncio
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from email.charset import Charset, QP
from email.policy import SMTP
import re
import socket
import dns.resolver
try:
    # pyrefly: ignore [missing-import]
    import dkim
except ImportError:
    dkim = None
import threading
from sqlalchemy import func
from sqlalchemy.orm import Session
from database import SessionLocal, QueueItem, Campaign, Tenant, Subscriber, TrackingLog, GlobalSettings
from ntp_sync import get_corrected_time, get_cached_corrected_time, refresh_ntp_offset_if_needed
from analytics_service import real_tracking_filter
from routes.campaign_routes import render_email_template, apply_targeting_rules_to_query, order_subscribers_for_queue

_gs_cache_lock = threading.Lock()
_gs_cache_data = None
_gs_cache_ts = 0.0


def get_cached_global_settings(force_refresh: bool = False) -> dict:
    """Return a thread-safe snapshot of GlobalSettings refreshed every 5 seconds."""
    global _gs_cache_data, _gs_cache_ts
    now_mono = time.monotonic()
    if not force_refresh and _gs_cache_data is not None and (now_mono - _gs_cache_ts) < 5.0:
        return _gs_cache_data
    with _gs_cache_lock:
        now_mono = time.monotonic()
        if not force_refresh and _gs_cache_data is not None and (now_mono - _gs_cache_ts) < 5.0:
            return _gs_cache_data
        db = SessionLocal()
        try:
            gs = db.query(GlobalSettings).first()
            snapshot = {
                "smtp_host": gs.smtp_host if gs else None,
                "smtp_port": (gs.smtp_port or 587) if gs else 587,
                "smtp_username": gs.smtp_username if gs else None,
                "smtp_password": gs.smtp_password if gs else None,
                "smtp_use_ssl": gs.smtp_use_ssl if gs else False,
                "smtp_use_tls": gs.smtp_use_tls if gs else True,
                "smtp_connection_reuse": gs.smtp_connection_reuse if (gs and gs.smtp_connection_reuse is not None) else True,
                "mail_server_identity": gs.mail_server_identity if gs else None,
                "public_url": gs.public_url if gs else None,
                "max_global_sending_threads": (gs.max_global_sending_threads or 50) if (gs and gs.max_global_sending_threads) else 50,
                "max_domain_sending_threads": (gs.max_domain_sending_threads or 20) if (gs and gs.max_domain_sending_threads) else 20,
            }
            _gs_cache_data = snapshot
            _gs_cache_ts = time.monotonic()
            return snapshot
        finally:
            db.close()

def html_to_text(html: str) -> str:
    if not html:
        return ""
    # Replace block tags with newlines
    text = re.sub(r'<(?:p|div|h\d|br|tr)[^>]*>', '\n', html, flags=re.IGNORECASE)
    # Remove all other tags
    text = re.sub(r'<[^>]+>', '', text)
    # Unescape some common HTML entities
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    # Collapse multiple consecutive newlines
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()

def make_mime_text(content: str, subtype: str) -> MIMEText:
    charset = Charset("utf-8")
    charset.body_encoding = QP
    return MIMEText(content, subtype, charset)

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
        # RFC 8058 requires List-Unsubscribe and List-Unsubscribe-Post to be signed by DKIM if present
        include_headers = [b'To', b'From', b'Subject', b'Content-Type']
        
        if b'\r\n\r\n' in msg_bytes:
            header_part = msg_bytes.split(b'\r\n\r\n', 1)[0]
        else:
            header_part = msg_bytes.split(b'\n\n', 1)[0]
        if b'list-unsubscribe:' in header_part.lower():
            include_headers.append(b'List-Unsubscribe')
        if b'list-unsubscribe-post:' in header_part.lower():
            include_headers.append(b'List-Unsubscribe-Post')
            
        sig = dkim.sign(
            message=msg_bytes,
            selector=tenant.dkim_selector.encode('utf-8'),
            domain=tenant.dkim_domain.encode('utf-8'),
            privkey=tenant.dkim_private_key.encode('utf-8'),
            include_headers=include_headers
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
        sender_domain = tenant.dkim_domain
        if not sender_domain and tenant.bounce_email and "@" in tenant.bounce_email:
            sender_domain = tenant.bounce_email.split("@")[-1]
        if not sender_domain:
            import socket
            sender_domain = socket.getfqdn()
        if not sender_domain or sender_domain == "localhost":
            sender_domain = tenant.smtp_host or "polypress.local"
        from_email = f"{tenant.mta_from_prefix or 'noreply'}@{sender_domain}"
        msg["From"] = f"{tenant.name} <{from_email}>"
        msg["To"] = item.email
        
        # Add headers for tracking / bounce correlation
        msg["X-PolyPress-Campaign"] = str(item.campaign_id)
        msg["X-PolyPress-Subscriber"] = str(item.subscriber_id)
        msg["X-PolyPress-QueueItem"] = str(item.id)
        msg["Return-Path"] = tenant.bounce_email or f"bounce@{tenant.dkim_domain or tenant.smtp_host}"
        
        # Add Date and Message-ID headers to prevent spam flags
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=sender_domain)
        
        # List-Unsubscribe Header Extraction (RFC 8058), preserving signed query parameters
        match = re.search(r'https?://[^\s"\'<>]+/api/embed/unsubscribe/\d+/\d+(?:\?[^\s"\'<>]*)?', item.body_html or "")
        if match:
            msg["List-Unsubscribe"] = f"<{match.group(0)}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
            
        # Attach plain text part first (standard alternative ordering)
        plain_text = html_to_text(item.body_html)
        part_text = make_mime_text(plain_text, "plain")
        msg.attach(part_text)
        
        part_html = make_mime_text(item.body_html, "html")
        msg.attach(part_html)
        
        msg_bytes = msg.as_bytes(policy=SMTP)
        msg_bytes = generate_dkim_signature(msg_bytes, tenant)
        
        port = tenant.smtp_port or 587
        host = tenant.smtp_host
        username = tenant.smtp_username
        password = tenant.smtp_password
        use_ssl = tenant.smtp_use_ssl
        use_tls = tenant.smtp_use_tls

        global_settings = get_cached_global_settings()
        if not host and global_settings.get("smtp_host"):
            host = global_settings["smtp_host"]
            port = global_settings.get("smtp_port") or 587
            username = global_settings.get("smtp_username")
            password = global_settings.get("smtp_password")
            use_ssl = global_settings.get("smtp_use_ssl")
            use_tls = global_settings.get("smtp_use_tls")
                
        if not host:
            return False, False, 500, "Outbound SMTP server not configured"
            
        use_reuse = global_settings.get("smtp_connection_reuse", True)
        conn_key = f"{host}:{port}:{username}:{use_ssl}:{use_tls}"
        
        if use_reuse:
            try:
                server = get_pooled_smtp(conn_key, host, port, use_ssl, use_tls, username, password)
                server.sendmail(tenant.bounce_email or f"bounce@{tenant.dkim_domain or tenant.smtp_host or 'localhost'}", item.email, msg_bytes)
                return True, True, 250, "Sent successfully"
            except Exception:
                # Connection dropped or stale; close pooled connection and fallback once
                close_pooled_smtp(conn_key)
                
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=15.0)
        else:
            server = smtplib.SMTP(host, port, timeout=15.0)
            if use_tls:
                server.ehlo()
                server.starttls()
                server.ehlo()
                
        if username and password:
            server.login(username, password)
            
        server.sendmail(tenant.bounce_email or f"bounce@{tenant.dkim_domain or tenant.smtp_host or 'localhost'}", item.email, msg_bytes)
        if not use_reuse:
            server.quit()
        else:
            if not hasattr(thread_local, "smtp_conns"):
                thread_local.smtp_conns = {}
            thread_local.smtp_conns[conn_key] = (server, time.monotonic())
                
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
        sender_domain = tenant.dkim_domain
        if not sender_domain and tenant.bounce_email and "@" in tenant.bounce_email:
            sender_domain = tenant.bounce_email.split("@")[-1]
        if not sender_domain:
            import socket
            sender_domain = socket.getfqdn()
        if not sender_domain or sender_domain == "localhost":
            sender_domain = "polypress.local"
        from_email = f"{tenant.mta_from_prefix or 'noreply'}@{sender_domain}"
        msg["From"] = f"{tenant.name} <{from_email}>"
        msg["To"] = item.email
        
        msg["X-PolyPress-Campaign"] = str(item.campaign_id)
        msg["X-PolyPress-Subscriber"] = str(item.subscriber_id)
        msg["X-PolyPress-QueueItem"] = str(item.id)
        msg["Return-Path"] = tenant.bounce_email or f"bounce@{sender_domain}"
        
        # Add Date and Message-ID headers to prevent spam flags
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=sender_domain)
        
        # List-Unsubscribe Header Extraction (RFC 8058), preserving signed query parameters
        match = re.search(r'https?://[^\s"\'<>]+/api/embed/unsubscribe/\d+/\d+(?:\?[^\s"\'<>]*)?', item.body_html or "")
        if match:
            msg["List-Unsubscribe"] = f"<{match.group(0)}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
            
        # Attach plain text part first (standard alternative ordering)
        plain_text = html_to_text(item.body_html)
        part_text = make_mime_text(plain_text, "plain")
        msg.attach(part_text)
        
        part_html = make_mime_text(item.body_html, "html")
        msg.attach(part_html)
        
        msg_bytes = msg.as_bytes(policy=SMTP)
        msg_bytes = generate_dkim_signature(msg_bytes, tenant)
        
        # Resolve HELO identity domain from cached GlobalSettings if set
        helo_domain = get_cached_global_settings().get("mail_server_identity") or sender_domain

        connected = False
        last_err = None
        for mx_host in mx_hosts:
            try:
                server = smtplib.SMTP(mx_host, 25, timeout=15.0)
                server.ehlo(helo_domain)
                if server.has_extn('STARTTLS'):
                    server.starttls()
                    server.ehlo(helo_domain)
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
        return True, "Sent successfully"
    else:
        logger.error(f"Transactional email failed to send to {to_email}: [{code}] {msg}")
        return False, f"[{code}] {msg}"


def send_transactional_email_by_tenant_id(to_email: str, subject: str, body_html: str, tenant_id: int):
    """Background-safe wrapper that opens its own DB session to load Tenant."""
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            logger.error(f"Transactional email skipped: Tenant ID {tenant_id} not found")
            return False, "Tenant not found"
        return send_transactional_email(to_email=to_email, subject=subject, body_html=body_html, tenant=tenant)
    finally:
        db.close()

from concurrent.futures import ThreadPoolExecutor

class TenantRateLimiter:
    def __init__(self, speed_limit_per_hour: int):
        self.speed_limit = speed_limit_per_hour
        self.tokens = 1.0
        self.last_update = time.time()

    def update_limit(self, speed_limit_per_hour: int):
        self.speed_limit = speed_limit_per_hour

    def consume(self) -> bool:
        if self.speed_limit <= 0:
            return True
        now = time.time()
        elapsed = now - self.last_update
        self.last_update = now
        # Add tokens: speed_limit / 3600 per second
        self.tokens = min(10.0, self.tokens + elapsed * (self.speed_limit / 3600.0))
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

active_threads_lock = threading.Lock()
active_threads = {}

domain_active_threads_lock = threading.Lock()
domain_active_threads = {}

SMTP_POOL_IDLE_SECONDS = 60.0

# Thread-local storage for persistent SMTP connection pooling
thread_local = threading.local()

def get_active_threads_for_tenant(tenant_id: int) -> int:
    with active_threads_lock:
        return active_threads.get(tenant_id, 0)

def get_active_threads_for_domain(domain: str) -> int:
    if not domain:
        return 0
    with domain_active_threads_lock:
        return domain_active_threads.get(domain.lower(), 0)

def _evict_idle_smtp_conns():
    if not hasattr(thread_local, "smtp_conns"):
        thread_local.smtp_conns = {}
        return
    now_mono = time.monotonic()
    stale_keys = [
        k for k, entry in thread_local.smtp_conns.items()
        if (now_mono - entry[1]) > SMTP_POOL_IDLE_SECONDS
    ]
    for k in stale_keys:
        entry = thread_local.smtp_conns.pop(k, None)
        if entry:
            try:
                entry[0].quit()
            except Exception:
                pass

def get_pooled_smtp(key: str, host: str, port: int, use_ssl: bool, use_tls: bool, username: str = None, password: str = None):
    _evict_idle_smtp_conns()

    entry = thread_local.smtp_conns.get(key)
    if entry is not None:
        server, _ = entry
        try:
            status = server.noop()
            if status[0] == 250:
                thread_local.smtp_conns[key] = (server, time.monotonic())
                return server
        except Exception:
            try:
                server.quit()
            except Exception:
                pass
            thread_local.smtp_conns.pop(key, None)
            
    if use_ssl:
        server = smtplib.SMTP_SSL(host, port, timeout=15.0)
    else:
        server = smtplib.SMTP(host, port, timeout=15.0)
        if use_tls:
            server.ehlo()
            server.starttls()
            server.ehlo()
            
    if username and password:
        server.login(username, password)
        
    thread_local.smtp_conns[key] = (server, time.monotonic())
    return server

def close_pooled_smtp(key: str):
    if hasattr(thread_local, "smtp_conns") and key in thread_local.smtp_conns:
        entry = thread_local.smtp_conns.pop(key, None)
        if entry:
            server = entry[0] if isinstance(entry, tuple) else entry
            try:
                server.quit()
            except Exception:
                pass

# Global Thread Pool Executor for concurrent sends (scales up to 200 workers)
executor = ThreadPoolExecutor(max_workers=200)
rate_limiters = {}

def _reconcile_campaign_status_atomic(db: Session, campaign_id: int, campaign_name: str = ""):
    """Transition campaign status cleanly using conditional SQL updates so paused/cancelled states are never overwritten."""
    pending_or_sending = db.query(QueueItem).filter(
        QueueItem.campaign_id == campaign_id,
        QueueItem.status.in_(["pending", "sending"])
    ).count()

    deferred_count = db.query(QueueItem).filter(
        QueueItem.campaign_id == campaign_id,
        QueueItem.status == "deferred"
    ).count()

    if pending_or_sending > 0:
        db.query(Campaign).filter(
            Campaign.id == campaign_id,
            Campaign.status == "flushing"
        ).update({Campaign.status: "sending"}, synchronize_session=False)
        db.commit()
    elif deferred_count > 0:
        changed = db.query(Campaign).filter(
            Campaign.id == campaign_id,
            Campaign.status == "sending"
        ).update({Campaign.status: "flushing"}, synchronize_session=False)
        db.commit()
        if changed:
            logger.info(f"Campaign '{campaign_name}' (ID: {campaign_id}) status updated to flushing ({deferred_count} deferred items remaining).")
    else:
        changed = db.query(Campaign).filter(
            Campaign.id == campaign_id,
            Campaign.status.in_(["sending", "flushing"])
        ).update({Campaign.status: "completed"}, synchronize_session=False)
        db.commit()
        if changed:
            logger.info(f"Campaign '{campaign_name}' (ID: {campaign_id}) finished dispatching all items (status: completed).")


def _run_scheduled_backup_sync():
    db = SessionLocal()
    try:
        from routes.backup_routes import perform_system_backup
        perform_system_backup(db)
    finally:
        db.close()


def deliver_item_task(
    item_id: int,
    pre_acquired: bool = False,
    pre_tenant_id: int = None,
    pre_domain: str = None,
):
    db = SessionLocal()
    item = None
    tenant_id = pre_tenant_id if pre_acquired else None
    dest_domain = pre_domain if pre_acquired else None
    acquired_tenant = bool(pre_acquired and pre_tenant_id is not None)
    acquired_domain = bool(pre_acquired and pre_domain)
    try:
        item = db.query(QueueItem).filter(QueueItem.id == item_id).first()
        if not item:
            return
        if not pre_acquired:
            tenant_id = item.tenant_id
            if tenant_id is not None:
                with active_threads_lock:
                    active_threads[tenant_id] = active_threads.get(tenant_id, 0) + 1
                acquired_tenant = True
            if item.email and "@" in item.email:
                dest_domain = item.email.split("@")[-1].lower()
                with domain_active_threads_lock:
                    domain_active_threads[dest_domain] = domain_active_threads.get(dest_domain, 0) + 1
                acquired_domain = True

        if item.status not in ["sending", "pending", "deferred"]:
            return

        tenant = db.query(Tenant).filter(Tenant.id == item.tenant_id).first()
        campaign = db.query(Campaign).filter(Campaign.id == item.campaign_id).first()
        subscriber = db.query(Subscriber).filter(Subscriber.id == item.subscriber_id).first()

        # Re-check live campaign status before dispatching over SMTP to prevent paused/cancelled race
        if campaign:
            if campaign.status == "paused":
                item.status = "pending"
                db.commit()
                return
            if campaign.status == "cancelled":
                db.delete(item)
                db.commit()
                return
            if campaign.status not in ["sending", "flushing", "automation"]:
                item.status = "pending"
                db.commit()
                return

        if not tenant or not campaign or not subscriber or subscriber.status not in ["active", "deferred"]:
            item.status = "failed"
            item.error_message = "Tenant, Campaign, or active/deferred Subscriber not found"
            item.error_code = 400
            db.commit()
            return
            
        # Send
        success = False
        if tenant.direct_send:
            success, is_transient, code, msg = send_direct_mta(item, tenant)
        else:
            success, is_transient, code, msg = send_external_smtp(item, tenant)
            
        # Increment attempts counter
        item.retries = (item.retries or 0) + 1
            
        # Update status
        if success:
            item.status = "sent"
            item.error_code = 250
            item.last_mx_response = "Sent successfully"
            db.query(Campaign).filter(Campaign.id == campaign.id).update(
                {Campaign.sent_count: func.coalesce(Campaign.sent_count, 0) + 1},
                synchronize_session=False,
            )
        else:
            item.error_code = code
            item.last_mx_response = msg
            item.error_message = msg
            
            if is_transient:
                item.status = "deferred"
                retry_mins = getattr(tenant, "retry_interval_minutes", 15) or 15
                item.next_attempt = datetime.utcnow() + timedelta(minutes=retry_mins)
            else:
                item.status = "failed"
                db.query(Campaign).filter(Campaign.id == campaign.id).update(
                    {
                        Campaign.failed_count: func.coalesce(Campaign.failed_count, 0) + 1,
                        Campaign.bounce_count: func.coalesce(Campaign.bounce_count, 0) + 1
                    },
                    synchronize_session=False,
                )
                
                subscriber.status = "bounced"
                subscriber.bounce_reason = f"[{code}] {msg}"
                subscriber.bounce_source_email = f"SMTP/MX: {item.email.split('@')[-1]}"
                
        db.commit()
        
        from engagement_service import trigger_engagement_recalc
        trigger_engagement_recalc(subscriber.id)
        
        # Dispatch Webhook Delivery notifications
        try:
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
        except Exception as webhook_err:
            logger.error(f"Failed to dispatch webhooks for item {item.id}: {webhook_err}")
            
        # Atomically reconcile campaign status only if still active in sending/flushing
        db.refresh(campaign)
        if campaign.status in ["sending", "flushing"]:
            _reconcile_campaign_status_atomic(db, campaign.id, campaign.name or "")
            
    except Exception as e:
        logger.exception(f"Error in deliver_item_task for QueueItem {item_id}: {e}")
    finally:
        if acquired_tenant and tenant_id is not None:
            with active_threads_lock:
                active_threads[tenant_id] = max(0, active_threads.get(tenant_id, 0) - 1)
        if acquired_domain and dest_domain:
            with domain_active_threads_lock:
                domain_active_threads[dest_domain] = max(0, domain_active_threads.get(dest_domain, 0) - 1)
        db.close()


async def process_queue():
    last_expiry_check = 0
    last_ntp_refresh = 0
    
    # Run Power Loss Recovery on startup
    db_recovery = SessionLocal()
    try:
        orphans = db_recovery.query(QueueItem).filter(QueueItem.status == "sending").all()
        if orphans:
            logger.info(f"Power Loss Recovery: Resetting {len(orphans)} orphaned QueueItems to pending status.")
            for o in orphans:
                o.status = "pending"
            db_recovery.commit()
    except Exception as e:
        logger.error(f"Failed running Power Loss Recovery check: {e}")
    finally:
        db_recovery.close()
        
    while True:
        db = SessionLocal()
        try:
            if time.time() - last_ntp_refresh > 300:
                last_ntp_refresh = time.time()
                await asyncio.to_thread(refresh_ntp_offset_if_needed)
            now = get_cached_corrected_time()
            
            # Check and evaluate A/B test campaigns whose test periods have elapsed
            try:
                ab_campaigns = db.query(Campaign).filter(
                    Campaign.ab_testing_enabled == True,
                    Campaign.ab_winning_variant == None,
                    Campaign.status.in_(["sending", "flushing"]),
                    Campaign.sent_at != None
                ).all()
                
                for ac in ab_campaigns:
                    eval_hours = ac.ab_test_hours if ac.ab_test_hours is not None else 24
                    eval_time = ac.sent_at + timedelta(hours=eval_hours)
                    if now >= eval_time:
                        logger.info(f"Evaluating A/B test campaign '{ac.name}' (ID: {ac.id}) after {eval_hours} hours...")
                        
                        best_variant = "A"
                        best_score = -1.0
                        
                        if ac.ab_variants:
                            for variant in ac.ab_variants:
                                vid = variant.get("id", "A")
                                opens = db.query(TrackingLog.subscriber_id).filter(
                                    TrackingLog.campaign_id == ac.id,
                                    TrackingLog.ab_variant == vid,
                                    TrackingLog.event_type == "open",
                                    real_tracking_filter(),
                                ).distinct().count()
                                
                                clicks = db.query(TrackingLog.subscriber_id).filter(
                                    TrackingLog.campaign_id == ac.id,
                                    TrackingLog.ab_variant == vid,
                                    TrackingLog.event_type == "click",
                                    real_tracking_filter(),
                                ).distinct().count()
                                
                                score = float(opens) if ac.ab_winner_criteria == "open_rate" else float(clicks)
                                logger.info(f"Variant '{vid}' scored {score} (opens: {opens}, clicks: {clicks})")
                                
                                if score > best_score:
                                    best_score = score
                                    best_variant = vid
                                    
                            ac.ab_winning_variant = best_variant
                            db.commit()
                            logger.info(f"Variant '{best_variant}' declared winner for campaign '{ac.name}'!")
                            
                            # Find winning variant config
                            winner = next((v for v in ac.ab_variants if v.get("id") == best_variant), None)
                            winner_subject = winner.get("subject") if winner else ac.subject
                            if winner and winner.get("is_custom_html"):
                                winner_body_html = winner.get("custom_html") or winner.get("body_html") or ""
                            else:
                                winner_body_html = winner.get("body_html") if winner else (ac.custom_html if (ac.is_custom_html and ac.custom_html) else (ac.body_html or ""))
                            winner_preheader = (winner.get("preheader") if winner else None) or (ac.preheader or "")
                            
                            # Find subscribers who already received a test email
                            sent_sub_ids = db.query(QueueItem.subscriber_id).filter(QueueItem.campaign_id == ac.id).all()
                            sent_sub_ids = {r[0] for r in sent_sub_ids}
                            
                            # Get all target subscribers for lists using unified targeting rules
                            target_lists = ac.list_ids or [ac.list_id] if (ac.list_ids or ac.list_id) else []
                            sub_query = db.query(Subscriber).filter(
                                Subscriber.list_id.in_(target_lists),
                                Subscriber.tenant_id == ac.tenant_id,
                                Subscriber.status.in_(["active", "deferred"])
                            )
                            sub_query = apply_targeting_rules_to_query(sub_query, ac.target_rules or {})
                            target_subscribers = sub_query.all()
                            
                            # De-duplicate
                            unique_subs = {}
                            for sub in target_subscribers:
                                if sub.email.lower() not in unique_subs:
                                    unique_subs[sub.email.lower()] = sub
                                    
                            remaining_subs = [s for s in unique_subs.values() if s.id not in sent_sub_ids]
                            
                            if remaining_subs:
                                effective_order = (getattr(ac, "send_order", None) or "inherit").strip().lower()
                                if effective_order == "inherit":
                                    tenant_obj = db.query(Tenant).filter(Tenant.id == ac.tenant_id).first()
                                    effective_order = (getattr(tenant_obj, "queue_send_order", None) or "default").strip().lower()
                                remaining_subs = order_subscribers_for_queue(remaining_subs, effective_order)

                                settings_snap = get_cached_global_settings()
                                tracking_domain = (settings_snap.get("public_url") or "").rstrip("/")
                                    
                                for sub in remaining_subs:
                                    body = render_email_template(
                                        body_html=winner_body_html,
                                        subscriber=sub,
                                        tracking_domain=tracking_domain,
                                        campaign_id=ac.id,
                                        subscriber_id=sub.id,
                                        preheader=winner_preheader,
                                    )
                                    
                                    item = QueueItem(
                                        tenant_id=ac.tenant_id,
                                        campaign_id=ac.id,
                                        subscriber_id=sub.id,
                                        email=sub.email,
                                        subject=winner_subject,
                                        body_html=body,
                                        status="pending",
                                        next_attempt=now,
                                        ab_variant=best_variant
                                    )
                                    db.add(item)
                                    
                                ac.total_recipients = (ac.total_recipients or 0) + len(remaining_subs)
                                db.commit()
                                logger.info(f"Queued winning variant '{best_variant}' for {len(remaining_subs)} remaining subscribers.")
            except Exception as ab_err:
                logger.error(f"Error evaluating A/B test campaigns: {ab_err}")

            # 0. Automatically start sending scheduled campaigns whose scheduled time has passed
            try:
                scheduled_campaigns = db.query(Campaign).filter(
                    Campaign.status == "scheduled",
                    Campaign.scheduled_send_at <= now
                ).all()
                for sc in scheduled_campaigns:
                    logger.info(f"NTP corrected clock triggered sending for scheduled campaign '{sc.name}' (scheduled at {sc.scheduled_send_at} UTC)")
                    sc.status = "sending"
                    sc.sent_at = now
                    db.commit()
            except Exception as se:
                logger.error(f"Error checking/promoting scheduled campaigns: {se}")
            
            # Reconcile campaign statuses atomically based on outbox queue items
            try:
                active_campaigns = db.query(Campaign).filter(
                    Campaign.status.in_(["sending", "flushing"])
                ).all()
                for camp in active_campaigns:
                    sent_items = db.query(QueueItem).filter(QueueItem.campaign_id == camp.id, QueueItem.status == "sent").count()
                    failed_items = db.query(QueueItem).filter(QueueItem.campaign_id == camp.id, QueueItem.status == "failed").count()
                    updates = {}
                    if sent_items > (camp.sent_count or 0):
                        updates[Campaign.sent_count] = sent_items
                    if failed_items > (camp.failed_count or 0):
                        updates[Campaign.failed_count] = failed_items
                    if updates:
                        db.query(Campaign).filter(Campaign.id == camp.id).update(updates, synchronize_session=False)
                        db.commit()

                    _reconcile_campaign_status_atomic(db, camp.id, camp.name or "")
            except Exception as rse:
                logger.error(f"Error reconciling campaign statuses: {rse}")
            
            # 1. Periodically check for expired queue items (once every 60 seconds)
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
                    
                    db.query(Campaign).filter(Campaign.id == exp_item.campaign_id).update(
                        {Campaign.failed_count: func.coalesce(Campaign.failed_count, 0) + 1},
                        synchronize_session=False,
                    )
                        
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
            
            # Evaluate automatic background backups without blocking the asyncio loop
            try:
                settings = db.query(GlobalSettings).first()
                if settings and settings.backup_interval_hours and settings.backup_interval_hours > 0:
                    last_backup = settings.last_backup_at
                    if not last_backup or (datetime.utcnow() - last_backup).total_seconds() >= settings.backup_interval_hours * 3600:
                        logger.info("Automatic backup schedule triggered.")
                        await asyncio.to_thread(_run_scheduled_backup_sync)
            except Exception as backup_err:
                logger.error(f"Error executing automatic scheduled backup: {backup_err}")
            
            # 2. Fetch active sending candidate batch ordered by QueueItem.id ASC to preserve send_order
            items = db.query(QueueItem).join(Campaign).filter(
                QueueItem.status.in_(["pending", "deferred"]),
                QueueItem.next_attempt <= now,
                Campaign.status.in_(["sending", "flushing", "automation"]) # Skip paused, draft, or completed campaigns
            ).order_by(QueueItem.id.asc()).limit(50).all()
            
            if not items:
                await asyncio.sleep(2)
                continue

            # Resolve global concurrency limits once per queue batch iteration
            global_settings = get_cached_global_settings()
            max_global_threads = global_settings.get("max_global_sending_threads", 50)
            max_domain_threads = global_settings.get("max_domain_sending_threads", 20)
                
            for item in items:
                # Re-verify campaign status is still active (protects against pause during batch loop)
                live_status = db.query(Campaign.status).filter(Campaign.id == item.campaign_id).scalar()
                if live_status not in ["sending", "flushing", "automation"]:
                    continue

                # Check overall program active thread limit
                with active_threads_lock:
                    total_active_threads = sum(active_threads.values())
                if total_active_threads >= max_global_threads:
                    break
                
                # Check destination domain active thread limit
                item_domain = item.email.split("@")[-1].lower() if (item and item.email and "@" in item.email) else ""
                if item_domain and get_active_threads_for_domain(item_domain) >= max_domain_threads:
                    continue
                
                # Resolve rate limiter for this tenant
                tenant_id = item.tenant_id
                
                # Check active thread footprint for this tenant against limit
                tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
                if tenant:
                    max_threads = tenant.max_sending_threads or 10
                    active = get_active_threads_for_tenant(tenant_id)
                    if active >= max_threads:
                        continue
                        
                if tenant_id not in rate_limiters:
                    limit = tenant.speed_emails_per_hour if tenant else 500
                    rate_limiters[tenant_id] = TenantRateLimiter(limit)
                else:
                    # Update limit dynamically if changed in DB
                    if tenant:
                        rate_limiters[tenant_id].update_limit(tenant.speed_emails_per_hour)
                        
                limiter = rate_limiters[tenant_id]
                if limiter.consume():
                    # Set status to sending to prevent multiple submission races
                    item.status = "sending"
                    db.commit()

                    # Pre-acquire thread counts before executor submission to eliminate burst overshoot
                    if tenant_id is not None:
                        with active_threads_lock:
                            active_threads[tenant_id] = active_threads.get(tenant_id, 0) + 1
                    if item_domain:
                        with domain_active_threads_lock:
                            domain_active_threads[item_domain] = domain_active_threads.get(item_domain, 0) + 1

                    try:
                        executor.submit(deliver_item_task, item.id, True, tenant_id, item_domain)
                    except Exception:
                        if tenant_id is not None:
                            with active_threads_lock:
                                active_threads[tenant_id] = max(0, active_threads.get(tenant_id, 0) - 1)
                        if item_domain:
                            with domain_active_threads_lock:
                                domain_active_threads[item_domain] = max(0, domain_active_threads.get(item_domain, 0) - 1)
                        raise
                
            await asyncio.sleep(0.1) # Sleep briefly to throttle loop queries
            
        except Exception as e:
            logger.exception(f"Error in process_queue loop: {e}")
            await asyncio.sleep(5)
        finally:
            db.close()

def start_sending_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(process_queue())
