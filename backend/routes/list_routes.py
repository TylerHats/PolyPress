import csv
import io
import json
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
import database as db_mod
from database import get_db, SubscriberList, Subscriber, User
import auth

router = APIRouter(prefix="/api/lists", tags=["lists"])

@router.get("")
def list_subscriber_lists(db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
    return db.query(SubscriberList).filter(SubscriberList.tenant_id == current_user.tenant_id).all()

@router.get("/{list_id}")
def get_subscriber_list(list_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
    sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == current_user.tenant_id).first()
    if not sub_list:
        raise HTTPException(status_code=404, detail="List not found")
    return sub_list

@router.post("")
def create_subscriber_list(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_write_access)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="List name required")
        
    sub_list = SubscriberList(
        tenant_id=current_user.tenant_id,
        name=name,
        description=payload.get("description"),
        custom_fields=payload.get("custom_fields", []),
        form_settings=payload.get("form_settings", {})
    )
    db.add(sub_list)
    db.commit()
    db.refresh(sub_list)
    return sub_list

@router.put("/{list_id}")
def update_subscriber_list(list_id: int, payload: dict, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_write_access)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == current_user.tenant_id).first()
    if not sub_list:
        raise HTTPException(status_code=404, detail="List not found")
        
    sub_list.name = payload.get("name", sub_list.name)
    sub_list.description = payload.get("description", sub_list.description)
    sub_list.custom_fields = payload.get("custom_fields", sub_list.custom_fields)
    sub_list.form_settings = payload.get("form_settings", sub_list.form_settings)
    
    db.commit()
    db.refresh(sub_list)
    return sub_list

@router.delete("/{list_id}")
def delete_subscriber_list(list_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_write_access)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
    sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == current_user.tenant_id).first()
    if not sub_list:
        raise HTTPException(status_code=404, detail="List not found")
        
    db.delete(sub_list)
    db.commit()
    return {"detail": "List deleted"}

# SUBSCRIBER ENDPOINTS

@router.get("/{list_id}/subscribers")
def list_subscribers(
    list_id: int, 
    page: int = 1, 
    limit: int = 50, 
    search: str = "", 
    status: str = "",
    engagement: int = None,
    tag: str = "",
    db: Session = Depends(get_db), 
    current_user: User = Depends(auth.get_current_user)
):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    # Verify list ownership
    sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == current_user.tenant_id).first()
    if not sub_list:
        raise HTTPException(status_code=404, detail="List not found")
        
    query = db.query(Subscriber).filter(Subscriber.list_id == list_id, Subscriber.tenant_id == current_user.tenant_id)
    if search:
        query = query.filter(
            (Subscriber.email.ilike(f"%{search}%")) | (Subscriber.name.ilike(f"%{search}%"))
        )
    if status:
        query = query.filter(Subscriber.status == status)
    if engagement is not None:
        query = query.filter(Subscriber.engagement_score == engagement)
    if tag:
        query = query.filter(Subscriber.tags.like(f'%"{tag}"%'))
        
    total = query.count()
    offset = (page - 1) * limit
    subscribers = query.order_by(Subscriber.created_at.desc()).offset(offset).limit(limit).all()
    
    return {"total": total, "page": page, "limit": limit, "subscribers": subscribers}

@router.post("/{list_id}/subscribers")
def add_subscriber(list_id: int, payload: dict, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_write_access)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == current_user.tenant_id).first()
    if not sub_list:
        raise HTTPException(status_code=404, detail="List not found")
        
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
        
    # Check if subscriber exists in this list
    existing = db.query(Subscriber).filter(
        Subscriber.list_id == list_id,
        Subscriber.email == email,
        Subscriber.tenant_id == current_user.tenant_id
    ).first()
    
    if existing:
        existing.name = payload.get("name", existing.name)
        existing.status = payload.get("status", "active")
        existing.custom_data = payload.get("custom_data", existing.custom_data)
        existing.tags = payload.get("tags", existing.tags)
        db.commit()
        db.refresh(existing)
        return existing
        
    subscriber = Subscriber(
        tenant_id=current_user.tenant_id,
        list_id=list_id,
        email=email,
        name=payload.get("name"),
        status=payload.get("status", "active"),
        custom_data=payload.get("custom_data", {}),
        tags=payload.get("tags", []),
        source_tag=payload.get("source_tag", "Manual Admin")
    )
    db.add(subscriber)
    db.commit()
    db.refresh(subscriber)
    return subscriber

