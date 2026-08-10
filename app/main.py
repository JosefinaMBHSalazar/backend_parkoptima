from datetime import datetime, timezone
import re
from typing import List, Optional

import bcrypt
import pytz
from fastapi import Depends, FastAPI, HTTPException, status 
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session 

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
)
from .services import analyze_scan_image, get_or_create_owner_profile, get_or_create_settings
from .analytics_engine import build_forecast, build_natural_language_summary, recommend_slot
from .auth import authenticate_vehicle_owner, authenticate_user, _verify_password
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

Base.metadata.create_all(bind=engine)

app = FastAPI(title="ParkOptima Owner Backend", version="1.0.0")


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

# â”€â”€â”€â”€â”€â”€ Timezone Helper â”€â”€â”€â”€â”€â”€
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
    db = SessionLocal()
    try:
        seed_default_accounts(db)
    finally:
        db.close()


@app.get("/health")
def health_check():
    return {"status": "ok"}


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


@app.get("/owner/settings", response_model=SystemSettingsResponse)
def get_settings(db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    return settings


@app.put("/owner/settings", response_model=SystemSettingsResponse)
def update_settings(payload: SystemSettingsBase, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    settings.system_name = payload.system_name
    settings.motor_fee = payload.motor_fee
    settings.four_wheel_fee = payload.four_wheel_fee
    db.commit()
    db.refresh(settings)
    return settings


@app.get("/owner/sessions", response_model=List[ParkingSessionResponse])
def list_sessions(db: Session = Depends(get_db)):
    sessions = db.query(ParkingSession).order_by(ParkingSession.entry_time.desc()).all()
    return sessions


@app.post("/owner/sessions", response_model=ParkingSessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(payload: ParkingSessionBase, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    session = ParkingSession(
        plate_number=payload.plate_number.upper(),
        vehicle_type=payload.vehicle_type,
        fee=payload.fee or (settings.motor_fee if payload.vehicle_type == "motor" else settings.four_wheel_fee),
        payment_method=payload.payment_method,
        status=payload.status,
        slot=payload.slot,
        notes=payload.notes,
        entry_time=datetime.now(pytz.UTC),  # Use timezone-aware UTC
    )
    db.add(session)
    db.commit()
    db.refresh(session)
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
    session.payment_method = payload.method
    # Don't change status here - let the exit process handle it
    db.add(session)
    db.commit()
    db.refresh(session)

    transaction = PaymentTransaction(session_id=session.id, amount=session.fee, method=payload.method)
    db.add(transaction)
    db.commit()
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


# â”€â”€ Authentication â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    try:
        user = authenticate_user(db, payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid email or password") from exc

    if payload.role and payload.role != user["role"]:
        raise HTTPException(
            status_code=403,
            detail=f"This account is not registered as {payload.role}",
        )

    return {
        "message": "Login successful",
        "user": user,
        "token": f"parkoptima-{user['role']}-{user['id']}",
    }


# â”€â”€ Password Management Endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    pin_hash = bcrypt.hashpw(payload.pin.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    account = VehicleAccount(
        plate_number=plate,
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
        account = authenticate_vehicle_owner(db, payload.plate_number, payload.pin)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid plate number or PIN") from exc

    return {
        "message": "Login successful",
        "user": account,
        "token": f"parkoptima-vehicle-{account['id']}",
    }


@app.post("/vehicle-owner/balance")
def vehicle_owner_balance(payload: VehicleAccountLogin, db: Session = Depends(get_db)):
    try:
        account = authenticate_vehicle_owner(db, payload.plate_number, payload.pin)
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# API routes consumed by the React frontend (vite proxies /api â†’ backend)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _api_normalize_vehicle_type(vehicle_type: Optional[str]) -> str:
    """Collapse backend ``vehicle_type`` values to the UI vocabulary."""
    if not vehicle_type:
        return "motor"
    vt = vehicle_type.lower()
    if vt in ("4_wheels", "4wheels", "four_wheel", "4 wheels") or "four" in vt or "4wheel" in vt:
        return "4wheels"
    return "motor"


@app.get("/api/health")
def api_health_check():
    return {"status": "ok"}


# â”€â”€ Sessions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
    # Check for duplicate active session
    existing = db.query(ParkingSession).filter(
        ParkingSession.plate_number == payload.plate_number,
        ParkingSession.status == 'parked'
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400, 
            detail=f"Vehicle {payload.plate_number} is already parked (Session ID: {existing.id})"
        )
    
    settings = get_or_create_settings(db)
    vehicle_type = _api_normalize_vehicle_type(payload.vehicle_type)
    fee = payload.fee
    if fee is None or fee == 0:
        fee = settings.motor_fee if vehicle_type == "motor" else settings.four_wheel_fee
    
    try:
        slot = recommend_slot(db, vehicle_type, payload.slot)["recommended_slot"]
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session = ParkingSession(
        plate_number=payload.plate_number.upper(),
        vehicle_type=vehicle_type,
        fee=fee,
        payment_method=payload.payment_method,
        status=payload.status or "parked",
        slot=slot,
        notes=payload.notes,
        entry_time=datetime.now(pytz.UTC),  # Use timezone-aware UTC
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@app.get("/api/slots/recommend")
def api_recommend_slot(vehicle_type: str = "motor", db: Session = Depends(get_db)):
    try:
        return recommend_slot(db, _api_normalize_vehicle_type(vehicle_type))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/analytics/forecast")
def api_forecast(horizon_hours: int = 6, db: Session = Depends(get_db)):
    if horizon_hours < 1 or horizon_hours > 24:
        raise HTTPException(status_code=400, detail="horizon_hours must be between 1 and 24")
    return build_forecast(db, horizon_hours)


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
    if payload.slot is not None:
        session.slot = payload.slot
    if payload.notes is not None:
        session.notes = payload.notes
    if payload.exit_time is not None:
        session.exit_time = ensure_utc(payload.exit_time)

    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@app.delete("/api/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(ParkingSession).filter(ParkingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
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
    return session


# â”€â”€ Vehicles (union of registered users + sessions) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.get("/api/vehicles", response_model=VehiclesResponse)
def api_get_vehicles(db: Session = Depends(get_db)):
    return {"vehicles": get_vehicles(db)}


# â”€â”€ Audit log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


# â”€â”€ Users management â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


# â”€â”€ Owner profile & settings â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.put("/api/owner/profile", response_model=OwnerProfileResponse)
def api_update_owner_profile(payload: OwnerProfileUpdate, db: Session = Depends(get_db)):
    return update_owner_profile(payload, db)


@app.get("/api/owner/settings", response_model=SystemSettingsResponse)
def api_get_settings(db: Session = Depends(get_db)):
    return get_settings(db)


@app.put("/api/owner/settings", response_model=SystemSettingsResponse)
def api_update_settings(payload: SystemSettingsBase, db: Session = Depends(get_db)):
    return update_settings(payload, db)


# â”€â”€ Profile (current logged-in user) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        return {"role": role or "vehicle_owner", "full_name": "â€”", "email": "", "image_url": None}
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


# â”€â”€ Vehicle owner balance / signup (API aliases) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.post("/api/vehicle-owner/balance")
def api_vehicle_owner_balance(payload: VehicleAccountLogin, db: Session = Depends(get_db)):
    return vehicle_owner_balance(payload, db)


@app.post("/api/vehicle-owner/signup", response_model=VehicleAccountResponse, status_code=status.HTTP_201_CREATED)
def api_vehicle_owner_signup(payload: VehicleAccountCreate, db: Session = Depends(get_db)):
    return vehicle_owner_signup(payload, db)


# â”€â”€ Wallet (server-side, atomic) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


# â”€â”€ Wallet Balance (new dedicated table) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/api/wallet-balance/{plate_number}")
def api_get_wallet_balance(plate_number: str, db: Session = Depends(get_db)):
    """Get wallet balance and vehicle info for a plate number."""
    try:
        return get_wallet_balance(db, plate_number)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/wallet-balance/amount/{plate_number}")
def api_get_wallet_balance_amount(plate_number: str, db: Session = Depends(get_db)):
    """Get just the balance amount for a plate number."""
    try:
        balance = get_wallet_balance_by_plate(db, plate_number)
        return {"plate_number": plate_number, "balance": balance}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/wallet-balance/top-up")
def api_wallet_balance_top_up(
    plate_number: str, 
    amount: float, 
    db: Session = Depends(get_db)
):
    """Top up a vehicle wallet using the wallet_balances table."""
    try:
        result = top_up_wallet(db, plate_number, amount)
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
    """Deduct from a vehicle wallet using the wallet_balances table."""
    try:
        return deduct_wallet(db, plate_number, amount, session_id, method)
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
