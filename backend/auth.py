import os
import hashlib
import secrets
import base64
import struct
import time
from datetime import datetime, timedelta
from typing import Optional
import jwt
from fastapi import Depends, HTTPException, status, Security, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import get_db, User, GlobalSettings, Tenant

SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_hex(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours

security = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    db_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()
    return f"{salt}${db_hash}"

def verify_password(password: str, hashed: str) -> bool:
    if not hashed or "$" not in hashed:
        return False
    salt, db_hash = hashed.split("$", 1)
    test_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()
    return secrets.compare_digest(db_hash, test_hash)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(
    request: Request,
    token: Optional[str] = Query(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: Session = Depends(get_db)
) -> User:
    jwt_token = None
    if credentials and credentials.credentials:
        jwt_token = credentials.credentials
    elif token:
        jwt_token = token
        
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not jwt_token:
        raise credentials_exception
        
    try:
        payload = jwt.decode(jwt_token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
        
    user = db.query(User).filter(User.email == email, User.is_active == True).first()
    if user is None:
        raise credentials_exception
        
    # Context switching for Super Admins via header override
    if user.role == "super_admin":
        tenant_id_header = request.headers.get("X-PolyPress-Tenant-Id")
        if tenant_id_header:
            from sqlalchemy.orm.attributes import set_committed_value
            if tenant_id_header in ["global", "null", "0", "None", ""]:
                set_committed_value(user, "tenant_id", None)
            else:
                try:
                    set_committed_value(user, "tenant_id", int(tenant_id_header))
                except ValueError:
                    pass
    # Context switching for Non-Super Admins (Multiple Tenant Access)
    elif user.role != "super_admin":
        tenant_id_header = request.headers.get("X-PolyPress-Tenant-Id")
        if tenant_id_header:
            try:
                tid = int(tenant_id_header)
                if user.allowed_tenants and tid in user.allowed_tenants:
                    from sqlalchemy.orm.attributes import set_committed_value
                    set_committed_value(user, "tenant_id", tid)
                elif user.tenant_id == tid:
                    pass
                else:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Access denied to this tenant"
                    )
            except ValueError:
                pass
                
    return user

def require_role(roles: list):
    def dependency(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource"
            )
        return current_user
    return dependency

def require_super_admin(current_user: User = Depends(get_current_user)):
    if current_user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required"
        )
    return current_user

def require_tenant_admin(current_user: User = Depends(get_current_user)):
    if current_user.role not in ["super_admin", "tenant_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant admin access required"
        )
    return current_user

def require_tenant_write_access(current_user: User = Depends(get_current_user)):
    if current_user.role not in ["super_admin", "tenant_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access denied: Tenant admin privileges required."
        )
    return current_user

def process_oidc_user(db: Session, email: str, name: str) -> User:
    """
    Process user logging in via OIDC. 
    Verifies domain rules and roles, auto-creates tenant or maps to existing tenant.
    """
    settings = db.query(GlobalSettings).first()
    
    # Extract domain
    domain = email.split("@")[-1].lower()
    
    # Domain whitelist check (unless domain check is empty)
    if settings.allowed_domains:
        allowed = [d.strip().lower() for d in settings.allowed_domains.split(",") if d.strip()]
        if domain not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied for domain: @{domain}. Domain not in OIDC whitelist."
            )
            
    # Check if user already exists
    user = db.query(User).filter(User.email == email).first()
    if user:
        if user.auth_type == "local":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This account is configured for local credentials authentication only."
            )
        return user
        
    # Check if we should auto-create a tenant for this domain
    tenant_name = domain.capitalize()
    
    # Try to find a matching tenant or create one
    tenant = db.query(Tenant).filter(Tenant.name == tenant_name).first()
    if not tenant and settings.auto_create_tenants:
        tenant = Tenant(name=tenant_name)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        
    # Determine role: If there are absolutely no users in the DB, make them super admin.
    # Otherwise, they are default pending approval.
    num_users = db.query(User).count()
    if num_users == 0:
        role = "super_admin"
    else:
        role = "pending"
        
    new_user = User(
        email=email,
        name=name,
        role=role,
        tenant_id=tenant.id if tenant else None,
        is_active=True,
        auth_type="oidc"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

def generate_totp_secret() -> str:
    random_bytes = secrets.token_bytes(10)
    return base64.b32encode(random_bytes).decode('utf-8').rstrip('=')

def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    try:
        # Normalize secret
        secret = secret.strip().replace(" ", "").upper()
        missing_padding = len(secret) % 8
        if missing_padding:
            secret += '=' * (8 - missing_padding)
        key = base64.b32decode(secret)
        
        current_time = int(time.time() // 30)
        
        for w in range(-window, window + 1):
            time_step = current_time + w
            msg = struct.pack(">Q", time_step)
            h = hmac = hashlib.sha1
            # Dynamic HMAC-SHA1 calculation
            h_mac = hmac = hashlib.sha1
            # We can use standard hmac library:
            import hmac
            h_digest = hmac.new(key, msg, hashlib.sha1).digest()
            o = h_digest[19] & 15
            token_val = (struct.unpack(">I", h_digest[o:o+4])[0] & 0x7fffffff) % 1000000
            if f"{token_val:06d}" == str(code).strip():
                return True
        return False
    except Exception as e:
        print(f"TOTP verification error: {e}")
        return False
