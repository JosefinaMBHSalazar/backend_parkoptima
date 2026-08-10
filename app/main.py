from datetime import datetime
from typing import List, Optional

from passlib.hash import bcrypt
from fastapi import Depends, FastAPI, HTTPException, status 
from sqlalchemy.orm import Session 

from .database import Base, engine, get_db
from .models import (
    OwnerProfile,
    ParkingSession,
    PaymentTransaction,
    SystemSettings,
    User,
    VehicleRegistration,
)
from .schemas import (
    OwnerProfileCreate,
    OwnerProfileResponse,
    ParkingSessionBase,
    ParkingSessionResponse,
    PaymentMethodRequest,
    ScanRequest,
    ScanResponse,
    SystemSettingsBase,
    SystemSettingsResponse,
    UserCreate,
    UserResponse,
    VehicleRegistrationCreate,
    VehicleRegistrationResponse,
)
from .services import analyze_scan_image, create_session_from_scan, get_or_create_owner_profile, get_or_create_settings
from .ownerdashboard import get_owner_dashboard_data
from .owneroverview import get_owner_overview_data
from .attendantdashboard import get_attendant_dashboard_data
from .vehicleownerdashboard import get_vehicle_owner_dashboard_data
from .auth import authenticate_user
from .balance import get_balance_summary
from .monitoring import get_live_monitor_data
from .payments import get_payments
from .audit_trail import get_audit_trail_data
from .balance_result import get_balance_result_data
from .check_balance import get_check_balance_data
from .login_page import get_login_page_data
from .logout_modal import get_logout_modal_data
from .my_vehicle import get_my_vehicle_data
from .profile_page import get_profile_page_data
from .quick_actions import get_quick_actions_data
from .register_page import get_register_page_data
from .reports import get_reports_data
from .scan_entry import get_scan_entry_data
from .scan_exit import get_scan_exit_data
from .signup_form import get_signup_form_data
from .system_settings import get_system_settings_data
from .transaction_log import get_transaction_log_data
from .vehicle_dashboard import get_vehicle_dashboard_data
from .vehicle_owner_portal import get_vehicle_owner_portal_data
from .vehicle_registration import get_vehicle_registration_data

Base.metadata.create_all(bind=engine)

app = FastAPI(title="ParkOptima Owner Backend", version="1.0.0")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/owner/profile", response_model=OwnerProfileResponse)
def get_owner_profile(db: Session = Depends(get_db)):
    profile = get_or_create_owner_profile(db)
    return profile


@app.post("/owner/profile", response_model=OwnerProfileResponse)
def update_owner_profile(payload: OwnerProfileCreate, db: Session = Depends(get_db)):
    profile = get_or_create_owner_profile(db)
    profile.full_name = payload.full_name
    profile.email = payload.email
    profile.image_url = payload.image_url
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
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@app.post("/owner/scan", response_model=ScanResponse)
def scan_vehicle(payload: ScanRequest, db: Session = Depends(get_db)):
    plate_number, confidence, vehicle_type = analyze_scan_image(payload.image_base64)
    settings = get_or_create_settings(db)
    session = create_session_from_scan(db, plate_number, vehicle_type, settings)
    return ScanResponse(plate_number=plate_number, confidence=confidence, vehicle_type=vehicle_type, session_id=session.id)


@app.post("/owner/sessions/{session_id}/payment", response_model=ParkingSessionResponse)
def update_payment(session_id: int, payload: PaymentMethodRequest, db: Session = Depends(get_db)):
    session = db.query(ParkingSession).filter(ParkingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status == "completed":
        raise HTTPException(status_code=409, detail="Completed transactions cannot be edited")
    session.payment_method = payload.method
    session.status = "completed"
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


@app.post("/auth/login")
def login(payload: dict, db: Session = Depends(get_db)):
    try:
        return authenticate_user(db, payload.get("email", ""), payload.get("password", ""))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


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
def check_balance(db: Session = Depends(get_db)):
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
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    if payload.role not in ["owner", "attendant", "vehicle_owner"]:
        raise HTTPException(status_code=400, detail="Invalid role")

    password_hash = bcrypt.hash(payload.password)
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


@app.post("/signup")
def signup_user(payload: UserCreate, db: Session = Depends(get_db)) -> UserResponse:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    if payload.role != "vehicle_owner":
        raise HTTPException(status_code=400, detail="Signup form is for vehicle owners only")

    password_hash = bcrypt.hash(payload.password)
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
