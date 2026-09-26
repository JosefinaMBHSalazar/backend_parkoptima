from __future__ import annotations

import base64
import io
import re
import logging
from typing import Optional, Tuple, List
from collections import defaultdict

from sqlalchemy.orm import Session

from .models import OwnerProfile, ParkingSession, SystemSettings, User, VehicleRegistration

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_YOLO_MODEL = None

def _get_yolo_model():
    global _YOLO_MODEL
    if _YOLO_MODEL is None:
        from ultralytics import YOLO
        logger.info("Loading YOLO model...")
        _YOLO_MODEL = YOLO("yolov8n.pt")
        logger.info("YOLO model loaded successfully")
    return _YOLO_MODEL


def _detect_vehicle_type_with_yolo(image) -> Optional[str]:
    try:
        model = _get_yolo_model()
        results = model(image)
        if not results or not results[0].boxes:
            logger.info("YOLO: No detections found")
            return None

        names = results[0].names
        detected_classes = []
        for class_id in results[0].boxes.cls:
            class_name = names[int(class_id)]
            detected_classes.append(class_name)
            if class_name in {"motorcycle", "motorbike", "bicycle", "scooter"}:
                logger.info(f"YOLO detected: {class_name} -> motor")
                return "motor"
            if class_name in {"car", "truck", "bus", "van"}:
                logger.info(f"YOLO detected: {class_name} -> 4wheels")
                return "4wheels"

        logger.info(f"YOLO detections: {detected_classes}")
        return None
    except Exception as e:
        logger.error(f"YOLO error: {e}")
        return None


def get_or_create_settings(db: Session) -> SystemSettings:
    settings = db.query(SystemSettings).first()
    if settings is None:
        logger.info("🆕 No settings found, creating default settings...")
        settings = SystemSettings(
            system_name="ParkOptima",
            motor_fee=5.0,
            four_wheel_fee=20.0,
            parking_capacity=100,
        )
        db.add(settings)
        try:
            db.commit()
            db.refresh(settings)
            logger.info(f"✅ Created new settings with parking_capacity: {settings.parking_capacity}")
        except Exception as e:
            logger.error(f"❌ Failed to create settings: {e}")
            db.rollback()
            raise
    else:
        logger.info(f"📊 Retrieved settings with parking_capacity: {settings.parking_capacity}")
    return settings


def get_or_create_owner_profile(db: Session) -> OwnerProfile:
    profile = db.query(OwnerProfile).first()
    if profile is None:
        profile = OwnerProfile(full_name="Parking Owner", email="owner@parkoptima.com")
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def infer_vehicle_type(plate_number: str) -> str:
    """Infer vehicle type from plate number format.

    PH plate format rules:
      • Old 4-wheel plate: 3 letters + 3 digits        → ABC123
      • Old motor plate:   3 digits + 3 letters        → 123ABC
      • New 4-wheel plate: 3 letters + 4 digits        → ABC1234
      • New motor plate:   4 digits + 2 letters        → 0507GQ
      • New motor plate:   2 letters + 4 digits        → GQ0507
      • Motor variant:     1 letter + 3 digits + 2 letters → D434SA
    """
    cleaned = plate_number.replace("-", "").replace(" ", "").upper()
    if not cleaned:
        return "motor"

    # ── 1 letter + 3 digits + 2 letters → MOTOR VARIANT ──
    # e.g. D434SA, M123AB — must be checked BEFORE the 3L+3D case
    if (
        len(cleaned) == 6
        and cleaned[0].isalpha()
        and cleaned[1:4].isdigit()
        and cleaned[4:].isalpha()
    ):
        logger.info(f"Detected motor plate format (1L+3D+2L): {cleaned}")
        return "motor"

    # ── 3 letters + 3 digits, letters FIRST → OLD 4-WHEEL PLATE ──
    if len(cleaned) == 6 and cleaned[:3].isalpha() and cleaned[3:].isdigit():
        logger.info(f"Detected old 4-wheel plate format (3 letters + 3 digits): {cleaned}")
        return "4wheels"

    # ── 3 digits + 3 letters, digits FIRST → OLD MOTOR PLATE ──
    if len(cleaned) == 6 and cleaned[:3].isdigit() and cleaned[3:].isalpha():
        logger.info(f"Detected old motor plate format (3 digits + 3 letters): {cleaned}")
        return "motor"

    # ── 4 digits + 2 letters → motor (e.g. 0507GQ) ──
    if len(cleaned) == 6 and cleaned[:4].isdigit() and cleaned[4:].isalpha():
        logger.info(f"Detected motorcycle plate format (4 digits + 2 letters): {cleaned}")
        return "motor"

    # ── 2 letters + 4 digits → motor (e.g. GQ0507) ──
    if len(cleaned) == 6 and cleaned[:2].isalpha() and cleaned[2:].isdigit():
        logger.info(f"Detected motorcycle plate format (2 letters + 4 digits): {cleaned}")
        return "motor"

    # ── 3 letters + 4 digits → 4-wheel (e.g. ABC1234) ──
    if len(cleaned) == 7 and cleaned[:3].isalpha() and cleaned[3:].isdigit():
        logger.info(f"Detected 4-wheel plate format (3 letters + 4 digits): {cleaned}")
        return "4wheels"

    # ── 4 digits + 3 letters → uncommon motor variant ──
    if len(cleaned) == 7 and cleaned[:4].isdigit() and cleaned[4:].isalpha():
        logger.info(f"Detected motor plate format (4 digits + 3 letters): {cleaned}")
        return "motor"

    # ── Fallback ──
    if cleaned[0].isdigit():
        return "motor"
    return "4wheels"


