import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db, get_history_db, User, Tenant, HistoricalMetric, Campaign, Subscriber
import auth

router = APIRouter(prefix="/api/reports", tags=["reports"])

@router.get("/history")
def get_history(
    tenant_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    history_db: Session = Depends(get_history_db),
    current_user: User = Depends(auth.get_current_user)
):
    # Context logic:
    if tenant_id is None:
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
