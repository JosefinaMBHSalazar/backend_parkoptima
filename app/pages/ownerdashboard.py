from datetime import datetime
from typing import Dict, List

from sqlalchemy.orm import Session

from ..models import ParkingSession
from ..analytics_engine import _hourly_values


def get_owner_dashboard_data(db: Session) -> Dict[str, object]:
    sessions = db.query(ParkingSession).order_by(ParkingSession.entry_time.desc()).all()
    paid_sessions = [session for session in sessions if session.payment_method]
    unpaid_sessions = [session for session in sessions if not session.payment_method]
    revenue = round(sum(float(session.fee or 0.0) for session in paid_sessions), 2)

    hourly_raw = _hourly_values(sessions, days=14)
    hourly_serialized = {
        k.isoformat() if hasattr(k, "isoformat") else str(k): v
        for k, v in hourly_raw.items()
    }

    return {
        "total_sessions": len(sessions),
        "paid_sessions": len(paid_sessions),
        "unpaid_sessions": len(unpaid_sessions),
        "revenue": revenue,
        "generated_at": datetime.utcnow().isoformat(),
        "sessions": [
            {
                "id": session.id,
                "plate_number": session.plate_number,
                "vehicle_type": session.vehicle_type,
                "entry_time": session.entry_time.isoformat() if session.entry_time else None,
                "exit_time": session.exit_time.isoformat() if session.exit_time else None,
                "fee": float(session.fee or 0.0),
                "payment_method": session.payment_method,
                "status": session.status,
                "notes": session.notes,
            }
            for session in sessions
        ],
    }

