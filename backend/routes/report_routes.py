import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from database import get_db, get_history_db, User, Tenant, HistoricalMetric, Campaign, Subscriber, SubscriberList
import auth
from analytics_service import get_bulk_campaign_metrics, reconcile_campaign_counts_bulk

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/dashboard-summary")
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_user),
):
    """Single-query dashboard summary replacing serial list-loop and redundant campaign/report polling."""
    tenant_id = current_user.tenant_id
    if tenant_id is None and current_user.role != "super_admin":
        raise HTTPException(status_code=400, detail="User not associated with a tenant")

    # 1. Lists and per-list subscriber counts in 2 queries total
    list_query = db.query(SubscriberList)
    sub_count_query = db.query(
        Subscriber.list_id,
        Subscriber.status,
        func.count(Subscriber.id),
    )
    if tenant_id is not None:
        list_query = list_query.filter(SubscriberList.tenant_id == tenant_id)
        sub_count_query = sub_count_query.filter(Subscriber.tenant_id == tenant_id)

    lists = list_query.order_by(SubscriberList.created_at.desc()).all()
    grouped_counts = sub_count_query.group_by(Subscriber.list_id, Subscriber.status).all()

    per_list = {
        l.id: {
            "id": l.id,
            "tenant_id": l.tenant_id,
            "name": l.name,
            "description": l.description,
            "total_subscribers": 0,
            "active_subscribers": 0,
            "unsubscribed": 0,
            "bounced": 0,
            "pending": 0,
        }
        for l in lists
    }
    total_subs = 0
    active_subs = 0
    for lid, sub_status, cnt in grouped_counts:
        c_int = int(cnt or 0)
        total_subs += c_int
        if sub_status == "active":
            active_subs += c_int
        entry = per_list.get(lid)
        if entry:
            entry["total_subscribers"] += c_int
            if sub_status == "active":
                entry["active_subscribers"] += c_int
            elif sub_status == "unsubscribed":
                entry["unsubscribed"] += c_int
            elif sub_status == "bounced":
                entry["bounced"] += c_int
            elif sub_status == "pending":
                entry["pending"] += c_int

    # 2. Campaign metrics using unified real open/click calculations
    camp_query = db.query(Campaign)
    if tenant_id is not None:
        camp_query = camp_query.filter(Campaign.tenant_id == tenant_id)
    campaigns = camp_query.order_by(Campaign.created_at.desc()).all()
    metrics_map = reconcile_campaign_counts_bulk(db, campaigns)

    total_sent = 0
    total_opens = 0
    total_clicks = 0
    total_bounces = 0
    recent_campaigns = []
    campaigns_summary = []

    for idx, c in enumerate(campaigns):
        m = metrics_map.get(c.id, {})
        c_sent = m.get("sent", c.sent_count or 0)
        c_opens = m.get("opens", c.open_count or 0)
        c_clicks = m.get("clicks", c.click_count or 0)
        c_bounces = c.bounce_count or 0
        total_sent += c_sent
        total_opens += c_opens
        total_clicks += c_clicks
        total_bounces += c_bounces
        created_iso = c.created_at.isoformat() if c.created_at else None
        campaigns_summary.append({
            "id": c.id,
            "status": c.status,
            "created_at": created_iso,
            "sent_count": c_sent,
            "open_count": c_opens,
            "bounce_count": c_bounces,
        })
        if idx < 10:
            recent_campaigns.append({
                "id": c.id,
                "name": c.name,
                "subject": c.subject,
                "status": c.status,
                "total_recipients": c.total_recipients or 0,
                "sent_count": c_sent,
                "failed_count": m.get("failed", c.failed_count or 0),
                "bounce_count": c_bounces,
                "open_count": c_opens,
                "click_count": c_clicks,
                "unique_clicks": m.get("unique_clicks", 0),
                "created_at": created_iso,
                "sent_at": c.sent_at.isoformat() if c.sent_at else None,
            })

    return {
        "total_subscribers": total_subs,
        "active_subscribers": active_subs,
        "total_lists": len(lists),
        "total_campaigns": len(campaigns),
        "total_sent": total_sent,
        "total_opens": total_opens,
        "total_clicks": total_clicks,
        "total_bounces": total_bounces,
        "lists_summary": list(per_list.values()),
        "recent_campaigns": recent_campaigns,
        "campaigns_summary": campaigns_summary,
    }


@router.get("/history")
def get_history(
    tenant_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    history_db: Session = Depends(get_history_db),
    current_user: User = Depends(auth.get_current_user)
):
    # Prevent cross-tenant IDOR on historical metrics
    if tenant_id is not None:
        if current_user.role != "super_admin":
            allowed = set(current_user.allowed_tenants or [])
            if tenant_id != current_user.tenant_id and tenant_id not in allowed:
                raise HTTPException(status_code=403, detail="Access denied to requested tenant reports")
    else:
        if current_user.role != "super_admin":
            if not current_user.tenant_id:
                raise HTTPException(status_code=403, detail="Access denied to global reports")
            tenant_id = current_user.tenant_id
            
    query = history_db.query(HistoricalMetric)
    if tenant_id is not None:
        query = query.filter(HistoricalMetric.tenant_id == tenant_id)
    else:
        query = query.filter(HistoricalMetric.tenant_id == None)
        
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", ""))
            query = query.filter(HistoricalMetric.recorded_at >= start_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format. Use ISO format.")
            
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", ""))
            if len(end_date.strip()) <= 10 or (end_dt.hour == 0 and end_dt.minute == 0 and end_dt.second == 0):
                end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            query = query.filter(HistoricalMetric.recorded_at <= end_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format. Use ISO format.")
            
    metrics = query.order_by(HistoricalMetric.recorded_at.asc()).all()
    return metrics

@router.get("/settings")
def get_report_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_user)
):
    # Return retention settings for the current active context
    if current_user.tenant_id is None:
        from database import GlobalSettings
        settings = db.query(GlobalSettings).first()
        return {
            "retention_days": settings.history_retention_days if settings else 30,
            "frequency_hours": settings.history_record_frequency_hours if settings else 24
        }
    else:
        tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
        return {
            "retention_days": tenant.history_retention_days if tenant else 30,
            "frequency_hours": tenant.history_record_frequency_hours if tenant else 24
        }