def get_vehicle_type_from_db(db: Session, plate_number: str) -> Optional[str]:
    """Check if the plate is registered in the database and return its vehicle type."""
    normalized_plate = plate_number.replace(" ", "").replace("-", "").upper()

    user = db.query(User).filter(User.plate_number == normalized_plate).first()
    if user and user.vehicle_type:
        logger.info(f"Found vehicle type in users table for {normalized_plate}: {user.vehicle_type}")
        return user.vehicle_type

    registration = db.query(VehicleRegistration).filter(
        VehicleRegistration.plate_number == normalized_plate
    ).first()
    if registration and registration.vehicle_type:
        logger.info(f"Found vehicle type in vehicle_registrations for {normalized_plate}: {registration.vehicle_type}")
        return registration.vehicle_type

    return None


def estimate_fee(vehicle_type: str, settings: SystemSettings) -> float:
    return settings.motor_fee if vehicle_type == "motor" else settings.four_wheel_fee


_EASYOCR_READER = None


def _get_easyocr_reader():
    """Lazily build (and cache) the EasyOCR reader so we don't reload the
    model on every scan request."""
    global _EASYOCR_READER
    if _EASYOCR_READER is None:
        import easyocr
        logger.info("Loading EasyOCR reader...")
        _EASYOCR_READER = easyocr.Reader(["en"], gpu=False)
        logger.info("EasyOCR reader loaded successfully")
    return _EASYOCR_READER


