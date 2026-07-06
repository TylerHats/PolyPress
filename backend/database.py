import os
import json
from datetime import datetime
from typing import List, Optional
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Text, JSON, text, inspect
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

BASE_DIR = os.path.realpath(os.path.dirname(__file__))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'polypress.db')}")

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

CURRENT_SCHEMA_VERSION = 9
SCHEMA_MISMATCH = False
DB_SCHEMA_VERSION = 0
CURRENT_HISTORY_SCHEMA_VERSION = 1
DB_HISTORY_SCHEMA_VERSION = 0

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
    local_login_enabled = Column(Boolean, default=True) # Disable local email/pass login if OIDC is only option
    mail_server_identity = Column(String, nullable=True) # Domain name for HELO/EHLO handshake
    
    # Auto-updates and Backups API
    auto_update = Column(Boolean, default=False)
    update_channel = Column(String, default="stable")
    backup_token = Column(String, nullable=True)
    external_backup_url = Column(String, nullable=True)
    external_backup_auth_header = Column(String, nullable=True)
    schema_version = Column(Integer, default=CURRENT_SCHEMA_VERSION)
    
    # History logs settings
    history_retention_days = Column(Integer, default=30)
    history_record_frequency_hours = Column(Integer, default=24)
    
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
    imap_delete_processed = Column(Boolean, default=False)
    
    # Bounce handling provider & Webhook secret
    bounce_provider = Column(String, default="imap")
    bounce_webhook_token = Column(String, nullable=True)
    
    # Speed Limit Configuration
    mta_from_prefix = Column(String, default="noreply")
    speed_emails_per_hour = Column(Integer, default=500) # 0 means unlimited
    max_sending_threads = Column(Integer, default=10)
    double_opt_in = Column(Boolean, default=False)
    sending_ip_override = Column(String, nullable=True)
    retry_interval_minutes = Column(Integer, default=15)
    double_opt_in_subject = Column(String, default="Confirm Your Subscription")
    double_opt_in_body_blocks = Column(JSON, nullable=True)
    double_opt_in_body_html = Column(Text, nullable=True)
    email_footer_blocks = Column(JSON, nullable=True)
    email_footer_html = Column(Text, nullable=True)
    
    # History logs settings
    history_retention_days = Column(Integer, default=30)
    history_record_frequency_hours = Column(Integer, default=24)
    
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
    allowed_tenants = Column(JSON, default=list)
    auth_type = Column(String, default="local") # local, oidc
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
    form_settings = Column(JSON, default=dict)
    
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
    list_ids = Column(JSON, default=list)
    name = Column(String, index=True)
    subject = Column(String)
    preheader = Column(String, nullable=True)
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
    scheduled_send_at = Column(DateTime, nullable=True)
    
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

# History Logs Separate Database Engine
HISTORY_DATABASE_URL = os.getenv("HISTORY_DATABASE_URL")
if not HISTORY_DATABASE_URL:
    if DATABASE_URL.startswith("sqlite:///"):
        db_path = DATABASE_URL.replace("sqlite:///", "")
        db_dir = os.path.dirname(db_path)
        if not db_dir:
            db_dir = "."
        HISTORY_DATABASE_URL = f"sqlite:///{os.path.join(db_dir, 'polypress_history.db')}"
    else:
        HISTORY_DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'polypress_history.db')}"

history_engine = create_engine(
    HISTORY_DATABASE_URL,
    connect_args={"check_same_thread": False} if HISTORY_DATABASE_URL.startswith("sqlite") else {}
)
HistorySessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=history_engine)
HistoryBase = declarative_base()

class HistoricalMetric(HistoryBase):
    __tablename__ = "historical_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, index=True, nullable=True) # Null for system-wide metrics
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)
    subscriber_count = Column(Integer, default=0)
    emails_sent = Column(Integer, default=0)
    email_opens = Column(Integer, default=0)
    link_clicks = Column(Integer, default=0)
    bounces = Column(Integer, default=0)

class HistorySettings(HistoryBase):
    __tablename__ = "history_settings"
    id = Column(Integer, primary_key=True)
    schema_version = Column(Integer, default=CURRENT_HISTORY_SCHEMA_VERSION)

