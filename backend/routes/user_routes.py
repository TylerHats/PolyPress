from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db, User, Tenant
import auth

router = APIRouter(prefix="/api/admin/users", tags=["users"])

@router.get("")
def list_users(db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    if current_user.role == "super_admin":
        users = db.query(User).all()
    else:
        admin_tenants = set(current_user.allowed_tenants or ([current_user.tenant_id] if current_user.tenant_id else []))
        all_users = db.query(User).all()
        users = []
        for u in all_users:
            if u.id == current_user.id:
                users.append(u)
                continue
            if u.role != "tenant_user":
                continue
            u_tenants = set(u.allowed_tenants or ([u.tenant_id] if u.tenant_id else []))
            if u_tenants.issubset(admin_tenants) and len(u_tenants) > 0:
                users.append(u)
        
    result = []
    for u in users:
        tenant_name = None
        if u.tenant_id:
            tenant = db.query(Tenant).filter(Tenant.id == u.tenant_id).first()
            if tenant:
                tenant_name = tenant.name
        result.append({
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "role": u.role,
            "is_active": u.is_active,
            "tenant_id": u.tenant_id,
            "tenant_name": tenant_name,
            "totp_enabled": u.totp_enabled,
            "auth_type": u.auth_type,
            "allowed_tenants": u.allowed_tenants or []
        })
    return result

@router.post("")
def create_user(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    email = payload.get("email")
    name = payload.get("name")
    password = payload.get("password")
    role = payload.get("role", "tenant_user")
    tenant_id = payload.get("tenant_id")
    auth_type = payload.get("auth_type", "local")
    
    if not email or not name or (auth_type == "local" and not password):
        raise HTTPException(status_code=400, detail="Email and name are required (and password for local accounts)")
        
    # Unique email check
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="A user with this email address already exists")
        
    # Enforce scoping rules
    allowed_tenants = payload.get("allowed_tenants", [])
    if current_user.role != "super_admin":
        # Tenant admins can only create users within their own tenant context
        tenant_id = current_user.tenant_id
        allowed_tenants = [tenant_id]
        if role not in ["tenant_admin", "tenant_user"]:
            role = "tenant_user"
    else:
        if role == "super_admin":
            tenant_id = None
            allowed_tenants = []
        else:
            if allowed_tenants:
                tenant_id = allowed_tenants[0]
            else:
                tenant_id = payload.get("tenant_id")
                if tenant_id:
                    allowed_tenants = [tenant_id]
            
    user = User(
        email=email,
        name=name,
        password_hash=auth.hash_password(password) if (auth_type == "local" and password) else None,
        role=role,
        tenant_id=tenant_id,
        allowed_tenants=allowed_tenants,
        is_active=payload.get("is_active", True),
        auth_type=auth_type
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return {"status": "success", "user_id": user.id}

@router.put("/{user_id}")
def update_user(user_id: int, payload: dict, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Scoping check (Bug 4)
    if current_user.role != "super_admin":
        if user.role != "tenant_user":
            raise HTTPException(status_code=403, detail="Not authorized to edit users with administrative roles")
        admin_tenants = set(current_user.allowed_tenants or ([current_user.tenant_id] if current_user.tenant_id else []))
        user_tenants = set(user.allowed_tenants or ([user.tenant_id] if user.tenant_id else []))
        if not user_tenants.issubset(admin_tenants) or len(user_tenants) == 0:
            raise HTTPException(status_code=403, detail="Not authorized to edit users outside your workspace context scopes")
        
    if "name" in payload:
        user.name = payload["name"]
    if "email" in payload:
        # Check if email is being updated and conflicts
        new_email = payload["email"]
        if new_email != user.email:
            existing = db.query(User).filter(User.email == new_email).first()
            if existing:
                raise HTTPException(status_code=400, detail="Email address is already in use")
            user.email = new_email
            
    if "role" in payload:
        new_role = payload["role"]
        if current_user.role == "super_admin":
            user.role = new_role
        else:
            # Tenant admins cannot grant super admin privileges
            if new_role not in ["tenant_admin", "tenant_user", "pending"]:
                raise HTTPException(status_code=403, detail="Invalid role modification permissions")
            user.role = new_role
            
    if "allowed_tenants" in payload and current_user.role == "super_admin":
        user.allowed_tenants = payload["allowed_tenants"]
        if payload["allowed_tenants"]:
            user.tenant_id = payload["allowed_tenants"][0]
        else:
            user.tenant_id = None
    elif "tenant_id" in payload and current_user.role == "super_admin":
        user.tenant_id = payload["tenant_id"]
        if payload["tenant_id"]:
            user.allowed_tenants = [payload["tenant_id"]]
        else:
            user.allowed_tenants = []
        
    if "is_active" in payload:
        # Don't let users deactivate themselves
        if user.id == current_user.id:
            raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
        user.is_active = payload["is_active"]
        
    if payload.get("reset_2fa") or payload.get("disable_2fa"):
        user.totp_enabled = False
        user.totp_secret = None
        
    if "password" in payload and payload["password"]:
        user.password_hash = auth.hash_password(payload["password"])
        
    if "auth_type" in payload:
        user.auth_type = payload["auth_type"]
        if user.auth_type == "oidc":
            user.totp_enabled = False
            user.totp_secret = None
            user.password_hash = None
        
    db.commit()
    return {"status": "success"}

@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(auth.require_tenant_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
        
    # Scoping check (Bug 4)
    if current_user.role != "super_admin":
        if user.role != "tenant_user":
            raise HTTPException(status_code=403, detail="Not authorized to delete users with administrative roles")
        admin_tenants = set(current_user.allowed_tenants or ([current_user.tenant_id] if current_user.tenant_id else []))
        user_tenants = set(user.allowed_tenants or ([user.tenant_id] if user.tenant_id else []))
        if not user_tenants.issubset(admin_tenants) or len(user_tenants) == 0:
            raise HTTPException(status_code=403, detail="Not authorized to delete users outside your workspace context scopes")
            
    db.delete(user)
    db.commit()
    return {"status": "success"}