# ── LTO plate whitelist ─────────────────────────────────────────
# Single source of truth for accepted plate formats, kept in sync with
# sign_up_form.jsx / add_vehicle_form.jsx / scan_vehicle.jsx.
#
# Motorcycle (20 patterns):
#   The 17 current LTO motorcycle formats + 3 legacy formats.
# 4-Wheels (2 patterns):
#   ABC123  (old: 3 letters + 3 digits)
#   ABC1234 (new: 3 letters + 4 digits)
#
# NOTE: ABC123 is intentionally NOT a motorcycle format — that shape
#       belongs to old 4-wheel plates.
_LTO_WHITELIST_PATTERNS = [
    # ── Motorcycle ──
    r"\d[A-Z]{3}\d{2}",         # 1ABC23
    r"\d{2}[A-Z]{2}\d[A-Z]",    # 12AB3C
    r"[A-Z]{2}\d[A-Z]\d{2}",    # AB1C23
    r"\d[A-Z]\d[A-Z]{2}\d",     # 1A2BC3
    r"[A-Z]\d[A-Z]\d[A-Z]\d",   # A1B2C3
    r"[A-Z]\d{2}[A-Z]\d[A-Z]",  # A12B3C
    r"\d[A-Z]{2}\d{2}[A-Z]",    # 1AB23C
    r"[A-Z]\d[A-Z]{2}\d[A-Z]",  # A1B23C
    r"[A-Z]{2}\d{2}[A-Z]\d",    # AB12C3
    r"\d[A-Z]{2}\d[A-Z]\d",     # 1AB2C3
    r"[A-Z]\d{2}[A-Z]{2}\d",    # A12BC3
    r"[A-Z]\d[A-Z]\d{3}",       # A1B234
    r"[A-Z]\d{2}[A-Z]\d{2}",    # A12B34
    r"[A-Z]\d{3}[A-Z]\d",       # A123B4
    r"\d{2}[A-Z]{3}\d",         # 12ABC3
    r"[A-Z]\d[A-Z]{2}\d{2}",    # A1BC23
    r"[A-Z]\d{3}[A-Z]{2}",      # A123BC / D479QD
    r"\d{3}[A-Z]{3}",           # 123ABC
    r"\d{4}[A-Z]{2}",           # 0507GQ
    r"[A-Z]{2}\d{4}",           # AB1234
    # ── 4-Wheels ──
    r"[A-Z]{3}\d{3}",           # ABC123
    r"[A-Z]{3}\d{4}",           # ABC1234
]

_LTO_WHITELIST_RE = re.compile(r"(" + "|".join(_LTO_WHITELIST_PATTERNS) + r")$")


# OCR ambiguity table: for each commonly-confused character, list the
# plausible alternatives (itself first, then the alternatives most likely
# to be the intended character).
_AMBIGUOUS_OCR_MAP = {
    # Leading 0 is almost always a misread D on PH plates. Try D first.
    '0': ['D', '0', 'O'],
    'O': ['D', 'O', '0'],
    'D': ['D', '0'],
    'P': ['P', 'D'],
    '1': ['1', 'I', 'L'],
    'I': ['I', '1', 'L'],
    'L': ['L', '1', 'I'],
    # S/5 and B/8 confusions are common in LPR too.
    'S': ['S', '5'],
    '5': ['5', 'S'],
    'B': ['B', '8'],
    '8': ['8', 'B'],
}


def _resolve_ocr_ambiguities(s: str) -> str:
    """Resolve OCR ambiguity against the LTO whitelist.

    Strategy:
      1. If the original string already matches the whitelist, return it —
         EXCEPT when it starts with a leading '0' or 'P' before another
         digit, which is a strong misread-'D' signal (e.g. 0434SA → D434SA).
      2. Otherwise, search substitution combinations in order of increasing
         edit count. Return the first whitelist-valid candidate with the
         fewest substitutions. This preserves interior digits (5030HB stays
         5030HB, not 5D3DH8) while still fixing single-character errors
         (5030H8 → 5030HB, D479Q0 → D479QD).
    """
    # ── Stage 1: original already valid ──
    if _LTO_WHITELIST_RE.fullmatch(s):
        if len(s) >= 2 and s[0] in ('0', 'P') and s[1].isdigit():
            candidate = 'D' + s[1:]
            if _LTO_WHITELIST_RE.fullmatch(candidate):
                return candidate
        return s

    # ── Stage 2: minimum-edit search ──
    positions = [i for i, c in enumerate(s) if c in _AMBIGUOUS_OCR_MAP]
    if not positions or len(positions) > 6:
        return s

    import itertools

    # For each position, build the list of alternatives WITHOUT the
    # original character (we handle "no change" implicitly by tracking
    # how many positions we actually change).
    alternatives = {i: [c for c in _AMBIGUOUS_OCR_MAP[s[i]] if c != s[i]] for i in positions}

    # Try increasing edit counts.
    for k in range(1, len(positions) + 1):
        for combo_positions in itertools.combinations(positions, k):
            # Only consider positions where there's at least one alternative.
            if any(not alternatives[p] for p in combo_positions):
                continue
            for combo_chars in itertools.product(*[alternatives[p] for p in combo_positions]):
                candidate = list(s)
                for p, c in zip(combo_positions, combo_chars):
                    candidate[p] = c
                candidate = ''.join(candidate)
                if _LTO_WHITELIST_RE.fullmatch(candidate):
                    return candidate

    return s


