import os
import json
import urllib.request
from threading import Thread
from email_validator import validate_email, EmailNotValidError

def send_async_email(app, msg_data):
    with app.app_context():
        _send_email_logic(msg_data)

def _send_email_logic(msg_data):
    api_key = os.environ.get("RESEND_API_KEY", "re_FGfBUhHy_9fwKsrz1wXr2Vu9LtTrrQMgE")
    
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    req = urllib.request.Request(url, data=json.dumps(msg_data).encode("utf-8"), headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = response.read()
            print(f"[EMAIL SUCCESS] Email sent to {msg_data['to']}", flush=True)
    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send email via Resend: {e}", flush=True)
        if hasattr(e, 'read'):
            print(f"[EMAIL ERROR DETAILS] {e.read().decode()}", flush=True)

def send_email(subject, recipient, body_html, app=None):
    # Resend requires you to use their onboarding email address if you don't have a verified domain
    sender = "onboarding@resend.dev"
    
    msg_data = {
        "from": f"MediScope <{sender}>",
        "to": [recipient],
        "subject": subject,
        "html": body_html
    }
    
    print(f"[EMAIL INITIATED] Queuing email to {recipient} asynchronously via Resend", flush=True)
    if app:
        Thread(target=send_async_email, args=(app, msg_data)).start()
    else:
        Thread(target=_send_email_logic, args=(msg_data,)).start()

def get_verification_email_body(name, verification_link):
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 12px;">
        <h2 style="color: #0ea5e9;">Welcome to MediScope!</h2>
        <p>Hi {name},</p>
        <p>Thank you for registering with MediScope. To activate your account and access your dashboard, please verify your email address by clicking the button below:</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{verification_link}" style="background-color: #0ea5e9; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; font-weight: bold;">Verify Email Address</a>
        </div>
        <p style="font-size: 14px; color: #64748b;">If you didn't create an account, you can safely ignore this email.</p>
        <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 20px 0;">
        <p style="font-size: 12px; color: #94a3b8;">&copy; 2026 MediScope AI Platform. All rights reserved.</p>
    </div>
    """

def get_reset_email_body(name, reset_link):
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 12px;">
        <h2 style="color: #0ea5e9;">Reset Your Password</h2>
        <p>Hi {name},</p>
        <p>We received a request to reset your MediScope password. Click the button below to set a new password. This link will expire in 30 minutes.</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{reset_link}" style="background-color: #0ea5e9; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; font-weight: bold;">Reset Password</a>
        </div>
        <p style="font-size: 14px; color: #64748b;">If you didn't request a password reset, please ignore this email or contact support if you have concerns.</p>
        <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 20px 0;">
        <p style="font-size: 12px; color: #94a3b8;">&copy; 2026 MediScope AI Platform. All rights reserved.</p>
    </div>
    """

def validate_email_globally(email):
    """
    Validates an email address globally by checking its syntax 
    and verifying if the domain has valid MX records.
    
    Returns: (is_valid: bool, error_message: str or None)
    """
    try:
        # Check syntax and deliverability (DNS/MX check)
        # check_deliverability=True performs the MX record lookup
        validation = validate_email(email, check_deliverability=True)
        
        # Get the normalized form of the email address
        normalized_email = validation.email
        return True, normalized_email
    except Exception as e:
        # The email is not valid (syntax or DNS)
        return False, str(e)

def get_otp_email_body(name, otp_code):
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 12px;">
        <h2 style="color: #0ea5e9;">Your Security Code</h2>
        <p>Hi {name},</p>
        <p>Your MediScope verification code is:</p>
        <div style="text-align: center; margin: 30px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 5px; color: #0f172a; background: #f1f5f9; padding: 10px 20px; border-radius: 8px;">{otp_code}</span>
        </div>
        <p style="font-size: 14px; color: #64748b;">This code will expire in 10 minutes. If you did not attempt to log in, please secure your account immediately.</p>
        <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 20px 0;">
        <p style="font-size: 12px; color: #94a3b8;">&copy; 2026 MediScope AI Platform. All rights reserved.</p>
    </div>
    """
