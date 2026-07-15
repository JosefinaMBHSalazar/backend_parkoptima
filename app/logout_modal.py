from typing import Dict


def get_logout_modal_data() -> Dict[str, object]:
    return {"message": "Are you sure you want to log out?", "confirm_label": "Log out"}
