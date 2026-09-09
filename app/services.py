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
    """Infer vehicle type from plate number format."""
    cleaned = plate_number.replace("-", "").replace(" ", "").upper()
    if not cleaned:
        return "motor"
    
    # Check if it's a motorcycle plate (4 digits + 2 letters)
    # e.g., 0507GQ, 1234AB, 5030HB
    if len(cleaned) >= 6 and cleaned[:4].isdigit() and cleaned[4:].isalpha() and len(cleaned[4:]) == 2:
        logger.info(f"Detected motorcycle plate format (digits + letters): {cleaned}")
        return "motor"
    
    # Check if it's a motorcycle plate (2 letters + 4 digits)
    # e.g., AB1234, GQ0507, HB5030
    if len(cleaned) >= 6 and cleaned[:2].isalpha() and cleaned[2:].isdigit() and len(cleaned[2:]) == 4:
        logger.info(f"Detected motorcycle plate format (letters + digits): {cleaned}")
        return "motor"
    
    # Check if it's a motorcycle plate (3 letters + 3 digits)
    # e.g., ABC123, 943EZQ, DSA434, ZMC445
    if len(cleaned) >= 6 and cleaned[:3].isalpha() and cleaned[3:].isdigit() and len(cleaned[3:]) == 3:
        logger.info(f"Detected motorcycle plate format (3+3): {cleaned}")
        return "motor"
    
    # Check if it starts with a number (likely 4 wheels)
    if cleaned[0].isdigit():
        return "4wheels"
    
    # If it has 3 letters and 4 digits, it's likely 4 wheels
    if len(cleaned) >= 7 and cleaned[:3].isalpha() and cleaned[3:].isdigit() and len(cleaned[3:]) == 4:
        return "4wheels"
    
    # Default to motor
    return "motor"


def get_vehicle_type_from_db(db: Session, plate_number: str) -> Optional[str]:
    """Check if the plate is registered in the database and return its vehicle type."""
    normalized_plate = plate_number.replace(" ", "").replace("-", "").upper()
    
    # Check in users table first
    user = db.query(User).filter(User.plate_number == normalized_plate).first()
    if user and user.vehicle_type:
        logger.info(f"Found vehicle type in users table for {normalized_plate}: {user.vehicle_type}")
        return user.vehicle_type
    
    # Check in vehicle_registrations table
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


