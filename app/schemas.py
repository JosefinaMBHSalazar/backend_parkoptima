from datetime import datetime
from typing import Optional
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
    system_name: str
    motor_fee: float
    four_wheel_fee: float


class SystemSettingsResponse(SystemSettingsBase):
    id: int
    updated_at: datetime

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


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: str
    role: str
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
