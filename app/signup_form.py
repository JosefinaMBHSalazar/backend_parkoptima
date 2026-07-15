from typing import Dict


def get_signup_form_data() -> Dict[str, object]:
    return {"message": "Sign up", "roles": ["owner", "attendant", "vehicle owner"]}
