from typing import Dict
from sqlalchemy.orm import Session
from ..models import ParkingSession


def get_vehicle_owner_portal_data(db: Session) -> Dict[str, object]:
    session = db.query(ParkingSession).order_by(ParkingSession.id.asc()).first()
    return {
        "plate_number": session.plate_number if session else None,
        "status": session.status if session else None,
        "vehicle_type": session.vehicle_type if session else None,
    }

