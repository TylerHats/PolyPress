from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import Response, RedirectResponse
from sqlalchemy.orm import Session
import database as db_mod
from database import get_db, Campaign, TrackingLog, Subscriber
from datetime import datetime

router = APIRouter(prefix="/api/track", tags=["tracking"])

# 1x1 transparent GIF binary representation
GIF_1X1 = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'

@router.get("/open/{campaign_id}/{subscriber_id}.gif")
def track_open(campaign_id: int, subscriber_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        # Resolve campaign and subscriber
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        subscriber = db.query(Subscriber).filter(Subscriber.id == subscriber_id).first()
        
        if campaign and subscriber:
            # Check for unique open
            existing_open = db.query(TrackingLog).filter(
                TrackingLog.campaign_id == campaign_id,
                TrackingLog.subscriber_id == subscriber_id,
                TrackingLog.event_type == "open"
            ).first()
            
            # Log open event
            log = TrackingLog(
                tenant_id=campaign.tenant_id,
                campaign_id=campaign_id,
                subscriber_id=subscriber_id,
                event_type="open",
                ip_address=request.client.host if request.client else None,
                headers=dict(request.headers)
            )
            
            # Note: We didn't define `headers` in DB TrackingLog, but let's save user_agent instead to match schema
            log.user_agent = request.headers.get("user-agent")
            db.add(log)
            
            if not existing_open:
                # Increment campaign unique opens
                campaign.open_count += 1
                
            db.commit()
            
            from webhook_dispatcher import trigger_webhook
            trigger_webhook(campaign.tenant_id, "email.open", {
                "campaign_id": campaign_id,
                "subscriber_id": subscriber_id,
                "email": subscriber.email
            })
            
            from engagement_service import trigger_engagement_recalc
            trigger_engagement_recalc(subscriber_id)
    except Exception as e:
        # Fail silently to avoid showing broken pixel image in email clients
        print(f"Tracking open error: {e}")
        
    return Response(
        content=GIF_1X1,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

@router.get("/click/{campaign_id}/{subscriber_id}")
def track_click(campaign_id: int, subscriber_id: int, url: str, request: Request, db: Session = Depends(get_db)):
    # Validate redirect scheme to prevent XSS / protocol manipulation
    import urllib.parse
    parsed_target = urllib.parse.urlparse(url)
    if parsed_target.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Invalid redirect scheme")
        
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        subscriber = db.query(Subscriber).filter(Subscriber.id == subscriber_id).first()
        
        if campaign and subscriber:
            # Log click event
            log = TrackingLog(
                tenant_id=campaign.tenant_id,
                campaign_id=campaign_id,
                subscriber_id=subscriber_id,
                event_type="click",
                link_url=url,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent")
            )
            db.add(log)
            
            # Check for unique click (on this specific URL)
            existing_click = db.query(TrackingLog).filter(
                TrackingLog.campaign_id == campaign_id,
                TrackingLog.subscriber_id == subscriber_id,
                TrackingLog.event_type == "click",
                TrackingLog.link_url == url,
                TrackingLog.id != log.id # ignore self
            ).first()
            
            # Increment total campaign click count if it is a unique link click by this subscriber
            if not existing_click:
                campaign.click_count += 1
                
            db.commit()
            
            from webhook_dispatcher import trigger_webhook
            trigger_webhook(campaign.tenant_id, "email.click", {
                "campaign_id": campaign_id,
                "subscriber_id": subscriber_id,
                "email": subscriber.email,
                "url": url
            })
            
            from engagement_service import trigger_engagement_recalc
            trigger_engagement_recalc(subscriber_id)
    except Exception as e:
        print(f"Tracking click error: {e}")
        
    return RedirectResponse(url=url)
