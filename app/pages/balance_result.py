from typing import Dict
from sqlalchemy.orm import Session
from ..models import ParkingSession


def get_balance_result_data(db: Session) -> Dict[str, object]:
    sessions = db.query(ParkingSession).all()
    paid = [session for session in sessions if session.payment_method]
    return {
        "balance": round(sum(float(session.fee or 0.0) for session in paid), 2),
        "paid_sessions": len(paid),
        "total_sessions": len(sessions),
    }

