from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import sqrt
from statistics import mean
from typing import Any, Dict, Iterable, List

from sqlalchemy.orm import Session

from .models import ParkingSession, SystemSettings


def _active_sessions(db: Session) -> List[ParkingSession]:
    return db.query(ParkingSession).filter(ParkingSession.status == "parked").all()


def _slot_ids(settings: SystemSettings) -> List[str]:
    # ✅ FIXED: Use parking_capacity instead of non-existent total_motor_slots/total_four_wheel_slots
    total = max(settings.parking_capacity or 100, 1)
    return [f"S{number}" for number in range(1, total + 1)]


def recommend_slot(db: Session, vehicle_type: str, requested_slot: str | None = None) -> Dict[str, Any]:
    settings = db.query(SystemSettings).first()
    if not settings:
        # Create default settings if none exist
        settings = SystemSettings(parking_capacity=100)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    
    slots = _slot_ids(settings)
    occupied: set[str] = set()
    if requested_slot:
        normalized = requested_slot.upper()
        if normalized not in slots:
            raise ValueError(f"Unknown slot {requested_slot}")
        if normalized in occupied:
            raise ValueError(f"Slot {normalized} is already occupied")
        return {"recommended_slot": normalized, "available_slots": [normalized], "reason": "requested_free_slot"}

    available = [slot for slot in slots if slot not in occupied]
    if not available:
        raise ValueError("No parking slots are currently available")
    return {
        "recommended_slot": available[0],
        "available_slots": available[:10],
        "reason": "nearest_free_slot_by_slot_number",
    }


def _hourly_values(sessions: Iterable[ParkingSession], days: int = 14) -> Dict[datetime, Dict[str, float]]:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    values: Dict[datetime, Dict[str, float]] = defaultdict(lambda: {"occupancy": 0.0, "revenue": 0.0})
    all_values: Dict[datetime, Dict[str, float]] = defaultdict(lambda: {"occupancy": 0.0, "revenue": 0.0})
    for session in sessions:
        entry = session.entry_time
        if not entry:
            continue
        key = entry.replace(minute=0, second=0, microsecond=0, tzinfo=None)
        target = all_values if entry.replace(tzinfo=None) < cutoff else values
        target[key]["occupancy"] += 1
        if session.payment_method:
            target[key]["revenue"] += float(session.fee or 0.0)
    return values or all_values


# Forecasting feature removed per user request. Historical/summary analytics remain.

def build_natural_language_summary(db: Session) -> Dict[str, Any]:
    sessions = db.query(ParkingSession).all()
    paid = [session for session in sessions if session.payment_method]
    revenue = sum(float(session.fee or 0.0) for session in paid)
    parked = sum(session.status == "parked" for session in sessions)
    completed = sum(session.status == "completed" for session in sessions)
    collection_rate = (len(paid) / len(sessions) * 100) if sessions else 0
    summary = (
        f"ParkOptima recorded {len(sessions)} parking sessions, with {parked} currently parked and {completed} completed. "
        f"Collected revenue is PHP {revenue:,.2f}, with a {collection_rate:.1f}% payment collection rate."
    )
    return {"summary": summary, "generated_by": "rule_based_analytics", "stats": {"sessions": len(sessions), "parked": parked, "completed": completed, "paid": len(paid), "revenue": round(revenue, 2), "collection_rate": round(collection_rate, 2)}}