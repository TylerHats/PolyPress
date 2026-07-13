from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from datetime import datetime

from database import get_db, AutomationFlow, AutomationLog, AutomationState, User
import auth

router = APIRouter(prefix="/api/automations", tags=["automations"])

@router.get("")
def list_automations(db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        if current_user.role == "super_admin":
            flows = db.query(AutomationFlow).order_by(AutomationFlow.created_at.desc()).all()
            return flows
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
    
    flows = db.query(AutomationFlow).filter(AutomationFlow.tenant_id == current_user.tenant_id).order_by(AutomationFlow.created_at.desc()).all()
    return flows

@router.post("")
def create_automation(payload: dict = Body(...), db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_write_access)):
    tenant_id = current_user.tenant_id
    if not tenant_id:
        if current_user.role == "super_admin":
            # Default to first tenant if admin is creating a flow
            from database import Tenant
            first_t = db.query(Tenant).first()
            if not first_t:
                raise HTTPException(status_code=400, detail="No tenants configured. Super admin must create a tenant first.")
            tenant_id = first_t.id
        else:
            raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    name = payload.get("name", "New Flow")
    description = payload.get("description", "")
    flow_data = payload.get("flow_data", {"nodes": []})
    
    flow = AutomationFlow(
        tenant_id=tenant_id,
        name=name,
        description=description,
        flow_data=flow_data,
        is_active=False
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return flow

@router.get("/{flow_id}")
def get_automation(flow_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id and current_user.role != "super_admin":
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    query = db.query(AutomationFlow).filter(AutomationFlow.id == flow_id)
    if current_user.tenant_id:
        query = query.filter(AutomationFlow.tenant_id == current_user.tenant_id)
    flow = query.first()
    
    if not flow:
        raise HTTPException(status_code=404, detail="Automation flow not found")
        
    return flow

@router.put("/{flow_id}")
def update_automation(flow_id: int, payload: dict = Body(...), db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_write_access)):
    if not current_user.tenant_id and current_user.role != "super_admin":
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    query = db.query(AutomationFlow).filter(AutomationFlow.id == flow_id)
    if current_user.tenant_id:
        query = query.filter(AutomationFlow.tenant_id == current_user.tenant_id)
    flow = query.first()
    
    if not flow:
        raise HTTPException(status_code=404, detail="Automation flow not found")
        
    flow.name = payload.get("name", flow.name)
    flow.description = payload.get("description", flow.description)
    flow.flow_data = payload.get("flow_data", flow.flow_data)
    flow.is_active = payload.get("is_active", flow.is_active)
    flow.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(flow)
    return flow

@router.delete("/{flow_id}")
def delete_automation(flow_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_write_access)):
    if not current_user.tenant_id and current_user.role != "super_admin":
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    query = db.query(AutomationFlow).filter(AutomationFlow.id == flow_id)
    if current_user.tenant_id:
        query = query.filter(AutomationFlow.tenant_id == current_user.tenant_id)
    flow = query.first()
    
    if not flow:
        raise HTTPException(status_code=404, detail="Automation flow not found")
        
    db.delete(flow)
    db.commit()
    return {"detail": "Automation flow deleted successfully"}

@router.get("/{flow_id}/logs")
def get_automation_logs(flow_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id and current_user.role != "super_admin":
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    query = db.query(AutomationFlow).filter(AutomationFlow.id == flow_id)
    if current_user.tenant_id:
        query = query.filter(AutomationFlow.tenant_id == current_user.tenant_id)
    flow = query.first()
    
    if not flow:
        raise HTTPException(status_code=404, detail="Automation flow not found")
        
    log_query = db.query(AutomationLog).filter(AutomationLog.flow_id == flow_id)
    if current_user.tenant_id:
        log_query = log_query.filter(AutomationLog.tenant_id == current_user.tenant_id)
    logs = log_query.order_by(AutomationLog.created_at.desc()).limit(100).all()
    
    # Return formatted logs list
    result = []
    for log in logs:
        sub_email = "Unknown"
        if log.subscriber:
            sub_email = log.subscriber.email
            
        result.append({
            "id": log.id,
            "subscriber_email": sub_email,
            "node_id": log.node_id,
            "node_type": log.node_type,
            "action_taken": log.action_taken,
            "details": log.details,
            "created_at": log.created_at
        })
        
    return result
