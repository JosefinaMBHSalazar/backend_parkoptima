from datetime import datetime
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
else:
    try:
        from sqlalchemy.orm import Session
    except ImportError:
        Session = None

from ..models import ParkingSession


def get_attendant_dashboard_data(db: Session) -> Dict[str, object]:
    today = datetime.utcnow().date()
    sessions = (
        db.query(ParkingSession)
        .filter(ParkingSession.entry_time.isnot(None))
        .order_by(ParkingSession.entry_time.desc())
        .all()
    )

    active_sessions = [session for session in sessions if session.status == "parked"]
    pending_payments = [session for session in sessions if not session.payment_method]
    revenue_today = round(
        sum(float(session.fee or 0.0) for session in sessions if session.payment_method and session.entry_time and session.entry_time.date() == today),
        2,
    )

    return {
        "active_sessions": len(active_sessions),
        "pending_payments": len(pending_payments),
        "revenue_today": revenue_today,
        "generated_at": datetime.utcnow().isoformat(),
    }

