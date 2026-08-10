from typing import Dict

from sqlalchemy.orm import Session

from ..models import ParkingSession


def get_vehicle_owner_dashboard_data(db: Session) -> Dict[str, object]:
    session = db.query(ParkingSession).order_by(ParkingSession.id.asc()).first()
    if session is None:
        return {
            "plate_number": None,
            "status": None,
            "vehicle_type": None,
            "fee": 0.0,
            "payment_method": None,
        }

    return {
        "plate_number": session.plate_number,
        "status": session.status,
        "vehicle_type": session.vehicle_type,
        "fee": float(session.fee or 0.0),
        "payment_method": session.payment_method,
    }

