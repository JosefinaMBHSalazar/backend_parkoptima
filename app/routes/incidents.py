import secrets
import re
from datetime import datetime, timedelta
from typing import List, Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models import IncidentReport, ParkingSession
from ..schemas import (
    IncidentVerifyRequest,
    IncidentVerifyResponse,
    IncidentCreateRequest,
    IncidentReportResponse,
    IncidentStatusUpdate,
)
from ..audit_crud import create_audit_log

router = APIRouter(prefix="/api/incidents", tags=["incidents"])

MANILA_TZ = pytz.timezone("Asia/Manila")

# ── Basic abuse prevention (in-memory, per-process) ──
# 3 submissions per IP per 10 minutes. Production would use Redis or a DB table.
_RATE_LIMIT: dict[str, list[datetime]] = {}
_RATE_WINDOW = timedelta(minutes=10)
_RATE_MAX = 10


def _check_rate_limit(ip: str) -> None:
    now = datetime.utcnow()
    bucket = [t for t in _RATE_LIMIT.get(ip, []) if now - t < _RATE_WINDOW]
    if len(bucket) >= _RATE_MAX:
        raise HTTPException(
            status_code=429,
            detail="Too many incident reports submitted recently. Please try again later.",
        )
    bucket.append(now)
    _RATE_LIMIT[ip] = bucket


def _normalize_plate(plate: str) -> str:
    return (plate or "").replace(" ", "").replace("-", "").upper()


def _find_active_session(db: DBSession, plate: str) -> Optional[ParkingSession]:
    normalized = _normalize_plate(plate)
    return (
        db.query(ParkingSession)
        .filter(
            ParkingSession.status == "parked",
            ParkingSession.plate_number == normalized,
        )
        .order_by(ParkingSession.entry_time.desc())
        .first()
    )


def _names_match(a: str, b: str) -> bool:
    """Case-insensitive, whitespace-normalized name match."""
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip().lower())
    return norm(a) == norm(b)


def _generate_reference() -> str:
    """IR-YYYYMMDD-XXXX where XXXX is a random 4-char alphanumeric."""
    date = datetime.now(MANILA_TZ).strftime("%Y%m%d")
    suffix = secrets.token_hex(2).upper()  # 4 hex chars
    return f"IR-{date}-{suffix}"


# ── Step 1: verify the plate has an active session AND the name matches ──
@router.post("/verify", response_model=IncidentVerifyResponse)
def verify_incident_report(payload: IncidentVerifyRequest, db: DBSession = Depends(get_db)):
    plate = _normalize_plate(payload.plate_number)
    if not plate:
        return IncidentVerifyResponse(ok=False, detail="Plate number is required.")

    session = _find_active_session(db, plate)
    if not session:
        return IncidentVerifyResponse(
            ok=False,
            detail="No active parking session found for this plate. The vehicle must be currently parked to file an incident report.",
        )

    recorded_owner = session.owner_name or ""
    if not recorded_owner:
        return IncidentVerifyResponse(
            ok=False,
            detail="This parking session has no owner name on record. Please see the attendant in person.",
        )

    if not _names_match(payload.reporter_name, recorded_owner):
        return IncidentVerifyResponse(
            ok=False,
            detail="The name you entered does not match the owner name on the parking record.",
        )

    return IncidentVerifyResponse(
        ok=True,
        session_id=session.id,
        plate_number=session.plate_number,
        owner_name=recorded_owner,
        vehicle_type=session.vehicle_type,
        entry_time=session.entry_time,
    )