@router.post("/settings")
def update_report_settings(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.require_tenant_admin)
):
    retention_days = payload.get("retention_days")
    frequency_hours = payload.get("frequency_hours")
    
    if retention_days is not None and not isinstance(retention_days, int):
        raise HTTPException(status_code=400, detail="retention_days must be an integer")
    if frequency_hours is not None and not isinstance(frequency_hours, int):
        raise HTTPException(status_code=400, detail="frequency_hours must be an integer")
        
    if current_user.tenant_id is None:
        if current_user.role != "super_admin":
            raise HTTPException(status_code=403, detail="Permission denied")
        from database import GlobalSettings
        settings = db.query(GlobalSettings).first()
        if not settings:
            raise HTTPException(status_code=404, detail="Settings not found")
        if retention_days is not None:
            settings.history_retention_days = retention_days
        if frequency_hours is not None:
            settings.history_record_frequency_hours = frequency_hours
        db.commit()
        return {"status": "success", "settings": {
            "retention_days": settings.history_retention_days,
            "frequency_hours": settings.history_record_frequency_hours
        }}
    else:
        from database import GlobalSettings
        global_settings = db.query(GlobalSettings).first()
        global_ret = global_settings.history_retention_days if global_settings else 30
        global_freq = global_settings.history_record_frequency_hours if global_settings else 24
        
        tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
            
        if retention_days is not None:
            # Must be equal or lower than global
            if retention_days > global_ret:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Retention time cannot exceed system-wide maximum retention of {global_ret} days"
                )
            tenant.history_retention_days = retention_days
            
        if frequency_hours is not None:
            # Must be equal or higher than global (slower frequency is okay, faster is not)
            if frequency_hours < global_freq:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Recording frequency cannot be faster than system-wide minimum frequency of {global_freq} hours"
                )
            tenant.history_record_frequency_hours = frequency_hours
            
        db.commit()
        return {"status": "success", "settings": {
            "retention_days": tenant.history_retention_days,
            "frequency_hours": tenant.history_record_frequency_hours
        }}

@router.post("/record-snapshot")
def force_record_snapshot(
    db: Session = Depends(get_db),
    history_db: Session = Depends(get_history_db),
    current_user: User = Depends(auth.require_tenant_admin)
):
    now = datetime.utcnow()

    def _compute_tenant_totals(camp_list):
        if not camp_list:
            return 0, 0, 0, 0
        metrics_map = get_bulk_campaign_metrics(db, [c.id for c in camp_list])
        sent_t = sum(max(metrics_map.get(c.id, {}).get("sent", 0), c.sent_count or 0) for c in camp_list)
        opens_t = sum(metrics_map.get(c.id, {}).get("opens", 0) for c in camp_list)
        clicks_t = sum(metrics_map.get(c.id, {}).get("clicks", 0) for c in camp_list)
        bounces_t = sum((c.bounce_count or 0) for c in camp_list)
        return sent_t, opens_t, clicks_t, bounces_t
    
    if current_user.tenant_id is None:
        if current_user.role != "super_admin":
            raise HTTPException(status_code=403, detail="Permission denied")
            
        sub_count = db.query(Subscriber).filter(Subscriber.status == "active").count()
        campaigns = db.query(Campaign).all()
        sent, opens, clicks, bounces = _compute_tenant_totals(campaigns)
        
        metric = HistoricalMetric(
            tenant_id=None,
            recorded_at=now,
            subscriber_count=sub_count,
            emails_sent=sent,
            email_opens=opens,
            link_clicks=clicks,
            bounces=bounces
        )
        history_db.add(metric)
        
        tenants = db.query(Tenant).all()
        for tenant in tenants:
            t_sub_count = db.query(Subscriber).filter(Subscriber.tenant_id == tenant.id, Subscriber.status == "active").count()
            t_campaigns = db.query(Campaign).filter(Campaign.tenant_id == tenant.id).all()
            t_sent, t_opens, t_clicks, t_bounces = _compute_tenant_totals(t_campaigns)
            
            t_metric = HistoricalMetric(
                tenant_id=tenant.id,
                recorded_at=now,
                subscriber_count=t_sub_count,
                emails_sent=t_sent,
                email_opens=t_opens,
                link_clicks=t_clicks,
                bounces=t_bounces
            )
            history_db.add(t_metric)
            
        history_db.commit()
        return {"status": "success", "message": "Global and all workspace snapshots recorded successfully."}
        
    else:
        tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
            
        sub_count = db.query(Subscriber).filter(Subscriber.tenant_id == tenant.id, Subscriber.status == "active").count()
        campaigns = db.query(Campaign).filter(Campaign.tenant_id == tenant.id).all()
        sent, opens, clicks, bounces = _compute_tenant_totals(campaigns)
        
        metric = HistoricalMetric(
            tenant_id=tenant.id,
            recorded_at=now,
            subscriber_count=sub_count,
            emails_sent=sent,
            email_opens=opens,
            link_clicks=clicks,
            bounces=bounces
        )
        history_db.add(metric)
        history_db.commit()
        return {"status": "success", "message": f"Snapshot recorded successfully for workspace: {tenant.name}."}
