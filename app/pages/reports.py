from typing import Dict
from sqlalchemy.orm import Session
from ..models import ParkingSession


def get_reports_data(db: Session) -> Dict[str, object]:
    sessions = db.query(ParkingSession).all()
    paid = [session for session in sessions if session.payment_method]
    unpaid = [session for session in sessions if not session.payment_method]
    return {
        "total_sessions": len(sessions),
        "paid_sessions": len(paid),
        "unpaid_sessions": len(unpaid),
        "revenue": round(sum(float(session.fee or 0.0) for session in paid), 2),
    }

