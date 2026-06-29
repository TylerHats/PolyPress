from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime
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
        body_blocks=payload.get("body_blocks", []),
        body_html=payload.get("body_html", ""),
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
    campaign.body_blocks = payload.get("body_blocks", campaign.body_blocks)
    campaign.body_html = payload.get("body_html", campaign.body_html)
    
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
        body_blocks=campaign.body_blocks,
        body_html=campaign.body_html,
        status="draft"
    )
    db.add(new_campaign)
    db.commit()
    db.refresh(new_campaign)
    return new_campaign

@router.post("/{campaign_id}/launch")
def launch_campaign(campaign_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    if campaign.status != "draft":
        raise HTTPException(status_code=400, detail="Campaign is already sent or sending")
        
    # Get subscribers
    subscribers = db.query(Subscriber).filter(
        Subscriber.list_id == campaign.list_id,
        Subscriber.tenant_id == current_user.tenant_id,
        Subscriber.status.in_(["active", "deferred"])
    ).all()
    
    if not subscribers:
        raise HTTPException(status_code=400, detail="Cannot send campaign to an empty list")
        
    settings = db.query(GlobalSettings).first()
    tracking_domain = settings.public_url if (settings and settings.public_url) else f"{request.base_url.scheme}://{request.base_url.netloc}"
    if tracking_domain:
        tracking_domain = tracking_domain.rstrip("/")
    
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
        
        item = QueueItem(
            tenant_id=current_user.tenant_id,
            campaign_id=campaign.id,
            subscriber_id=sub.id,
            email=sub.email,
            subject=campaign.subject,
            body_html=body,
            status="pending"
        )
        db.add(item)
        queue_items.append(item)
        
    campaign.status = "sending"
    campaign.total_recipients = len(queue_items)
    campaign.sent_at = datetime.utcnow()
    
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
    clicks = db.query(TrackingLog.link_url, db_mod.func.count(TrackingLog.id).label("click_count")).filter(
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
def preview_campaign(campaign_id: int, mock_name: str = "John Doe", mock_email: str = "john@example.com", db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == current_user.tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    # Create mock subscriber
    mock_sub = Subscriber(
        email=mock_email,
        name=mock_name,
        custom_data={"city": "Metropolis", "company": "Daily Planet"}
    )
    
    rendered = render_email_template(
        body_html=campaign.body_html,
        subscriber=mock_sub,
        tracking_domain="https://polypress.local",
        campaign_id=campaign.id,
        subscriber_id=0
    )
    return HTMLResponse(content=rendered)
