import time
import logging
import asyncio
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from email.charset import Charset, QP
import re
import socket
import dns.resolver
try:
    # pyrefly: ignore [missing-import]
    import dkim
except ImportError:
    dkim = None
from sqlalchemy.orm import Session
from database import SessionLocal, QueueItem, Campaign, Tenant, Subscriber, TrackingLog, GlobalSettings
from ntp_sync import get_corrected_time
from routes.campaign_routes import render_email_template

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
        
        # List-Unsubscribe Header Extraction (RFC 8058)
        match = re.search(r'https?://[^/]+/api/embed/unsubscribe/\d+/\d+', item.body_html)
        if match:
            msg["List-Unsubscribe"] = f"<{match.group(0)}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
            
        # Attach plain text part first (standard alternative ordering)
        plain_text = html_to_text(item.body_html)
        part_text = make_mime_text(plain_text, "plain")
        msg.attach(part_text)
        
        part_html = make_mime_text(item.body_html, "html")
        msg.attach(part_html)
        
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
        
        # List-Unsubscribe Header Extraction (RFC 8058)
        match = re.search(r'https?://[^/]+/api/embed/unsubscribe/\d+/\d+', item.body_html)
        if match:
            msg["List-Unsubscribe"] = f"<{match.group(0)}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
            
        # Attach plain text part first (standard alternative ordering)
        plain_text = html_to_text(item.body_html)
        part_text = make_mime_text(plain_text, "plain")
        msg.attach(part_text)
        
        part_html = make_mime_text(item.body_html, "html")
        msg.attach(part_html)
        
        msg_bytes = msg.as_bytes()
        msg_bytes = generate_dkim_signature(msg_bytes, tenant)
        
        # Resolve HELO identity domain from GlobalSettings if set
        helo_domain = sender_domain
        db = SessionLocal()
        try:
            from database import GlobalSettings
            settings = db.query(GlobalSettings).first()
            if settings and settings.mail_server_identity:
                helo_domain = settings.mail_server_identity
        except Exception as helo_err:
            logger.warning(f"Could not load mail_server_identity global setting: {helo_err}")
        finally:
            db.close()

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
    else:
        logger.error(f"Transactional email failed to send to {to_email}: [{code}] {msg}")
    return success

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

# Global Thread Pool Executor for concurrent sends
executor = ThreadPoolExecutor(max_workers=50)
rate_limiters = {}

def deliver_item_task(item_id: int):
    db = SessionLocal()
    try:
        item = db.query(QueueItem).filter(QueueItem.id == item_id).first()
        if not item:
            return
            
        tenant = db.query(Tenant).filter(Tenant.id == item.tenant_id).first()
        campaign = db.query(Campaign).filter(Campaign.id == item.campaign_id).first()
        subscriber = db.query(Subscriber).filter(Subscriber.id == item.subscriber_id).first()
        
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
            campaign.sent_count = Campaign.sent_count + 1
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
                campaign.failed_count = Campaign.failed_count + 1
                
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
            
        # Reconcile campaign status (bypass for automation campaigns)
        if campaign.status == "automation":
            return
            
        pending_or_sending = db.query(QueueItem).filter(
            QueueItem.campaign_id == campaign.id,
            QueueItem.status.in_(["pending", "sending"])
        ).count()
        
        deferred_count = db.query(QueueItem).filter(
            QueueItem.campaign_id == campaign.id,
            QueueItem.status == "deferred"
        ).count()
        
        if pending_or_sending > 0:
            if campaign.status != "sending":
                campaign.status = "sending"
                db.commit()
        else:
            if deferred_count > 0:
                if campaign.status != "flushing":
                    campaign.status = "flushing"
                    db.commit()
                    logger.info(f"Campaign '{campaign.name}' (ID: {campaign.id}) status updated to flushing ({deferred_count} deferred items remaining).")
            else:
                if campaign.status != "completed":
                    campaign.status = "completed"
                    db.commit()
                    logger.info(f"Campaign '{campaign.name}' (ID: {campaign.id}) finished dispatching all items (status: completed).")
            
    except Exception as e:
        logger.exception(f"Error in deliver_item_task for QueueItem {item_id}: {e}")
    finally:
        db.close()

