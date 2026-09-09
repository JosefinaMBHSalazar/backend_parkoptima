from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import secrets
from datetime import datetime, timedelta
import os
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User, PasswordResetToken
import bcrypt

router = APIRouter(prefix="/auth", tags=["auth"])

# Email configuration - read from environment variables
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

class PasswordResetRequest(BaseModel):
    email: str

class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str

def send_reset_email(email: str, reset_link: str):
    """Send password reset email using SMTP"""
    try:
        # Check if email credentials are configured
        if not SMTP_USER or not SMTP_PASSWORD:
            print("⚠️ SMTP credentials not configured. Email not sent.")
            print(f"📧 Reset link (would have been sent): {reset_link}")
            return True  # Return True for demo purposes
        
        # Create message
        subject = "ParkOptima - Password Reset Request"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #1e2d6b; padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0;">Park<span style="color: #2ec4b6;">Optima</span></h1>
                <p style="color: rgba(255,255,255,0.7); margin: 5px 0 0;">Smart Parking. Smarter Entry.</p>
            </div>
            <div style="background-color: #ffffff; padding: 30px; border: 1px solid #e0e0e0; border-radius: 0 0 10px 10px;">
                <h2 style="color: #1e2d6b;">Password Reset Request</h2>
                <p style="color: #555; line-height: 1.6;">
                    We received a request to reset your password for your ParkOptima account.
                    Click the button below to create a new password:
                </p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_link}" 
                       style="background-color: #1e2d6b; color: white; padding: 12px 30px; 
                              text-decoration: none; border-radius: 6px; font-weight: bold;
                              display: inline-block;">
                        Reset Password
                    </a>
                </div>
                <p style="color: #555; line-height: 1.6; font-size: 14px;">
                    This link will expire in 1 hour. If you didn't request this, please ignore this email.
                </p>
                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
                <p style="color: #888; font-size: 12px; text-align: center; margin: 0;">
                    © 2026 ParkOptima · Smart Parking Management System
                </p>
            </div>
        </body>
        </html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = email

        # Attach HTML body
        msg.attach(MIMEText(body, "html"))

        # Send email
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        print(f"✅ Password reset email sent to {email}")
        return True
    except Exception as e:
        print(f"❌ Email sending error: {e}")
        return False

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
    success = send_reset_email(request.email, reset_link)
    
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
    if not SMTP_USER or not SMTP_PASSWORD:
        return {
            "success": False,
            "message": "SMTP credentials not configured",
            "smtp_configured": False
        }
    
    test_email = SMTP_USER
    reset_link = f"{FRONTEND_URL}/reset-password?token=test123"
    success = send_reset_email(test_email, reset_link)
    
    return {
        "success": success,
        "sent_to": test_email,
        "smtp_configured": True,
        "frontend_url": FRONTEND_URL
    }