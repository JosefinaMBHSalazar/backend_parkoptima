from typing import List, Dict
from sqlalchemy.orm import Session
from .models import ParkingSession


def get_transaction_log_data(db: Session) -> List[Dict[str, object]]:
    sessions = db.query(ParkingSession).order_by(ParkingSession.entry_time.desc()).all()
    return [
        {
            "id": session.id,
            "plate_number": session.plate_number,
            "vehicle_type": session.vehicle_type,
            "fee": float(session.fee or 0.0),
            "payment_method": session.payment_method,
            "status": session.status,
            "entry_time": session.entry_time.isoformat() if session.entry_time else None,
        }
        for session in sessions
    ]
