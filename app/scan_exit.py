from typing import Dict
from sqlalchemy.orm import Session
from fastapi import HTTPException

from .models import ParkingSession
from .services import analyze_scan_image, create_session_from_scan, get_or_create_settings


def process_scan_exit(db: Session, image_base64: str) -> Dict[str, object]:
    try:
        plate_number, confidence, vehicle_type = analyze_scan_image(image_base64)
        session = (
            db.query(ParkingSession)
            .filter(
                ParkingSession.plate_number == plate_number.upper(),
                ParkingSession.status == "parked",
            )
            .order_by(ParkingSession.entry_time.desc())
            .first()
        )

        if session is None:
            settings = get_or_create_settings(db)
            session = create_session_from_scan(db, plate_number, vehicle_type, settings)

        session.status = "completed"
        db.add(session)
        db.commit()
        db.refresh(session)

        return {
            "plate_number": plate_number,
            "confidence": confidence,
            "vehicle_type": vehicle_type,
            "status": session.status,
            "session_id": session.id,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def get_scan_exit_data(db: Session, image_base64: str | None = None) -> Dict[str, object]:
    if not image_base64:
        session = db.query(ParkingSession).order_by(ParkingSession.id.desc()).first()
        return {
            "plate_number": session.plate_number if session else None,
            "status": session.status if session else "completed",
            "payment_method": session.payment_method if session else None,
        }
    return process_scan_exit(db, image_base64)
