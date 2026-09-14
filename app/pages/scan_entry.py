from typing import Dict
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ..models import ParkingSession
from ..services import analyze_scan_image, create_session_from_scan, get_or_create_settings


def process_scan_entry(db: Session, image_base64: str) -> Dict[str, object]:
    try:
        plate_number, confidence, vehicle_type = analyze_scan_image(image_base64)
        settings = get_or_create_settings(db)
        session = create_session_from_scan(db, plate_number, vehicle_type, settings)
        return {
            "plate_number": plate_number,
            "confidence": confidence,
            "vehicle_type": vehicle_type,
            "status": session.status,
            "session_id": session.id,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def get_scan_entry_data(db: Session, image_base64: str | None = None) -> Dict[str, object]:
    if not image_base64:
        session = db.query(ParkingSession).order_by(ParkingSession.id.desc()).first()
        return {
            "plate_number": session.plate_number if session else None,
            "status": session.status if session else "parked",
            "vehicle_type": session.vehicle_type if session else None,
        }
    return process_scan_entry(db, image_base64)

