from __future__ import annotations

import base64
import io
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from .models import OwnerProfile, ParkingSession, SystemSettings
from .plate_patterns import classify_plate_type, extract_plate_candidate, normalize_plate_key

_YOLO_MODEL = None


def _get_yolo_model():
    global _YOLO_MODEL
    if _YOLO_MODEL is None:
        from ultralytics import YOLO

        _YOLO_MODEL = YOLO("yolov8n.pt")
    return _YOLO_MODEL


def _detect_vehicle_type_with_yolo(image) -> Optional[str]:
    try:
        model = _get_yolo_model()
        results = model(image)
        if not results or not results[0].boxes:
            return None

        names = results[0].names
        for class_id in results[0].boxes.cls:
            class_name = names[int(class_id)]
            if class_name in {"motorcycle", "motorbike", "bicycle", "scooter"}:
                return "motor"
            if class_name in {"car", "truck", "bus", "van"}:
                return "4_wheels"
    except Exception:
        return None
    return None


def get_or_create_settings(db: Session) -> SystemSettings:
    settings = db.query(SystemSettings).first()
    if settings is None:
        settings = SystemSettings(system_name="ParkOptima", motor_fee=5.0, four_wheel_fee=20.0)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def get_or_create_owner_profile(db: Session) -> OwnerProfile:
    profile = db.query(OwnerProfile).first()
    if profile is None:
        profile = OwnerProfile(full_name="Parking Owner", email="owner@parkoptima.com")
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def infer_vehicle_type(plate_number: str) -> str:
    vehicle_type = classify_plate_type(plate_number)
    if vehicle_type is None:
        raise ValueError("The scan does not contain a recognized vehicle plate")
    return vehicle_type


def estimate_fee(vehicle_type: str, settings: SystemSettings) -> float:
    return settings.motor_fee if vehicle_type == "motor" else settings.four_wheel_fee


def analyze_scan_image(image_base64: str) -> Tuple[str, float, str]:
    import cv2
    import easyocr
    import numpy as np

    image_bytes = base64.b64decode(image_base64.split(",", 1)[-1])
    image_array = np.asarray(bytearray(io.BytesIO(image_bytes).read()), dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Invalid image")

    reader = easyocr.Reader(["en"], gpu=False)
    raw_results = reader.readtext(image, detail=1, paragraph=False)
    ocr_results = [{"text": result[1], "confidence": float(result[2])} for result in raw_results]
    plate = extract_plate_candidate(ocr_results)
    if plate is None:
        raise ValueError("No recognized vehicle plate found in the image")

    confidence = next((item["confidence"] for item in ocr_results if normalize_plate_key(item["text"]) == plate), 0.0)
    return plate, confidence, infer_vehicle_type(plate)


def create_session_from_scan(db: Session, plate_number: str, vehicle_type: str, settings: SystemSettings) -> ParkingSession:
    session = ParkingSession(
        plate_number=plate_number.upper(),
        vehicle_type=vehicle_type,
        fee=estimate_fee(vehicle_type, settings),
        status="parked",
        payment_method=None,
        slot="A1",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session
