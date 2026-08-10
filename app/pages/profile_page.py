from typing import Dict
from sqlalchemy.orm import Session
from ..models import OwnerProfile


def get_profile_page_data(db: Session) -> Dict[str, object]:
    profile = db.query(OwnerProfile).first()
    return {
        "full_name": profile.full_name if profile else "Parking Owner",
        "email": profile.email if profile else "owner@parkoptima.com",
        "image_url": profile.image_url if profile else None,
    }

