from typing import Dict, Optional
import logging

import bcrypt
from sqlalchemy.orm import Session

from .models import OwnerProfile, User, VehicleAccount

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class InactiveAccountError(ValueError):
    """Raised when a user exists but their account is not active.

    Subclasses ValueError so existing callers that catch ValueError still
    work, but allows the login endpoint to surface a distinct 403 if it
    wants to.
    """
    pass


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
        logger.info(f"Password hash: {user.password_hash[:30]}..." if user.password_hash else "No password hash")

        # ── Block non-active accounts (status check BEFORE password check) ──
        # Legacy rows with missing/empty status are treated as Active.
        user_status = (user.status or 'Active').strip()
        if user_status.lower() != 'active':
            logger.warning(
                f"🚫 Login blocked for {user.email}: account status is '{user_status}'"
            )
            raise InactiveAccountError("account is not active")

        if _verify_password(password, user.password_hash):
            logger.info(f"✅ Password verified for user: {user.email}")
            return {
                "id": user.id,
                "full_name": user.full_name,
                "email": user.email,
                "role": user.role,
            }
        else:
            logger.warning(f"❌ Password verification failed for user: {user.email}")

    # Backwards-compatible fallback: owner profile
    profile = db.query(OwnerProfile).filter(OwnerProfile.email == normalized).first()
    if profile:
        logger.info(f"Found user in owner_profiles table: {profile.email}")
        logger.info(f"Password hash: {profile.password_hash[:30]}..." if profile.password_hash else "No password hash")

        if _verify_password(password, profile.password_hash):
            logger.info(f"✅ Password verified for owner profile: {profile.email}")
            return {
                "id": profile.id,
                "full_name": profile.full_name,
                "email": profile.email,
                "role": "owner",
            }
        else:
            logger.warning(f"❌ Password verification failed for owner profile: {profile.email}")

    # If we get here, check if the email exists at all (for debugging)
    user_exists = db.query(User).filter(User.email == normalized).first() is not None
    profile_exists = db.query(OwnerProfile).filter(OwnerProfile.email == normalized).first() is not None
    logger.warning(f"Authentication failed for user: {normalized}. User exists: {user_exists}, Profile exists: {profile_exists}")
    raise ValueError("invalid credentials")


def authenticate_vehicle_owner(db: Session, plate_number: str = None, pin: str = None, email: str = None) -> Dict[str, object]:
    """Authenticate a vehicle owner by plate number or email + PIN."""
    account = None
    
    if email:
        # Look up by email
        normalized_email = (email or "").strip().lower()
        account = db.query(VehicleAccount).filter(VehicleAccount.email == normalized_email).first()
        if account is None:
            logger.warning(f"Vehicle account not found for email: {normalized_email}")
            raise ValueError("invalid credentials")
        logger.info(f"Found vehicle account for email: {normalized_email}")
    elif plate_number:
        # Look up by plate number
        normalized_plate = (plate_number or "").strip().upper()
        account = db.query(VehicleAccount).filter(VehicleAccount.plate_number == normalized_plate).first()
        if account is None:
            logger.warning(f"Vehicle account not found for plate: {normalized_plate}")
            raise ValueError("invalid credentials")
        logger.info(f"Found vehicle account for plate: {normalized_plate}")
    else:
        raise ValueError("invalid credentials")
    
    if not _verify_password(pin, account.pin_hash):
        identifier = email or plate_number
        logger.warning(f"PIN verification failed for: {identifier}")
        raise ValueError("invalid credentials")

    logger.info(f"✅ Vehicle owner authenticated: {account.plate_number}")
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