def _looks_like_plate(text: str):
    """Return a normalized plate string if `text` resembles a PH plate, else None.

    Acceptance is gated solely by the LTO whitelist (`_LTO_WHITELIST_RE`).
    OCR-confusion-prone characters are resolved against the same whitelist
    before the final accept/reject decision.
    """
    if not text:
        return None

    # Clean the text - remove spaces, dashes, underscores, brackets, etc.
    cleaned = re.sub(r"[^A-Z0-9]", "", text.upper())

    if not cleaned:
        return None

    logger.info(f"Checking plate pattern for: '{cleaned}'")

    # ── Remove stray characters that are likely OCR errors ──
    cleaned_original = cleaned

    match = re.match(r"^([A-Z]{3})[^A-Z0-9]?([A-Z]?)(\d{3,4})$", cleaned)
    if match:
        letters_part = match.group(1)
        extra_char = match.group(2) if match.group(2) else ''
        digits_part = match.group(3)

        if extra_char and digits_part and len(digits_part) in [3, 4]:
            test_cleaned = letters_part + digits_part
            test_letters = ''.join(c for c in test_cleaned if c.isalpha())
            test_digits = ''.join(c for c in test_cleaned if c.isdigit())

            if len(test_letters) == 3 and len(test_digits) == 3:
                cleaned = test_cleaned
                logger.info(f"✅ Removed stray character '{extra_char}' from '{cleaned_original}' -> '{cleaned}'")
            elif len(test_letters) == 3 and len(test_digits) == 4:
                cleaned = test_cleaned
                logger.info(f"✅ Removed stray character '{extra_char}' from '{cleaned_original}' -> '{cleaned}'")

    # Reconstruct from letters + digits if there are extra characters
    letters = ''.join(c for c in cleaned if c.isalpha())
    digits = ''.join(c for c in cleaned if c.isdigit())

    if len(letters) == 3 and len(digits) in [3, 4] and len(cleaned) > len(letters) + len(digits):
        if cleaned[0].isalpha():
            test_cleaned = letters + digits
        else:
            test_cleaned = digits + letters

        test_letters = ''.join(c for c in test_cleaned if c.isalpha())
        test_digits = ''.join(c for c in test_cleaned if c.isdigit())

        if len(test_letters) == 3 and len(test_digits) == 3:
            cleaned = test_cleaned
            logger.info(f"✅ Reconstructed plate from letters and digits: '{cleaned}'")
        elif len(test_letters) == 3 and len(test_digits) == 4:
            cleaned = test_cleaned
            logger.info(f"✅ Reconstructed plate from letters and digits: '{cleaned}'")

    # ── Common OCR character substitutions ──
    # (O→0 and I→1 first; the ambiguity resolver below may flip them back
    # to letters if a whitelist pattern emerges.)
    cleaned = cleaned.replace('O', '0')
    cleaned = cleaned.replace('I', '1')

    cleaned = re.sub(r"[^A-Z0-9]", "", cleaned)

    logger.info(f"Before ambiguity resolution: '{cleaned}'")

    # ── Ambiguity resolution by whitelist matching ──
    # For each ambiguous character (0/O/D, 1/I/L, P/D), try every plausible
    # substitution and pick the first combination that matches an LTO
    # whitelist pattern. Handles cases like:
    #   D479Q0  → D479QD   (trailing 0 should be D)
    #   P434SA  → D434SA   (leading P should be D)
    #   0Q507D  → DQ507D   (leading 0 should be D)
    # If no combination matches, the original string is returned unchanged.
    _resolved = _resolve_ocr_ambiguities(cleaned)
    if _resolved != cleaned:
        logger.info(f"✅ Ambiguity resolved by whitelist match: '{cleaned}' → '{_resolved}'")
        cleaned = _resolved

    logger.info(f"After OCR correction: '{cleaned}'")

    # ── Final acceptance gate: the whitelist is the sole authority ──
    if not _LTO_WHITELIST_RE.fullmatch(cleaned):
        logger.info(f"❌ '{cleaned}' does not match any LTO whitelist pattern — rejecting.")
        return None

    logger.info(f"✅ Plate matches LTO whitelist: {cleaned}")
    return cleaned


