from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
import zoneinfo
import re
import urllib.parse
import database as db_mod
from database import get_db, Campaign, SubscriberList, Subscriber, QueueItem, User, TrackingLog, GlobalSettings
import auth

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])

def render_email_template(body_html: str, subscriber: Subscriber, tracking_domain: str, campaign_id: int, subscriber_id: int) -> str:
    rendered = body_html or ""
    rendered = rendered.replace("{{email}}", subscriber.email or "")
    rendered = rendered.replace("{{name}}", subscriber.name or "")
    
    # Custom attributes replacement
    if subscriber.custom_data:
        for k, v in subscriber.custom_data.items():
            rendered = rendered.replace(f"{{{{{k}}}}}", str(v or ""))
            
    # Strip any unresolved double curly brackets to avoid raw markup leaks
    rendered = re.sub(r'\{\{[a-zA-Z0-9_-]+\}\}', '', rendered)
    
    # Inject unsubscribe URL
    unsubscribe_url = f"{tracking_domain}/api/embed/unsubscribe/{subscriber.id}/{campaign_id}"
    rendered = rendered.replace("{{unsubscribe_url}}", unsubscribe_url)
    
    # Inject open tracking pixel
    open_pixel = f'<img src="{tracking_domain}/api/track/open/{campaign_id}/{subscriber_id}.gif" width="1" height="1" style="display:none;" />'
    if "</body>" in rendered:
        rendered = rendered.replace("</body>", f"{open_pixel}</body>")
    else:
        rendered += open_pixel
        
    # Rewrite links for click tracking
    def click_rewriter(match):
        url = match.group(2)
        if "api/embed/unsubscribe" in url or url.startswith("#") or url.startswith("mailto:") or url.startswith("tel:"):
            return match.group(0)
        encoded_url = urllib.parse.quote(url)
        redirect_url = f"{tracking_domain}/api/track/click/{campaign_id}/{subscriber_id}?url={encoded_url}"
        return f'{match.group(1)}"{redirect_url}"'
        
    rendered = re.sub(r'(href\s*=\s*)["\']([^"\']+)["\']', click_rewriter, rendered, flags=re.IGNORECASE)
    
    return rendered

