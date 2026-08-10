from datetime import datetime
from typing import Dict

from sqlalchemy.orm import Session

from ..models import ParkingSession


def get_owner_overview_data(db: Session) -> Dict[str, object]:
    sessions = db.query(ParkingSession).order_by(ParkingSession.entry_time.desc()).all()
    paid_sessions = [session for session in sessions if session.payment_method]
    unpaid_sessions = [session for session in sessions if not session.payment_method]
    revenue = round(sum(float(session.fee or 0.0) for session in paid_sessions), 2)

    return {
        "total_sessions": len(sessions),
        "paid_sessions": len(paid_sessions),
        "unpaid_sessions": len(unpaid_sessions),
        "revenue": revenue,
        "generated_at": datetime.utcnow().isoformat(),
    }

