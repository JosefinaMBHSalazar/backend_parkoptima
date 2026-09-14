import os
from dotenv import load_dotenv

load_dotenv()

from datetime import datetime, timezone
import re
from typing import List, Optional

import bcrypt
import pytz
from fastapi import Depends, FastAPI, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session 
from sqlalchemy import inspect, text

from .database import Base, SessionLocal, engine, get_db
from .models import (
    AuditLog,
    OwnerProfile,
    ParkingSession,
    PaymentTransaction,
    SystemSettings,
    User,
    VehicleAccount,
    VehicleRegistration,
    WalletBalance,
    Vehicle,  
)
from .schemas import (
    AuditLogCreate,
    AuditLogResponse,
    LoginRequest,
    OwnerProfileCreate,
    OwnerProfileResponse,
    OwnerProfileUpdate,
    ParkingSessionBase,
    ProfileUpdate,
    ParkingSessionResponse,
    ParkingSessionUpdate,
    PaymentMethodRequest,
    ScanRequest,
    ScanResponse,
    SystemSettingsBase,
    SystemSettingsResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
    VehicleAccountCreate,
    VehicleAccountLogin,
    VehicleAccountResponse,
    VehicleListItem,
    VehiclesResponse,
    VehicleRegistrationCreate,
    VehicleRegistrationResponse,
    WalletDeductRequest,
    WalletTopUpRequest,
    PasswordChangeRequest,
    PasswordChangeResponse,
    PasswordVerifyRequest,
    PasswordVerifyResponse,
    VehicleCreate,  
)
from .services import analyze_scan_image, get_or_create_owner_profile, get_or_create_settings
from .analytics_engine import build_natural_language_summary
import asyncio

from .routes import password_reset, receipts

from .auth import ( authenticate_vehicle_owner, authenticate_user, _verify_password, InactiveAccountError,)
from .pages.ownerdashboard import get_owner_dashboard_data
from .pages.owneroverview import get_owner_overview_data
from .pages.attendantdashboard import get_attendant_dashboard_data
from .pages.vehicleownerdashboard import get_vehicle_owner_dashboard_data
from .seed import seed_default_accounts
from .pages.balance import get_balance_summary
from .pages.monitoring import get_live_monitor_data
from .pages.payments import get_payments
from .pages.audit_trail import get_audit_trail_data
from .audit_crud import create_audit_log, get_audit_logs
from .pages.balance_result import get_balance_result_data
from .pages.check_balance import get_check_balance_data
from .pages.login_page import get_login_page_data
from .pages.logout_modal import get_logout_modal_data
from .pages.my_vehicle import get_my_vehicle_data
from .pages.profile_page import get_profile_page_data
from .pages.quick_actions import get_quick_actions_data
from .pages.register_page import get_register_page_data
from .pages.reports import get_reports_data
from .pages.scan_entry import get_scan_entry_data
from .pages.scan_exit import get_scan_exit_data
from .pages.signup_form import get_signup_form_data
from .pages.system_settings import get_system_settings_data
from .pages.transaction_log import get_transaction_log_data
from .users_crud import delete_user, get_users, update_user
from .vehicles import get_vehicles
from .pages.wallet import (
    deduct_wallet, 
    get_wallet_balance, 
    top_up_wallet,
    get_wallet_balance_by_plate,
    get_or_create_wallet_balance,
)
from .pages.vehicle_dashboard import get_vehicle_dashboard_data
from .pages.vehicle_owner_portal import get_vehicle_owner_portal_data
from .pages.vehicle_registration import get_vehicle_registration_data
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Helper function to migrate database schema ──
def migrate_database():
    """Add missing columns to existing tables."""
    inspector = inspect(engine)
    
    # Check if vehicle_accounts table has email column
    try:
        columns = inspector.get_columns('vehicle_accounts')
        column_names = [col['name'] for col in columns]
        
        if 'email' not in column_names:
            logger.info("Adding 'email' column to vehicle_accounts table...")
            with engine.connect() as conn:
                # SQLite doesn't support adding columns with IF NOT EXISTS
                # So we check first
                if engine.name == 'sqlite':
                    conn.execute(text("ALTER TABLE vehicle_accounts ADD COLUMN email VARCHAR(120)"))
                else:
                    conn.execute(text("ALTER TABLE vehicle_accounts ADD COLUMN email VARCHAR(120) NULL"))
                conn.commit()
            logger.info("✅ Added 'email' column to vehicle_accounts")
        else:
            logger.info("✅ 'email' column already exists in vehicle_accounts")
    except Exception as e:
        logger.warning(f"Could not verify vehicle_accounts table: {e}")
    
    # Check if vehicles table exists - if not, create it
    try:
        inspector = inspect(engine)
        if 'vehicles' not in inspector.get_table_names():
            logger.info("Creating 'vehicles' table...")
            Base.metadata.create_all(bind=engine)
            logger.info("✅ 'vehicles' table created")
    except Exception as e:
        logger.warning(f"Could not create vehicles table: {e}")

    # ── parking_sessions: plate_type, entry_method, created_by ──
    try:
        columns = inspector.get_columns('parking_sessions')
        col_names = [c['name'] for c in columns]

        with engine.connect() as conn:
            if 'plate_type' not in col_names:
                logger.info("Adding 'plate_type' column to parking_sessions...")
                conn.execute(text("ALTER TABLE parking_sessions ADD COLUMN plate_type VARCHAR(20) DEFAULT 'registered'"))
                conn.commit()
                logger.info("✅ Added 'plate_type'")

            if 'entry_method' not in col_names:
                logger.info("Adding 'entry_method' column to parking_sessions...")
                conn.execute(text("ALTER TABLE parking_sessions ADD COLUMN entry_method VARCHAR(20) DEFAULT 'scan'"))
                conn.commit()
                logger.info("✅ Added 'entry_method'")

            if 'created_by' not in col_names:
                logger.info("Adding 'created_by' column to parking_sessions...")
                conn.execute(text("ALTER TABLE parking_sessions ADD COLUMN created_by VARCHAR(120)"))
                conn.commit()
                logger.info("✅ Added 'created_by'")
    except Exception as e:
        logger.warning(f"Could not add parking_sessions columns: {e}")

    # ── parking_sessions: balance_after for receipt snapshots ──
    try:
        columns = [c['name'] for c in inspector.get_columns('parking_sessions')]
        if 'balance_after' not in columns:
            logger.info("Adding 'balance_after' column to parking_sessions...")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE parking_sessions ADD COLUMN balance_after FLOAT"))
                conn.commit()
            logger.info("✅ Added 'balance_after'")
        else:
            logger.info("✅ 'balance_after' column already exists in parking_sessions")
    except Exception as e:
        logger.warning(f"Could not add parking_sessions.balance_after: {e}")

    # ── parking_sessions: drop the deprecated 'slot' column ──
    try:
        columns = [c['name'] for c in inspector.get_columns('parking_sessions')]
        if 'slot' in columns:
            logger.info("Dropping 'slot' column from parking_sessions...")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE parking_sessions DROP COLUMN slot"))
                conn.commit()
            logger.info("✅ Dropped 'slot'")
        else:
            logger.info("✅ 'slot' column already dropped from parking_sessions")
    except Exception as e:
        logger.warning(f"Could not drop parking_sessions.slot: {e}")

