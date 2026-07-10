import time
import email
from email.parser import BytesParser
import imaplib
import re
import logging
import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from database import SessionLocal, Tenant, Subscriber, Campaign

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bounce_worker")

def parse_bounce_report(msg_bytes: bytes):
    """
    Parses email bytes to extract PolyPress tracking headers, bounced recipient, diagnostic reasons.
    """
    msg = email.message_from_bytes(msg_bytes)
    
    campaign_id = None
    subscriber_id = None
    queue_item_id = None
    bounced_email = None
    diagnostic_code = None
    is_spam = False
    sender_email = msg.get("From", "Unknown Sender")
    
    # 1. Search headers of the bounce itself (sometimes headers are returned directly or parsed)
    # Check if this is a spam report (ARF - Abuse Report Format)
    for part in msg.walk():
        content_type = part.get_content_type()
        if content_type == "message/feedback-report":
            is_spam = True
            report_text = part.get_payload(decode=True)
            if report_text:
                report_str = report_text.decode('utf-8', errors='ignore')
                for line in report_str.split('\n'):
                    if line.lower().startswith('feedback-type:'):
                        if 'abuse' in line.lower():
                            is_spam = True
                            
        # Delivery status notifications can be multipart/report
        if content_type == "message/delivery-status":
            delivery_text = part.get_payload(decode=True)
            if delivery_text:
                delivery_str = delivery_text.decode('utf-8', errors='ignore')
                # Look for Failed-Recipients
                match_rec = re.search(r'Final-Recipient:\s*rfc822;\s*([^\s]+)', delivery_str, re.IGNORECASE)
                if match_rec:
                    bounced_email = match_rec.group(1).strip()
                # Look for Diagnostic-Code
                match_diag = re.search(r'Diagnostic-Code:\s*([^\n\r]+)', delivery_str, re.IGNORECASE)
                if match_diag:
                    diagnostic_code = match_diag.group(1).strip()
                    
        # Often the original message headers are attached as message/rfc822
        if content_type == "message/rfc822":
            orig_msg_bytes = part.get_payload()[0].as_bytes()
            orig_msg = email.message_from_bytes(orig_msg_bytes)
            campaign_id = orig_msg.get("X-PolyPress-Campaign")
            subscriber_id = orig_msg.get("X-PolyPress-Subscriber")
            queue_item_id = orig_msg.get("X-PolyPress-QueueItem")
            if not bounced_email:
                bounced_email = orig_msg.get("To")
                
    # 2. Fallback: Search the raw text of the bounce message for headers and recipient patterns
    raw_text = msg_bytes.decode('utf-8', errors='ignore')
    
    if not campaign_id:
        m = re.search(r'X-PolyPress-Campaign:\s*(\d+)', raw_text, re.IGNORECASE)
        if m:
            campaign_id = int(m.group(1))
            
    if not subscriber_id:
        m = re.search(r'X-PolyPress-Subscriber:\s*(\d+)', raw_text, re.IGNORECASE)
        if m:
            subscriber_id = int(m.group(1))
            
    if not queue_item_id:
        m = re.search(r'X-PolyPress-QueueItem:\s*(\d+)', raw_text, re.IGNORECASE)
        if m:
            queue_item_id = int(m.group(1))
            
    if not diagnostic_code:
        m = re.search(r'Diagnostic-Code:\s*([^\n\r]+)', raw_text, re.IGNORECASE)
        if m:
            diagnostic_code = m.group(1).strip()
            
    if not diagnostic_code:
        # Fallback diagnostic check for basic SMTP strings
        m = re.search(r'(\d{3}\s+[\d\.]+[\w\s:-]+)', raw_text)
        if m:
            diagnostic_code = m.group(1).strip()
            
    # Try parsing diagnostic codes or failed recipients from raw text if not found
    if not bounced_email:
        email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
        fail_matches = re.findall(rf'(?:failed|undeliverable|bounced|recipient|to)\s+<?({email_pattern})>?', raw_text, re.IGNORECASE)
        if fail_matches:
            bounced_email = fail_matches[0]

    return {
        "campaign_id": campaign_id,
        "subscriber_id": subscriber_id,
        "queue_item_id": queue_item_id,
        "bounced_email": bounced_email,
        "diagnostic_code": diagnostic_code or "No diagnostic code resolved in DSN.",
        "is_spam": is_spam,
        "sender_email": sender_email
    }

