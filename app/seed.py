"""Seed default accounts so the frontend's built-in credentials work out of the box.

Runs on application startup and is idempotent: it only creates accounts that
are missing and never overwrites existing data.
"""

import bcrypt
from sqlalchemy.orm import Session

from .models import User, VehicleAccount

# Matches the default staff credentials referenced by the frontend LoginPage.
DEFAULT_STAFF = [
    {
        "full_name": "System Owner",
        "email": "owner@parkoptima.com",
        "password": "Owner@2025",
        "role": "owner",
    },
    {
        "full_name": "System Attendant",
        "email": "attendant@parkoptima.com",
        "password": "Attendant@2025",
        "role": "attendant",
    },
]

# A demo vehicle-owner account (plate number + PIN) for testing the portal.
DEFAULT_VEHICLE_ACCOUNTS = [
    {
        "plate_number": "ABC1234",
        "pin": "1234",
        "owner_name": "Demo Driver",
        "contact": "09123456789",
        "vehicle_type": "Motorcycle",
        "brand": "Kawasaki",
        "balance": 50.0,
    },
]


def _hash(value: str) -> str:
    return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def seed_default_accounts(db: Session) -> None:
    for staff in DEFAULT_STAFF:
        existing = db.query(User).filter(User.email == staff["email"]).first()
        if existing is None:
            db.add(
                User(
                    full_name=staff["full_name"],
                    email=staff["email"],
                    password_hash=_hash(staff["password"]),
                    role=staff["role"],
                )
            )

    for vehicle in DEFAULT_VEHICLE_ACCOUNTS:
        plate = vehicle["plate_number"].upper()
        existing = db.query(VehicleAccount).filter(VehicleAccount.plate_number == plate).first()
        if existing is None:
            db.add(
                VehicleAccount(
                    plate_number=plate,
                    pin_hash=_hash(vehicle["pin"]),
                    owner_name=vehicle["owner_name"],
                    contact=vehicle["contact"],
                    vehicle_type=vehicle["vehicle_type"],
                    brand=vehicle["brand"],
                    balance=vehicle["balance"],
                )
            )

    db.commit()
