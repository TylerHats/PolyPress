import os
import hmac
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
from database import get_db, User, GlobalSettings, Tenant, DATABASE_URL, BASE_DIR


def _load_or_create_secret_key() -> str:
    env_key = os.getenv("JWT_SECRET_KEY")
    if env_key:
        return env_key
    if DATABASE_URL.startswith("sqlite:///") and ":memory:" not in DATABASE_URL:
        db_dir = os.path.dirname(os.path.realpath(DATABASE_URL.replace("sqlite:///", "", 1)))
    else:
        db_dir = os.path.realpath(BASE_DIR)
    secret_file = os.path.join(db_dir, ".polypress_secret")
    try:
        if os.path.exists(secret_file):
            with open(secret_file, "r", encoding="utf-8") as f:
                stored = f.read().strip()
            if len(stored) >= 32:
                return stored
        os.makedirs(db_dir, exist_ok=True)
        new_key = secrets.token_hex(32)
        fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_key)
        return new_key
    except Exception:
        return secrets.token_hex(32)


SECRET_KEY = _load_or_create_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours

security = HTTPBearer(auto_error=False)


def sign_url_token(payload_str: str) -> str:
    """Compute a deterministic HMAC-SHA256 signature for public URL verification."""
    return hmac.new(
        SECRET_KEY.encode("utf-8"),
        payload_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]


def verify_url_token(payload_str: str, sig: Optional[str]) -> bool:
    """Constant-time check for HMAC URL signatures."""
    if not sig:
        return False
    expected = sign_url_token(payload_str)
    return hmac.compare_digest(expected, str(sig).strip())


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


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None, purpose: str = "access"):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "purpose": purpose})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_totp_challenge_token(email: str) -> str:
    return create_access_token(
        {"sub": email},
        expires_delta=timedelta(minutes=5),
        purpose="totp_challenge",
    )


def verify_totp_challenge_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("purpose") != "totp_challenge":
            return None
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def _resolve_authenticated_user(
    request: Request,
    token: Optional[str],
    credentials: Optional[HTTPAuthorizationCredentials],
    db: Session,
    allow_pending: bool = False,
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
        purpose: str = payload.get("purpose")
        if email is None or purpose != "access":
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
        
    user = db.query(User).filter(User.email == email, User.is_active == True).first()
    if user is None:
        raise credentials_exception

    if not allow_pending and user.role == "pending":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is pending administrator approval"
        )
        
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


