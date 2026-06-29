import os
import json
from datetime import datetime
from typing import List, Optional
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Text, JSON, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

BASE_DIR = os.path.realpath(os.path.dirname(__file__))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'polypress.db')}")

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class GlobalSettings(Base):
    __tablename__ = "global_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    app_name = Column(String, default="PolyPress")
    app_logo = Column(String, nullable=True) # Base64 or local file path
    public_url = Column(String, nullable=True) # Public facing domain base URL
    oidc_enabled = Column(Boolean, default=False)
    oidc_issuer = Column(String, nullable=True)
    oidc_client_id = Column(String, nullable=True)
    oidc_client_secret = Column(String, nullable=True)
    oidc_redirect_url = Column(String, nullable=True)
    
    # Access controls
    allowed_domains = Column(String, nullable=True) # Comma-separated domains (e.g. "company.com,org.net")
    auto_create_tenants = Column(Boolean, default=True) # Automatically create a tenant for a new OIDC domain
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Tenant(Base):
    __tablename__ = "tenants"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    logo_path = Column(String, nullable=True)
    
    # Outgoing Email Server Settings
    smtp_host = Column(String, nullable=True)
    smtp_port = Column(Integer, nullable=True)
    smtp_username = Column(String, nullable=True)
    smtp_password = Column(String, nullable=True)
    smtp_use_ssl = Column(Boolean, default=False)
    smtp_use_tls = Column(Boolean, default=True)
    
    # Direct Send (MTA) & DKIM
    direct_send = Column(Boolean, default=False)
    dkim_selector = Column(String, default="polypress")
    dkim_domain = Column(String, nullable=True)
    dkim_private_key = Column(Text, nullable=True)
    dkim_public_key = Column(Text, nullable=True) # Public key portion of DNS record
    
    # Bounce handling settings (IMAP)
    bounce_email = Column(String, nullable=True) # Bounce address, e.g. bounce@domain.com
    imap_host = Column(String, nullable=True)
    imap_port = Column(Integer, nullable=True)
    imap_username = Column(String, nullable=True)
    imap_password = Column(String, nullable=True)
    imap_use_ssl = Column(Boolean, default=True)
    
    # Speed Limit Configuration
    speed_emails_per_hour = Column(Integer, default=500) # 0 means unlimited
    max_sending_threads = Column(Integer, default=10)
    double_opt_in = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    subscriber_lists = relationship("SubscriberList", back_populates="tenant", cascade="all, delete-orphan")
    subscribers = relationship("Subscriber", back_populates="tenant", cascade="all, delete-orphan")
    campaigns = relationship("Campaign", back_populates="tenant", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True) # Null for Super Admin
    email = Column(String, unique=True, index=True)
    name = Column(String, nullable=True)
    role = Column(String, default="tenant_user") # super_admin, tenant_admin, tenant_user
    password_hash = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    totp_secret = Column(String, nullable=True)
    totp_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    tenant = relationship("Tenant", back_populates="users")

class SubscriberList(Base):
    __tablename__ = "subscriber_lists"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    
    # JSON definition of subscriber attributes (e.g. city, gender, etc.)
    # Format: [{"key": "city", "label": "City", "type": "text"}]
    custom_fields = Column(JSON, default=list)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    tenant = relationship("Tenant", back_populates="subscriber_lists")
    subscribers = relationship("Subscriber", back_populates="subscriber_list", cascade="all, delete-orphan")
    campaigns = relationship("Campaign", back_populates="subscriber_list")

