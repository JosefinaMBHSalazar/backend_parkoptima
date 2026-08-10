from typing import List

from sqlalchemy.orm import Session

from .models import AuditLog


def create_audit_log(db: Session, *, user_id=None, user_email=None, user_role=None,
                     action_type: str, reference_id=None, details=None) -> AuditLog:
    entry = AuditLog(
        user_id=str(user_id) if user_id is not None else None,
        user_email=user_email,
        user_role=user_role,
        action_type=action_type,
        reference_id=reference_id,
        details=details,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_audit_logs(db: Session) -> List[AuditLog]:
    return db.query(AuditLog).order_by(AuditLog.timestamp.desc()).all()
