from sqlalchemy import Column, Integer, String, DateTime, Float, Text
from sqlalchemy.sql import func
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


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    system_name = Column(String(120), nullable=False, default="ParkOptima")
    motor_fee = Column(Float, nullable=False, default=5.0)
    four_wheel_fee = Column(Float, nullable=False, default=20.0)
    total_motor_slots = Column(Integer, nullable=False, default=50)
    total_four_wheel_slots = Column(Integer, nullable=False, default=50)
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
    slot = Column(String(20), nullable=True)
    notes = Column(Text, nullable=True)
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