def process_tenant_bounces(db: Session, tenant: Tenant):
    if not tenant.imap_host or not tenant.imap_username or not tenant.imap_password:
        return
        
    logger.info(f"Checking bounces for tenant: {tenant.name} via IMAP {tenant.imap_host}")
    imap = None
    try:
        if tenant.imap_use_ssl:
            imap = imaplib.IMAP4_SSL(tenant.imap_host, tenant.imap_port or 993, timeout=15)
        else:
            imap = imaplib.IMAP4(tenant.imap_host, tenant.imap_port or 143, timeout=15)
            
        imap.login(tenant.imap_username.encode("utf-8"), tenant.imap_password.encode("utf-8"))
        imap.select("INBOX")
        
        status, messages = imap.search(None, "UNSEEN")
        if status != "OK":
            return
            
        msg_ids = messages[0].split()
        logger.info(f"Found {len(msg_ids)} unread bounce emails")
        
        for msg_id in msg_ids:
            try:
                res, data = imap.fetch(msg_id, "(RFC822)")
                if res != "OK":
                    continue
                    
                msg_bytes = data[0][1]
                bounce_info = parse_bounce_report(msg_bytes)
                
                # Locate subscriber
                subscriber = None
                if bounce_info["subscriber_id"]:
                    subscriber = db.query(Subscriber).filter(
                        Subscriber.id == bounce_info["subscriber_id"],
                        Subscriber.tenant_id == tenant.id
                    ).first()
                    
                if not subscriber and bounce_info["bounced_email"]:
                    subscriber = db.query(Subscriber).filter(
                        Subscriber.email == bounce_info["bounced_email"],
                        Subscriber.tenant_id == tenant.id
                    ).first()
                    
                if subscriber:
                    new_status = "spam" if bounce_info["is_spam"] else "bounced"
                    if subscriber.status != new_status:
                        subscriber.status = new_status
                        
                        # Store bounce reason and originating source
                        if bounce_info["is_spam"]:
                            subscriber.complaint_reason = bounce_info["diagnostic_code"]
                        else:
                            subscriber.bounce_reason = bounce_info["diagnostic_code"]
                        subscriber.bounce_source_email = bounce_info["sender_email"]
                        
                        logger.info(f"Updated subscriber {subscriber.email} to {new_status} (Reason: {bounce_info['diagnostic_code']})")
                        
                        # Increment campaign statistics if resolved
                        if bounce_info["campaign_id"]:
                            campaign = db.query(Campaign).filter(
                                Campaign.id == bounce_info["campaign_id"],
                                Campaign.tenant_id == tenant.id
                            ).first()
                            if campaign:
                                campaign.bounce_count = Campaign.bounce_count + 1
                                
                    db.commit()
                    
                    from webhook_dispatcher import trigger_webhook
                    trigger_webhook(tenant.id, f"subscriber.{new_status}", {
                        "id": subscriber.id,
                        "email": subscriber.email,
                        "name": subscriber.name,
                        "status": subscriber.status,
                        "reason": bounce_info["diagnostic_code"],
                        "source": bounce_info["sender_email"],
                        "campaign_id": bounce_info["campaign_id"]
                    })
                    
                if getattr(tenant, "imap_delete_processed", False):
                    imap.store(msg_id, "+FLAGS", "\\Deleted")
                else:
                    imap.store(msg_id, "+FLAGS", "\\Seen")
            except Exception as e:
                logger.error(f"Error processing IMAP message {msg_id}: {e}")
                
        if getattr(tenant, "imap_delete_processed", False):
            imap.expunge()
        imap.close()
    except Exception as e:
        logger.error(f"IMAP connection failed for tenant {tenant.name}: {e}")
    finally:
        if imap:
            try:
                imap.logout()
            except:
                pass

async def bounce_worker_loop():
    while True:
        db = SessionLocal()
        try:
            tenants = db.query(Tenant).all()
            for tenant in tenants:
                process_tenant_bounces(db, tenant)
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error in bounce worker loop: {e}")
        finally:
            db.close()
            
        await asyncio.sleep(300)

def start_bounce_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bounce_worker_loop())