Base.metadata.create_all(bind=engine)

app = FastAPI(title="ParkOptima Owner Backend", version="1.0.0")


# Simple WebSocket connection manager for broadcasting events
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        await websocket.send_json(message)

    async def broadcast(self, message: dict):
        to_remove = []
        for conn in list(self.active_connections):
            try:
                await conn.send_json(message)
            except Exception:
                to_remove.append(conn)
        for r in to_remove:
            self.disconnect(r)


manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Echo/ping support: client may send ping messages with timestamp
            data = await websocket.receive_json()
            if isinstance(data, dict) and data.get('type') == 'ping' and 'ts' in data:
                await manager.send_personal_message({'type': 'pong', 'ts': data['ts'], 'server_ts': datetime.utcnow().isoformat()}, websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


def validate_signup_credentials(password: str, contact: Optional[str] = None) -> None:
    if not re.fullmatch(r"(?=.{6,}$)(?=.*\d)(?=.*[^A-Za-z0-9]).*", password):
        raise HTTPException(status_code=422, detail="Password must have at least 6 characters, 1 number, and 1 special character")
    if contact is not None and not re.fullmatch(r"\d{10,11}", contact):
        raise HTTPException(status_code=422, detail="Contact number must be 10-11 digits")

# Allow the Vite dev server (and other local frontends) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(password_reset.router)
app.include_router(receipts.router)

# ────── Timezone Helper ──────
MANILA_TZ = pytz.timezone('Asia/Manila')

def ensure_utc(dt):
    """Ensure a datetime is timezone-aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return pytz.UTC.localize(dt)
    return dt.astimezone(pytz.UTC)

def convert_to_manila(dt):
    """Convert a datetime to Manila timezone for display."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(MANILA_TZ)

@app.on_event("startup")
def _seed_on_startup() -> None:
    # First, migrate the database schema
    migrate_database()
    
    db = SessionLocal()
    try:
        seed_default_accounts(db)
    finally:
        db.close()


@app.get("/health")
def health_check():
    return {"status": "ok"}


def _api_normalize_vehicle_type(vehicle_type: Optional[str]) -> str:
    """Collapse backend ``vehicle_type`` values to the UI vocabulary."""
    if not vehicle_type:
        return "motor"
    vt = vehicle_type.lower()
    if vt in ("4_wheels", "4wheels", "four_wheel", "4 wheels") or "four" in vt or "4wheel" in vt:
        return "4wheels"
    return "motor"


def resolve_wallet_owner_plate(db: Session, plate_number: str) -> Optional[str]:
    """For a given plate, return the plate whose wallet actually holds the
    balance.

    Resolution order:
      1. The plate itself, if it's already a primary vehicle in `users`.
      2. The owner's primary plate, if the plate is in `vehicles` as a
         non-primary vehicle.
      3. None — the plate isn't registered anywhere (caller should fall
         back to creating its own wallet row).
    """
    if not plate_number:
        return None
    plate = plate_number.replace(" ", "").upper()

    # 1️⃣ Primary vehicle in users table
    user = db.query(User).filter(User.plate_number == plate).first()
    if user:
        return user.plate_number  # its own wallet

    # 2️⃣ Additional vehicle in vehicles table
    vehicle = db.query(Vehicle).filter(Vehicle.plate_number == plate).first()
    if vehicle:
        # Find the owner
        owner = db.query(User).filter(User.id == vehicle.user_id).first()
        if owner and owner.plate_number:
            return owner.plate_number  # primary plate = source of truth
        # No primary plate on file — fall through
    return None


def snapshot_session_balance(db: Session, session: ParkingSession) -> None:
    """Record the wallet balance onto the session row *right now*.

    Call this immediately after a payment (or exit/unpaid confirmation)
    is committed. Safe to call multiple times — it just overwrites.

    Never raises: a snapshot failure must not break the payment flow.
    """
    if session is None:
        return
    try:
        wallet_plate = (
            resolve_wallet_owner_plate(db, session.plate_number)
            or session.plate_number
        )
        wallet = db.query(WalletBalance).filter(
            WalletBalance.plate_number == wallet_plate
        ).first()
        session.balance_after = float(wallet.balance) if wallet else 0.0
        db.add(session)
        db.commit()
        db.refresh(session)
        logger.info(
            f"📸 Snapshot: session {session.id} balance_after = {session.balance_after}"
        )
    except Exception as e:
        # Never let a snapshot failure break the payment flow
        db.rollback()
        logger.warning(f"Could not snapshot balance for session {session.id}: {e}")


@app.get("/owner/profile", response_model=OwnerProfileResponse)
def get_owner_profile(db: Session = Depends(get_db)):
    profile = get_or_create_owner_profile(db)
    return profile


@app.put("/owner/profile", response_model=OwnerProfileResponse)
def update_owner_profile(payload: OwnerProfileUpdate, db: Session = Depends(get_db)):
    profile = get_or_create_owner_profile(db)
    if payload.full_name is not None:
        profile.full_name = payload.full_name
    if payload.email is not None:
        profile.email = payload.email
    if payload.image_url is not None:
        profile.image_url = payload.image_url
    if payload.password:
        profile.password_hash = bcrypt.hashpw(
            payload.password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
    db.commit()
    db.refresh(profile)
    return profile


@app.get("/owner/sessions", response_model=List[ParkingSessionResponse])
def list_sessions(db: Session = Depends(get_db)):
    sessions = db.query(ParkingSession).order_by(ParkingSession.entry_time.desc()).all()
    return sessions


@app.post("/owner/sessions", response_model=ParkingSessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(payload: ParkingSessionBase, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    # Duplicate/open-session check: prevent creating a new entry if the same plate is already parked
    existing = db.query(ParkingSession).filter(
        ParkingSession.plate_number == payload.plate_number.upper(),
        ParkingSession.status == 'parked'
    ).first()
    if existing:
        # Log the duplicate attempt and broadcast audit
        try:
            entry = create_audit_log(db, user_id=None, user_email=None, user_role='attendant', action_type='duplicate_entry_attempt', reference_id=str(existing.id), details=f"Attempt to create duplicate session for plate {payload.plate_number}")
            try:
                asyncio.create_task(manager.broadcast({'type': 'audit', 'audit': {
                    'id': entry.id,
                    'user_id': entry.user_id,
                    'user_email': entry.user_email,
                    'user_role': entry.user_role,
                    'action_type': entry.action_type,
                    'reference_id': entry.reference_id,
                    'details': entry.details,
                    'timestamp': entry.timestamp.isoformat() if entry.timestamp is not None else None,
                }}))
            except Exception:
                pass
        except Exception:
            pass
        raise HTTPException(status_code=409, detail=f"Active session already exists for plate {payload.plate_number}")

    session = ParkingSession(
        plate_number=payload.plate_number.upper(),
        vehicle_type=payload.vehicle_type,
        fee=payload.fee or (settings.motor_fee if payload.vehicle_type == "motor" else settings.four_wheel_fee),
        payment_method=payload.payment_method,
        status=payload.status,
        notes=payload.notes,
        entry_time=datetime.now(pytz.UTC),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    if session.payment_method:
        snapshot_session_balance(db, session)

    # Broadcast session creation to connected WS clients
    try:
        asyncio.create_task(manager.broadcast({
            'type': 'session_created',
            'session': {
                'id': session.id,
                'plate_number': session.plate_number,
                'status': session.status,
                'entry_time': session.entry_time.isoformat() if session.entry_time is not None else None,
                'vehicle_type': session.vehicle_type,
            }
        }))
    except Exception:
        pass
    return session


@app.post("/owner/scan", response_model=ScanResponse)
def scan_vehicle(payload: ScanRequest, db: Session = Depends(get_db)):
    """Scan a vehicle and return the detected plate information.
    This does NOT create a session - it only detects the plate.
    """
    # Pass the db session to check for registered vehicle type
    plate_number, confidence, vehicle_type = analyze_scan_image(payload.image_base64, db)
    # Return the detected plate without creating a session
    return ScanResponse(
        plate_number=plate_number, 
        confidence=confidence, 
        vehicle_type=vehicle_type,
        session_id=None  # No session created yet
    )


@app.post("/owner/sessions/{session_id}/payment", response_model=ParkingSessionResponse)
def update_payment(session_id: int, payload: PaymentMethodRequest, db: Session = Depends(get_db)):
    session = db.query(ParkingSession).filter(ParkingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    # Validate fee matches current system settings to avoid wrong charge
    settings = get_or_create_settings(db)
    expected_fee = settings.motor_fee if session.vehicle_type == "motor" else settings.four_wheel_fee
    if abs((session.fee or 0) - (expected_fee or 0)) > 0.01:
        # Log mismatch and broadcast audit
        try:
            entry = create_audit_log(db, user_id=None, user_email=None, user_role='attendant', action_type='payment_fee_mismatch', reference_id=str(session.id), details=f"Session fee {session.fee} does not match expected {expected_fee}")
            try:
                asyncio.create_task(manager.broadcast({'type': 'audit', 'audit': {
                    'id': entry.id,
                    'user_id': entry.user_id,
                    'user_email': entry.user_email,
                    'user_role': entry.user_role,
                    'action_type': entry.action_type,
                    'reference_id': entry.reference_id,
                    'details': entry.details,
                    'timestamp': entry.timestamp.isoformat() if entry.timestamp is not None else None,
                }}))
            except Exception:
                pass
        except Exception:
            pass
        raise HTTPException(status_code=409, detail="Session fee does not match current system settings")

    # Prevent duplicate payment transactions (same session + method)
    existing_tx = db.query(PaymentTransaction).filter(PaymentTransaction.session_id == session.id, PaymentTransaction.method == payload.method).first()
    if existing_tx:
        try:
            entry = create_audit_log(db, user_id=None, user_email=None, user_role='attendant', action_type='duplicate_payment_attempt', reference_id=str(session.id), details=f"Duplicate payment attempt: method={payload.method}")
            try:
                asyncio.create_task(manager.broadcast({'type': 'audit', 'audit': {
                    'id': entry.id,
                    'user_id': entry.user_id,
                    'user_email': entry.user_email,
                    'user_role': entry.user_role,
                    'action_type': entry.action_type,
                    'reference_id': entry.reference_id,
                    'details': entry.details,
                    'timestamp': entry.timestamp.isoformat() if entry.timestamp is not None else None,
                }}))
            except Exception:
                pass
        except Exception:
            pass
        raise HTTPException(status_code=409, detail="Payment for this session using the same method already exists")

    session.payment_method = payload.method
    # Don't change status here - let the exit process handle it
    db.add(session)
    db.commit()
    db.refresh(session)

    transaction = PaymentTransaction(session_id=session.id, amount=session.fee, method=payload.method)
    db.add(transaction)
    db.commit()


    snapshot_session_balance(db, session)

    # Broadcast session update with payment transaction
    try:
        asyncio.create_task(manager.broadcast({
            'type': 'session_updated',
            'session': {
                'id': session.id,
                'plate_number': session.plate_number,
                'status': session.status,
                'payment_method': session.payment_method,
            },
            'transaction': {
                'id': transaction.id,
                'amount': transaction.amount,
                'method': transaction.method,
                'created_at': transaction.created_at.isoformat() if hasattr(transaction, 'created_at') and transaction.created_at is not None else None,
            }
        }))
    except Exception:
        pass
    return session


@app.get("/owner/reports")
def get_reports(db: Session = Depends(get_db)):
    sessions = db.query(ParkingSession).all()
    paid = [s for s in sessions if s.payment_method]
    unpaid = [s for s in sessions if not s.payment_method]
    revenue = sum(s.fee for s in paid)
    return {
        "total_sessions": len(sessions),
        "paid_sessions": len(paid),
        "unpaid_sessions": len(unpaid),
        "revenue": revenue,
        "generated_at": datetime.utcnow().isoformat(),
    }


@app.get("/owner/overview")
def owner_overview(db: Session = Depends(get_db)):
    return get_owner_overview_data(db)


@app.get("/owner/dashboard")
def owner_dashboard(db: Session = Depends(get_db)):
    return get_owner_dashboard_data(db)


@app.get("/attendant/dashboard")
def attendant_dashboard(db: Session = Depends(get_db)):
    return get_attendant_dashboard_data(db)


@app.get("/vehicle-owner/dashboard")
def vehicle_owner_dashboard(db: Session = Depends(get_db)):
    return get_vehicle_owner_dashboard_data(db)


# ── Authentication ─────────────────────────────────────────────

@app.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    try:
        user = authenticate_user(db, payload.email, payload.password)
    except InactiveAccountError as exc:
        # Distinct 403 so the user knows their account is disabled,
        # instead of the generic "invalid credentials" 401.
        raise HTTPException(
            status_code=403,
            detail="Your account has been deactivated. Please contact the owner.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid email or password") from exc

    ROLE_LABELS = {
        "owner": "Parking Owner",
        "attendant": "Parking Attendant",
        "vehicle_owner": "Vehicle Owner",
    }

    if payload.role and payload.role != user["role"]:
        friendly = ROLE_LABELS.get(payload.role, payload.role)
        raise HTTPException(
            status_code=403,
            detail=f"This account is not registered as a {friendly}. Please use the correct login portal.",
        )

    return {
        "message": "Login successful",
        "user": user,
        "token": f"parkoptima-{user['role']}-{user['id']}",
    }


# ── Password Management Endpoints ─────────────────────────────

@app.post("/auth/verify-password", response_model=PasswordVerifyResponse)
def verify_password(payload: PasswordVerifyRequest, db: Session = Depends(get_db)):
    """Verify if the provided password matches the user's current password."""
    try:
        # Try to authenticate the user
        user = authenticate_user(db, payload.email, payload.password)
        return PasswordVerifyResponse(valid=True, user_id=user["id"])
    except ValueError:
        return PasswordVerifyResponse(valid=False, user_id=None)


@app.post("/auth/change-password", response_model=PasswordChangeResponse)
def change_password(payload: PasswordChangeRequest, db: Session = Depends(get_db)):
    """Change a user's password after verifying the current password."""
    try:
        # Normalize email
        normalized_email = payload.email.strip().lower()
        logger.info(f"Attempting to change password for: {normalized_email}")
        
        # First, verify the current password
        user = authenticate_user(db, normalized_email, payload.current_password)
        logger.info(f"Password verified for user: {normalized_email}")
        
        # Get the user ID from the authentication result
        user_id = user.get("id")
        
        # FIRST: Try to find and update in the users table
        db_user = db.query(User).filter(User.email == normalized_email).first()
        if db_user:
            logger.info(f"Found user in users table: {db_user.email}, role: {db_user.role}")
            db_user.password_hash = bcrypt.hashpw(
                payload.new_password.encode("utf-8"), 
                bcrypt.gensalt()
            ).decode("utf-8")
            db.commit()
            logger.info(f"Password updated for user in users table: {db_user.email}")
            return PasswordChangeResponse(
                message="Password updated successfully", 
                user_id=db_user.id
            )
        
        # SECOND: Try owner_profiles table as fallback
        owner_profile = db.query(OwnerProfile).filter(OwnerProfile.email == normalized_email).first()
        if owner_profile:
            logger.info(f"Found user in owner_profiles table: {owner_profile.email}")
            owner_profile.password_hash = bcrypt.hashpw(
                payload.new_password.encode("utf-8"), 
                bcrypt.gensalt()
            ).decode("utf-8")
            db.commit()
            logger.info(f"Password updated for owner profile: {owner_profile.email}")
            return PasswordChangeResponse(
                message="Password updated successfully", 
                user_id=owner_profile.id
            )
        
        # If we get here, the user wasn't found in either table
        logger.warning(f"User not found in any table: {normalized_email}")
        raise HTTPException(status_code=404, detail="User not found")
        
    except ValueError as exc:
        logger.error(f"Password verification failed: {str(exc)}")
        raise HTTPException(status_code=401, detail="Current password is incorrect") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error changing password: {str(exc)}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/vehicle-owner/signup", response_model=VehicleAccountResponse, status_code=status.HTTP_201_CREATED)
def vehicle_owner_signup(payload: VehicleAccountCreate, db: Session = Depends(get_db)):
    plate = payload.plate_number.strip().upper()
    if not plate:
        raise HTTPException(status_code=400, detail="Plate number is required")
    if not payload.pin or len(payload.pin) < 4:
        raise HTTPException(status_code=400, detail="PIN must be at least 4 digits")

    existing = db.query(VehicleAccount).filter(VehicleAccount.plate_number == plate).first()
    if existing:
        raise HTTPException(status_code=400, detail="Plate number is already registered")
    
    # Check email uniqueness if provided
    if payload.email:
        email_lower = payload.email.strip().lower()
        existing_email = db.query(VehicleAccount).filter(VehicleAccount.email == email_lower).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email is already registered")
    else:
        email_lower = None

    pin_hash = bcrypt.hashpw(payload.pin.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    account = VehicleAccount(
        plate_number=plate,
        email=email_lower,
        pin_hash=pin_hash,
        owner_name=payload.owner_name,
        contact=payload.contact,
        vehicle_type=payload.vehicle_type,
        brand=payload.brand,
        balance=0.0,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@app.post("/vehicle-owner/login")
def vehicle_owner_login(payload: VehicleAccountLogin, db: Session = Depends(get_db)):
    try:
        account = authenticate_vehicle_owner(db, plate_number=payload.plate_number, email=payload.email, pin=payload.pin)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid credentials") from exc

    return {
        "message": "Login successful",
        "user": account,
        "token": f"parkoptima-vehicle-{account['id']}",
    }


@app.post("/vehicle-owner/balance")
def vehicle_owner_balance(payload: VehicleAccountLogin, db: Session = Depends(get_db)):
    try:
        account = authenticate_vehicle_owner(db, plate_number=payload.plate_number, email=payload.email, pin=payload.pin)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="No account found") from exc

    return {
        "balance": account["balance"],
        "plateNumber": account["plate_number"],
        "ownerName": account["owner_name"],
        "vehicleType": account["vehicle_type"],
        "brand": account["brand"],
        "contact": account["contact"],
    }


@app.get("/balance/check")
def check_balance(db: Session = Depends(get_db)):
    return get_balance_summary(db)


@app.get("/live-monitor")
def live_monitor(db: Session = Depends(get_db)):
    return get_live_monitor_data(db)


@app.get("/payments")
def payments(db: Session = Depends(get_db)):
    return get_payments(db)


@app.get("/audit-trail")
def audit_trail(db: Session = Depends(get_db)):
    return get_audit_trail_data(db)


@app.get("/balance-result")
def balance_result(db: Session = Depends(get_db)):
    return get_balance_result_data(db)


@app.get("/check-balance")
def check_balance_page(db: Session = Depends(get_db)):
    return get_check_balance_data(db)


@app.get("/login-page")
def login_page(db: Session = Depends(get_db)):
    return get_login_page_data(db)


@app.get("/logout-modal")
def logout_modal():
    return get_logout_modal_data()


@app.get("/my-vehicle")
def my_vehicle(db: Session = Depends(get_db)):
    return get_my_vehicle_data(db)


@app.get("/profile-page")
def profile_page(db: Session = Depends(get_db)):
    return get_profile_page_data(db)


@app.get("/quick-actions")
def quick_actions():
    return get_quick_actions_data()


@app.get("/register-page")
def register_page():
    return get_register_page_data()


@app.get("/reports-page")
def reports_page(db: Session = Depends(get_db)):
    return get_reports_data(db)


@app.get("/scan-entry")
def scan_entry(db: Session = Depends(get_db)):
    return get_scan_entry_data(db)


@app.post("/scan-entry")
def scan_entry_image(payload: dict, db: Session = Depends(get_db)):
    return get_scan_entry_data(db, payload.get("image_base64"))


@app.get("/scan-exit")
def scan_exit(db: Session = Depends(get_db)):
    return get_scan_exit_data(db)


@app.post("/scan-exit")
def scan_exit_image(payload: dict, db: Session = Depends(get_db)):
    return get_scan_exit_data(db, payload.get("image_base64"))


@app.get("/signup-form")
def signup_form():
    return get_signup_form_data()


@app.post("/register")
def register_user(payload: UserCreate, db: Session = Depends(get_db)) -> UserResponse:
    validate_signup_credentials(payload.password, payload.contact)
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    if payload.role not in ["owner", "attendant", "vehicle_owner"]:
        raise HTTPException(status_code=400, detail="Invalid role")

    password_hash = bcrypt.hashpw(payload.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user = User(
        full_name=payload.full_name,
        email=payload.email,
        password_hash=password_hash,
        role=payload.role,
        contact=payload.contact,
        plate_number=payload.plate_number,
        vehicle_type=payload.vehicle_type,
        brand=payload.brand,
        model=payload.model,
        color=payload.color,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        contact=user.contact,
        plate_number=user.plate_number,
        vehicle_type=user.vehicle_type,
        brand=user.brand,
        model=user.model,
        color=user.color,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@app.post("/signup")
def signup_user(payload: UserCreate, db: Session = Depends(get_db)) -> UserResponse:
    validate_signup_credentials(payload.password, payload.contact)
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    if payload.role != "vehicle_owner":
        raise HTTPException(status_code=400, detail="Signup form is for vehicle owners only")

    password_hash = bcrypt.hashpw(payload.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user = User(
        full_name=payload.full_name,
        email=payload.email,
        password_hash=password_hash,
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@app.post("/vehicle-registration")
def register_vehicle(payload: VehicleRegistrationCreate, db: Session = Depends(get_db)) -> VehicleRegistrationResponse:
    registration = VehicleRegistration(
        plate_number=payload.plate_number.upper(),
        vehicle_type=payload.vehicle_type,
        owner_name=payload.owner_name,
        user_id=payload.user_id,
    )
    db.add(registration)
    db.commit()
    db.refresh(registration)
    return VehicleRegistrationResponse(
        id=registration.id,
        plate_number=registration.plate_number,
        vehicle_type=registration.vehicle_type,
        owner_name=registration.owner_name,
        user_id=registration.user_id,
        created_at=registration.created_at,
        updated_at=registration.updated_at,
    )


@app.get("/system-settings")
def system_settings(db: Session = Depends(get_db)):
    return get_system_settings_data(db)


@app.get("/transaction-log")
def transaction_log(db: Session = Depends(get_db)):
    return get_transaction_log_data(db)


@app.get("/vehicle-dashboard")
def vehicle_dashboard(db: Session = Depends(get_db)):
    return get_vehicle_dashboard_data(db)


@app.get("/vehicle-owner-portal")
def vehicle_owner_portal(db: Session = Depends(get_db)):
    return get_vehicle_owner_portal_data(db)


@app.get("/vehicle-registration")
def vehicle_registration():
    return get_vehicle_registration_data()


# ──────────────────────────────────────────────────────────────
# API routes consumed by the React frontend (vite proxies /api → backend)
# ──────────────────────────────────────────────────────────────
# NOTE: `_api_normalize_vehicle_type`, `resolve_wallet_owner_plate`, and
# `snapshot_session_balance` are now defined near the top of the file so
# the helpers can call each other without forward references.


@app.get("/api/health")
def api_health_check():
    return {"status": "ok"}


# ── Sessions ─────────────────────────────────────────────────
@app.get("/api/sessions", response_model=List[ParkingSessionResponse])
def api_list_sessions(db: Session = Depends(get_db)):
    sessions = db.query(ParkingSession).order_by(ParkingSession.entry_time.desc()).all()
    
    # Convert times to Manila timezone for display
    for session in sessions:
        if session.entry_time:
            session.entry_time = convert_to_manila(session.entry_time)
        if session.exit_time:
            session.exit_time = convert_to_manila(session.exit_time)
    
    return sessions


@app.post("/api/sessions", response_model=ParkingSessionResponse, status_code=status.HTTP_201_CREATED)
def api_create_session(payload: ParkingSessionBase, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)

    plate_type = (payload.plate_type or "registered").lower()
    if plate_type not in ("registered", "temporary", "no_plate"):
        raise HTTPException(status_code=422, detail="Invalid plate_type")

    # ── Auto-generate an identifier for no-plate entries ──
    plate_number = (payload.plate_number or "").strip().upper()

    # Treat placeholder values as "empty" for no_plate entries so the
    # backend always generates a fresh, unique NOPLATE-YYYYMMDD-NNNN.
    PLACEHOLDER_PLATES = {"AUTO", "AUTO-ID", "NO_PLATE", "NOPLATE", "N/A", "NA", "-"}

    if plate_type == "no_plate" and (not plate_number or plate_number in PLACEHOLDER_PLATES):
        today = datetime.now(MANILA_TZ).strftime("%Y%m%d")
        existing_today = db.query(ParkingSession).filter(
            ParkingSession.plate_type == "no_plate",
            ParkingSession.plate_number.like(f"NOPLATE-{today}-%")
        ).count()
        plate_number = f"NOPLATE-{today}-{existing_today + 1:04d}"

    if not plate_number:
        raise HTTPException(status_code=422, detail="plate_number is required")

    # ── Format check only applies to registered plates from scan flow ──
    if plate_type == "registered" and payload.entry_method == "scan":
        normalized = plate_number.replace(" ", "").upper()
        if not re.match(r"^[A-Z0-9]{4,8}$", normalized):
            raise HTTPException(status_code=422, detail="Invalid registered plate format")

    # ── Duplicate active-session check ──
    existing = db.query(ParkingSession).filter(
        ParkingSession.plate_number == plate_number,
        ParkingSession.status == 'parked'
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Vehicle {plate_number} is already parked (Session ID: {existing.id})"
        )

    vehicle_type = _api_normalize_vehicle_type(payload.vehicle_type)
    fee = payload.fee
    if fee is None or fee == 0:
        fee = settings.motor_fee if vehicle_type == "motor" else settings.four_wheel_fee

    # ── Server-side capacity guard ──
    parked_count = db.query(ParkingSession).filter(ParkingSession.status == "parked").count()
    if settings.parking_capacity and parked_count >= settings.parking_capacity:
        raise HTTPException(
            status_code=409,
            detail=f"Facility is full ({parked_count}/{settings.parking_capacity}). Entry blocked."
        )

    session = ParkingSession(
        plate_number=plate_number,
        vehicle_type=vehicle_type,
        fee=fee,
        payment_method=payload.payment_method,
        status=payload.status or "parked",
        notes=payload.notes,
        plate_type=plate_type,
        entry_method=payload.entry_method or "scan",
        created_by=payload.created_by,
        entry_time=datetime.now(pytz.UTC),
    )
    db.add(session)
    db.commit()
    db.refresh(session)


    if session.payment_method:
        snapshot_session_balance(db, session)

    try:
        asyncio.create_task(manager.broadcast({
            'type': 'session_created',
            'session': {
                'id': session.id,
                'plate_number': session.plate_number,
                'plate_type': session.plate_type,
                'entry_method': session.entry_method,
                'status': session.status,
                'entry_time': session.entry_time.isoformat() if session.entry_time is not None else None,
                'vehicle_type': session.vehicle_type,
            }
        }))
    except Exception:
        pass

    return session


@app.get("/api/analytics/summary")
def api_analytics_summary(db: Session = Depends(get_db)):
    return build_natural_language_summary(db)


@app.get("/api/sessions/{session_id}", response_model=ParkingSessionResponse)
def api_get_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(ParkingSession).filter(ParkingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Convert times to Manila timezone for display
    if session.entry_time:
        session.entry_time = convert_to_manila(session.entry_time)
    if session.exit_time:
        session.exit_time = convert_to_manila(session.exit_time)
    
    return session


@app.put("/api/sessions/{session_id}", response_model=ParkingSessionResponse)
def api_update_session(session_id: int, payload: ParkingSessionUpdate, db: Session = Depends(get_db)):
    session = db.query(ParkingSession).filter(ParkingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status == "completed":
        raise HTTPException(status_code=409, detail="Completed transactions cannot be edited")

    if payload.plate_number is not None:
        session.plate_number = payload.plate_number.upper()
    if payload.vehicle_type is not None:
        session.vehicle_type = _api_normalize_vehicle_type(payload.vehicle_type)
    if payload.fee is not None:
        session.fee = payload.fee
    if payload.payment_method is not None:
        session.payment_method = payload.payment_method
    if payload.status is not None:
        # Only set exit_time when status changes to completed
        if payload.status == "completed" and not session.exit_time:
            session.exit_time = datetime.now(pytz.UTC)  # Use timezone-aware UTC
        session.status = payload.status
    if payload.notes is not None:
        session.notes = payload.notes
    if payload.exit_time is not None:
        session.exit_time = ensure_utc(payload.exit_time)

    db.add(session)
    db.commit()
    db.refresh(session)


    if session.status == "completed" and session.payment_method and session.balance_after is None:
        snapshot_session_balance(db, session)

    return session


@app.delete("/api/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(ParkingSession).filter(ParkingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status == "completed":
        raise HTTPException(status_code=409, detail="Completed transactions cannot be deleted")
    db.delete(session)
    db.commit()


@app.post("/api/sessions/{session_id}/payment", response_model=ParkingSessionResponse)
def api_session_payment(session_id: int, payload: PaymentMethodRequest, db: Session = Depends(get_db)):
    session = db.query(ParkingSession).filter(ParkingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session.payment_method = payload.method
    # Don't change status here - let the exit process handle it
    
    db.add(session)
    db.commit()
    db.refresh(session)

    transaction = PaymentTransaction(session_id=session.id, amount=session.fee, method=payload.method)
    db.add(transaction)
    db.commit()

    snapshot_session_balance(db, session)

    return session


# ── Vehicles (union of registered users + sessions) ──────────
@app.get("/api/vehicles", response_model=VehiclesResponse)
def api_get_vehicles(db: Session = Depends(get_db)):
    return {"vehicles": get_vehicles(db)}


# ── Vehicle Management ─────────────────────────────────────────

@app.post("/api/users/{user_id}/vehicles", response_model=VehicleCreate)
def add_vehicle(user_id: int, payload: VehicleCreate, db: Session = Depends(get_db)):
    """Add a new vehicle to a user's account"""
    # Check if user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if plate number already exists in vehicles table
    existing_vehicle = db.query(Vehicle).filter(Vehicle.plate_number == payload.plate_number).first()
    if existing_vehicle:
        raise HTTPException(status_code=400, detail="Plate number is already registered")
    
    # Also check if plate exists in users table (for backward compatibility)
    existing_user = db.query(User).filter(User.plate_number == payload.plate_number).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Plate number is already registered")
    
    # If this is the primary vehicle, unset any existing primary
    if payload.is_primary:
        db.query(Vehicle).filter(Vehicle.user_id == user_id).update({"is_primary": False})
    
    vehicle = Vehicle(
        user_id=user_id,
        plate_number=payload.plate_number,
        vehicle_type=payload.vehicle_type,
        brand=payload.brand,
        model=payload.model,
        color=payload.color,
        is_primary=payload.is_primary
    )
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@app.get("/api/users/{user_id}/vehicles")
def get_user_vehicles(user_id: int, db: Session = Depends(get_db)):
    """Get all vehicles for a user"""
    vehicles = db.query(Vehicle).filter(Vehicle.user_id == user_id).all()
    return vehicles


@app.put("/api/users/{user_id}/vehicles/{vehicle_id}", response_model=VehicleCreate)
def update_vehicle(user_id: int, vehicle_id: int, payload: VehicleCreate, db: Session = Depends(get_db)):
    """Update a vehicle"""
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id, Vehicle.user_id == user_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    
    # Check if plate number already exists (excluding this vehicle)
    existing = db.query(Vehicle).filter(
        Vehicle.plate_number == payload.plate_number,
        Vehicle.id != vehicle_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Plate number is already registered")
    
    # Also check users table
    existing_user = db.query(User).filter(User.plate_number == payload.plate_number).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Plate number is already registered")
    
    vehicle.plate_number = payload.plate_number
    vehicle.vehicle_type = payload.vehicle_type
    vehicle.brand = payload.brand
    vehicle.model = payload.model
    vehicle.color = payload.color
    vehicle.is_primary = payload.is_primary
    
    db.commit()
    db.refresh(vehicle)
    return vehicle


@app.delete("/api/users/{user_id}/vehicles/{vehicle_id}")
def delete_vehicle(user_id: int, vehicle_id: int, db: Session = Depends(get_db)):
    """Delete a vehicle"""
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id, Vehicle.user_id == user_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    
    db.delete(vehicle)
    db.commit()
    return {"message": "Vehicle deleted successfully"}


@app.get("/api/vehicles/check/{plate_number}")
def check_plate_exists(plate_number: str, db: Session = Depends(get_db)):
    """Check if a plate number already exists in the system"""
    normalized = plate_number.replace(" ", "").upper()
    
    # Check in vehicles table
    vehicle = db.query(Vehicle).filter(Vehicle.plate_number == normalized).first()
    if vehicle:
        return {"exists": True, "table": "vehicles", "user_id": vehicle.user_id}
    
    # Check in users table (for backward compatibility)
    user = db.query(User).filter(User.plate_number == normalized).first()
    if user:
        return {"exists": True, "table": "users", "user_id": user.id}
    
    return {"exists": False}


# ── Audit log ────────────────────────────────────────────────
@app.get("/api/audit-log", response_model=List[AuditLogResponse])
def api_get_audit_logs(db: Session = Depends(get_db)):
    return get_audit_logs(db)


@app.post("/api/audit-log", response_model=AuditLogResponse, status_code=status.HTTP_201_CREATED)
def api_create_audit_log(payload: AuditLogCreate, db: Session = Depends(get_db)):
    return create_audit_log(
        db,
        user_id=payload.user_id,
        user_email=payload.user_email,
        user_role=payload.user_role,
        action_type=payload.action_type,
        reference_id=payload.reference_id,
        details=payload.details,
    )


# ── Users management ─────────────────────────────────────────
@app.get("/api/users", response_model=List[UserResponse])
def api_get_users(db: Session = Depends(get_db)):
    return get_users(db)


@app.post("/api/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def api_create_user(payload: UserCreate, db: Session = Depends(get_db)):
    validate_signup_credentials(payload.password, payload.contact)
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    if payload.role not in ["owner", "attendant", "vehicle_owner"]:
        raise HTTPException(status_code=400, detail="Invalid role")

    password_hash = bcrypt.hashpw(payload.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user = User(
        full_name=payload.full_name,
        email=payload.email,
        password_hash=password_hash,
        role=payload.role,
        contact=payload.contact,
        plate_number=payload.plate_number,
        vehicle_type=payload.vehicle_type,
        brand=payload.brand,
        model=payload.model,
        color=payload.color,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@app.put("/api/users/{user_id}", response_model=UserResponse)
def api_update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)):
    user = update_user(db, user_id, payload)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.delete("/api/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_user(user_id: int, db: Session = Depends(get_db)):
    if not delete_user(db, user_id):
        raise HTTPException(status_code=404, detail="User not found")


@app.get("/api/users/plate/{plate_number}")
def api_get_user_by_plate(plate_number: str, db: Session = Depends(get_db)):
    plate = plate_number.strip().upper()

    # 1️⃣ Check users table (primary vehicle / legacy)
    user = db.query(User).filter(User.plate_number == plate).first()
    if user:
        return {
            "plate_number": user.plate_number,
            "full_name": user.full_name,
            "vehicle_type": user.vehicle_type,
            "brand": user.brand,
            "model": user.model,
            "color": user.color,
            "user_id": user.id,
            "is_registered": True,
            "source": "users",
            # For a primary vehicle, the "owner plate" is itself
            "owner_plate_number": user.plate_number,
        }

    # 2️⃣ Check vehicles table (additional vehicles)
    vehicle = db.query(Vehicle).filter(Vehicle.plate_number == plate).first()
    if vehicle:
        owner = db.query(User).filter(User.id == vehicle.user_id).first()
        return {
            "plate_number": vehicle.plate_number,
            "full_name": owner.full_name if owner else None,
            "vehicle_type": vehicle.vehicle_type,
            "brand": vehicle.brand,
            "model": vehicle.model,
            "color": vehicle.color,
            "user_id": vehicle.user_id,
            "is_registered": True,
            "source": "vehicles",
            "owner_plate_number": owner.plate_number if owner else None,
        }

    raise HTTPException(status_code=404, detail="Plate not found")


# ── Owner profile & settings ─────────────────────────────────
@app.get("/api/owner/profile", response_model=OwnerProfileResponse)
def api_get_owner_profile(db: Session = Depends(get_db)):
    return get_owner_profile(db)


@app.put("/api/owner/profile", response_model=OwnerProfileResponse)
def api_update_owner_profile(payload: OwnerProfileUpdate, db: Session = Depends(get_db)):
    profile = get_or_create_owner_profile(db)
    
    if payload.full_name is not None:
        profile.full_name = payload.full_name
    if payload.email is not None:
        profile.email = payload.email
    if payload.image_url is not None:
        profile.image_url = payload.image_url
    if payload.password:
        profile.password_hash = bcrypt.hashpw(
            payload.password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
    
    db.commit()
    db.refresh(profile)
    
    # Return the updated profile
    return OwnerProfileResponse(
        id=profile.id,
        full_name=profile.full_name,
        email=profile.email,
        image_url=profile.image_url,
        created_at=profile.created_at,
        updated_at=profile.updated_at
    )


# ── Owner System Settings ─────────────────────────────────────

@app.get("/api/owner/settings", response_model=SystemSettingsResponse)
def api_get_settings(db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)

    logger.info(
        f"GET SETTINGS -> id={settings.id}, "
        f"parking_capacity={settings.parking_capacity}"
    )

    return settings


@app.put("/api/owner/settings", response_model=SystemSettingsResponse)
def api_update_settings(
    payload: SystemSettingsBase,
    db: Session = Depends(get_db)
):
    logger.info("========== UPDATE SYSTEM SETTINGS ==========")
    logger.info(f"Incoming payload: {payload.dict()}")

    settings = get_or_create_settings(db)
    
    # Store old values for comparison
    old_capacity = settings.parking_capacity
    logger.info(f"Old parking_capacity: {old_capacity}")

    # Update the actual SQLAlchemy object
    settings.system_name = payload.system_name
    settings.motor_fee = payload.motor_fee
    settings.four_wheel_fee = payload.four_wheel_fee
    settings.parking_capacity = payload.parking_capacity

    logger.info(
        f"Saving -> system_name={settings.system_name}, "
        f"motor_fee={settings.motor_fee}, "
        f"four_wheel_fee={settings.four_wheel_fee}, "
        f"parking_capacity={settings.parking_capacity}"
    )

    try:
        # Log before commit
        logger.info("Attempting to commit to database...")
        db.commit()
        logger.info("✅ Commit successful!")
        
        db.refresh(settings)
        logger.info(f"REFRESHED VALUE -> parking_capacity={settings.parking_capacity}")

        # Double-check with a direct query
        direct_check = db.query(SystemSettings).first()
        logger.info(f"DIRECT QUERY CHECK -> parking_capacity={direct_check.parking_capacity if direct_check else 'NO RECORD'}")

        return settings

    except Exception as e:
        db.rollback()
        logger.exception(f"❌ Failed to save system settings: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save system settings: {str(e)}"
        )


# ── Profile (current logged-in user) ─────────────────────────
@app.get("/api/profile")
def api_get_profile(role: Optional[str] = None, db: Session = Depends(get_db)):
    if role == "owner":
        profile = get_or_create_owner_profile(db)
        return {
            "role": "owner",
            "full_name": profile.full_name,
            "email": profile.email,
            "image_url": profile.image_url,
        }
    users = db.query(User).filter(User.role == (role or "vehicle_owner")).all()
    if not users:
        return {"role": role or "vehicle_owner", "full_name": "—", "email": "", "image_url": None}
    user = users[0]
    return {
        "role": user.role,
        "full_name": user.full_name,
        "email": user.email,
        "image_url": None,
    }


@app.put("/api/profile", response_model=OwnerProfileResponse)
def api_update_profile(payload: ProfileUpdate, db: Session = Depends(get_db)):
    profile = get_or_create_owner_profile(db)
    if payload.full_name is not None:
        profile.full_name = payload.full_name
    if payload.email is not None:
        profile.email = payload.email
    if payload.image_url is not None:
        profile.image_url = payload.image_url
    if payload.password:
        profile.password_hash = bcrypt.hashpw(
            payload.password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
    db.commit()
    db.refresh(profile)
    return profile


# ── Vehicle owner balance / signup (API aliases) ──────────────
@app.post("/api/vehicle-owner/balance")
def api_vehicle_owner_balance(payload: VehicleAccountLogin, db: Session = Depends(get_db)):
    return vehicle_owner_balance(payload, db)


@app.post("/api/vehicle-owner/signup", response_model=VehicleAccountResponse, status_code=status.HTTP_201_CREATED)
def api_vehicle_owner_signup(payload: VehicleAccountCreate, db: Session = Depends(get_db)):
    return vehicle_owner_signup(payload, db)


# ── Wallet (server-side, atomic) ─────────────────────────────
@app.post("/api/wallet/top-up", response_model=VehicleAccountResponse)
def api_wallet_top_up(payload: WalletTopUpRequest, db: Session = Depends(get_db)):
    try:
        result = top_up_wallet(db, payload.plate_number, payload.amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    account = db.query(VehicleAccount).filter(VehicleAccount.plate_number == payload.plate_number.upper()).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Vehicle account not found")
    return account


@app.post("/api/wallet/deduct", response_model=VehicleAccountResponse)
def api_wallet_deduct(payload: WalletDeductRequest, db: Session = Depends(get_db)):
    try:
        result = deduct_wallet(
            db, payload.plate_number, payload.amount,
            session_id=payload.session_id or 0, method=payload.method or "wallet",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    account = db.query(VehicleAccount).filter(VehicleAccount.plate_number == payload.plate_number.upper()).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Vehicle account not found")
    return account


# ── Wallet Balance ──────────────────────

@app.get("/api/wallet-balance/{plate_number}")
def api_get_wallet_balance(plate_number: str, db: Session = Depends(get_db)):
    """Get wallet balance and vehicle info for a plate number."""
    try:
        return get_wallet_balance(db, plate_number)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/wallet-balance/amount/{plate_number}")
def api_get_wallet_balance_amount(plate_number: str, db: Session = Depends(get_db)):
    """Get just the balance amount for a plate number.

    For additional vehicles registered in the `vehicles` table, the
    balance lives on the owner's primary plate wallet, so we resolve
    to that plate before reading.
    """
    try:
        plate = plate_number.replace(" ", "").upper()

        # Try the plate itself first
        try:
            balance = get_wallet_balance_by_plate(db, plate)
            # If the plate has a wallet row, honor it even if 0 — the
            # caller decides whether to fall back.
            return {"plate_number": plate, "balance": balance}
        except ValueError:
            pass  # no wallet row for this plate yet

        # Fall back: is this an additional vehicle?
        owner_plate = resolve_wallet_owner_plate(db, plate)
        if owner_plate and owner_plate != plate:
            try:
                balance = get_wallet_balance_by_plate(db, owner_plate)
                return {"plate_number": plate, "balance": balance, "source_plate": owner_plate}
            except ValueError:
                pass

        # Not registered / no wallet anywhere
        raise ValueError(f"No wallet balance found for {plate}")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/wallet-balance/top-up")
def api_wallet_balance_top_up(
    plate_number: str,
    amount: float,
    db: Session = Depends(get_db)
):
    """Top up a vehicle wallet.

    If the plate is an additional vehicle (registered in `vehicles` as
    a non-primary row), the money is applied to the owner's primary
    plate wallet so the balance the owner sees on their primary plate
    actually grows.
    """
    try:
        plate = plate_number.replace(" ", "").upper()

        # Resolve to the plate whose wallet should grow
        target_plate = plate
        owner_plate = resolve_wallet_owner_plate(db, plate)
        if owner_plate and owner_plate != plate:
            target_plate = owner_plate
            logger.info(f"💰 Top-up for additional vehicle {plate} routed to primary plate wallet {target_plate}")

        result = top_up_wallet(db, target_plate, amount)

         # ── Audit log: record the top-up ──
        try:
            create_audit_log(
                db,
                user_id=None,
                user_email=None,
                user_role='vehicle_owner',
                action_type='Top Up',
                reference_id=plate,
                details=f"Wallet top-up of ₱{amount:.2f} for {plate}",
            )
        except Exception as e:
            logger.warning(f"Could not write Top Up audit log: {e}")
            
        # Echo the plate the caller asked about so the UI can display it
        if isinstance(result, dict):
            result.setdefault("plate_number", plate)
            result.setdefault("source_plate", target_plate)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/wallet-balance/deduct")
def api_wallet_balance_deduct(
    plate_number: str,
    amount: float,
    session_id: int = 0,
    method: str = "wallet",
    db: Session = Depends(get_db)
):
    try:
        plate = plate_number.replace(" ", "").upper()

        target_plate = plate
        owner_plate = resolve_wallet_owner_plate(db, plate)
        if owner_plate and owner_plate != plate:
            target_plate = owner_plate
            logger.info(f"💸 Deduction for additional vehicle {plate} routed to primary plate wallet {target_plate}")

        result = deduct_wallet(db, target_plate, amount, session_id, method)

        # ── Snapshot the resulting balance onto the session row ──
        if session_id:
            session_row = db.query(ParkingSession).filter(ParkingSession.id == session_id).first()
            if session_row is not None:
                balance_val = None
                if isinstance(result, dict):
                    balance_val = result.get("balance")
                elif isinstance(result, (int, float)):
                    balance_val = result
                if balance_val is not None:
                    session_row.balance_after = float(balance_val)
                    db.commit()
                    logger.info(f"📸 Snapshot: session {session_id} balance_after = {session_row.balance_after}")

        if isinstance(result, dict):
            result.setdefault("plate_number", plate)
            result.setdefault("source_plate", target_plate)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/wallet-balance/create/{plate_number}")
def api_create_wallet_balance(plate_number: str, db: Session = Depends(get_db)):
    """Create a wallet balance entry for a plate number (initial balance = 0)."""
    try:
        wallet = get_or_create_wallet_balance(db, plate_number)
        return {
            "plate_number": wallet.plate_number,
            "balance": wallet.balance,
            "created_at": wallet.created_at,
            "updated_at": wallet.updated_at
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/wallet-balance/{plate_number}")
def api_delete_wallet_balance(plate_number: str, db: Session = Depends(get_db)):
    """Delete a wallet balance entry for a plate number."""
    try:
        wallet = db.query(WalletBalance).filter(WalletBalance.plate_number == plate_number).first()
        if not wallet:
            raise HTTPException(status_code=404, detail="Wallet balance not found")
        
        db.delete(wallet)
        db.commit()
        return {"message": f"Wallet balance for {plate_number} deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))