import csv
import io
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Body
from sqlalchemy.orm import Session
import database as db_mod
from database import get_db, SubscriberList, Subscriber, User
import auth

router = APIRouter(prefix="/api/lists", tags=["lists"])

@router.get("")
def list_subscriber_lists(db: Session = Depends(get_db), current_user: User = Depends(auth.get_current_user)):
    if not current_user.tenant_id:
        if current_user.role == "super_admin":
            return db.query(SubscriberList).all()
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
        custom_fields=payload.get("custom_fields") if payload.get("custom_fields") is not None else [{
            "key": "name",
            "label": "Name",
            "type": "text",
            "required": False,
            "show_on_form": True,
            "form_order": 1
        }],
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
    if current_user.role == "super_admin":
        sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id).first()
    else:
        if not current_user.tenant_id:
            raise HTTPException(status_code=400, detail="User not associated with a tenant")
        sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == current_user.tenant_id).first()
        
    if not sub_list:
        raise HTTPException(status_code=404, detail="List not found")
        
    if current_user.role == "super_admin":
        query = db.query(Subscriber).filter(Subscriber.list_id == list_id)
    else:
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
    if current_user.role == "super_admin":
        sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id).first()
    else:
        if not current_user.tenant_id:
            raise HTTPException(status_code=400, detail="User not associated with a tenant")
        sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == current_user.tenant_id).first()
        
    if not sub_list:
        raise HTTPException(status_code=404, detail="List not found")
        
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
        
    # Check if subscriber exists in this list
    if current_user.role == "super_admin":
        existing = db.query(Subscriber).filter(
            Subscriber.list_id == list_id,
            Subscriber.email == email
        ).first()
    else:
        existing = db.query(Subscriber).filter(
            Subscriber.list_id == list_id,
            Subscriber.email == email,
            Subscriber.tenant_id == current_user.tenant_id
        ).first()
    
    if existing:
        old_status = existing.status
        existing.name = payload.get("name", existing.name)
        existing.status = payload.get("status", "active")
        existing.custom_data = payload.get("custom_data", existing.custom_data)
        existing.tags = payload.get("tags", existing.tags)
        db.commit()
        db.refresh(existing)
        
        if existing.status == "active" and old_status != "active":
            from automation_worker import trigger_automation_on_list_join
            trigger_automation_on_list_join(db, existing, list_id)
            
        return existing
        
    subscriber = Subscriber(
        tenant_id=sub_list.tenant_id,
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
    
    if subscriber.status == "active":
        from automation_worker import trigger_automation_on_list_join
        trigger_automation_on_list_join(db, subscriber, list_id)
        
    return subscriber

@router.delete("/{list_id}/subscribers/{sub_id}")
def remove_subscriber(list_id: int, sub_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_write_access)):
    if current_user.role == "super_admin":
        subscriber = db.query(Subscriber).filter(
            Subscriber.id == sub_id,
            Subscriber.list_id == list_id
        ).first()
    else:
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

def detect_delimiter(sample_text: str) -> str:
    if not sample_text:
        return ","
    first_line = sample_text.split('\n')[0]
    counts = {
        ",": first_line.count(","),
        ";": first_line.count(";"),
        "\t": first_line.count("\t"),
        "|": first_line.count("|")
    }
    best_delim = ","
    max_count = 0
    for delim, count in counts.items():
        if count > max_count:
            max_count = count
            best_delim = delim
    return best_delim