@router.get("")
def list_campaigns(db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    # Scoped to current tenant
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User is not associated with a tenant")
    return db.query(Campaign).filter(Campaign.tenant_id == current_user.tenant_id).order_by(Campaign.created_at.desc()).all()

@router.get("/{campaign_id}")
def get_campaign(campaign_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign

@router.post("")
def create_campaign(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    list_id = payload.get("list_id")
    if not list_id:
        raise HTTPException(status_code=400, detail="Subscriber list ID required")
        
    sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == current_user.tenant_id).first()
    if not sub_list:
        raise HTTPException(status_code=404, detail="Subscriber list not found")
        
    campaign = Campaign(
        tenant_id=current_user.tenant_id,
        list_id=list_id,
        name=payload.get("name", "Untitled Campaign"),
        subject=payload.get("subject", "No Subject"),
        preheader=payload.get("preheader", ""),
        body_blocks=payload.get("body_blocks", []),
        body_html=payload.get("body_html", ""),
        target_rules=payload.get("target_rules", {}),
        status="draft"
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign

@router.put("/{campaign_id}")
def update_campaign(campaign_id: int, payload: dict, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    if campaign.status != "draft":
        raise HTTPException(status_code=400, detail="Cannot edit a campaign that has already been queued or sent")
        
    campaign.name = payload.get("name", campaign.name)
    campaign.subject = payload.get("subject", campaign.subject)
    campaign.preheader = payload.get("preheader", campaign.preheader)
    campaign.body_blocks = payload.get("body_blocks", campaign.body_blocks)
    campaign.body_html = payload.get("body_html", campaign.body_html)
    campaign.target_rules = payload.get("target_rules", campaign.target_rules)
    
    if "list_id" in payload:
        sub_list = db.query(SubscriberList).filter(SubscriberList.id == payload["list_id"], SubscriberList.tenant_id == current_user.tenant_id).first()
        if not sub_list:
            raise HTTPException(status_code=404, detail="Subscriber list not found")
        campaign.list_id = payload["list_id"]
        
    db.commit()
    db.refresh(campaign)
    return campaign

@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    db.delete(campaign)
    db.commit()
    return {"detail": "Campaign deleted"}

@router.post("/{campaign_id}/duplicate")
def duplicate_campaign(campaign_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    new_campaign = Campaign(
        tenant_id=current_user.tenant_id,
        list_id=campaign.list_id,
        name=f"Copy of {campaign.name}",
        subject=campaign.subject,
        preheader=campaign.preheader,
        body_blocks=campaign.body_blocks,
        body_html=campaign.body_html,
        status="draft"
    )
    db.add(new_campaign)
    db.commit()
    db.refresh(new_campaign)
    return new_campaign

@router.post("/{campaign_id}/launch")
def launch_campaign(campaign_id: int, request: Request, payload: dict = None, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    if campaign.status not in ["draft", "scheduled"]:
        raise HTTPException(status_code=400, detail="Campaign is already sending or sent")
        
    # Check if scheduling is specified in payload
    scheduled_time = None
    if payload and payload.get("scheduled_send_at"):
        try:
            # Parse localized date time using ZoneInfo
            raw_time = datetime.fromisoformat(payload["scheduled_send_at"].replace("Z", ""))
            tz_name = payload.get("timezone", "UTC")
            if raw_time.tzinfo is None:
                local_tz = zoneinfo.ZoneInfo(tz_name)
                raw_time = raw_time.replace(tzinfo=local_tz)
            scheduled_time = raw_time.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid scheduled date format: {e}")
            
    # Get subscribers matching list constraints and targeting rules
    query = db.query(Subscriber).filter(
        Subscriber.list_id == campaign.list_id,
        Subscriber.tenant_id == current_user.tenant_id,
        Subscriber.status.in_(["active", "deferred"])
    )
    
    rules = campaign.target_rules or {}
    if rules:
        target_tag = rules.get("tag")
        if target_tag:
            query = query.filter(Subscriber.tags.like(f'%"{target_tag}"%'))
            
        target_engagement = rules.get("engagement")
        if target_engagement is not None and target_engagement != "":
            query = query.filter(Subscriber.engagement_score == int(target_engagement))
            
        signup_after = rules.get("signup_after")
        if signup_after and str(signup_after).strip():
            try:
                dt = datetime.fromisoformat(str(signup_after).replace("Z", ""))
                query = query.filter(Subscriber.created_at >= dt)
            except Exception:
                pass
                
        signup_before = rules.get("signup_before")
        if signup_before and str(signup_before).strip():
            try:
                dt = datetime.fromisoformat(str(signup_before).replace("Z", ""))
                query = query.filter(Subscriber.created_at <= dt)
            except Exception:
                pass
                
    subscribers = query.all()
    
    if not subscribers:
        raise HTTPException(status_code=400, detail="Cannot send campaign to an empty list")
        
    settings = db.query(GlobalSettings).first()
    tracking_domain = settings.public_url if (settings and settings.public_url) else f"{request.base_url.scheme}://{request.base_url.netloc}"
    if tracking_domain:
        tracking_domain = tracking_domain.rstrip("/")
    
    # Clear any previous queue items if re-scheduling/updating
    db.query(QueueItem).filter(QueueItem.campaign_id == campaign.id).delete()
    
    # Create queue items
    queue_items = []
    for sub in subscribers:
        body = render_email_template(
            body_html=campaign.body_html,
            subscriber=sub,
            tracking_domain=tracking_domain,
            campaign_id=campaign.id,
            subscriber_id=sub.id
        )
        
        # next_attempt set to future scheduled time or now
        next_attempt = scheduled_time if scheduled_time else datetime.utcnow()
        
        item = QueueItem(
            tenant_id=current_user.tenant_id,
            campaign_id=campaign.id,
            subscriber_id=sub.id,
            email=sub.email,
            subject=campaign.subject,
            body_html=body,
            status="pending",
            next_attempt=next_attempt
        )
        db.add(item)
        queue_items.append(item)
        
    if scheduled_time:
        campaign.status = "scheduled"
        campaign.scheduled_send_at = scheduled_time
        campaign.total_recipients = len(queue_items)
        campaign.sent_at = None
        db.commit()
        return {"detail": f"Campaign scheduled successfully for {scheduled_time} UTC. {len(queue_items)} emails staged."}
    else:
        campaign.status = "sending"
        campaign.total_recipients = len(queue_items)
        campaign.sent_at = datetime.utcnow()
        campaign.scheduled_send_at = None
        db.commit()
        return {"detail": f"Campaign launched successfully. {len(queue_items)} emails queued."}

@router.get("/{campaign_id}/stats")
def get_campaign_stats(campaign_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    # Get detailed link clicks
    clicks = db.query(TrackingLog.link_url, func.count(TrackingLog.id).label("click_count")).filter(
        TrackingLog.campaign_id == campaign_id,
        TrackingLog.event_type == "click"
    ).group_by(TrackingLog.link_url).all()
    
    click_stats = [{"link": c.link_url, "clicks": c.click_count} for c in clicks]
    
    return {
        "id": campaign.id,
        "name": campaign.name,
        "subject": campaign.subject,
        "total_recipients": campaign.total_recipients,
        "sent": campaign.sent_count,
        "failed": campaign.failed_count,
        "bounces": campaign.bounce_count,
        "opens": campaign.open_count,
        "clicks": campaign.click_count,
        "click_stats": click_stats
    }

@router.get("/{campaign_id}/preview", response_class=HTMLResponse)
def preview_campaign(
    campaign_id: int, 
    request: Request,
    mock_name: str = "John Doe", 
    mock_email: str = "john@example.com", 
    token: str = Query(None),
    db: Session = Depends(get_db)
):
    user = None
    if token:
        try:
            import jwt
            from auth import SECRET_KEY, ALGORITHM
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            email = payload.get("sub")
            user = db.query(User).filter(User.email == email, User.is_active == True).first()
        except Exception:
            pass
            
    if not user:
        raise HTTPException(status_code=401, detail="Authentication token required")
        
    if not user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    # Create mock subscriber
    mock_sub = Subscriber(
        email=mock_email,
        name=mock_name,
        custom_data={"city": "Metropolis", "company": "Daily Planet"}
    )
    
    tracking_domain = f"{request.base_url.scheme}://{request.base_url.netloc}".rstrip("/")
    rendered = render_email_template(
        body_html=campaign.body_html,
        subscriber=mock_sub,
        tracking_domain=tracking_domain,
        campaign_id=campaign.id,
        subscriber_id=0
    )
    return HTMLResponse(content=rendered)

@router.post("/{campaign_id}/pause")
def pause_campaign(campaign_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    if campaign.status != "sending":
        raise HTTPException(status_code=400, detail="Only active sending campaigns can be paused")
        
    campaign.status = "paused"
    db.commit()
    return {"detail": "Campaign paused successfully."}

@router.post("/{campaign_id}/resume")
def resume_campaign(campaign_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    if campaign.status != "paused":
        raise HTTPException(status_code=400, detail="Only paused campaigns can be resumed")
        
    campaign.status = "sending"
    db.commit()
    return {"detail": "Campaign resumed successfully."}

@router.post("/{campaign_id}/cancel")
def cancel_campaign(campaign_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    if campaign.status not in ["sending", "paused", "queued", "scheduled"]:
        raise HTTPException(status_code=400, detail="Only queued, scheduled, paused, or sending campaigns can be cancelled")
        
    # Delete pending outbox items for this campaign
    db.query(QueueItem).filter(QueueItem.campaign_id == campaign.id, QueueItem.status == "pending").delete()
    
    campaign.status = "cancelled"
    db.commit()
    return {"detail": "Campaign broadcast cancelled successfully."}

@router.get("/{campaign_id}/click-map")
def get_campaign_click_map(campaign_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    from sqlalchemy import func
    clicks = db.query(
        TrackingLog.link_url,
        func.count(TrackingLog.id).label("click_count")
    ).filter(
        TrackingLog.campaign_id == campaign_id,
        TrackingLog.event_type == "click"
    ).group_by(TrackingLog.link_url).all()
    
    click_map = [{"url": c[0], "clicks": c[1]} for c in clicks if c[0]]
    total_opens = campaign.open_count or 1
    
    formatted_map = []
    for item in click_map:
        percentage = (item["clicks"] / total_opens) * 100
        formatted_map.append({
            "url": item["url"],
            "clicks": item["clicks"],
            "percentage": round(percentage, 1)
        })
        
    return {
        "campaign_id": campaign_id,
        "total_clicks": sum(item["clicks"] for item in click_map),
        "click_map": formatted_map,
        "body_html": campaign.body_html
    }

