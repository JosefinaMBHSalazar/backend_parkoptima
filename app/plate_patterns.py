import re
from typing import Any, Dict, List, Optional, Tuple

PLATE_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"^[A-Z]{3}\d{3}$"), "4_wheels"),
    (re.compile(r"^[A-Z]{2}\d{4}$"), "motor"),
    (re.compile(r"^\d{4}[A-Z]{2}$"), "motor"),
    (re.compile(r"^[A-Z]{3}\d{4}$"), "4_wheels"),
    (re.compile(r"^\d{3}[A-Z]{3}$"), "motor"),
    (re.compile(r"^[A-Z]\d{3}[A-Z]{2}$"), "motor"),
    (re.compile(r"^[A-Z]{2}\d{3}[A-Z]$"), "motor"),
    (re.compile(r"^\d[A-Z]{3}\d{2}$"), "motor"),
    (re.compile(r"^[A-Z]\d{4}[A-Z]$"), "motor"),
    (re.compile(r"^[A-Z]\d{2}[A-Z]\d{3}$"), "motor"),
    (re.compile(r"^[A-Z]\d{2}[A-Z]\d{2}$"), "motor"),
]

OCR_CORRECTIONS = {"O": "0", "Q": "0", "I": "1", "L": "1", "S": "5", "Z": "2", "B": "8", "G": "6"}


def normalize_plate_key(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def classify_plate_type(plate: str) -> Optional[str]:
    normalized = normalize_plate_key(plate)
    if not normalized:
        return None

    for pattern, vehicle_type in PLATE_PATTERNS:
        if pattern.fullmatch(normalized):
            return vehicle_type

    corrected = "".join(OCR_CORRECTIONS.get(char, char) for char in normalized)
    if corrected != normalized:
        for pattern, vehicle_type in PLATE_PATTERNS:
            if pattern.fullmatch(corrected):
                return vehicle_type
    return None


def extract_plate_candidate(ocr_results: List[Dict[str, Any]]) -> Optional[str]:
    for item in ocr_results:
        cleaned = normalize_plate_key(str(item.get("text") or ""))
        if not cleaned:
            continue
        if classify_plate_type(cleaned):
            return cleaned
        corrected = "".join(OCR_CORRECTIONS.get(char, char) for char in cleaned)
        if corrected != cleaned and classify_plate_type(corrected):
            return corrected
    return None