def parse_status_value(raw_val: str, status_mappings: dict = None) -> str:
    if not raw_val:
        return "active"
    val_lower = raw_val.strip().lower()
    
    # Check custom mappings
    if status_mappings:
        for k, v in status_mappings.items():
            if k.strip().lower() == val_lower:
                v_clean = v.strip().lower()
                if v_clean in ["active", "unsubscribed", "pending", "bounced", "complained", "spam"]:
                    return "spam" if v_clean in ("complained", "spam") else v_clean
                    
    # Default fallback mappings
    if val_lower in ["active", "opt-in", "optin", "yes", "subscribe", "subscribed", "true", "1"]:
        return "active"
    if val_lower in ["pending", "confirm", "unconfirmed", "double opt-in", "opt-in-pending"]:
        return "pending"
    if val_lower in ["unsubscribed", "opt-out", "optout", "no", "unsubscribe", "false", "0", "complained", "bounced", "spam"]:
        if val_lower in ["complained", "spam"]:
            return "spam"
        if val_lower == "bounced":
            return "bounced"
        return "unsubscribed"
        
    return "active"

# CSV PARSING & IMPORT

@router.post("/{list_id}/parse-headers")
async def parse_csv_headers(list_id: int, file: UploadFile = File(...), delimiter: str = None, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_write_access)):
    if current_user.role == "super_admin":
        sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id).first()
    else:
        if not current_user.tenant_id:
            raise HTTPException(status_code=400, detail="User not associated with a tenant")
        sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == current_user.tenant_id).first()
        
    if not sub_list:
        raise HTTPException(status_code=404, detail="List not found")
        
    contents = await file.read()
    decoded = contents.decode('utf-8', errors='ignore')
    
    # Resolve custom delimiter
    if delimiter in ["comma", ","]:
        delim = ","
    elif delimiter in ["semicolon", ";"]:
        delim = ";"
    elif delimiter in ["tab", "\t"]:
        delim = "\t"
    elif delimiter in ["bar", "|"]:
        delim = "|"
    else:
        delim = detect_delimiter(decoded)
        
    reader = csv.reader(io.StringIO(decoded), delimiter=delim)
    
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
    delimiter: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.require_tenant_write_access)
):
    if current_user.role == "super_admin":
        sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id).first()
    else:
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
    status_col = mapping_dict.get("status")
    status_mappings = mapping_dict.get("status_mappings", {})
    custom_map = mapping_dict.get("custom_fields", {})
    
    if not email_col:
        raise HTTPException(status_code=400, detail="Email column mapping is required")
        
    contents = await file.read()
    decoded = contents.decode('utf-8', errors='ignore')
    
    # Resolve custom delimiter
    if delimiter in ["comma", ","]:
        delim = ","
    elif delimiter in ["semicolon", ";"]:
        delim = ";"
    elif delimiter in ["tab", "\t"]:
        delim = "\t"
    elif delimiter in ["bar", "|"]:
        delim = "|"
    else:
        delim = detect_delimiter(decoded)
        
    reader = csv.DictReader(io.StringIO(decoded), delimiter=delim)
    
    imported_count = 0
    skipped_count = 0
    
    # Pre-fetch existing subscribers to avoid N+1 queries during matching
    if current_user.role == "super_admin":
        existing_subs = {s.email.lower(): s for s in db.query(Subscriber).filter(
            Subscriber.list_id == list_id
        ).all()}
    else:
        existing_subs = {s.email.lower(): s for s in db.query(Subscriber).filter(
            Subscriber.list_id == list_id,
            Subscriber.tenant_id == current_user.tenant_id
        ).all()}
    
    new_actives = []
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
                
        # Parse status dynamically
        status_val = "active"
        if status_col and status_col in row_clean:
            status_val = parse_status_value(row_clean[status_col], status_mappings)
            
        if email_key in existing_subs:
            sub = existing_subs[email_key]
            old_status = sub.status
            if name_val:
                sub.name = name_val
            sub.status = status_val
            sub.custom_data.update(custom_data)
            if old_status != "active" and status_val == "active":
                new_actives.append(sub)
        else:
            sub = Subscriber(
                tenant_id=sub_list.tenant_id,
                list_id=list_id,
                email=email_val.strip(),
                name=name_val,
                status=status_val,
                custom_data=custom_data,
                source_tag="CSV Import",
                created_at=datetime.utcnow()
            )
            db.add(sub)
            existing_subs[email_key] = sub
            if status_val == "active":
                new_actives.append(sub)
            
        imported_count += 1
        # Flush every 100 rows
        if imported_count % 100 == 0:
            db.flush()
            
    db.commit()
    
    # Trigger automation list join flows
    from automation_worker import trigger_automation_on_list_join
    for active_sub in new_actives:
        trigger_automation_on_list_join(db, active_sub, list_id)
        
    return {"imported": imported_count, "skipped": skipped_count}

