from typing import Dict, List

from sqlalchemy.orm import Session

from .models import ParkingSession, User, VehicleAccount


def _normalize_vt(value) -> str:
    if not value:
        return "Motor"
    vt = str(value).lower()
    if "4wheel" in vt or "four" in vt or vt in ("4 wheels", "4wheels"):
        return "4 Wheels"
    return "Motor"


def get_vehicles(db: Session) -> List[Dict[str, object]]:
    """Return a union of registered vehicle owners (``users``), wallet-backed
    ``vehicle_accounts`` and any plates seen in ``parking_sessions`` — mirroring the
    frontend's VehicleRegistration union shape. Vehicle accounts contribute the
    authoritative wallet ``balance``.
    """
    registered: Dict[str, Dict[str, object]] = {}

    accounts = db.query(VehicleAccount).all()
    for a in accounts:
        plate = (a.plate_number or "").upper()
        if not plate or plate in registered:
            continue
        registered[plate] = {
            "plate": plate,
            "owner": a.owner_name or "—",
            "vehicleType": _normalize_vt(a.vehicle_type),
            "brand": a.brand or "Generic",
            "model": "",
            "color": "",
            "slot": "TBD",
            "status": "Active",
            "email": "",
            "contact": a.contact or "",
            "balance": float(a.balance or 0.0),
            "source": "account",
        }

    users = db.query(User).filter(User.role == "vehicle_owner").all()
    for u in users:
        plate = (u.plate_number or "").upper()
        if not plate or plate in registered:
            continue
        registered[plate] = {
            "plate": plate,
            "owner": u.full_name or "—",
            "vehicleType": _normalize_vt(u.vehicle_type),
            "brand": u.brand or "Generic",
            "model": u.model or "",
            "color": u.color or "",
            "slot": "TBD",
            "status": u.status or "Active",
            "email": u.email or "",
            "contact": u.contact or "",
            "balance": 0.0,
            "source": "registered",
        }

    sessions = db.query(ParkingSession).all()
    for s in sessions:
        plate = (s.plate_number or "").upper()
        if plate and plate not in registered:
            registered[plate] = {
                "plate": plate,
                "owner": "—",
                "vehicleType": _normalize_vt(s.vehicle_type),
                "brand": "—",
                "model": "",
                "color": "",
                "slot": "TBD",
                "status": "Active",
                "email": "",
                "contact": "",
                "balance": 0.0,
                "source": "session",
            }

    return list(registered.values())
