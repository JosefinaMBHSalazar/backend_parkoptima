from typing import Dict, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from ..models import PaymentTransaction, VehicleAccount, User, WalletBalance


def _normalize_vehicle_type(vehicle_type: str) -> str:
    if not vehicle_type:
        return "Motor"
    vt = vehicle_type.lower()
    if "motor" in vt or ("4wheel" not in vt and "four" not in vt):
        if "motor" in vt or vt in ("motor", "m"):
            return "Motor"
    if "4wheel" in vt or "four" in vt or vt == "4 wheels" or vt == "4wheels":
        return "4 Wheels"
    return "Motor"


def get_or_create_wallet_balance(db: Session, plate_number: str) -> WalletBalance:
    """Get or create a wallet balance entry for a plate number."""
    plate = plate_number.strip().upper()
    wallet = db.query(WalletBalance).filter(WalletBalance.plate_number == plate).first()
    
    if wallet is None:
        # First, check if the user exists in the users table
        user = db.query(User).filter(User.plate_number == plate).first()
        
        # If user doesn't exist, create a minimal user entry first
        if user is None:
            # Check if there's a vehicle account
            account = db.query(VehicleAccount).filter(VehicleAccount.plate_number == plate).first()
            
            if account is not None:
                # Create user from vehicle account
                user = User(
                    plate_number=plate,
                    full_name=account.owner_name or "Unknown",
                    vehicle_type=account.vehicle_type or "Motor",
                    brand=account.brand or "",
                    contact=account.contact or "",
                    status="active"
                )
            else:
                # Create a minimal user entry for this plate
                user = User(
                    plate_number=plate,
                    full_name="Unknown Owner",
                    vehicle_type="Motor",
                    brand="",
                    contact="",
                    status="active"
                )
            
            db.add(user)
            db.flush()  # Flush to get the user ID without committing
        
        wallet = WalletBalance(plate_number=plate, balance=0.0)
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
    
    return wallet


def get_wallet_balance(db: Session, plate_number: str) -> Dict[str, object]:
    """Return the wallet balance and vehicle metadata for a plate number."""
    plate = plate_number.strip().upper()
    
    wallet = get_or_create_wallet_balance(db, plate)
    
    user = db.query(User).filter(User.plate_number == plate).first()
    
    if user is not None:
        return {
            "plateNumber": plate,
            "balance": float(wallet.balance or 0.0),
            "ownerName": user.full_name,
            "vehicleType": _normalize_vehicle_type(user.vehicle_type),
            "brand": user.brand,
            "contact": user.contact,
        }
    
    account = db.query(VehicleAccount).filter(VehicleAccount.plate_number == plate).first()
    if account is not None:
        return {
            "plateNumber": account.plate_number,
            "balance": float(wallet.balance or 0.0),
            "ownerName": account.owner_name,
            "vehicleType": _normalize_vehicle_type(account.vehicle_type),
            "brand": account.brand,
            "contact": account.contact,
        }
    
    raise ValueError("No account found for plate number")


def top_up_wallet(db: Session, plate_number: str, amount: float) -> Dict[str, object]:
    """Atomically add credits to a vehicle wallet and record the transaction."""
    if amount <= 0:
        raise ValueError("Top-up amount must be greater than zero")

    plate = plate_number.strip().upper()
    
    wallet = get_or_create_wallet_balance(db, plate)
    
    wallet.balance = float(wallet.balance or 0.0) + amount
    wallet.updated_at = datetime.now()
    db.add(wallet)
    db.commit()
    db.refresh(wallet)

    # Fix: session_id should be None for top-ups (not 0)
    transaction = PaymentTransaction(session_id=None, amount=amount, method="wallet_topup")
    db.add(transaction)
    db.commit()

    return {"plateNumber": plate, "balance": float(wallet.balance)}


def deduct_wallet(db: Session, plate_number: str, amount: float,
                  session_id: int = 0, method: str = "wallet") -> Dict[str, object]:
    """Atomically deduct a parking fee from a vehicle wallet in one transaction."""
    if amount <= 0:
        raise ValueError("Deduction amount must be greater than zero")

    plate = plate_number.strip().upper()
    
    wallet = get_or_create_wallet_balance(db, plate)
    
    current = float(wallet.balance or 0.0)
    if current < amount:
        raise ValueError(f"Insufficient wallet balance. Current: ₱{current:.2f}, Required: ₱{amount:.2f}")

    wallet.balance = current - amount
    wallet.updated_at = datetime.now()
    db.add(wallet)
    db.commit()
    db.refresh(wallet)

    # Fix: use None if session_id is 0 or None
    transaction = PaymentTransaction(session_id=session_id if session_id > 0 else None, amount=amount, method=method)
    db.add(transaction)
    db.commit()

    return {"plateNumber": plate, "balance": float(wallet.balance)}


def get_wallet_balance_by_plate(db: Session, plate_number: str) -> Optional[float]:
    """Get just the balance amount for a plate number."""
    plate = plate_number.strip().upper()
    wallet = db.query(WalletBalance).filter(WalletBalance.plate_number == plate).first()
    
    if wallet is None:
        return 0.0
    
    return float(wallet.balance or 0.0)