# ── Step 2: submit the incident report ──
@router.post("", response_model=IncidentReportResponse, status_code=201)
def create_incident_report(
    payload: IncidentCreateRequest,
    request: Request,
    db: DBSession = Depends(get_db),
):
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    plate = _normalize_plate(payload.plate_number)
    if not plate:
        raise HTTPException(status_code=422, detail="Plate number is required.")

    session = _find_active_session(db, plate)
    if not session:
        raise HTTPException(
            status_code=409,
            detail="No active parking session found for this plate.",
        )

    recorded_owner = session.owner_name or ""
    if not _names_match(payload.reporter_name, recorded_owner):
        raise HTTPException(
            status_code=403,
            detail="Reporter name does not match the owner on record.",
        )

    incident_type = (payload.incident_type or "").strip().lower()
    if incident_type not in ("scratch", "dent", "other"):
        raise HTTPException(status_code=422, detail="Invalid incident type.")

    description = (payload.description or "").strip()
    if len(description) < 10:
        raise HTTPException(status_code=422, detail="Description must be at least 10 characters.")

    # Very light validation of the photo payload (data URL of a jpeg/png)
    photo = payload.photo_data or None
    if photo is not None:
        if not photo.startswith("data:image/"):
            raise HTTPException(status_code=422, detail="Photo must be an image data URL.")
        # ~2 MB cap on the raw base64 payload
        if len(photo) > 3_000_000:
            raise HTTPException(status_code=413, detail="Photo is too large (max ~2 MB).")

    # Guarantee reference uniqueness (retry a couple times in the unlikely collision case)
    ref = _generate_reference()
    for _ in range(3):
        exists = db.query(IncidentReport).filter(IncidentReport.reference_number == ref).first()
        if not exists:
            break
        ref = _generate_reference()

    report = IncidentReport(
        reference_number=ref,
        session_id=session.id,
        plate_number=session.plate_number,
        owner_name=recorded_owner,
        reporter_name=(payload.reporter_name or "").strip(),
        incident_type=incident_type,
        description=description,
        photo_data=photo,
        status="submitted",
        reporter_ip=ip,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

        # ── Audit trail: submitted ──
    try:
        create_audit_log(
            db,
            user_id=None,
            user_email=None,                    
            user_role="vehicle_owner",          
            action_type="Incident Report Submitted",
            reference_id=report.reference_number,
            details=(
                f"Type: {incident_type} · Plate: {report.plate_number} "
                f"· Session: {session.id} · Reporter: {report.reporter_name}"
            ),
        )
    except Exception:
        pass

    return report


# ── Listing for Attendant / Owner ──
@router.get("", response_model=List[IncidentReportResponse])
def list_incident_reports(
    status: Optional[str] = None,
    plate: Optional[str] = None,
    reference: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: DBSession = Depends(get_db),
):
    q = db.query(IncidentReport)

    if status and status != "all":
        q = q.filter(IncidentReport.status == status)

    if plate:
        q = q.filter(IncidentReport.plate_number.like(f"%{_normalize_plate(plate)}%"))

    if reference:
        q = q.filter(IncidentReport.reference_number.like(f"%{reference.upper()}%"))

    if date_from:
        try:
            d = datetime.fromisoformat(date_from).replace(tzinfo=pytz.UTC)
            q = q.filter(IncidentReport.created_at >= d)
        except Exception:
            pass

    if date_to:
        try:
            d = datetime.fromisoformat(date_to).replace(tzinfo=pytz.UTC)
            q = q.filter(IncidentReport.created_at <= d)
        except Exception:
            pass

    return q.order_by(IncidentReport.created_at.desc()).all()


@router.get("/{report_id}", response_model=IncidentReportResponse)
def get_incident_report(report_id: int, db: DBSession = Depends(get_db)):
    row = db.query(IncidentReport).filter(IncidentReport.id == report_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Incident report not found.")
    return row


# ── Status changes (Under Review / Resolved) ──
@router.put("/{report_id}/status", response_model=IncidentReportResponse)
def update_incident_status(
    report_id: int,
    payload: IncidentStatusUpdate,
    db: DBSession = Depends(get_db),
):
    row = db.query(IncidentReport).filter(IncidentReport.id == report_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Incident report not found.")

    new_status = (payload.status or "").strip().lower()
    if new_status not in ("submitted", "under_review", "resolved"):
        raise HTTPException(status_code=422, detail="Invalid status.")

    previous = row.status
    row.status = new_status

    if new_status == "resolved":
        row.resolution_notes = (payload.resolution_notes or "").strip() or None
        row.resolved_by = (payload.resolved_by or "").strip() or None
        row.resolved_at = datetime.utcnow()
    elif new_status == "under_review":
        # Clear any previous resolution if it's moving back into review
        row.resolution_notes = None
        row.resolved_by = None
        row.resolved_at = None

    db.add(row)
    db.commit()
    db.refresh(row)

    # ── Audit trail: status change ──
    try:
        detail = (
            f"{previous} → {new_status} · Plate: {row.plate_number}"
            + (f" · Notes: {row.resolution_notes}" if row.resolution_notes else "")
        )

        # Attribute the row to the real actor. Falls back to 'attendant'
        # only when the caller sent nothing at all (e.g. direct curl).
        actor_role  = (payload.actor_role  or "").strip().lower() or "attendant"
        actor_email = (payload.actor_email or "").strip() or None
        actor_name  = (payload.actor_name  or "").strip() or None

        create_audit_log(
            db,
            user_id=None,
            user_email=actor_email,
            user_role=actor_role,
            action_type="Incident Report Status Changed",
            reference_id=row.reference_number,
            details=(
                f"[{actor_name or actor_email or 'unknown'}] {detail}"
                if (actor_name or actor_email)
                else detail
            ),
        )
    except Exception:
        pass

    return row