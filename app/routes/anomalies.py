from datetime import datetime, timedelta
from typing import List, Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models import Anomaly, ParkingSession, SystemSettings
from ..schemas import AnomalyResponse, AnomalyResolveRequest
from ..audit_crud import create_audit_log
from ..services import get_or_create_settings

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])

MANILA_TZ = pytz.timezone("Asia/Manila")

# Tunables — these are the rule thresholds. Adjust per resort policy.
LONG_STAY_HOURS = 12
DUPLICATE_WINDOW_MINUTES = 15


# ──────────────────────────────────────────────────────────────
# Detection
# ──────────────────────────────────────────────────────────────

def _upsert_anomaly(
    db: DBSession,
    *,
    session_id: Optional[int],
    plate_number: str,
    anomaly_type: str,
    severity: str,
    details: str,
) -> Optional[Anomaly]:
    """Return the existing row for (plate, type, session_id) if one
    exists — regardless of status — otherwise insert a new one.

    Idempotent by design: the *existence* of a row for this key is
    what suppresses insertion, not its status. The previous version
    only suppressed inserts when the existing row was still 'flagged',
    so any dismissed/verified row caused a fresh insert on the next
    detection pass — which is what produced thousands of duplicate
    long_stay rows.
    """
    q = db.query(Anomaly).filter(
        Anomaly.plate_number == plate_number,
        Anomaly.anomaly_type == anomaly_type,
    )
    if session_id is not None:
        q = q.filter(Anomaly.session_id == session_id)

    # Deterministic: always consider the most recent row for this key.
    existing = q.order_by(Anomaly.id.desc()).first()

    if existing is not None:
        # Row already exists for this key. Do NOT insert. If it's still
        # flagged, just bump detected_at so the UI shows fresh activity.
        if existing.status == "flagged":
            existing.detected_at = datetime.utcnow()
            existing.severity = severity
            existing.details = details
            db.add(existing)
            db.commit()
            db.refresh(existing)
        return None

    row = Anomaly(
        session_id=session_id,
        plate_number=plate_number,
        anomaly_type=anomaly_type,
        severity=severity,
        status="flagged",
        details=details,
        detected_at=datetime.utcnow(),
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        # A concurrent request inserted the same (session_id,
        # anomaly_type) between our SELECT and our INSERT. Roll back
        # and return None so the caller treats it as "already exists".
        db.rollback()
        return None


def run_detection(db: DBSession) -> List[Anomaly]:
    """Scan current data and flag any new anomalies. Returns the list of
    anomalies newly created in this pass."""
    created: List[Anomaly] = []
    settings = get_or_create_settings(db)

    # ── Rule 1: long stays ──
    cutoff = datetime.utcnow() - timedelta(hours=LONG_STAY_HOURS)
    long_stays = db.query(ParkingSession).filter(
        ParkingSession.status == "parked",
        ParkingSession.entry_time <= cutoff,
    ).all()
    for s in long_stays:
        hours = (datetime.utcnow() - s.entry_time.replace(tzinfo=None)).total_seconds() / 3600
        row = _upsert_anomaly(
            db,
            session_id=s.id,
            plate_number=s.plate_number,
            anomaly_type="long_stay",
            severity="high",
            details=f"Vehicle parked for {hours:.1f}h (threshold {LONG_STAY_HOURS}h).",
        )
        if row:
            created.append(row)

    # ── Rule 2: fee mismatches on active sessions ──
    parked = db.query(ParkingSession).filter(ParkingSession.status == "parked").all()
    for s in parked:
        expected = (
            float(settings.motor_fee or 0)
            if s.vehicle_type == "motor"
            else float(settings.four_wheel_fee or 0)
        )
        actual = float(s.fee or 0)
        if abs(actual - expected) > 0.01:
            row = _upsert_anomaly(
                db,
                session_id=s.id,
                plate_number=s.plate_number,
                anomaly_type="fee_mismatch",
                severity="medium",
                details=f"Fee ₱{actual:.2f} does not match configured ₱{expected:.2f} for {s.vehicle_type}.",
            )
            if row:
                created.append(row)

    # ── Rule 3: unpaid exits ──
    unpaid_exits = db.query(ParkingSession).filter(
        ParkingSession.status == "completed",
        ParkingSession.payment_method.is_(None),
    ).all()
    for s in unpaid_exits:
        row = _upsert_anomaly(
            db,
            session_id=s.id,
            plate_number=s.plate_number,
            anomaly_type="unpaid_exit",
            severity="high",
            details="Session marked completed without a recorded payment method.",
        )
        if row:
            created.append(row)

    # ── Rule 4: duplicate entries (same plate, two sessions within window) ──
    window_start = datetime.utcnow() - timedelta(minutes=DUPLICATE_WINDOW_MINUTES)
    recent = db.query(ParkingSession).filter(
        ParkingSession.entry_time >= window_start,
    ).order_by(ParkingSession.plate_number, ParkingSession.entry_time).all()

    seen: dict[str, ParkingSession] = {}
    for s in recent:
        prev = seen.get(s.plate_number)
        if prev and (s.entry_time - prev.entry_time).total_seconds() < DUPLICATE_WINDOW_MINUTES * 60:
            row = _upsert_anomaly(
                db,
                session_id=s.id,
                plate_number=s.plate_number,
                anomaly_type="duplicate_entry",
                severity="medium",
                details=(
                    f"Duplicate entry for {s.plate_number} within "
                    f"{DUPLICATE_WINDOW_MINUTES} minutes "
                    f"(session #{prev.id} → #{s.id})."
                ),
            )
            if row:
                created.append(row)
        seen[s.plate_number] = s

    return created


# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────

@router.get("", response_model=List[AnomalyResponse])
def list_anomalies(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    plate: Optional[str] = None,
    db: DBSession = Depends(get_db),
):
    """Read-only list of anomalies.

    Detection is *not* run here — that's the job of /scan (called by
    the owner dashboard on its own cadence) and the periodic task.
    Running detection on every read caused the Live Monitor's 8 s
    verifyPoll to insert a new row per active overstay every tick.
    """
    q = db.query(Anomaly)
    if status and status != "all":
        q = q.filter(Anomaly.status == status)
    if severity and severity != "all":
        q = q.filter(Anomaly.severity == severity)
    if plate:
        q = q.filter(Anomaly.plate_number.like(f"%{plate.upper()}%"))

    return q.order_by(Anomaly.detected_at.desc()).all()


@router.post("/scan", response_model=List[AnomalyResponse])
def scan_now(db: DBSession = Depends(get_db)):
    """Force a detection pass. Returns the *newly created* anomalies."""
    return run_detection(db)


@router.put("/{anomaly_id}/resolve", response_model=AnomalyResponse)
def resolve_anomaly(
    anomaly_id: int,
    payload: AnomalyResolveRequest,
    db: DBSession = Depends(get_db),
):
    row = db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Anomaly not found.")

    action = (payload.action or "").strip().lower()
    if action not in ("verify", "override", "dismiss"):
        raise HTTPException(status_code=422, detail="Action must be verify, override, or dismiss.")

    # Map action → terminal status
    new_status = {
        "verify": "verified",
        "override": "overridden",
        "dismiss": "dismissed",
    }[action]

    if row.status != "flagged":
        raise HTTPException(
            status_code=409,
            detail=f"This anomaly has already been resolved as '{row.status}'.",
        )

    previous = row.status
    row.status = new_status
    row.resolution_notes = (payload.resolution_notes or "").strip() or None
    row.resolved_by = (
        (payload.actor_name or payload.actor_email or "").strip() or None
    )
    row.resolved_at = datetime.utcnow()

    db.add(row)
    db.commit()
    db.refresh(row)

    # ── Audit trail: anomaly resolution ──
    try:
        actor_role  = (payload.actor_role  or "").strip().lower() or "attendant"
        actor_email = (payload.actor_email or "").strip() or None
        actor_name  = (payload.actor_name  or "").strip() or None

        action_label = {
            "verify":   "Anomaly Verified",
            "override": "Anomaly Overridden",
            "dismiss":  "Anomaly Dismissed",
        }[action]

        detail = (
            f"{row.anomaly_type} · Plate: {row.plate_number}"
            f" · Session: {row.session_id or '—'}"
            f" · Severity: {row.severity}"
            f" · {previous} → {new_status}"
            + (f" · Notes: {row.resolution_notes}" if row.resolution_notes else "")
        )

        create_audit_log(
            db,
            user_id=None,
            user_email=actor_email,
            user_role=actor_role,
            action_type=action_label,
            reference_id=f"AN-{row.id}",
            details=(
                f"[{actor_name or actor_email or 'unknown'}] {detail}"
                if (actor_name or actor_email)
                else detail
            ),
        )
    except Exception:
        pass

    return row

@router.post("/resolve-by-key", response_model=AnomalyResponse)
def resolve_anomaly_by_key(
    payload: dict,
    db: DBSession = Depends(get_db),
):
    """Resolve (create-then-resolve) an anomaly identified by the client's
    string key.

    The attendant's Live Monitor derives anomalies from session rules, so
    their IDs look like "overstay-42", "after-hours-12", "facility-full",
    "duplicate-ABC1234" — not DB row IDs. This endpoint lets the frontend
    log a resolution for one of those without pre-creating the row.

    The client key is stored in `details` with a stable "[key:...]" marker,
    so we can find the row again on subsequent calls without a schema
    change.
    """
    data = payload or {}

    client_key   = (data.get("client_key") or "").strip()
    plate        = (data.get("plate_number") or "").strip().upper()
    anomaly_type = (data.get("anomaly_type") or "").strip().lower()
    severity     = (data.get("severity") or "medium").strip().lower()
    details      = (data.get("details") or "").strip() or None
    session_id   = data.get("session_id")
    action       = (data.get("action") or "").strip().lower()

    if not client_key:
        raise HTTPException(status_code=422, detail="client_key is required.")
    if not plate:
        raise HTTPException(status_code=422, detail="plate_number is required.")
    if not anomaly_type:
        raise HTTPException(status_code=422, detail="anomaly_type is required.")
    if action not in ("verify", "override", "dismiss"):
        raise HTTPException(
            status_code=422,
            detail="Action must be verify, override, or dismiss.",
        )

    # Normalize a few aliases that the Live Monitor uses so the DB values
    # stay consistent with the owner-side detection vocabulary.
    type_aliases = {
        "overstay":            "long_stay",
        "unpaid_overstay":     "long_stay",
        "after_hours_paid":    "long_stay",
        "after_hours_unpaid":  "long_stay",
        "duplicate":           "duplicate_entry",
        "facility_full":       "capacity_breach",
    }
    canonical_type = type_aliases.get(anomaly_type, anomaly_type)

    # severity: Live Monitor uses "critical" — map it to the backend's "high".
    if severity == "critical":
        severity = "high"
    if severity not in ("low", "medium", "high"):
        severity = "medium"

    key_marker = f"[key:{client_key}]"

    row = (
        db.query(Anomaly)
        .filter(
            Anomaly.plate_number == plate,
            Anomaly.anomaly_type == canonical_type,
            Anomaly.details.like(f"%{key_marker}%"),
        )
        .order_by(Anomaly.id.desc())
        .first()
    )

    if row is None:
        row = Anomaly(
            session_id=session_id,
            plate_number=plate,
            anomaly_type=canonical_type,
            severity=severity,
            status="flagged",
            details=f"{key_marker} {details}" if details else key_marker,
            detected_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

    # Idempotent: if it's already resolved, just return the row.
    if row.status != "flagged":
        return row

    new_status = {
        "verify":   "verified",
        "override": "overridden",
        "dismiss":  "dismissed",
    }[action]

    previous = row.status
    row.status = new_status
    row.resolution_notes = (data.get("resolution_notes") or "").strip() or None
    row.resolved_by = (
        (data.get("actor_name") or data.get("actor_email") or "").strip() or None
    )
    row.resolved_at = datetime.utcnow()

    db.add(row)
    db.commit()
    db.refresh(row)

    # ── Audit trail ──
    try:
        actor_role  = (data.get("actor_role")  or "").strip().lower() or "attendant"
        actor_email = (data.get("actor_email") or "").strip() or None
        actor_name  = (data.get("actor_name")  or "").strip() or None

        action_label = {
            "verify":   "Anomaly Verified",
            "override": "Anomaly Overridden",
            "dismiss":  "Anomaly Dismissed",
        }[action]

        detail = (
            f"{row.anomaly_type} · Plate: {row.plate_number}"
            f" · Session: {row.session_id or '—'}"
            f" · Severity: {row.severity}"
            f" · {previous} → {new_status}"
            + (f" · Notes: {row.resolution_notes}" if row.resolution_notes else "")
        )

        create_audit_log(
            db,
            user_id=None,
            user_email=actor_email,
            user_role=actor_role,
            action_type=action_label,
            reference_id=f"AN-{row.id}",
            details=(
                f"[{actor_name or actor_email or 'unknown'}] {detail}"
                if (actor_name or actor_email)
                else detail
            ),
        )
    except Exception:
        pass

    return row

@router.post("/flag-by-key", response_model=AnomalyResponse)
def flag_anomaly_by_key(
    payload: dict,
    db: DBSession = Depends(get_db),
):
    """Create (or return existing) anomaly row and write an audit entry
    for the *flagging* event, separate from resolution.

    Used by ScanVehicle when the scanner itself detects a rule violation
    (duplicate entry, verification failure, etc.) before it becomes a
    session anomaly. Keeps the anomaly registry complete.
    """
    data = payload or {}

    client_key   = (data.get("client_key") or "").strip()
    plate        = (data.get("plate_number") or "").strip().upper()
    anomaly_type = (data.get("anomaly_type") or "").strip().lower()
    severity     = (data.get("severity") or "medium").strip().lower()
    details      = (data.get("details") or "").strip() or None
    session_id   = data.get("session_id")

    if not client_key or not plate or not anomaly_type:
        raise HTTPException(status_code=422, detail="client_key, plate_number, and anomaly_type are required.")

    if severity == "critical":
        severity = "high"
    if severity not in ("low", "medium", "high"):
        severity = "medium"

    key_marker = f"[key:{client_key}]"

    existing = (
        db.query(Anomaly)
        .filter(
            Anomaly.plate_number == plate,
            Anomaly.anomaly_type == anomaly_type,
            Anomaly.details.like(f"%{key_marker}%"),
        )
        .order_by(Anomaly.id.desc())
        .first()
    )

    # If it's already flagged (or resolved), just return it — idempotent.
    if existing:
        return existing

    row = Anomaly(
        session_id=session_id,
        plate_number=plate,
        anomaly_type=anomaly_type,
        severity=severity,
        status="flagged",
        details=f"{key_marker} {details}" if details else key_marker,
        detected_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # ── Audit trail: the *flagging* event ──
    try:
        actor_role  = (data.get("actor_role")  or "").strip().lower() or "attendant"
        actor_email = (data.get("actor_email") or "").strip() or None
        actor_name  = (data.get("actor_name")  or "").strip() or None

        type_label = {
            "duplicate_entry":      "Duplicate Entry Flagged",
            "verification_failed":  "Verification Failure Flagged",
            "overstay":             "Overstay Flagged",
            "unpaid_overstay":      "Unpaid Overstay Flagged",
            "after_hours_paid":     "After-Hours Presence Flagged",
            "after_hours_unpaid":   "After-Hours Unpaid Flagged",
            "facility_full":        "Facility Full Flagged",
            "unpaid_exit":          "Unpaid Exit Flagged",
            "fee_mismatch":         "Fee Mismatch Flagged",
            "long_stay":            "Long Stay Flagged",
        }.get(anomaly_type, "Anomaly Flagged")

        detail = (
            f"{anomaly_type} · Plate: {plate}"
            f" · Session: {session_id or '—'}"
            f" · Severity: {severity}"
            + (f" · {details}" if details else "")
        )

        create_audit_log(
            db,
            user_id=None,
            user_email=actor_email,
            user_role=actor_role,
            action_type=type_label,
            reference_id=f"AN-{row.id}",
            details=(
                f"[{actor_name or actor_email or 'system'}] {detail}"
                if (actor_name or actor_email)
                else detail
            ),
        )
    except Exception:
        pass

    return row