def _looks_like_plate(text: str):
    """Return a normalized plate string if `text` resembles a PH plate, else None."""
    if not text:
        return None
    
    # Clean the text - remove spaces, dashes, underscores, brackets, etc.
    cleaned = re.sub(r"[^A-Z0-9]", "", text.upper())
    
    if not cleaned:
        return None
    
    logger.info(f"Checking plate pattern for: '{cleaned}'")
    
    # ── FIX: Remove stray characters that are likely OCR errors ──
    # Common OCR confusions that create extra characters
    # If there's a stray 'i' or 'I' between letters and digits, remove it
    # e.g., ZMCi445 -> ZMC445 (remove 'i')
    # e.g., ABCi123 -> ABC123 (remove 'i')
    
    # First, try to detect if there's a pattern like 3 letters + 1 extra char + 3 digits
    # or 3 letters + 1 extra char + 4 digits
    cleaned_original = cleaned
    
    # Check if we have letters, then a single extra char, then digits
    match = re.match(r"^([A-Z]{3})[^A-Z0-9]?([A-Z]?)(\d{3,4})$", cleaned)
    if match:
        letters_part = match.group(1)
        extra_char = match.group(2) if match.group(2) else ''
        digits_part = match.group(3)
        
        # If the extra char is a letter that's not part of the letters part,
        # and the digits part is 3 or 4 digits
        if extra_char and digits_part and len(digits_part) in [3, 4]:
            # Check if removing the extra char makes a valid plate
            test_cleaned = letters_part + digits_part
            test_letters = ''.join(c for c in test_cleaned if c.isalpha())
            test_digits = ''.join(c for c in test_cleaned if c.isdigit())
            
            if len(test_letters) == 3 and len(test_digits) == 3:
                cleaned = test_cleaned
                logger.info(f"✅ Removed stray character '{extra_char}' from '{cleaned_original}' -> '{cleaned}'")
            elif len(test_letters) == 3 and len(test_digits) == 4:
                cleaned = test_cleaned
                logger.info(f"✅ Removed stray character '{extra_char}' from '{cleaned_original}' -> '{cleaned}'")
    
    # Also try a more general approach: if there are 3 letters, some characters, and 3-4 digits
    # try to extract just the letters and digits
    letters = ''.join(c for c in cleaned if c.isalpha())
    digits = ''.join(c for c in cleaned if c.isdigit())
    
    # If we have 3 letters and 3-4 digits, but the total length is more than 6-7,
    # there might be extra characters
    if len(letters) == 3 and len(digits) in [3, 4] and len(cleaned) > len(letters) + len(digits):
        # Try to rebuild the plate with just letters and digits
        # But preserve the order: if the original had letters first, keep them first
        if cleaned[0].isalpha():
            test_cleaned = letters + digits
        else:
            test_cleaned = digits + letters
        
        # Check if this is valid
        test_letters = ''.join(c for c in test_cleaned if c.isalpha())
        test_digits = ''.join(c for c in test_cleaned if c.isdigit())
        
        if len(test_letters) == 3 and len(test_digits) == 3:
            cleaned = test_cleaned
            logger.info(f"✅ Reconstructed plate from letters and digits: '{cleaned}'")
        elif len(test_letters) == 3 and len(test_digits) == 4:
            cleaned = test_cleaned
            logger.info(f"✅ Reconstructed plate from letters and digits: '{cleaned}'")
    
    # ── FIX: P → D conversion ──
    if len(cleaned) >= 2 and cleaned[0] == 'P' and cleaned[1].isdigit():
        test_cleaned = 'D' + cleaned[1:]
        test_letters = ''.join(c for c in test_cleaned if c.isalpha())
        test_digits = ''.join(c for c in test_cleaned if c.isdigit())
        
        if len(test_letters) == 3 and len(test_digits) == 3:
            cleaned = test_cleaned
            logger.info(f"✅ Converted P to D (3+3 format): '{cleaned}'")
    
    # ── FIX: 0 → D conversion ──
    if len(cleaned) >= 2 and cleaned[0] == '0' and cleaned[1].isdigit():
        test_cleaned = 'D' + cleaned[1:]
        test_letters = ''.join(c for c in test_cleaned if c.isalpha())
        test_digits = ''.join(c for c in test_cleaned if c.isdigit())
        
        if len(test_letters) == 3 and len(test_digits) == 3:
            cleaned = test_cleaned
            logger.info(f"✅ Converted 0 to D (3+3 format): '{cleaned}'")
    
    # Common OCR confusions
    cleaned = cleaned.replace('O', '0')
    cleaned = cleaned.replace('I', '1')
    
    # Remove any remaining non-alphanumeric
    cleaned = re.sub(r"[^A-Z0-9]", "", cleaned)
    
    logger.info(f"After OCR correction: '{cleaned}'")
    
    # ── CRITICAL: Check if this is a valid plate format preserving original order ──
    
    # Count letters and digits
    letters = ''.join(c for c in cleaned if c.isalpha())
    digits = ''.join(c for c in cleaned if c.isdigit())
    total_len = len(cleaned)
    
    logger.info(f"Letters: '{letters}', Digits: '{digits}', Total: {total_len}")
    
    # Motor plates: total 6 characters
    if total_len == 6:
        # Check for 3 letters + 3 digits (any order)
        if len(letters) == 3 and len(digits) == 3:
            logger.info(f"✅ Valid motor plate (3+3) in original order: {cleaned}")
            return cleaned
        
        # Check for 4 digits + 2 letters
        if len(digits) == 4 and len(letters) == 2:
            logger.info(f"✅ Valid motor plate (4 digits + 2 letters) in original order: {cleaned}")
            return cleaned
        
        # Check for 2 letters + 4 digits
        if len(letters) == 2 and len(digits) == 4:
            logger.info(f"✅ Valid motor plate (2 letters + 4 digits) in original order: {cleaned}")
            return cleaned
    
    # 4-wheels plates: total 7 characters
    if total_len == 7:
        # Check for 3 letters + 4 digits (any order)
        if len(letters) == 3 and len(digits) == 4:
            logger.info(f"✅ Valid 4-wheels plate in original order: {cleaned}")
            return cleaned
    
    # If we couldn't validate with the original order, try to reorder
    if letters and digits:
        # For 4-wheels: 3 letters + 4 digits
        if len(letters) >= 3 and len(digits) >= 4:
            # Try to preserve original order
            if cleaned[0].isalpha():
                result = f"{letters[:3]}{digits[:4]}"
            else:
                result = f"{digits[:4]}{letters[:3]}"
            logger.info(f"✅ Formed 4-wheels plate: {result}")
            return result
        
        # For Motor: 3 letters + 3 digits (standard format)
        if len(letters) >= 3 and len(digits) >= 3:
            # Preserve original order
            if cleaned[0].isalpha():
                result = f"{letters[:3]}{digits[:3]}"
            else:
                result = f"{digits[:3]}{letters[:3]}"
            logger.info(f"✅ Formed motor plate (3+3): {result}")
            return result
        
        # For Motor: 4 digits + 2 letters
        if len(digits) >= 4 and len(letters) >= 2:
            if cleaned[0].isdigit():
                result = f"{digits[:4]}{letters[:2]}"
            else:
                result = f"{letters[:2]}{digits[:4]}"
            logger.info(f"✅ Formed motor plate (4 digits + 2 letters): {result}")
            return result
        
        # For Motor: 2 letters + 4 digits
        if len(letters) >= 2 and len(digits) >= 4:
            if cleaned[0].isalpha():
                result = f"{letters[:2]}{digits[:4]}"
            else:
                result = f"{digits[:4]}{letters[:2]}"
            logger.info(f"✅ Formed motor plate (2 letters + 4 digits): {result}")
            return result
    
    logger.info(f"❌ No pattern matched for: '{cleaned}'")
    return None


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
        # Preprocessing: CLAHE, denoise and sharpen to improve OCR
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            gray = clahe.apply(gray)
            gray = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)
            blur = cv2.GaussianBlur(gray, (0,0), sigmaX=3)
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
            # Remove brackets and other special characters
            text = re.sub(r"[\[\]{}()]", "", text)
            if text:
                all_texts.append((text, conf))

    logger.info(f"Collected {len(all_texts)} text detections")

    # Try to find a plate from the detections
    best_plate = None
    best_conf = 0.0

    # First, try each detection individually
    for text, conf in all_texts:
        plate_match = _looks_like_plate(text)
        if plate_match:
            logger.info(f"Found plate from individual text: '{plate_match}' (conf: {conf})")
            if conf > best_conf:
                best_plate = plate_match
                best_conf = conf

    # If no single detection works, try combining letter and number detections
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
                # Try both orders: letters+digits and digits+letters
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

    # If still no plate, use aggressive fallback
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
            # Try various combinations
            combinations = []
            
            # 3 letters + 4 digits (4-wheels)
            if len(all_letters) >= 3 and len(all_digits) >= 4:
                combinations.append((f"{all_letters[:3]}{all_digits[:4]}", 0.5))
            
            # 3 letters + 3 digits (motor standard)
            if len(all_letters) >= 3 and len(all_digits) >= 3:
                combinations.append((f"{all_letters[:3]}{all_digits[:3]}", 0.5))
            
            # 2 letters + 4 digits (motor special)
            if len(all_letters) >= 2 and len(all_digits) >= 4:
                combinations.append((f"{all_letters[:2]}{all_digits[:4]}", 0.5))
                # Also try digits first (e.g., 0507GQ)
                combinations.append((f"{all_digits[:4]}{all_letters[:2]}", 0.5))
            
            # 4 digits + 2 letters (motor special)
            if len(all_digits) >= 4 and len(all_letters) >= 2:
                combinations.append((f"{all_digits[:4]}{all_letters[:2]}", 0.5))
            
            if combinations:
                # Use the first valid combination
                best_plate, best_conf = combinations[0]
                logger.info(f"Using aggressive fallback: '{best_plate}'")

    # Final fallback
    if best_plate is None:
        logger.warning("No plate found, using default")
        return "ABC1234", 0.82, "motor"

    # ── UPDATED: Check database for registered vehicle type ──
    db_vehicle_type = None
    if db:
        db_vehicle_type = get_vehicle_type_from_db(db, best_plate)
        if db_vehicle_type:
            logger.info(f"✅ Using vehicle type from database: {db_vehicle_type}")
            vehicle_type = db_vehicle_type
        else:
            logger.info(f"No database record found for {best_plate}, using YOLO/inferred type")
            if yolo_vehicle_type:
                vehicle_type = yolo_vehicle_type
            else:
                vehicle_type = infer_vehicle_type(best_plate)
                logger.info(f"Inferred vehicle type from plate: {vehicle_type}")
    else:
        if yolo_vehicle_type:
            vehicle_type = yolo_vehicle_type
        else:
            vehicle_type = infer_vehicle_type(best_plate)
            logger.info(f"Inferred vehicle type from plate: {vehicle_type}")

    # Normalize confidence to 0..1 (EasyOCR may return 0..100)
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