def get_history_db():
    db = HistorySessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    global SCHEMA_MISMATCH, DB_SCHEMA_VERSION, DB_HISTORY_SCHEMA_VERSION
    
    # 0. Storage Write Permissions Diagnostics Check
    if DATABASE_URL.startswith("sqlite:///"):
        db_path = DATABASE_URL.replace("sqlite:///", "")
        db_dir = os.path.dirname(db_path)
        if not db_dir:
            db_dir = "."
        else:
            try:
                os.makedirs(db_dir, exist_ok=True)
            except Exception as e:
                print(f"CRITICAL WARNING: Failed to create database directory '{db_dir}': {e}")
        
        # Test file write permissions
        try:
            test_file = os.path.join(db_dir, ".polypress_write_test")
            with open(test_file, "w") as f:
                f.write("write_test")
            os.remove(test_file)
            print(f"Diagnostics: Verified database directory '{db_dir}' is writable.")
        except Exception as e:
            print("\n" + "="*80)
            print(f"CRITICAL PERMISSION WARNING: The database directory '{db_dir}' is NOT writable!")
            print(f"Detailed Error: {e}")
            print("PolyPress will fail to persist any configuration changes or user updates!")
            print("Ensure that absolute host paths have the correct write permissions for the container.")
            print("="*80 + "\n")
            
    # 1. Create tables first (so schema_version column exists on new databases)
    Base.metadata.create_all(bind=engine)
    HistoryBase.metadata.create_all(bind=history_engine)
    
    # 2. Check if schema_version exists in database
    db_schema_version = 1
    try:
        with engine.begin() as conn:
            # Check global_settings table columns
            res = conn.execute(text("PRAGMA table_info(global_settings)")).fetchall()
            cols = [r[1] for r in res]
            
            # If schema_version column doesn't exist, we must create it first
            if "schema_version" not in cols:
                conn.execute(text("ALTER TABLE global_settings ADD COLUMN schema_version INTEGER DEFAULT 1"))
                
            # Now fetch the schema_version value
            res_val = conn.execute(text("SELECT schema_version FROM global_settings LIMIT 1")).fetchone()
            if res_val is not None and res_val[0] is not None:
                db_schema_version = int(res_val[0])
                DB_SCHEMA_VERSION = db_schema_version
    except Exception as e:
        print(f"Error checking DB schema version: {e}")
        
    # 2.5 Check if history_schema_version exists in history database
    db_history_schema_version = 1
    try:
        with history_engine.begin() as conn:
            # Check history_settings table info
            res = conn.execute(text("PRAGMA table_info(history_settings)")).fetchall()
            cols = [r[1] for r in res]
            
            if "schema_version" not in cols:
                conn.execute(text("ALTER TABLE history_settings ADD COLUMN schema_version INTEGER DEFAULT 1"))
                
            res_val = conn.execute(text("SELECT schema_version FROM history_settings LIMIT 1")).fetchone()
            if res_val is None:
                conn.execute(text(f"INSERT INTO history_settings (schema_version) VALUES ({CURRENT_HISTORY_SCHEMA_VERSION})"))
                db_history_schema_version = CURRENT_HISTORY_SCHEMA_VERSION
            else:
                db_history_schema_version = int(res_val[0])
            DB_HISTORY_SCHEMA_VERSION = db_history_schema_version
    except Exception as e:
        print(f"Error checking History DB version: {e}")
        
    # 3. Mismatch check
    if db_schema_version > CURRENT_SCHEMA_VERSION or db_history_schema_version > CURRENT_HISTORY_SCHEMA_VERSION:
        print(f"CRITICAL ERROR: Main Database version ({db_schema_version}) or History Database version ({db_history_schema_version}) is newer than code versions ({CURRENT_SCHEMA_VERSION} / {CURRENT_HISTORY_SCHEMA_VERSION})!")
        SCHEMA_MISMATCH = True
        DB_SCHEMA_VERSION = db_schema_version
        DB_HISTORY_SCHEMA_VERSION = db_history_schema_version
        return  # Block migrations and initialization
        
    # 4. If compatible, run dynamic column reconciliation for main database
    try:
        with engine.begin() as conn:
            inspector = inspect(engine)
            for table_name, table_obj in Base.metadata.tables.items():
                if not inspector.has_table(table_name):
                    continue
                
                existing_cols = {col["name"].lower(): col for col in inspector.get_columns(table_name)}
                
                for col_name, col_obj in table_obj.columns.items():
                    if col_name.lower() not in existing_cols:
                        col_type_str = str(col_obj.type).split('(')[0]
                        if "VARCHAR" in col_type_str.upper() or "STRING" in col_type_str.upper():
                            col_type_str = "VARCHAR"
                        elif "BOOLEAN" in col_type_str.upper():
                            col_type_str = "BOOLEAN"
                        elif "INTEGER" in col_type_str.upper():
                            col_type_str = "INTEGER"
                        elif "TEXT" in col_type_str.upper():
                            col_type_str = "TEXT"
                        elif "JSON" in col_type_str.upper():
                            col_type_str = "JSON"
                        elif "DATETIME" in col_type_str.upper():
                            col_type_str = "DATETIME"
                        
                        default_clause = ""
                        if col_obj.default is not None:
                            if hasattr(col_obj.default, 'arg') and not callable(col_obj.default.arg):
                                arg = col_obj.default.arg
                                if isinstance(arg, bool):
                                    default_clause = f" DEFAULT {1 if arg else 0}"
                                elif isinstance(arg, (int, float)):
                                    default_clause = f" DEFAULT {arg}"
                                elif isinstance(arg, str):
                                    default_clause = f" DEFAULT '{arg}'"
                        
                        alter_query = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type_str}{default_clause}"
                        print(f"Migrating schema: Running query '{alter_query}'")
                        conn.execute(text(alter_query))
                        
            # Update schema_version in DB to CURRENT_SCHEMA_VERSION after migrations complete
            conn.execute(text(f"UPDATE global_settings SET schema_version = {CURRENT_SCHEMA_VERSION}"))
            DB_SCHEMA_VERSION = CURRENT_SCHEMA_VERSION
    except Exception as migration_error:
        print(f"Database migration error: {migration_error}")

    # 4.5. If compatible, run dynamic column reconciliation for History DB
    try:
        with history_engine.begin() as conn:
            inspector = inspect(history_engine)
            for table_name, table_obj in HistoryBase.metadata.tables.items():
                if not inspector.has_table(table_name):
                    continue
                
                existing_cols = {col["name"].lower(): col for col in inspector.get_columns(table_name)}
                
                for col_name, col_obj in table_obj.columns.items():
                    if col_name.lower() not in existing_cols:
                        col_type_str = str(col_obj.type).split('(')[0]
                        if "VARCHAR" in col_type_str.upper() or "STRING" in col_type_str.upper():
                            col_type_str = "VARCHAR"
                        elif "BOOLEAN" in col_type_str.upper():
                            col_type_str = "BOOLEAN"
                        elif "INTEGER" in col_type_str.upper():
                            col_type_str = "INTEGER"
                        elif "TEXT" in col_type_str.upper():
                            col_type_str = "TEXT"
                        elif "JSON" in col_type_str.upper():
                            col_type_str = "JSON"
                        elif "DATETIME" in col_type_str.upper():
                            col_type_str = "DATETIME"
                        
                        default_clause = ""
                        if col_obj.default is not None:
                            if hasattr(col_obj.default, 'arg') and not callable(col_obj.default.arg):
                                arg = col_obj.default.arg
                                if isinstance(arg, bool):
                                    default_clause = f" DEFAULT {1 if arg else 0}"
                                elif isinstance(arg, (int, float)):
                                    default_clause = f" DEFAULT {arg}"
                                elif isinstance(arg, str):
                                    default_clause = f" DEFAULT '{arg}'"
                        
                        alter_query = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type_str}{default_clause}"
                        print(f"Migrating history schema: Running query '{alter_query}'")
                        conn.execute(text(alter_query))
                        
            conn.execute(text(f"UPDATE history_settings SET schema_version = {CURRENT_HISTORY_SCHEMA_VERSION}"))
            DB_HISTORY_SCHEMA_VERSION = CURRENT_HISTORY_SCHEMA_VERSION
    except Exception as history_migration_error:
        print(f"History Database migration error: {history_migration_error}")

    db = SessionLocal()
    try:
        # Seed settings if empty
        settings = db.query(GlobalSettings).first()
        if not settings:
            settings = GlobalSettings(app_name="PolyPress", schema_version=CURRENT_SCHEMA_VERSION)
            db.add(settings)
            db.commit()
    finally:
        db.close()
