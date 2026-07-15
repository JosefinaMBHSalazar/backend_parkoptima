from typing import Dict, List
from sqlalchemy.orm import Session
from .models import ParkingSession


def get_live_monitor_data(db: Session) -> Dict[str, object]:
    sessions = db.query(ParkingSession).order_by(ParkingSession.entry_time.desc()).all()
    return {
        "sessions": [
            {
                "id": session.id,
                "plate_number": session.plate_number,
                "status": session.status,
                "slot": session.slot,
                "payment_method": session.payment_method,
            }
            for session in sessions
        ],
        "active_sessions": sum(1 for session in sessions if session.status == "parked"),
    }
