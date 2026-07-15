from typing import Dict
from sqlalchemy.orm import Session
from .models import SystemSettings


def get_system_settings_data(db: Session) -> Dict[str, object]:
    settings = db.query(SystemSettings).first()
    return {
        "system_name": settings.system_name if settings else "ParkOptima",
        "motor_fee": float(settings.motor_fee if settings else 5.0),
        "four_wheel_fee": float(settings.four_wheel_fee if settings else 20.0),
    }
