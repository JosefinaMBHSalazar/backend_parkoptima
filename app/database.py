import os
from pathlib import Path
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import declarative_base, sessionmaker
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── FIX: Set MySQL as default ──
# First, check if DATABASE_URL is set in environment
DATABASE_URL = os.getenv("DATABASE_URL", "")

# If not set, use MySQL as default
if not DATABASE_URL:
    # Use MySQL by default
    DATABASE_URL = "mysql+pymysql://root:@localhost/parkoptima"
    logger.info(f"Using default MySQL database: {DATABASE_URL}")
else:
    logger.info(f"Using database from environment: {DATABASE_URL}")

# Connection arguments
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# Create engine with fallback
try:
    engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
    # Test connection
    with engine.connect() as conn:
        logger.info("✅ Database connection successful")
except Exception as e:
    logger.error(f"❌ Failed to connect to database: {e}")
    # If MySQL fails, fallback to SQLite
    if DATABASE_URL.startswith("mysql"):
        default_db_path = Path(__file__).resolve().parent.parent / "parkoptima.db"
        fallback_url = f"sqlite:///{default_db_path}"
        logger.info(f"Falling back to SQLite at: {default_db_path}")
        engine = create_engine(fallback_url, connect_args={"check_same_thread": False}, pool_pre_ping=True)
        # Update DATABASE_URL to reflect fallback
        DATABASE_URL = fallback_url
    else:
        raise

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_tables():
    """Create all tables if they don't exist, and handle schema migrations."""
    from .models import (
        OwnerProfile, SystemSettings, ParkingSession, PaymentTransaction,
        User, VehicleRegistration, VehicleAccount, AuditLog, WalletBalance
    )
    
    inspector = inspect(engine)
    
    #Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Tables created/verified")
    
    # Check if VehicleAccount has email column
    with engine.connect() as conn:
        try:
            # Get column info for vehicle_accounts
            columns = inspector.get_columns('vehicle_accounts')
            column_names = [col['name'] for col in columns]
            
            if 'email' not in column_names:
                logger.info("Adding 'email' column to vehicle_accounts...")
                
                # For SQLite, we need to use ALTER TABLE
                if DATABASE_URL.startswith("sqlite"):
                    # SQLite doesn't support adding columns with constraints easily
                    conn.execute("ALTER TABLE vehicle_accounts ADD COLUMN email VARCHAR(120)")
                    conn.commit()
                    logger.info("✅ Added 'email' column to vehicle_accounts (SQLite)")
                else:
                    # For MySQL/PostgreSQL
                    conn.execute("ALTER TABLE vehicle_accounts ADD COLUMN email VARCHAR(120) NULL")
                    conn.commit()
                    logger.info("✅ Added 'email' column to vehicle_accounts (MySQL)")
            else:
                logger.info("✅ 'email' column already exists in vehicle_accounts")
                
        except Exception as e:
            logger.warning(f"Could not verify/modify vehicle_accounts table: {e}")