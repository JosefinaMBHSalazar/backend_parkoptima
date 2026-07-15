from typing import List, Dict


def get_quick_actions_data() -> List[Dict[str, object]]:
    return [
        {"name": "My Vehicle", "path": "/vehicle-owner/my-vehicle"},
        {"name": "Parking History", "path": "/vehicle-owner/history"},
        {"name": "Change PIN", "path": "/vehicle-owner/change-pin"},
    ]