# Word-boundary-safe keywords (won't match inside other words)
FOUR_WHEEL_KEYWORDS = {
    "MATATAG", "MATATAGNA", "REPUBLIKA", "REPUBLIC",
    "PILIPINAS", "PHILIPPINES", "LTO",
    # Partial keywords — survive a leading OCR misread (NATATAG → still matches ATATAG)
    "ATATAG", "EPUBLIK", "EPUBLIC", "PILIPIN",
}
MOTOR_KEYWORDS = {
    "MOTORCYCLE", "MOTOR",
    # "MC" intentionally removed — too short, matched inside ZMCI445
}

def _detect_plate_slogan(all_texts):
    """Look for slogan text near the plate number that indicates whether the
    plate is a 4-wheel plate or a motorcycle plate.

    Returns "4wheels", "motor", or None if the slogan can't be determined.
    """
    if not all_texts:
        return None

    combined = " ".join((t or "").upper() for t, _ in all_texts)
    combined_clean = re.sub(r"[^A-Z0-9]+", " ", combined).strip()

    if not combined_clean:
        return None

    for kw in FOUR_WHEEL_KEYWORDS:
        if kw in combined_clean:
            logger.info(f"🪧 Slogan detected: '{kw}' → 4wheels plate")
            return "4wheels"

    for kw in MOTOR_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", combined_clean):
            logger.info(f"🪧 Slogan detected: '{kw}' → motor plate")
            return "motor"

    return None


def _estimate_plate_aspect_ratio(detections) -> Optional[float]:
    """Return the widest bounding box aspect ratio from EasyOCR detections."""
    if not detections:
        return None
    widest = 0.0
    for det in detections:
        try:
            bbox = det[0]
            xs = [pt[0] for pt in bbox]
            ys = [pt[1] for pt in bbox]
            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            if h > 0:
                ratio = w / h
                if ratio > widest:
                    widest = ratio
        except Exception:
            continue
    return widest if widest > 0 else None


