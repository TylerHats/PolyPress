from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
import os
from database import get_db, User, GlobalSettings
import auth
from acme_helper import ACMEClient, acme_log_buffer, clear_acme_logs, log_progress
from cryptography import x509

router = APIRouter(prefix="/api/ssl", tags=["ssl"])

BASE_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
CERTS_DIR = os.path.join(BASE_DIR, "certs")

@router.get("/status")
def get_ssl_status(request: Request, db: Session = Depends(get_db), current_user: User = Depends(auth.require_super_admin)):
    is_proxy_https = False
    
    # 1. Check header
    if request.headers.get("x-forwarded-proto") == "https":
        is_proxy_https = True
        
    # 2. Check public_url
    settings = db.query(GlobalSettings).first()
    if settings and settings.public_url and settings.public_url.lower().startswith("https://"):
        is_proxy_https = True

    priv_key_path = os.path.join(CERTS_DIR, "privkey.pem")
    cert_path = os.path.join(CERTS_DIR, "fullchain.pem")
    
    status_payload = {
        "configured": False,
        "is_proxy_https": is_proxy_https
    }
    
    if not os.path.exists(priv_key_path) or not os.path.exists(cert_path):
        return status_payload
        
    try:
        with open(cert_path, "rb") as f:
            cert_data = f.read()
            cert = x509.load_pem_x509_certificate(cert_data)
            
        expiry = getattr(cert, "not_valid_after_utc", None)
        if not expiry:
            expiry = cert.not_valid_after
            
        issuer = cert.issuer.rfc4514_string()
        subject = cert.subject.rfc4514_string()
        
        status_payload.update({
            "configured": True,
            "expiry": expiry.isoformat(),
            "issuer": issuer,
            "subject": subject
        })
        return status_payload
    except Exception as e:
        status_payload.update({"error": str(e)})
        return status_payload

@router.post("/generate")
def generate_ssl_certificate(payload: dict, current_user: User = Depends(auth.require_super_admin)):
    domain = payload.get("domain")
    email = payload.get("email")
    use_staging = payload.get("use_staging", True)
    
    if not domain or not email:
        raise HTTPException(status_code=400, detail="Domain name and email address are required")
        
    clear_acme_logs()
    log_progress(f"Starting SSL/TLS generation request for {domain}...")
    
    try:
        os.makedirs(CERTS_DIR, exist_ok=True)
        client = ACMEClient(domain=domain, email=email, use_staging=use_staging)
        client.request_certificates(CERTS_DIR)
        return {
            "status": "success",
            "logs": acme_log_buffer
        }
    except Exception as e:
        log_progress(f"ERROR: SSL generation failed: {e}")
        return {
            "status": "failed",
            "logs": acme_log_buffer
        }

@router.get("/logs")
def get_ssl_logs(current_user: User = Depends(auth.require_super_admin)):
    return acme_log_buffer
