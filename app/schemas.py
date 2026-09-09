from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class OwnerProfileBase(BaseModel):
    full_name: str
    email: str
    image_url: Optional[str] = None


class OwnerProfileCreate(OwnerProfileBase):
    password: Optional[str] = None


class OwnerProfileResponse(OwnerProfileBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SystemSettingsBase(BaseModel):
    system_name: str = "ParkOptima"
    motor_fee: float = 5.0
    four_wheel_fee: float = 20.0
    parking_capacity: int = 100

class SystemSettingsResponse(SystemSettingsBase):
    id: int
    updated_at: Optional[datetime] = None  
    
    class Config:
        from_attributes = True


class ParkingSessionBase(BaseModel):
    plate_number: str
    vehicle_type: str = "motor"
    fee: float = 0.0
    payment_method: Optional[str] = None
    status: str = "parked"
    slot: Optional[str] = None
    notes: Optional[str] = None


class ParkingSessionUpdate(BaseModel):
    plate_number: Optional[str] = None
    vehicle_type: Optional[str] = None
    fee: Optional[float] = None
    payment_method: Optional[str] = None
    status: Optional[str] = None
    slot: Optional[str] = None
    notes: Optional[str] = None
    exit_time: Optional[datetime] = None


class ParkingSessionResponse(ParkingSessionBase):
    id: int
    entry_time: datetime
    exit_time: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PaymentMethodRequest(BaseModel):
    method: str


class ScanRequest(BaseModel):
    image_base64: str


class ScanResponse(BaseModel):
    plate_number: str
    confidence: float
    vehicle_type: str
    session_id: Optional[int] = None


class UserCreate(BaseModel):
    full_name: str
    email: str
    password: str
    role: str = "vehicle_owner"
    contact: Optional[str] = None
    plate_number: Optional[str] = None
    vehicle_type: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: str
    role: str
    contact: Optional[str] = None
    plate_number: Optional[str] = None
    vehicle_type: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None
    status: Optional[str] = "Active"
    created_at: datetime
    updated_at: datetime
    image_url: Optional[str] = None

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    email: str
    password: str
    role: Optional[str] = None


class VehicleAccountCreate(BaseModel):
    plate_number: str
    email: Optional[str] = None
    pin: str
    owner_name: Optional[str] = None
    contact: Optional[str] = None
    vehicle_type: Optional[str] = None
    brand: Optional[str] = None


class VehicleAccountLogin(BaseModel):
    email: Optional[str] = None
    plate_number: Optional[str] = None
    pin: str


class VehicleAccountResponse(BaseModel):
    id: int
    plate_number: str
    owner_name: Optional[str] = None
    contact: Optional[str] = None
    vehicle_type: Optional[str] = None
    brand: Optional[str] = None
    balance: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VehicleRegistrationCreate(BaseModel):
    plate_number: str
    vehicle_type: str
    owner_name: str
    user_id: Optional[int] = None


class VehicleRegistrationResponse(VehicleRegistrationCreate):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OwnerProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    image_url: Optional[str] = None
    password: Optional[str] = None


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    image_url: Optional[str] = None
    password: Optional[str] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    plate_number: Optional[str] = None
    contact: Optional[str] = None
    vehicle_type: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None
    password: Optional[str] = None
    image_url: Optional[str] = None


class AuditLogCreate(BaseModel):
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    user_role: Optional[str] = None
    action_type: str
    reference_id: Optional[str] = None
    details: Optional[str] = None


class AuditLogResponse(BaseModel):
    id: int
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    user_role: Optional[str] = None
    action_type: str
    reference_id: Optional[str] = None
    details: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True


class WalletTopUpRequest(BaseModel):
    plate_number: str
    amount: float


class WalletDeductRequest(BaseModel):
    plate_number: str
    amount: float
    session_id: Optional[int] = None
    method: Optional[str] = "wallet"

class VehicleCreate(BaseModel):
    plate_number: str
    vehicle_type: str = "motor"
    brand: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None
    is_primary: bool = False



class VehicleListItem(BaseModel):
    plate: str
    owner: str
    vehicleType: str
    brand: str = ""
    model: str = ""
    color: str = ""
    slot: str = "TBD"
    status: str = "Active"
    email: str = ""
    contact: str = ""
    balance: float = 0.0
    source: str = "registered"


class VehiclesResponse(BaseModel):
    vehicles: List[VehicleListItem]


# ── NEW: Password Schemas ──────────────────────────────────────

class PasswordVerifyRequest(BaseModel):
    """Request schema for verifying a password."""
    email: str
    password: str


class PasswordVerifyResponse(BaseModel):
    """Response schema for password verification."""
    valid: bool
    user_id: Optional[int] = None


class PasswordChangeRequest(BaseModel):
    """Request schema for changing a password."""
    email: str
    current_password: str
    new_password: str


class PasswordChangeResponse(BaseModel):
    """Response schema for password change."""
    message: str
    user_id: int