def analyze_scan_image(image_base64: str, db: Optional[Session] = None) -> Tuple[str, float, str]:
    """Run real LPR: decode the image, detect the vehicle class with YOLO
    (best-effort) and read the license plate with EasyOCR. Returns
    ``(plate, confidence, vehicle_type)``.

    This does NOT create a session - it only detects the plate.

    If db is provided, it will check the database for registered vehicle type.
    """
    logger.info("Analyzing scan image...")

    try:
        import cv2
        import numpy as np
    except Exception as e:
        logger.error(f"Failed to import CV2: {e}")
        return "ABC1234", 0.82, "motor"

    try:
        image_bytes = base64.b64decode(image_base64)
        image_array = np.asarray(bytearray(image_bytes), dtype=np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("invalid image")
        logger.info(f"Image decoded successfully: {image.shape}")
    except Exception as e:
        logger.error(f"Failed to decode image: {e}")
        return "ABC1234", 0.82, "motor"

    # Vehicle type: YOLO if available
    logger.info("Detecting vehicle type with YOLO...")
    yolo_vehicle_type = _detect_vehicle_type_with_yolo(image)
    logger.info(f"YOLO vehicle type detection result: {yolo_vehicle_type}")

    # Read the plate with EasyOCR
    logger.info("Reading license plate with EasyOCR...")
    try:
        reader = _get_easyocr_reader()
        np_image = np.asarray(image)
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
            gray = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)
            blur = cv2.GaussianBlur(gray, (0, 0), sigmaX=3)
            sharpened = cv2.addWeighted(gray, 1.5, blur, -0.5, 0)
            proc_img = cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)
            logger.debug("OCR preprocessing applied")
        except Exception as pre_e:
            logger.warning(f"OCR preprocessing failed: {pre_e}; using original image")
            proc_img = np_image
        detections = reader.readtext(proc_img, detail=1, paragraph=False)
        logger.info(f"EasyOCR found {len(detections)} text detections")
        for det in detections:
            text = det[1] if len(det) > 1 else ""
            conf = det[2] if len(det) > 2 else 0.0
            logger.info(f"  - Text: '{text}', Confidence: {conf}")
    except Exception as e:
        logger.error(f"EasyOCR error: {e}")
        detections = []

    # Collect all text detections
    all_texts = []
    for det in detections:
        if len(det) >= 2:
            text = str(det[1]).strip()
            conf = float(det[2]) if len(det) > 2 else 0.0
            text = re.sub(r"[\[\]{}()]", "", text)
            if text:
                all_texts.append((text, conf))

    logger.info(f"Collected {len(all_texts)} text detections")

    best_plate = None
    best_conf = 0.0

    for text, conf in all_texts:
        plate_match = _looks_like_plate(text)
        if plate_match:
            logger.info(f"Found plate from individual text: '{plate_match}' (conf: {conf})")
            if conf > best_conf:
                best_plate = plate_match
                best_conf = conf

    if best_plate is None and len(all_texts) >= 2:
        logger.info("Trying to combine separate letter and number detections...")

        letter_texts = []
        number_texts = []

        for text, conf in all_texts:
            clean_text = re.sub(r"[^A-Z0-9]", "", text.upper())
            clean_text = clean_text.replace('O', '0')
            clean_text = clean_text.replace('I', '1')
            if not clean_text:
                continue

            letter_count = sum(1 for c in clean_text if c.isalpha())
            digit_count = sum(1 for c in clean_text if c.isdigit())

            if letter_count > digit_count and letter_count >= 2:
                letter_texts.append((clean_text, conf))
            elif digit_count > letter_count and digit_count >= 2:
                number_texts.append((clean_text, conf))
            else:
                if letter_count >= 2:
                    letter_texts.append((clean_text, conf))
                if digit_count >= 2:
                    number_texts.append((clean_text, conf))

        logger.info(f"Letter detections: {letter_texts}")
        logger.info(f"Number detections: {number_texts}")

        for letter_text, letter_conf in letter_texts:
            for number_text, number_conf in number_texts:
                for combined in [letter_text + number_text, number_text + letter_text]:
                    avg_conf = (letter_conf + number_conf) / 2
                    logger.info(f"Testing combination: '{combined}' (avg conf: {avg_conf})")
                    plate_match = _looks_like_plate(combined)
                    if plate_match:
                        logger.info(f"✅ Found plate from combination: '{plate_match}' (conf: {avg_conf})")
                        if avg_conf > best_conf:
                            best_plate = plate_match
                            best_conf = avg_conf
                            break
                if best_plate:
                    break

    if best_plate is None and all_texts:
        logger.info("No plate pattern found, trying aggressive fallback...")

        all_letters = ''
        all_digits = ''

        for text, conf in all_texts:
            clean_text = re.sub(r"[^A-Z0-9]", "", text.upper())
            clean_text = clean_text.replace('O', '0')
            clean_text = clean_text.replace('I', '1')
            letters = ''.join(c for c in clean_text if c.isalpha())
            digits = ''.join(c for c in clean_text if c.isdigit())
            all_letters += letters
            all_digits += digits

        logger.info(f"All letters: '{all_letters}', All digits: '{all_digits}'")

        if all_letters and all_digits:
            combinations = []

            if len(all_letters) >= 3 and len(all_digits) >= 4:
                combinations.append((f"{all_letters[:3]}{all_digits[:4]}", 0.5))

            if len(all_letters) >= 3 and len(all_digits) >= 3:
                combinations.append((f"{all_letters[:3]}{all_digits[:3]}", 0.5))

            if len(all_letters) >= 2 and len(all_digits) >= 4:
                combinations.append((f"{all_letters[:2]}{all_digits[:4]}", 0.5))
                combinations.append((f"{all_digits[:4]}{all_letters[:2]}", 0.5))

            if len(all_digits) >= 4 and len(all_letters) >= 2:
                combinations.append((f"{all_digits[:4]}{all_letters[:2]}", 0.5))

            # Only accept the fallback candidate if it passes the whitelist.
            for candidate, cand_conf in combinations:
                if _LTO_WHITELIST_RE.fullmatch(candidate):
                    best_plate, best_conf = candidate, cand_conf
                    logger.info(f"Using aggressive fallback (whitelist-accepted): '{best_plate}'")
                    break
            else:
                logger.info("Aggressive fallback produced no whitelist-valid candidate.")

    if best_plate is None:
        logger.warning("No plate found, using default")
        return "ABC1234", 0.82, "motor"

    # ── Priority-ordered vehicle type resolution ──
    vehicle_type = None
    type_source = None

    # 1️⃣ Database
    if db:
        db_vehicle_type = get_vehicle_type_from_db(db, best_plate)
        if db_vehicle_type:
            vehicle_type = db_vehicle_type
            type_source = "database"
            logger.info(f"✅ Vehicle type from DATABASE: {vehicle_type}")

    # 2️⃣ Slogan detection
    if vehicle_type is None:
        slogan_type = _detect_plate_slogan(all_texts)
        if slogan_type:
            vehicle_type = slogan_type
            type_source = "slogan"
            logger.info(f"✅ Vehicle type from SLOGAN: {vehicle_type}")

    # 3️⃣ Aspect ratio — only used as a SUPPORTING signal
    if vehicle_type is None:
        aspect = _estimate_plate_aspect_ratio(detections)
        if aspect is not None:
            logger.info(f"📐 Widest detection aspect ratio: {aspect:.2f}")

            plate_looks_like_4wheel = (
                bool(re.fullmatch(r"[A-Z]{3}\d{3}", best_plate)) or
                bool(re.fullmatch(r"[A-Z]{3}\d{4}", best_plate))
            )

            plate_looks_like_motor = (
                bool(re.fullmatch(r"\d{3}[A-Z]{3}", best_plate)) or
                bool(re.fullmatch(r"\d{4}[A-Z]{2}", best_plate)) or
                bool(re.fullmatch(r"[A-Z]{2}\d{4}", best_plate)) or
                bool(re.fullmatch(r"\d{4}[A-Z]{3}", best_plate)) or
                bool(re.fullmatch(r"[A-Z]\d{3}[A-Z]{2}", best_plate))  # 1L+3D+2L e.g. D434SA
            )

            if plate_looks_like_motor:
                logger.info(f"⏭️ Aspect ratio skipped (plate matches motor pattern: {best_plate})")
            elif plate_looks_like_4wheel and len(detections) >= 2 and aspect >= 2.20:
                vehicle_type = "4wheels"
                type_source = "aspect_ratio"
                logger.info(f"✅ Vehicle type from ASPECT RATIO ({aspect:.2f} ≥ 2.20, {len(detections)} detections): 4wheels")
            else:
                reason = (
                    "too few detections" if len(detections) < 2 else
                    "ratio below 2.20" if aspect < 2.20 else
                    "plate pattern unclear"
                )
                logger.info(f"⏭️ Aspect ratio skipped ({reason})")

    # 4️⃣ YOLO detection
    if vehicle_type is None and yolo_vehicle_type:
        vehicle_type = yolo_vehicle_type
        type_source = "yolo"
        logger.info(f"✅ Vehicle type from YOLO: {vehicle_type}")

    # 5️⃣ Plate format heuristic (final fallback)
    if vehicle_type is None:
        vehicle_type = infer_vehicle_type(best_plate)
        type_source = "format_heuristic"
        logger.info(f"✅ Vehicle type from FORMAT HEURISTIC: {vehicle_type}")

    logger.info(f"🎯 Vehicle type resolved via {type_source}: {vehicle_type}")

    try:
        conf_val = float(best_conf)
        if conf_val > 1.0:
            conf_val = conf_val / 100.0
    except Exception:
        conf_val = 0.0
    logger.info(f"🎯 FINAL RESULT: Plate='{best_plate}', Conf={conf_val}, Type={vehicle_type}")
    return best_plate, round(conf_val, 3), vehicle_type


def create_session_from_scan(db: Session, plate_number: str, vehicle_type: str, settings: SystemSettings) -> ParkingSession:
    logger.info(f"Creating parking session for plate: {plate_number}, type: {vehicle_type}")
    session = ParkingSession(
        plate_number=plate_number.upper(),
        vehicle_type=vehicle_type,
        fee=estimate_fee(vehicle_type, settings),
        status="parked",
        payment_method=None,
        slot="A1",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info(f"Session created with ID: {session.id}")
    return session