@router.delete("/{list_id}/subscribers/{sub_id}")
def remove_subscriber(list_id: int, sub_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_write_access)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    subscriber = db.query(Subscriber).filter(
        Subscriber.id == sub_id,
        Subscriber.list_id == list_id,
        Subscriber.tenant_id == current_user.tenant_id
    ).first()
    
    if not subscriber:
        raise HTTPException(status_code=404, detail="Subscriber not found")
        
    db.delete(subscriber)
    db.commit()
    return {"detail": "Subscriber removed"}

# CSV PARSING & IMPORT

@router.post("/{list_id}/parse-headers")
async def parse_csv_headers(list_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_write_access)):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    # Check list ownership
    sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == current_user.tenant_id).first()
    if not sub_list:
        raise HTTPException(status_code=404, detail="List not found")
        
    contents = await file.read()
    decoded = contents.decode('utf-8', errors='ignore')
    reader = csv.reader(io.StringIO(decoded))
    
    try:
        headers = next(reader)
    except StopIteration:
        raise HTTPException(status_code=400, detail="CSV file is empty")
        
    return {"headers": [h.strip() for h in headers if h.strip()]}

@router.post("/{list_id}/import")
async def import_csv_subscribers(
    list_id: int,
    file: UploadFile = File(...),
    mapping: str = Form(...), # JSON mapping: {"email": "Email", "name": "Name", "custom_fields": {"city": "CityCol"}}
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.require_tenant_write_access)
):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="User not associated with a tenant")
        
    sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == current_user.tenant_id).first()
    if not sub_list:
        raise HTTPException(status_code=404, detail="List not found")
        
    try:
        mapping_dict = json.loads(mapping)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid mapping configuration format")
        
    email_col = mapping_dict.get("email")
    name_col = mapping_dict.get("name")
    custom_map = mapping_dict.get("custom_fields", {})
    
    if not email_col:
        raise HTTPException(status_code=400, detail="Email column mapping is required")
        
    contents = await file.read()
    decoded = contents.decode('utf-8', errors='ignore')
    reader = csv.DictReader(io.StringIO(decoded))
    
    imported_count = 0
    skipped_count = 0
    
    # Pre-fetch existing subscribers to avoid N+1 queries during matching
    existing_subs = {s.email.lower(): s for s in db.query(Subscriber).filter(
        Subscriber.list_id == list_id,
        Subscriber.tenant_id == current_user.tenant_id
    ).all()}
    
    for row in reader:
        # Resolve column names (handling whitespace)
        row_clean = {k.strip(): v.strip() for k, v in row.items() if k}
        
        email_val = row_clean.get(email_col)
        if not email_val or "@" not in email_val:
            skipped_count += 1
            continue
            
        email_key = email_val.strip().lower()
        name_val = row_clean.get(name_col) if name_col else None
        
        # Populate custom data
        custom_data = {}
        for db_key, csv_col in custom_map.items():
            if csv_col in row_clean:
                custom_data[db_key] = row_clean[csv_col]
                
        if email_key in existing_subs:
            sub = existing_subs[email_key]
            if name_val:
                sub.name = name_val
            sub.status = "active" # Reset status to active on re-import
            sub.custom_data.update(custom_data)
        else:
            sub = Subscriber(
                tenant_id=current_user.tenant_id,
                list_id=list_id,
                email=email_val.strip(),
                name=name_val,
                status="active",
                custom_data=custom_data,
                source_tag="CSV Import"
            )
            db.add(sub)
            existing_subs[email_key] = sub
            
        imported_count += 1
        # Flush every 100 rows
        if imported_count % 100 == 0:
            db.flush()
            
    db.commit()
    return {"imported": imported_count, "skipped": skipped_count}
