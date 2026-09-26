from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import secrets
from datetime import datetime, timedelta
import os
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User, PasswordResetToken
from ..email_service import send_password_reset_email
import bcrypt

router = APIRouter(prefix="/auth", tags=["auth"])

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password")
async def forgot_password(request: PasswordResetRequest, db: Session = Depends(get_db)):
    """Request password reset"""
    # Check if user exists
    user = db.query(User).filter(User.email == request.email).first()
    if not user:
        # For security, don't reveal if email exists or not
        return {"message": "If an account exists with this email, a reset link has been sent."}

    # Generate reset token
    token = secrets.token_urlsafe(32)
    expiry = datetime.utcnow() + timedelta(hours=1)

    # Store token in database
    reset_token = PasswordResetToken(
        email=request.email,
        token=token,
        expires_at=expiry,
        used=False
    )
    db.add(reset_token)
    db.commit()

    # Create reset link
    reset_link = f"{FRONTEND_URL}/reset-password?token={token}"

    # Send email
    success = send_password_reset_email(request.email, reset_link)

    if not success:
        print(f"⚠️ Failed to send reset email to {request.email}")

    return {"message": "If an account exists with this email, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(request: PasswordResetConfirm, db: Session = Depends(get_db)):
    """Reset password using token"""
    # Find valid token
    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == request.token,
        PasswordResetToken.used == False,
        PasswordResetToken.expires_at > datetime.utcnow()
    ).first()

    if not reset_token:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    # Update user password
    user = db.query(User).filter(User.email == reset_token.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Hash new password
    password_hash = bcrypt.hashpw(
        request.new_password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    user.password_hash = password_hash

    # Mark token as used
    reset_token.used = True
    db.commit()

    return {"message": "Password reset successful"}


@router.get("/test-email")
async def test_email():
    """Test endpoint to verify email configuration"""
    # SMTP config now lives in email_service; this endpoint just tries a send.
    # If SMTP isn't configured, send_password_reset_email returns False
    # (and email_service prints a warning).
    from ..email_service import SMTP_USER

    if not SMTP_USER:
        return {
            "success": False,
            "message": "SMTP credentials not configured",
            "smtp_configured": False
        }

    test_email = SMTP_USER
    reset_link = f"{FRONTEND_URL}/reset-password?token=test123"
    success = send_password_reset_email(test_email, reset_link)

    return {
        "success": success,
        "sent_to": test_email,
        "smtp_configured": True,
        "frontend_url": FRONTEND_URL
    }