class Subscriber(Base):
    __tablename__ = "subscribers"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True)
    list_id = Column(Integer, ForeignKey("subscriber_lists.id"), index=True)
    email = Column(String, index=True)
    name = Column(String, nullable=True)
    status = Column(String, default="active", index=True) # active, unsubscribed, bounced, spam
    
    # JSON key-value store mapping list custom fields
    # Format: {"city": "New York", "gender": "male"}
    custom_data = Column(JSON, default=dict)
    
    # Source tag (e.g. from embedded forms, CSV, etc.)
    source_tag = Column(String, nullable=True)
    
    # Advanced Segmentation: engagement score (1 to 5 stars) and tags list
    engagement_score = Column(Integer, default=3, index=True)
    tags = Column(JSON, default=list)
    
    # Double Opt-In and Bounce Diagnostics
    double_opt_in_token = Column(String, unique=True, index=True, nullable=True)
    bounce_reason = Column(Text, nullable=True)
    complaint_reason = Column(Text, nullable=True)
    bounce_source_email = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    tenant = relationship("Tenant", back_populates="subscribers")
    subscriber_list = relationship("SubscriberList", back_populates="subscribers")

class Campaign(Base):
    __tablename__ = "campaigns"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    list_id = Column(Integer, ForeignKey("subscriber_lists.id"))
    name = Column(String, index=True)
    subject = Column(String)
    
    # Visual Builder blocks representation (JSON)
    # Format: [{"type": "header", "content": "Welcome"}, ...]
    body_blocks = Column(JSON, default=list)
    body_html = Column(Text) # Exported raw HTML for actual email transmission
    
    status = Column(String, default="draft") # draft, queued, sending, sent, cancelled
    target_rules = Column(JSON, default=dict)
    
    # Statistics
    total_recipients = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    bounce_count = Column(Integer, default=0)
    open_count = Column(Integer, default=0)
    click_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)
    
    tenant = relationship("Tenant", back_populates="campaigns")
    subscriber_list = relationship("SubscriberList", back_populates="campaigns")
    queue_items = relationship("QueueItem", back_populates="campaign", cascade="all, delete-orphan")
    tracking_logs = relationship("TrackingLog", back_populates="campaign", cascade="all, delete-orphan")

class QueueItem(Base):
    __tablename__ = "queue_items"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), index=True)
    subscriber_id = Column(Integer, ForeignKey("subscribers.id"))
    
    email = Column(String)
    subject = Column(String)
    body_html = Column(Text)
    
    status = Column(String, default="pending", index=True) # pending, sending, sent, failed
    retries = Column(Integer, default=0)
    next_attempt = Column(DateTime, default=datetime.utcnow, index=True)
    error_message = Column(Text, nullable=True)
    last_mx_response = Column(Text, nullable=True)
    error_code = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    campaign = relationship("Campaign", back_populates="queue_items")

class TrackingLog(Base):
    __tablename__ = "tracking_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), index=True)
    subscriber_id = Column(Integer, ForeignKey("subscribers.id"), index=True)
    
    event_type = Column(String, index=True) # open, click
    link_url = Column(String, nullable=True) # Null for email open event
    
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    campaign = relationship("Campaign", back_populates="tracking_logs")
    
class ApiKey(Base):
    __tablename__ = "api_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    name = Column(String)
    prefix = Column(String)
    key_hash = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    url = Column(String)
    secret = Column(String)
    events = Column(JSON, default=list)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
    
    # Auto-migration queries for SQLite databases
    try:
        with engine.begin() as conn:
            # Check subscribers table
            res = conn.execute(text("PRAGMA table_info(subscribers)")).fetchall()
            cols = [r[1] for r in res]
            if "engagement_score" not in cols:
                conn.execute(text("ALTER TABLE subscribers ADD COLUMN engagement_score INTEGER DEFAULT 3"))
            if "tags" not in cols:
                conn.execute(text("ALTER TABLE subscribers ADD COLUMN tags JSON DEFAULT '[]'"))
                
            # Check campaigns table
            res = conn.execute(text("PRAGMA table_info(campaigns)")).fetchall()
            cols = [r[1] for r in res]
            if "target_rules" not in cols:
                conn.execute(text("ALTER TABLE campaigns ADD COLUMN target_rules JSON DEFAULT '{}'"))
    except Exception as migration_error:
        print(f"Database migration note: {migration_error}")

    db = SessionLocal()
    try:
        # Seed settings if empty
        settings = db.query(GlobalSettings).first()
        if not settings:
            settings = GlobalSettings(app_name="PolyPress")
            db.add(settings)
            db.commit()
    finally:
        db.close()
