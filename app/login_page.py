from typing import Dict
from sqlalchemy.orm import Session
from .models import OwnerProfile


def get_login_page_data(db: Session) -> Dict[str, object]:
    profile = db.query(OwnerProfile).first()
    return {
        "default_email": profile.email if profile else "owner@parkoptima.com",
        "default_role": "owner",
    }
