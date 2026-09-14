from typing import Dict


def get_vehicle_registration_data() -> Dict[str, object]:
    return {"message": "Vehicle registration", "required_fields": ["plate_number", "vehicle_type", "owner_name"]}

