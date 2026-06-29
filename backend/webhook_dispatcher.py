import requests
import hmac
import hashlib
import json
from datetime import datetime
from sqlalchemy.orm import Session
from database import SessionLocal, WebhookSubscription
import logging
from threading import Thread

logger = logging.getLogger("webhook_dispatcher")

def send_webhook_request(url: str, secret: str, event_type: str, payload: dict):
    try:
        body_dict = {
            "event": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": payload
        }
        body = json.dumps(body_dict)
        
        # Calculate HMAC SHA256 signature
        signature = hmac.new(
            secret.encode('utf-8'),
            body.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        headers = {
            "Content-Type": "application/json",
            "X-PolyPress-Signature": signature,
            "User-Agent": "PolyPress-Webhook-Dispatcher/1.0"
        }
        
        res = requests.post(url, data=body, headers=headers, timeout=5.0)
        logger.info(f"Webhook {event_type} dispatched to {url} - Response Code: {res.status_code}")
    except Exception as e:
        logger.error(f"Webhook delivery failed for {url}: {e}")

def trigger_webhook(tenant_id: int, event_type: str, payload: dict):
    db = SessionLocal()
    try:
        subscriptions = db.query(WebhookSubscription).filter(
            WebhookSubscription.tenant_id == tenant_id,
            WebhookSubscription.active == True
        ).all()
        
        for sub in subscriptions:
            # Check if subscribed to specific event or wildcard '*'
            if event_type in sub.events or "*" in sub.events:
                # Dispatch asynchronously on separate background thread to avoid HTTP thread lag
                t = Thread(target=send_webhook_request, args=(sub.url, sub.secret, event_type, payload))
                t.start()
    except Exception as e:
        logger.error(f"Error resolving webhooks for tenant {tenant_id}: {e}")
    finally:
        db.close()
