from typing import Dict, Optional
import logging

import bcrypt
from sqlalchemy.orm import Session

from .models import OwnerProfile, User, VehicleAccount

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _verify_password(password: str, password_hash: Optional[str]) -> bool:
    """Verify a password against a bcrypt hash."""
    if not password_hash:
        logger.warning("Password hash is empty or None")
        return False
    try:
        # Check if it's a valid bcrypt hash
        if not password_hash.startswith('$2b$'):
            logger.warning(f"Password hash doesn't start with $2b$: {password_hash[:20]}...")
            return False
        result = bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        logger.info(f"Password verification result: {result}")
        return result
    except (ValueError, TypeError) as e:
        logger.error(f"Password verification error: {e}")
        # Stored hash is not a valid bcrypt hash (e.g. seed/dummy data)
        return False


def authenticate_user(db: Session, email: str, password: str) -> Dict[str, object]:
    """Authenticate a staff user (owner / attendant / vehicle_owner) by email + password.

    Verifies against the ``users`` table using bcrypt. Falls back to the
    ``owner_profiles`` table for backwards compatibility with older data.
    """
    normalized = (email or "").strip().lower()
    logger.info(f"Attempting to authenticate user: {normalized}")

    # First, try to find the user in the users table
    user = db.query(User).filter(User.email == normalized).first()
    if user:
        logger.info(f"Found user in users table: {user.email}, role: {user.role}")
        logger.info(f"Password hash length: {len(user.password_hash) if user.password_hash else 0}")
        
        if _verify_password(password, user.password_hash):
            logger.info(f"Password verified for user: {user.email}")
            return {
                "id": user.id,
                "full_name": user.full_name,
                "email": user.email,
                "role": user.role,
            }
        else:
            logger.warning(f"Password verification failed for user: {user.email}")

    # Backwards-compatible fallback: owner profile
    profile = db.query(OwnerProfile).filter(OwnerProfile.email == normalized).first()
    if profile:
        logger.info(f"Found user in owner_profiles table: {profile.email}")
        logger.info(f"Password hash length: {len(profile.password_hash) if profile.password_hash else 0}")
        
        if _verify_password(password, profile.password_hash):
            logger.info(f"Password verified for owner profile: {profile.email}")
            return {
                "id": profile.id,
                "full_name": profile.full_name,
                "email": profile.email,
                "role": "owner",
            }
        else:
            logger.warning(f"Password verification failed for owner profile: {profile.email}")

    logger.warning(f"Authentication failed for user: {normalized}")
    raise ValueError("invalid credentials")


def authenticate_vehicle_owner(db: Session, plate_number: str, pin: str) -> Dict[str, object]:
    """Authenticate a vehicle owner by plate number + PIN."""
    normalized = (plate_number or "").strip().upper()
    account = db.query(VehicleAccount).filter(VehicleAccount.plate_number == normalized).first()
    
    if account is None:
        logger.warning(f"Vehicle account not found for plate: {normalized}")
        raise ValueError("invalid credentials")
    
    logger.info(f"Found vehicle account for plate: {normalized}")
    
    if not _verify_password(pin, account.pin_hash):
        logger.warning(f"PIN verification failed for plate: {normalized}")
        raise ValueError("invalid credentials")

    logger.info(f"Vehicle owner authenticated: {normalized}")
    return {
        "id": account.id,
        "plate_number": account.plate_number,
        "owner_name": account.owner_name,
        "contact": account.contact,
        "vehicle_type": account.vehicle_type,
        "brand": account.brand,
        "balance": account.balance,
        "role": "vehicle_owner",
    }