from typing import Dict
from sqlalchemy.orm import Session
from ..models import ParkingSession


def get_vehicle_dashboard_data(db: Session) -> Dict[str, object]:
    session = db.query(ParkingSession).order_by(ParkingSession.id.desc()).first()
    return {
        "plate_number": session.plate_number if session else None,
        "status": session.status if session else None,
        "vehicle_type": session.vehicle_type if session else None,
        "fee": float(session.fee or 0.0) if session else 0.0,
    }

