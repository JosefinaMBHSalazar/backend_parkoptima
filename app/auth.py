from typing import Dict

from passlib.hash import bcrypt
from sqlalchemy.orm import Session

from .models import OwnerProfile, User


def authenticate_user(db: Session, email: str, password: str) -> Dict[str, object]:
    # Try users table first
    user = db.query(User).filter(User.email == email).first()
    if user:
        try:
            if bcrypt.verify(password, user.password_hash):
                return {
                    "id": user.id,
                    "full_name": user.full_name,
                    "email": user.email,
                    "role": user.role,
                }
        except Exception:
            # fallthrough to invalid
            pass

    # Fall back to owner profile
    profile = db.query(OwnerProfile).filter(OwnerProfile.email == email).first()
    if profile:
        if profile.password_hash:
            try:
                if bcrypt.verify(password, profile.password_hash):
                    return {
                        "id": profile.id,
                        "full_name": profile.full_name,
                        "email": profile.email,
                        "role": "owner",
                    }
            except Exception:
                pass
        raise ValueError("invalid credentials")

    raise ValueError("invalid credentials")
