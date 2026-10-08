from sqlalchemy import Column, ForeignKey, Integer, String, DateTime, Float, Text, Boolean, UniqueConstraint
from sqlalchemy.sql import func
from datetime import datetime  
from .database import Base


class OwnerProfile(Base):
    __tablename__ = "owner_profiles"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(120), nullable=False, default="Parking Owner")
    email = Column(String(255), nullable=False, unique=True, default="owner@parkoptima.com")
    image_url = Column(String(500), nullable=True)
    password_hash = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), index=True)
    token = Column(String(255), unique=True, index=True)  
    expires_at = Column(DateTime)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)



class OTPCode(Base):
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), index=True, nullable=False)
    code_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)          
    attempts = Column(Integer, nullable=False, default=0)
    used = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)  


class SystemSettings(Base):
    __tablename__ = "system_settings"
    id = Column(Integer, primary_key=True, index=True)
    system_name = Column(String(120), nullable=False, default="ParkOptima")
    motor_fee = Column(Float, nullable=False, default=5.0)
    four_wheel_fee = Column(Float, nullable=False, default=20.0)
    motorcycle_capacity = Column(Integer, nullable=False, default=90)
    four_wheel_capacity = Column(Integer, nullable=False, default=10)
    parking_capacity = Column(Integer, nullable=False, default=100)
    operating_open_minutes = Column(Integer, nullable=False, default=420)
    operating_close_minutes = Column(Integer, nullable=False, default=1020)
    receipt_facility_name = Column(String(80),  nullable=True, default="")
    receipt_header        = Column(String(120), nullable=True, default="")
    receipt_footer        = Column(String(160), nullable=True, default="")
    receipt_notes         = Column(Text,        nullable=True, default="")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class ParkingSession(Base):
    __tablename__ = "parking_sessions"

    id = Column(Integer, primary_key=True, index=True)
    plate_number = Column(String(32), nullable=False, index=True)
    vehicle_type = Column(String(20), nullable=False, default="motor")
    entry_time = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    exit_time = Column(DateTime(timezone=True), nullable=True)
    fee = Column(Float, nullable=False, default=0.0)
    payment_method = Column(String(30), nullable=True)
    status = Column(String(20), nullable=False, default="parked")
    notes = Column(Text, nullable=True)
    plate_type = Column(String(20), nullable=False, default="registered", index=True)   
    entry_method = Column(String(20), nullable=False, default="scan")                    
    created_by = Column(String(120), nullable=True)
    owner_name = Column(String(100), nullable=True)
    balance_after = Column(Float, nullable=True)                                       
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, nullable=True) 
    amount = Column(Float, nullable=False, default=0.0)
    method = Column(String(30), nullable=False, default="cash")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(120), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="vehicle_owner")
    status = Column(String(20), nullable=False, default="Active")
    plate_number = Column(String(32), nullable=True, index=True)
    contact = Column(String(30), nullable=True)
    vehicle_type = Column(String(40), nullable=True)
    brand = Column(String(60), nullable=True)
    model = Column(String(60), nullable=True)
    color = Column(String(40), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    image_url = Column(String(500), nullable=True)
    otp_verified = Column(Boolean, nullable=False, default=False)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    plate_number = Column(String(32), nullable=False, unique=True, index=True)
    vehicle_type = Column(String(20), nullable=False, default="motor")
    brand = Column(String(60), nullable=True)
    model = Column(String(60), nullable=True)
    color = Column(String(40), nullable=True)
    is_primary = Column(Boolean, default=False) 
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

class VehicleRegistration(Base):
    __tablename__ = "vehicle_registrations"

    id = Column(Integer, primary_key=True, index=True)
    plate_number = Column(String(32), nullable=False, index=True)
    vehicle_type = Column(String(20), nullable=False, default="motor")
    owner_name = Column(String(120), nullable=False)
    user_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class VehicleAccount(Base):
    """Vehicle owner account authenticated by plate number + PIN.

    This backs the frontend "Vehicle Owner" login, sign-up and balance check
    flows (plate number + 4-digit PIN), which the other tables do not cover.
    """

    __tablename__ = "vehicle_accounts"

    id = Column(Integer, primary_key=True, index=True)
    plate_number = Column(String(32), nullable=False, unique=True, index=True)
    email = Column(String(120), nullable=True, unique=True, index=True)
    pin_hash = Column(String(255), nullable=False)
    owner_name = Column(String(120), nullable=True)
    contact = Column(String(30), nullable=True)
    vehicle_type = Column(String(40), nullable=True)
    brand = Column(String(60), nullable=True)
    balance = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class AuditLog(Base):
    """System-wide audit trail of user actions (login, scan entry/exit, payments, etc.)."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(120), nullable=True)
    user_email = Column(String(255), nullable=True)
    user_role = Column(String(60), nullable=True)
    action_type = Column(String(80), nullable=False)
    reference_id = Column(String(120), nullable=True)
    details = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class WalletBalance(Base):
    __tablename__ = "wallet_balances"

    id = Column(Integer, primary_key=True, index=True)
    plate_number = Column(String(32), nullable=False, unique=True, index=True)
    balance = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class IncidentReport(Base):
    __tablename__ = "incident_reports"

    id = Column(Integer, primary_key=True, index=True)
    reference_number = Column(String(32), unique=True, index=True, nullable=False)

    # Linked session (the active parking session at the time of reporting)
    session_id = Column(Integer, nullable=True, index=True)
    plate_number = Column(String(32), nullable=False, index=True)
    owner_name = Column(String(120), nullable=True)     

    # Reporter-provided fields
    reporter_name = Column(String(120), nullable=False) 
    incident_type = Column(String(40), nullable=False)  
    description = Column(Text, nullable=False)
    photo_data = Column(Text, nullable=True)            

    # Workflow
    status = Column(String(20), nullable=False, default="submitted")  
    resolution_notes = Column(Text, nullable=True)
    resolved_by = Column(String(120), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # Abuse-prevention metadata
    reporter_ip = Column(String(64), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class Anomaly(Base):
    __tablename__ = "anomalies"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("parking_sessions.id"), nullable=True)

    plate_number = Column(String(20), nullable=False, index=True)
    anomaly_type = Column(String(50), nullable=False)    
    severity = Column(String(20), nullable=False, default="medium")  
    status = Column(String(20), nullable=False, default="flagged")   

    details = Column(Text, nullable=True)                 
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    resolved_by = Column(String(120), nullable=True)      
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


    __table_args__ = (
        # One row per (session_id, anomaly_type). NULL session_id is
        # intentionally allowed to repeat — MySQL/MariaDB treat NULLs as
        # distinct in unique indexes, which is exactly right: anomalies
        # not tied to a session (e.g. facility_full) can repeat, but a
        # real session can only have one long_stay, one unpaid_exit, etc.
        # This is what stops concurrent detection passes from inserting
        # N copies of the same row.
        UniqueConstraint(
            "session_id", "anomaly_type",
            name="uq_anomaly_session_type",
        ),
    )


class OccupancyLog(Base):
    __tablename__ = "occupancy_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Per-type snapshot
    motor_occupied = Column(Integer, nullable=False, default=0)
    motor_capacity = Column(Integer, nullable=False, default=0)

    four_wheel_occupied = Column(Integer, nullable=False, default=0)
    four_wheel_capacity = Column(Integer, nullable=False, default=0)

    total_occupied = Column(Integer, nullable=False, default=0)
    total_capacity = Column(Integer, nullable=False, default=0)

    is_full = Column(Boolean, nullable=False, default=False)

    # "periodic" | "entry" | "exit" | "status_change"
    trigger = Column(String(20), nullable=False, default="periodic")