@router.get("/{list_id}/subscribers/{sub_id}/activity")
def get_subscriber_activity(
    list_id: int,
    sub_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_user)
):
    if current_user.role == "super_admin":
        subscriber = db.query(Subscriber).filter(
            Subscriber.id == sub_id,
            Subscriber.list_id == list_id
        ).first()
    else:
        if not current_user.tenant_id:
            raise HTTPException(status_code=400, detail="User not associated with a tenant")
        subscriber = db.query(Subscriber).filter(
            Subscriber.id == sub_id,
            Subscriber.list_id == list_id,
            Subscriber.tenant_id == current_user.tenant_id
        ).first()
        
    if not subscriber:
        raise HTTPException(status_code=404, detail="Subscriber not found")
        
    from database import SubscriberActivity
    activities = db.query(SubscriberActivity)\
        .filter(SubscriberActivity.subscriber_id == sub_id)\
        .order_by(SubscriberActivity.created_at.desc())\
        .all()
        
    return activities

@router.post("/{list_id}/test-subscribers")
def test_subscribers_hygiene(
    list_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.require_tenant_write_access)
):
    import dns.resolver
    import concurrent.futures
    
    if current_user.role == "super_admin":
        sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id).first()
    else:
        if not current_user.tenant_id:
            raise HTTPException(status_code=400, detail="User not associated with a tenant")
        sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == current_user.tenant_id).first()
        
    if not sub_list:
        raise HTTPException(status_code=404, detail="List not found")
        
    subscribers = db.query(Subscriber).filter(Subscriber.list_id == list_id).all()
    if not subscribers:
        return {"total_checked": 0, "invalid_count": 0, "results": []}
        
    domains = set()
    for s in subscribers:
        if "@" in s.email:
            domains.add(s.email.split("@")[-1].strip().lower())
            
    domain_status = {}
    
    def resolve_domain(domain):
        try:
            try:
                answers = dns.resolver.resolve(domain, 'MX')
                if answers:
                    return domain, True
            except Exception:
                pass
            try:
                answers = dns.resolver.resolve(domain, 'A')
                if answers:
                    return domain, True
            except Exception:
                pass
            return domain, False
        except Exception:
            return domain, False

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(resolve_domain, d): d for d in domains}
        for fut in concurrent.futures.as_completed(futures):
            d, is_valid = fut.result()
            domain_status[d] = is_valid
            
    results = []
    invalid_count = 0
    for s in subscribers:
        domain = s.email.split("@")[-1].strip().lower() if "@" in s.email else ""
        is_valid = domain_status.get(domain, False) if domain else False
        if not is_valid:
            invalid_count += 1
        results.append({
            "id": s.id,
            "email": s.email,
            "name": s.name,
            "status": s.status,
            "domain_valid": is_valid
        })
        
    return {
        "total_checked": len(subscribers),
        "invalid_count": invalid_count,
        "results": results
    }

@router.post("/{list_id}/bulk-unsubscribe")
def bulk_unsubscribe_subscribers(
    list_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.require_tenant_write_access)
):
    if current_user.role == "super_admin":
        sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id).first()
    else:
        if not current_user.tenant_id:
            raise HTTPException(status_code=400, detail="User not associated with a tenant")
        sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == current_user.tenant_id).first()
        
    if not sub_list:
        raise HTTPException(status_code=404, detail="List not found")
        
    sub_ids = payload.get("subscriber_ids", [])
    if not sub_ids:
        return {"detail": "No subscribers specified."}
        
    db.query(Subscriber).filter(
        Subscriber.id.in_(sub_ids),
        Subscriber.list_id == list_id
    ).update({"status": "unsubscribed"}, synchronize_session=False)
    
    db.commit()
    return {"detail": f"Successfully unsubscribed {len(sub_ids)} contacts."}