async def process_queue():
    last_expiry_check = 0
    
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
            now = get_corrected_time()
            
            # Check and evaluate A/B test campaigns whose test periods have elapsed
            try:
                from datetime import timedelta
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
                                    TrackingLog.event_type == "open"
                                ).distinct().count()
                                
                                clicks = db.query(TrackingLog.subscriber_id).filter(
                                    TrackingLog.campaign_id == ac.id,
                                    TrackingLog.ab_variant == vid,
                                    TrackingLog.event_type == "click"
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
                            winner_body_html = winner.get("body_html") if winner else ac.body_html
                            
                            # Find subscribers who already received a test email
                            sent_sub_ids = db.query(QueueItem.subscriber_id).filter(QueueItem.campaign_id == ac.id).all()
                            sent_sub_ids = {r[0] for r in sent_sub_ids}
                            
                            # Get all target subscribers for lists
                            target_lists = ac.list_ids or [ac.list_id] if (ac.list_ids or ac.list_id) else []
                            sub_query = db.query(Subscriber).filter(
                                Subscriber.list_id.in_(target_lists),
                                Subscriber.tenant_id == ac.tenant_id,
                                Subscriber.status.in_(["active", "deferred"])
                            )
                            
                            # Evaluate targeting rules
                            rules = ac.target_rules or {}
                            if rules:
                                target_tag = rules.get("tag")
                                if target_tag:
                                    tags_list = [t.strip() for t in target_tag.split(",") if t.strip()]
                                    if tags_list:
                                        from sqlalchemy import or_
                                        tag_filters = [Subscriber.tags.like(f'%"{t}"%') for t in tags_list]
                                        sub_query = sub_query.filter(or_(*tag_filters))
                                    
                                target_engagements = rules.get("engagement")
                                if target_engagements:
                                    if isinstance(target_engagements, list):
                                        scores = [int(e) for e in target_engagements if str(e).isdigit()]
                                        if scores:
                                            sub_query = sub_query.filter(Subscriber.engagement_score.in_(scores))
                                    elif str(target_engagements).isdigit():
                                        sub_query = sub_query.filter(Subscriber.engagement_score == int(target_engagements))
                                    
                                signup_after = rules.get("signup_after")
                                if signup_after and str(signup_after).strip():
                                    try:
                                        dt = datetime.fromisoformat(str(signup_after).replace("Z", ""))
                                        sub_query = sub_query.filter(Subscriber.created_at >= dt)
                                    except Exception:
                                        pass
                                        
                                signup_before = rules.get("signup_before")
                                if signup_before and str(signup_before).strip():
                                    try:
                                        dt = datetime.fromisoformat(str(signup_before).replace("Z", ""))
                                        sub_query = sub_query.filter(Subscriber.created_at <= dt)
                                    except Exception:
                                        pass
                            
                            target_subscribers = sub_query.all()
                            
                            # De-duplicate
                            unique_subs = {}
                            for sub in target_subscribers:
                                if sub.email.lower() not in unique_subs:
                                    unique_subs[sub.email.lower()] = sub
                                    
                            remaining_subs = [s for s in unique_subs.values() if s.id not in sent_sub_ids]
                            
                            if remaining_subs:
                                settings = db.query(GlobalSettings).first()
                                tracking_domain = settings.public_url if (settings and settings.public_url) else ""
                                if tracking_domain:
                                    tracking_domain = tracking_domain.rstrip("/")
                                    
                                for sub in remaining_subs:
                                    body = render_email_template(
                                        body_html=winner_body_html,
                                        subscriber=sub,
                                        tracking_domain=tracking_domain,
                                        campaign_id=ac.id,
                                        subscriber_id=sub.id
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
                                    
                                ac.total_recipients += len(remaining_subs)
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
            
            # Reconcile campaign statuses based on outbox queue items
            try:
                active_campaigns = db.query(Campaign).filter(
                    Campaign.status.in_(["sending", "flushing"])
                ).all()
                for camp in active_campaigns:
                    pending_or_sending = db.query(QueueItem).filter(
                        QueueItem.campaign_id == camp.id,
                        QueueItem.status.in_(["pending", "sending"])
                    ).count()
                    
                    deferred_count = db.query(QueueItem).filter(
                        QueueItem.campaign_id == camp.id,
                        QueueItem.status == "deferred"
                    ).count()
                    
                    if pending_or_sending > 0:
                        if camp.status != "sending":
                            camp.status = "sending"
                            db.commit()
                    else:
                        # All emails have been sent once!
                        if deferred_count > 0:
                            if camp.status != "flushing":
                                camp.status = "flushing"
                                db.commit()
                                logger.info(f"Campaign '{camp.name}' status updated to flushing (has {deferred_count} deferred items left).")
                        else:
                            if camp.status != "completed":
                                camp.status = "completed"
                                db.commit()
                                logger.info(f"Campaign '{camp.name}' status updated to completed (all queue items processed/purged).")
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
                    
                    camp = db.query(Campaign).filter(Campaign.id == exp_item.campaign_id).first()
                    if camp:
                        camp.failed_count += 1
                        
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
            
            # 2. Fetch active sending candidate batch (up to 50 items)
            items = db.query(QueueItem).join(Campaign).filter(
                QueueItem.status.in_(["pending", "deferred"]),
                QueueItem.next_attempt <= now,
                Campaign.status.in_(["sending", "flushing", "automation"]) # Skip paused, draft, or completed campaigns
            ).order_by(QueueItem.created_at.asc()).limit(50).all()
            
            if not items:
                await asyncio.sleep(2)
                continue
                
            for item in items:
                # Resolve rate limiter for this tenant
                tenant_id = item.tenant_id
                if tenant_id not in rate_limiters:
                    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
                    limit = tenant.speed_emails_per_hour if tenant else 500
                    rate_limiters[tenant_id] = TenantRateLimiter(limit)
                else:
                    # Update limit dynamically if changed in DB
                    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
                    if tenant:
                        rate_limiters[tenant_id].update_limit(tenant.speed_emails_per_hour)
                        
                limiter = rate_limiters[tenant_id]
                if limiter.consume():
                    # Set status to sending to prevent multiple submission races
                    item.status = "sending"
                    db.commit()
                    
                    # Submit task to concurrent thread pool
                    executor.submit(deliver_item_task, item.id)
                
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
