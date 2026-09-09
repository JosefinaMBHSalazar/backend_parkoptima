from typing import List

import bcrypt
from sqlalchemy.orm import Session

from .models import User


def get_users(db: Session) -> List[User]:
    return db.query(User).order_by(User.id.asc()).all()


def update_user(db: Session, user_id: int, data) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None

    # ✅ ADDED 'image_url' to the list of fields
    for field in ("full_name", "email", "role", "status", "plate_number",
                 "contact", "vehicle_type", "brand", "model", "color", "image_url"):
        value = getattr(data, field, None)
        if value is not None:
            setattr(user, field, value)

    if getattr(data, "password", None):
        user.password_hash = bcrypt.hashpw(
            data.password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: int) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return False
    db.delete(user)
    db.commit()
    return True