@router.post("/{list_id}/bulk-action")
def bulk_action_subscribers(
    list_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.require_tenant_write_access)
):
    action = payload.get("action") # delete, status, add_tag, remove_tag
    if not action:
        raise HTTPException(status_code=400, detail="Action specified is required")
        
    select_all_matching = bool(payload.get("select_all_matching", False))
    sub_ids = payload.get("subscriber_ids", [])
    
    if current_user.role == "super_admin":
        sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id).first()
    else:
        if not current_user.tenant_id:
            raise HTTPException(status_code=400, detail="User not associated with a tenant")
        sub_list = db.query(SubscriberList).filter(SubscriberList.id == list_id, SubscriberList.tenant_id == current_user.tenant_id).first()
        
    if not sub_list:
        raise HTTPException(status_code=404, detail="List not found")
        
    query = db.query(Subscriber).filter(Subscriber.list_id == list_id)
    if current_user.role != "super_admin":
        query = query.filter(Subscriber.tenant_id == current_user.tenant_id)
        
    if select_all_matching:
        search = payload.get("search", "")
        status_filter = payload.get("status", "")
        engagement = payload.get("engagement")
        tag_filter = payload.get("tag", "")
        
        if search:
            query = query.filter((Subscriber.email.ilike(f"%{search}%")) | (Subscriber.name.ilike(f"%{search}%")))
        if status_filter:
            query = query.filter(Subscriber.status == status_filter)
        if engagement is not None and str(engagement).isdigit():
            query = query.filter(Subscriber.engagement_score == int(engagement))
        if tag_filter:
            query = query.filter(Subscriber.tags.like(f'%"{tag_filter}"%'))
    else:
        if not sub_ids:
            return {"detail": "No subscribers specified for bulk action."}
        query = query.filter(Subscriber.id.in_(sub_ids))
        
    subscribers_to_update = query.all()
    count = len(subscribers_to_update)
    
    if count == 0:
        return {"detail": "No matching subscribers found for bulk action."}
        
    if action == "delete":
        for s in subscribers_to_update:
            db.delete(s)
        db.commit()
        return {"detail": f"Successfully deleted {count} contacts."}
        
    elif action == "status":
        new_status = payload.get("new_status")
        if not new_status or new_status not in ["active", "unsubscribed", "bounced", "pending", "spam", "deferred", "failed"]:
            raise HTTPException(status_code=400, detail="Invalid target status")
        for s in subscribers_to_update:
            s.status = new_status
        db.commit()
        return {"detail": f"Successfully updated status to '{new_status}' for {count} contacts."}
        
    elif action == "add_tag":
        tag_name = payload.get("tag_name", "").strip()
        if not tag_name:
            raise HTTPException(status_code=400, detail="Tag name required")
        for s in subscribers_to_update:
            tags = list(s.tags or [])
            if tag_name not in tags:
                tags.append(tag_name)
                s.tags = tags
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(s, "tags")
        db.commit()
        return {"detail": f"Successfully added tag '{tag_name}' to {count} contacts."}
        
    elif action == "remove_tag":
        tag_name = payload.get("tag_name", "").strip()
        if not tag_name:
            raise HTTPException(status_code=400, detail="Tag name required")
        for s in subscribers_to_update:
            tags = list(s.tags or [])
            if tag_name in tags:
                tags.remove(tag_name)
                s.tags = tags
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(s, "tags")
        db.commit()
        return {"detail": f"Successfully removed tag '{tag_name}' from {count} contacts."}
        
    else:
        raise HTTPException(status_code=400, detail="Unsupported bulk action")


