import os
from pathlib import Path
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import declarative_base, sessionmaker
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Require DATABASE_URL from the environment (loaded via .env)
# ─────────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Copy .env.example to .env and configure "
        "the MySQL connection string before starting the backend."
    )

logger.info(f"Using database from environment: {DATABASE_URL}")

# ─────────────────────────────────────────────────────────────────────
# Connection arguments
# ─────────────────────────────────────────────────────────────────────
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# ─────────────────────────────────────────────────────────────────────
# Create engine. Fail loudly if the DB isn't reachable — no silent
# SQLite fallback, because that hides misconfiguration.
# ─────────────────────────────────────────────────────────────────────
try:
    engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
    with engine.connect() as conn:
        logger.info("✅ Database connection successful")
except Exception as e:
    logger.error(f"❌ Failed to connect to database: {e}")
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

    # Create tables if they don't exist
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