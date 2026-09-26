import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")


def _send(to_email: str, subject: str, html_body: str) -> bool:
    """Send an HTML email. Returns True on success, False otherwise.

    Never raises — callers can log a warning and continue.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"⚠️ SMTP not configured. Would send to {to_email}: {subject}")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        print(f"✅ Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        print(f"❌ Email send failed to {to_email}: {e}")
        return False


def send_password_reset_email(email: str, reset_link: str) -> bool:
    """Existing password-reset email — copied from routes/password_reset.py."""
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
    return _send(email, "ParkOptima - Password Reset Request", body)


def send_otp_email(email: str, code: str) -> bool:
    """Send the first-login verification code."""
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background-color: #1e2d6b; padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
            <h1 style="color: white; margin: 0;">Park<span style="color: #2ec4b6;">Optima</span></h1>
            <p style="color: rgba(255,255,255,0.7); margin: 5px 0 0;">Smart Parking. Smarter Entry.</p>
        </div>
        <div style="background-color: #ffffff; padding: 30px; border: 1px solid #e0e0e0; border-radius: 0 0 10px 10px;">
            <h2 style="color: #1e2d6b;">Verify Your Account</h2>
            <p style="color: #555; line-height: 1.6;">
                Welcome to ParkOptima! Enter this code to finish setting up your account:
            </p>
            <div style="text-align: center; margin: 30px 0;">
                <span style="font-family: 'Courier New', monospace; font-size: 36px;
                             font-weight: bold; color: #1e2d6b; letter-spacing: 8px;
                             background: #F5F7FB; padding: 16px 28px; border-radius: 10px;
                             display: inline-block;">
                    {code}
                </span>
            </div>
            <p style="color: #555; line-height: 1.6; font-size: 14px;">
                This code expires in 10 minutes. If you didn't create a ParkOptima account, please ignore this email.
            </p>
            <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
            <p style="color: #888; font-size: 12px; text-align: center; margin: 0;">
                © 2026 ParkOptima · Smart Parking Management System
            </p>
        </div>
    </body>
    </html>
    """
    return _send(email, "ParkOptima - Verify Your Account", body)