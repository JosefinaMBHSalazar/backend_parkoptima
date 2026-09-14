from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models import ParkingSession, WalletBalance, User, Vehicle

import pytz

MANILA_TZ = pytz.timezone("Asia/Manila")

router = APIRouter(prefix="/api", tags=["receipts"])

def _to_manila_iso(dt):
    """Convert a possibly-naive UTC datetime to a Manila-aware ISO string."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(MANILA_TZ).isoformat()

def _resolve_owner_plate(db: DBSession, plate_number: str) -> str:
    """Return the plate whose wallet is the source of truth for this plate.

    Mirrors `resolve_wallet_owner_plate` in main.py: primary vehicle first,
    then fall back to the owner's primary plate for additional vehicles.
    """
    if not plate_number:
        return plate_number
    plate = plate_number.replace(" ", "").upper()

    user = db.query(User).filter(User.plate_number == plate).first()
    if user:
        return user.plate_number

    vehicle = db.query(Vehicle).filter(Vehicle.plate_number == plate).first()
    if vehicle:
        owner = db.query(User).filter(User.id == vehicle.user_id).first()
        if owner and owner.plate_number:
            return owner.plate_number

    return plate  # not registered anywhere; use as-is


@router.get("/sessions/{session_id}/receipt")
def get_session_receipt(session_id: int, db: DBSession = Depends(get_db)):
    session = db.query(ParkingSession).filter(ParkingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != "completed":
        raise HTTPException(
            status_code=409,
            detail="Receipt is only available for completed sessions",
        )

    fee = float(session.fee or 0)
    wallet_plate = _resolve_owner_plate(db, session.plate_number)
    method = (session.payment_method or "").lower()

    # ── Balance AFTER the transaction — from the snapshot ONLY ──
    if session.balance_after is not None:
        balance_after = float(session.balance_after)
    else:
        # Legacy row written before we started snapshotting.
        # Do NOT read the live wallet — that would be today's value,
        # not the value at the time of this transaction.
        balance_after = None

    # ── Balance BEFORE the transaction ──
    if balance_after is None:
        balance_before = None
    elif method == "wallet":
        balance_before = balance_after + fee
    else:
        # Cash never changes the wallet — before == after
        balance_before = balance_after

    return {
        "receipt_number": f"RCPT-{session.id:06d}",
        "session_id": session.id,
        "plate_number": session.plate_number,
        "vehicle_type": session.vehicle_type,
        "entry_time": _to_manila_iso(session.entry_time),
        "exit_time": _to_manila_iso(session.exit_time),
        "fee": fee,
        "payment_method": session.payment_method or "unpaid",
        "status": session.status,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "current_balance": balance_after,
        "wallet_plate": wallet_plate,
        "issued_at": _to_manila_iso(session.exit_time),
    }