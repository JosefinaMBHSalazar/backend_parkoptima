from typing import Dict, List
from sqlalchemy.orm import Session
from .models import ParkingSession


def get_audit_trail_data(db: Session) -> List[Dict[str, object]]:
    sessions = db.query(ParkingSession).order_by(ParkingSession.entry_time.desc()).all()
    return [
        {
            "id": session.id,
            "plate_number": session.plate_number,
            "event": session.status,
            "payment_method": session.payment_method,
            "fee": float(session.fee or 0.0),
            "timestamp": session.entry_time.isoformat() if session.entry_time else None,
        }
        for session in sessions
    ]
