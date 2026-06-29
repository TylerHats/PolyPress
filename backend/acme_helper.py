import os
import json
import base64
import hashlib
import time
import requests
import logging
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography import x509
from cryptography.x509.oid import NameOID

logger = logging.getLogger("acme_helper")

# Staging and Production directory endpoints
ACME_STAGING_DIR = "https://acme-staging-v02.api.letsencrypt.org/directory"
ACME_PROD_DIR = "https://acme-v02.api.letsencrypt.org/directory"

# In-memory challenge token dictionary for FastAPI to intercept
active_challenges = {}
acme_log_buffer = []

def log_progress(msg: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    acme_log_buffer.append(f"[{timestamp}] {msg}")
    logger.info(msg)

def clear_acme_logs():
    acme_log_buffer.clear()

def b64_url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode('utf-8').rstrip('=')

class ACMEClient:
    def __init__(self, domain: str, email: str, use_staging: bool = True):
        self.domain = domain.strip().lower()
        self.email = email.strip()
        self.directory_url = ACME_STAGING_DIR if use_staging else ACME_PROD_DIR
        self.endpoints = {}
        self.account_key = None
        self.account_kid = None
        self.nonce = None

    def load_or_generate_account_key(self, key_path: str) -> rsa.RSAPrivateKey:
        if os.path.exists(key_path):
            log_progress("Loading existing ACME account key...")
            with open(key_path, "rb") as f:
                self.account_key = serialization.load_pem_private_key(f.read(), password=None)
        else:
            log_progress("Generating new ACME account key...")
            os.makedirs(os.path.dirname(key_path), exist_ok=True)
            self.account_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            with open(key_path, "wb") as f:
                f.write(self.account_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption()
                ))
        return self.account_key

    def fetch_directory(self):
        log_progress(f"Fetching ACME directory from {self.directory_url}...")
        res = requests.get(self.directory_url, timeout=10)
        res.raise_for_status()
        self.endpoints = res.json()

    def get_nonce(self) -> str:
        nonce_url = self.endpoints.get("newNonce")
        res = requests.head(nonce_url, timeout=10)
        res.raise_for_status()
        self.nonce = res.headers.get("Replay-Nonce")
        return self.nonce

    def get_jwk(self) -> dict:
        numbers = self.account_key.public_key().public_numbers()
        return {
            "kty": "RSA",
            "n": b64_url_encode(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, byteorder='big')),
            "e": b64_url_encode(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, byteorder='big'))
        }

    def get_key_thumbprint(self) -> str:
        jwk = self.get_jwk()
        jwk_json = json.dumps(jwk, sort_keys=True, separators=(',', ':'))
        thumbprint_bytes = hashlib.sha256(jwk_json.encode('utf-8')).digest()
        return b64_url_encode(thumbprint_bytes)

    def send_signed_request(self, url: str, payload: dict) -> requests.Response:
        if not self.nonce:
            self.get_nonce()
            
        protected = {
            "alg": "RS256",
            "nonce": self.nonce,
            "url": url
        }
        if self.account_kid:
            protected["kid"] = self.account_kid
        else:
            protected["jwk"] = self.get_jwk()
            
        protected_b64 = b64_url_encode(json.dumps(protected).encode('utf-8'))
        
        if payload is None:
            # POST-as-GET requests carry an empty string payload
            payload_b64 = ""
        else:
            payload_b64 = b64_url_encode(json.dumps(payload).encode('utf-8'))
            
        signing_input = f"{protected_b64}.{payload_b64}".encode('utf-8')
        signature = self.account_key.sign(
            signing_input,
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        signature_b64 = b64_url_encode(signature)
        
        headers = {"Content-Type": "application/jose+json"}
        data = {
            "protected": protected_b64,
            "payload": payload_b64,
            "signature": signature_b64
        }
        
        res = requests.post(url, json=data, headers=headers, timeout=15)
        
        # Capture next nonce from response headers
        if "Replay-Nonce" in res.headers:
            self.nonce = res.headers["Replay-Nonce"]
            
        return res

    def register_account(self):
        url = self.endpoints.get("newAccount")
        payload = {
            "termsOfServiceAgreed": True,
            "contact": [f"mailto:{self.email}"]
        }
        log_progress("Registering ACME account...")
        res = self.send_signed_request(url, payload)
        if res.status_code in [200, 201]:
            self.account_kid = res.headers.get("Location")
            log_progress(f"Registered account successfully. Account ID: {self.account_kid}")
        else:
            raise Exception(f"Account registration failed: [{res.status_code}] {res.text}")

    def request_certificates(self, cert_dir: str):
        # 1. Directory & Nonce setup
        self.fetch_directory()
        account_key_path = os.path.join(cert_dir, "account_key.pem")
        self.load_or_generate_account_key(account_key_path)
        self.register_account()
        
        # 2. Create Order
        order_url = self.endpoints.get("newOrder")
        order_payload = {
            "identifiers": [{"type": "dns", "value": self.domain}]
        }
        log_progress(f"Creating ACME order for domain: {self.domain}...")
        res = self.send_signed_request(order_url, order_payload)
        if res.status_code != 201:
            raise Exception(f"Order creation failed: [{res.status_code}] {res.text}")
            
        order_data = res.json()
        auth_urls = order_data.get("authorizations", [])
        finalize_url = order_data.get("finalize")
        
        # 3. Resolve challenges (HTTP-01)
        challenge_found = False
        for auth_url in auth_urls:
            log_progress(f"Fetching authorization challenges from: {auth_url}...")
            auth_res = self.send_signed_request(auth_url, None) # POST-as-GET
            auth_res.raise_for_status()
            auth_data = auth_res.json()
            
            challenges = auth_data.get("challenges", [])
            for chal in challenges:
                if chal.get("type") == "http-01":
                    challenge_url = chal.get("url")
                    token = chal.get("token")
                    challenge_found = True
                    break
            if challenge_found:
                break
                
        if not challenge_found:
            raise Exception("No HTTP-01 challenge offered by ACME provider.")
            
        # 4. Map challenge token for FastAPI dynamically
        thumbprint = self.get_key_thumbprint()
        key_authorization = f"{token}.{thumbprint}"
        active_challenges[token] = key_authorization
        log_progress(f"Mapped ACME challenge token: {token} -> serving key authorization.")
        
        # 5. Tell Let's Encrypt to verify
        log_progress("Signaling ACME provider to trigger HTTP-01 check...")
        chal_res = self.send_signed_request(challenge_url, {})
        if chal_res.status_code != 200:
            active_challenges.pop(token, None)
            raise Exception(f"Challenge trigger failure: [{chal_res.status_code}] {chal_res.text}")
            
        # 6. Poll for success
        log_progress("Polling authorization status...")
        authorized = False
        for attempt in range(12): # Poll up to 60 seconds
            time.sleep(5)
            auth_res = self.send_signed_request(auth_url, None)
            auth_res.raise_for_status()
            auth_status = auth_res.json().get("status")
            log_progress(f"Authorization status check {attempt + 1}: {auth_status}")
            if auth_status == "valid":
                authorized = True
                break
            elif auth_status in ["invalid", "revoked"]:
                raise Exception("ACME authorization verification failed. Please check port 80 accessibility.")
                
        # Clean challenge map
        active_challenges.pop(token, None)
        
        if not authorized:
            raise Exception("ACME authorization timed out.")
            
        log_progress("Domain verified successfully!")
        
        # 7. Generate Domain Keys
        domain_key_path = os.path.join(cert_dir, "privkey.pem")
        log_progress("Generating RSA domain private key...")
        domain_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with open(domain_key_path, "wb") as f:
            f.write(domain_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))
            
        # 8. Sign CSR
        log_progress("Signing Certificate Signing Request (CSR)...")
        csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, self.domain)
        ])).sign(domain_key, hashes.SHA256())
        csr_der = csr.public_bytes(serialization.Encoding.DER)
        
        # 9. Finalize Order
        finalize_payload = {
            "csr": b64_url_encode(csr_der)
        }
        log_progress("Sending finalization request...")
        fin_res = self.send_signed_request(finalize_url, finalize_payload)
        if fin_res.status_code != 200:
            raise Exception(f"Finalization failed: [{fin_res.status_code}] {fin_res.text}")
            
        fin_data = fin_res.json()
        certificate_url = fin_data.get("certificate")
        
        # 10. Fetch Certificate
        log_progress("Fetching certificate chain...")
        cert_res = self.send_signed_request(certificate_url, None)
        if cert_res.status_code != 200:
            raise Exception(f"Certificate fetch failed: [{cert_res.status_code}] {cert_res.text}")
            
        # 11. Save Certificate
        cert_chain_path = os.path.join(cert_dir, "fullchain.pem")
        with open(cert_chain_path, "w") as f:
            f.write(cert_res.text)
            
        log_progress("==============================================")
        log_progress("   SSL CERTIFICATE SUCCESSFULLY GENERATED!   ")
        log_progress(f"   Private Key:  {domain_key_path}")
        log_progress(f"   Cert Chain:   {cert_chain_path}")
        log_progress("==============================================")
        return True