def get_authenticated_user(
    request: Request,
    token: Optional[str] = Query(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: Session = Depends(get_db)
) -> User:
    return _resolve_authenticated_user(request, token, credentials, db, allow_pending=True)


def get_current_user(
    request: Request,
    token: Optional[str] = Query(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: Session = Depends(get_db)
) -> User:
    return _resolve_authenticated_user(request, token, credentials, db, allow_pending=False)

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

def process_oidc_user(db: Session, email: str, name: str, userinfo: dict = None) -> User:
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
        # Sync role and allowed_tenants on subsequent login
        if userinfo:
            role_claim = settings.oidc_role_claim or "role"
            claim_val = userinfo.get(role_claim)
            claim_vals = []
            if isinstance(claim_val, list):
                claim_vals = [str(v).strip().lower() for v in claim_val]
            elif claim_val:
                claim_vals = [str(claim_val).strip().lower()]
                
            sa_val = (settings.oidc_super_admin_value or "super_admin").strip().lower()
            ta_val = (settings.oidc_tenant_admin_value or "tenant_admin").strip().lower()
            tu_val = (settings.oidc_tenant_user_value or "tenant_user").strip().lower()
            
            if sa_val in claim_vals:
                user.role = "super_admin"
            elif ta_val in claim_vals:
                user.role = "tenant_admin"
            elif tu_val in claim_vals:
                user.role = "tenant_user"
                
            tenant_claim = settings.oidc_tenant_claim or "tenant"
            tenant_val = userinfo.get(tenant_claim)
            if tenant_val:
                tenant_vals = tenant_val if isinstance(tenant_val, list) else [tenant_val]
                sync_allowed = []
                primary_t = None
                for t_val in tenant_vals:
                    t_val_str = str(t_val).strip()
                    t_obj = None
                    if t_val_str.isdigit():
                        t_obj = db.query(Tenant).filter(Tenant.id == int(t_val_str)).first()
                    else:
                        t_obj = db.query(Tenant).filter(Tenant.name.ilike(t_val_str)).first()
                    if t_obj:
                        if not primary_t:
                            primary_t = t_obj
                        if t_obj.id not in sync_allowed:
                            sync_allowed.append(t_obj.id)
                if primary_t:
                    user.tenant_id = primary_t.id
                if sync_allowed:
                    user.allowed_tenants = sync_allowed
        db.commit()
        return user
        
    # Check if we should map tenant using claim or auto-create a tenant for this domain
    tenant = None
    allowed_tenants = []
    
    if userinfo:
        tenant_claim = settings.oidc_tenant_claim or "tenant"
        tenant_val = userinfo.get(tenant_claim)
        if tenant_val:
            tenant_vals = tenant_val if isinstance(tenant_val, list) else [tenant_val]
            for t_val in tenant_vals:
                t_val_str = str(t_val).strip()
                t_obj = None
                if t_val_str.isdigit():
                    t_obj = db.query(Tenant).filter(Tenant.id == int(t_val_str)).first()
                else:
                    t_obj = db.query(Tenant).filter(Tenant.name.ilike(t_val_str)).first()
                if t_obj:
                    if not tenant:
                        tenant = t_obj
                    if t_obj.id not in allowed_tenants:
                        allowed_tenants.append(t_obj.id)
                        
    if not tenant:
        tenant_name = domain.capitalize()
        tenant = db.query(Tenant).filter(Tenant.name == tenant_name).first()
        if not tenant and settings.auto_create_tenants:
            tenant = Tenant(name=tenant_name)
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
            
    if tenant and tenant.id not in allowed_tenants:
        allowed_tenants.append(tenant.id)
        
    # Determine role: If there are absolutely no users in the DB, make them super admin.
    # Otherwise, check mapped claim values.
    num_users = db.query(User).count()
    if num_users == 0:
        role = "super_admin"
    else:
        role = "pending"
        if userinfo:
            role_claim = settings.oidc_role_claim or "role"
            claim_val = userinfo.get(role_claim)
            claim_vals = []
            if isinstance(claim_val, list):
                claim_vals = [str(v).strip().lower() for v in claim_val]
            elif claim_val:
                claim_vals = [str(claim_val).strip().lower()]
                
            sa_val = (settings.oidc_super_admin_value or "super_admin").strip().lower()
            ta_val = (settings.oidc_tenant_admin_value or "tenant_admin").strip().lower()
            tu_val = (settings.oidc_tenant_user_value or "tenant_user").strip().lower()
            
            if sa_val in claim_vals:
                role = "super_admin"
            elif ta_val in claim_vals:
                role = "tenant_admin"
            elif tu_val in claim_vals:
                role = "tenant_user"
         
    new_user = User(
        email=email,
        name=name,
        role=role,
        tenant_id=tenant.id if tenant else None,
        allowed_tenants=allowed_tenants,
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

def verify_totp_with_step(secret: str, code: str, window: int = 1) -> Optional[int]:
    """Verify a TOTP code and return the matching 30-second time_step on success."""
    try:
        code_str = str(code or "").strip()
        if not code_str.isdigit() or len(code_str) != 6:
            return None
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
            h_digest = hmac.new(key, msg, hashlib.sha1).digest()
            o = h_digest[19] & 15
            token_val = (struct.unpack(">I", h_digest[o:o+4])[0] & 0x7fffffff) % 1000000
            if hmac.compare_digest(f"{token_val:06d}", code_str):
                return time_step
        return None
    except Exception as e:
        print(f"TOTP verification error: {e}")
        return None


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    return verify_totp_with_step(secret, code, window=window) is not None
