from flask import Flask, request, jsonify, send_from_directory, send_file, redirect, session, render_template, abort, flash, url_for
from datetime import datetime, timedelta, timezone
from flask_cors import CORS
import joblib
import pandas as pd
import os
import io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from itsdangerous import URLSafeTimedSerializer
from utils.email_utils import send_email, get_verification_email_body, get_reset_email_body, validate_email_globally, get_otp_email_body
from werkzeug.security import generate_password_hash
from utils.security import encrypt_data, decrypt_data
import random
from database.db import (
    register_doctor,
    register_patient,
    save_patient_record,
    get_patients_with_latest_record,
    get_patient_history,
    get_patient_record,
    get_patient_by_id,
    get_doctor_by_id,
    login_user,
    delete_patient,
    delete_doctor,
    verify_email_in_db,
    set_user_reset_token,
    get_user_by_reset_token,
    update_user_password,
    log_audit_action,
    get_patients_with_latest_record_audited,
    get_all_doctors
)

import re
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
socketio = SocketIO(app, cors_allowed_origins="*")
CORS(app, supports_credentials=True)

# File Upload configuration
if os.environ.get("VERCEL"):
    UPLOAD_FOLDER = '/tmp/uploads/medical_reports'
else:
    UPLOAD_FOLDER = 'uploads/medical_reports'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Token Serializer
ts = URLSafeTimedSerializer(app.secret_key)

def is_valid_email(email):
    """Basic regex to check email format."""
    return re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email) is not None

# ==============================
# LOAD ML MODEL
# ==============================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(BASE_DIR, "models", "disease_predictor.pkl")
scaler_path = os.path.join(BASE_DIR, "models", "scaler.pkl")

model = joblib.load(model_path)
scaler = joblib.load(scaler_path)

# ==============================
# FRONTEND ROUTES
# ==============================

@app.route("/")
def home():
    return send_from_directory("frontend", "index.html")


@app.route("/login", methods=["GET"])
def login_page():
    return send_from_directory("frontend", "login.html")


@app.route("/patient-dashboard")
def patient_dashboard():
    if "user_id" not in session or session.get("role") != "patient":
        return redirect("/login?role=patient")
    return send_from_directory("frontend", "patient_dashboard.html")


@app.route("/doctor-dashboard")
def doctor_dashboard():
    if "user_id" not in session or session.get("role") != "doctor":
        return redirect("/login?role=doctor")
    return send_from_directory("frontend", "doctor_dashboard.html")


@app.route("/patient-register", methods=["GET"])
def patient_register_page():
    return send_from_directory("frontend", "patient_register.html")


@app.route("/doctor-register", methods=["GET"])
def doctor_register_page():
    return send_from_directory("frontend", "doctor_register.html")


@app.route("/forgot-password", methods=["GET"])
def forgot_password_page():
    return send_from_directory("frontend", "forgot_password.html")


@app.route("/reset-password", methods=["GET"])
def reset_password_page():
    return send_from_directory("frontend", "reset_password.html")


# ==============================
# REGISTER DOCTOR
# ==============================

@app.route("/doctor-register", methods=["POST"])
def doctor_register_api():

    data = request.json
    email = data.get("email", "").strip()

    is_valid, validation_result = validate_email_globally(email)
    if not is_valid:
        return jsonify({"success": False, "message": f"Email validation failed: {validation_result}"}), 400
    
    # Use the normalized email
    email = validation_result

    try:
        # Generate verification token
        token = ts.dumps(data["email"], salt="email-confirm")
        
        result = register_doctor(
            data["name"],
            data["age"],
            data["specialization"],
            data["email"],
            data["password"],
            license_number=data.get("license_number"),
            verification_token=token
        )

        if isinstance(result, dict) and result.get("error"):
            return jsonify({"success": False, "message": result["error"]}), 400

        # Send verification email
        verification_url = url_for("verify_email", token=token, role="doctor", _external=True)
        email_body = get_verification_email_body(data["name"], verification_url)
        send_email("Verify your MediScope Account", data["email"], email_body, app)

        return jsonify({"success": True, "message": "Doctor registered! Please check your email to verify your account."})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400


# ==============================
# REGISTER PATIENT
# ==============================


@app.route("/patient-register", methods=["POST"])
def register_patient_api():
    # Detect if request is JSON or Multipart
    if request.is_json:
        data = request.json
        medical_report = None
    else:
        data = request.form
        medical_report = request.files.get("medical_report")

    email = data.get("email", "").strip()

    is_valid, validation_result = validate_email_globally(email)
    if not is_valid:
        return jsonify({"success": False, "message": f"Email validation failed: {validation_result}"}), 400
        
    # Use the normalized email
    email = validation_result

    name = data.get("name")
    age = data.get("age")
    gender = data.get("gender")
    password = data.get("password")
    family_history = data.get("family_history")
    medications = data.get("medications")

    try:
        # Handle file upload if present
        report_path = None
        if medical_report and medical_report.filename != "" and allowed_file(medical_report.filename):
            from werkzeug.utils import secure_filename
            import uuid
            
            filename = secure_filename(medical_report.filename)
            # Add unique prefix to avoid collisions
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            medical_report.save(save_path)
            report_path = os.path.join('medical_reports', unique_filename)

        # Generate verification token
        token = ts.dumps(email, salt="email-confirm")

        result = register_patient(
            name,
            age,
            gender,
            email,
            password,
            family_history,
            medications,
            verification_token=token,
            medical_report_path=report_path
        )

        # Send verification email
        verification_url = url_for("verify_email", token=token, role="patient", _external=True)
        email_body = get_verification_email_body(name, verification_url)
        send_email("Verify your MediScope Account", email, email_body, app)

        return jsonify({
            "success": True,
            "message": "Patient registered! Please check your email to verify your account.",
            "patient_id": result
        })

    except Exception as e:
        print(f"Registration Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 400


# ==============================
# LOGIN
# ==============================

@app.route("/login", methods=["POST"])
def login():

    data = request.json

    email = data.get("email")
    password = data.get("password")
    role = data.get("role")

    result = login_user(email, password, role)

    if "error" in result:
        if result["error"] == "VERIFICATION_REQUIRED":
            return jsonify({"success": False, "message": "Email not verified. Please check your inbox for the verification link."}), 403
        if result["error"] == "EMAIL_NOT_FOUND":
            return jsonify({"success": False, "message": "This email address is not registered. Please create an account."}), 404
        return jsonify({"success": False, "message": "Incorrect email or password. Please try again."}), 401

    # Check if 2FA is enabled for this user
    user_data = get_doctor_by_id(result["user_id"]) if role == "doctor" else get_patient_by_id(result["user_id"])
    
    if user_data and user_data.get("two_factor_enabled") == 1:
        # Generate 6-digit OTP
        otp = str(random.randint(100000, 999999))
        session["pending_user_id"] = result["user_id"]
        session["pending_role"] = role
        session["otp_code"] = otp
        session["otp_expiry"] = (datetime.utcnow() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        
        # Send OTP Email
        email_body = get_otp_email_body(user_data["name"], otp)
        send_email("Your MediScope Security Code", email, email_body, app)
        
        return jsonify({
            "success": True,
            "requires_2fa": True,
            "message": "Two-factor authentication required. Please check your email for the code."
        })

    session["user_id"] = result.get("user_id")
    session["role"] = role

    log_audit_action(session["user_id"], session["role"], "LOGIN_SUCCESS", details=f"User logged in as {role}")

    redirect_url = "/doctor-dashboard" if role == "doctor" else "/patient-dashboard"

    return jsonify({
        "success": True,
        "message": "Login successful",
        "redirect": redirect_url,
    })

@app.route("/verify-otp", methods=["POST"])
def verify_otp():
    data = request.json
    otp_input = data.get("otp", "").strip()
    
    if "pending_user_id" not in session or "otp_code" not in session:
        return jsonify({"success": False, "message": "Session expired. Please log in again."}), 401
    
    # Check expiry
    expiry_str = session.get("otp_expiry")
    if expiry_str:
        expiry = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
        if datetime.utcnow() > expiry:
            return jsonify({"success": False, "message": "OTP has expired. Please log in again."}), 401
            
    if otp_input == session["otp_code"]:
        session["user_id"] = session.pop("pending_user_id")
        session["role"] = session.pop("pending_role")
        session.pop("otp_code")
        session.pop("otp_expiry")
        
        log_audit_action(session["user_id"], session["role"], "LOGIN_SUCCESS_2FA", details="User verified with 2FA")
        
        redirect_url = "/doctor-dashboard" if session["role"] == "doctor" else "/patient-dashboard"
        return jsonify({
            "success": True, 
            "message": "Verification successful", 
            "redirect": redirect_url
        })
    else:
        return jsonify({"success": False, "message": "Invalid security code. Please try again."}), 401

@app.route("/toggle-2fa", methods=["POST"])
def toggle_2fa():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
        
    data = request.json
    enabled = 1 if data.get("enabled", False) else 0
    
    from database.db import engine, doctors, patients, text
    table = doctors if session["role"] == "doctor" else patients
    
    with engine.connect() as conn:
        conn.execute(
            table.update().where(table.c.id == session["user_id"]).values(two_factor_enabled=enabled)
        )
        conn.commit()
    
    log_audit_action(session["user_id"], session["role"], "TOGGLE_2FA", details=f"2FA set to {'enabled' if enabled else 'disabled'}")
    return jsonify({"success": True, "message": f"2FA {'enabled' if enabled else 'disabled'} successfully"})


@app.route("/logout", methods=["GET", "POST"])
def logout():
    # Capture role before clearing session so we can route back correctly.
    role = session.get("role")
    session.clear()

    redirect_target = "/login"
    if role in ("doctor", "patient"):
        redirect_target = f"/login?role={role}"

    if request.method == "GET":
        flash("You have been logged out successfully.", "success")
        return redirect(redirect_target)

    return jsonify({"success": True, "message": "Logged out", "redirect": redirect_target})


# ==============================
# EMAIL VERIFICATION ENDPOINT
# ==============================

@app.route("/verify-email")
def verify_email():
    token = request.args.get("token")
    role = request.args.get("role")
    
    if not token or not role:
        return redirect(url_for("login_page", status="error", message="Invalid verification link."))
        
    try:
        # Check if token is valid and not expired (e.g., 24 hours)
        email = ts.loads(token, salt="email-confirm", max_age=86400)
    except Exception:
        return redirect(url_for("login_page", status="error", message="The verification link is invalid or has expired."))
        
    success = verify_email_in_db(token, role)
    
    if success:
        return redirect(url_for("login_page", status="success", message="Email verified successfully! You can now log in."))
    else:
        return redirect(url_for("login_page", status="error", message="Verification failed. Token may be invalid or already used."))


# ==============================
# FORGOT PASSWORD ENDPOINTS
# ==============================

@app.route("/forgot-password", methods=["POST"])
def forgot_password_api():
    data = request.json
    email = data.get("email")
    role = data.get("role")
    
    if not email or not role:
        return jsonify({"success": False, "message": "Email and role are required."}), 400
        
    # Generate reset token (expires in 30 minutes)
    token = ts.dumps(email, salt="password-reset")
    expiry = (datetime.utcnow() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    
    success = set_user_reset_token(email, role, token, expiry)
    
    if success:
        reset_url = url_for("reset_password_page", token=token, role=role, _external=True)
        # We need the user's name for the email. For simplicity, we just use a generic 'User' 
        # or fetch it if needed. Let's just use 'User' or the email prefix.
        name = email.split('@')[0]
        email_body = get_reset_email_body(name, reset_url)
        send_email("Reset Your MediScope Password", email, email_body, app)
        return jsonify({"success": True, "message": "A password reset link has been sent to your email."})
    else:
        return jsonify({"success": False, "message": "This email address is not registered in our system."}), 404


@app.route("/reset-password", methods=["POST"])
def reset_password_api():
    data = request.json
    token = data.get("token")
    role = data.get("role")
    new_password = data.get("password")
    
    if not token or not role or not new_password:
        return jsonify({"success": False, "message": "Invalid request."}), 400
        
    try:
        # Validate token and expiry (30 mins)
        email = ts.loads(token, salt="password-reset", max_age=1800)
    except Exception:
        return jsonify({"success": False, "message": "The reset link is invalid or has expired."}), 400
        
    # Check if token matches the one in DB
    user = get_user_by_reset_token(token, role)
    if not user:
        return jsonify({"success": False, "message": "Invalid or already used token."}), 400
        
    # Update password
    new_password_hash = generate_password_hash(new_password)
    update_user_password(user.id, role, new_password_hash)
    
    return jsonify({"success": True, "message": "Password updated successfully! You can now log in."})


# ==============================
# DELETE PATIENT
# ==============================

@app.route("/patient/<int:patient_id>", methods=["DELETE"])
def delete_patient_route(patient_id):
    """Delete a patient and all their medical records (cascade delete).
    
    Used when:
    - Patient is deceased
    - Patient requests account deletion
    """
    
    try:
        result = delete_patient(patient_id)
        
        if result.get("success"):
            return jsonify({
                "success": True,
                "message": result.get("message")
            }), 200
        else:
            return jsonify({
                "success": False,
                "error": result.get("error")
            }), 400
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==============================
# DELETE DOCTOR
# ==============================

@app.route("/doctor/<int:doctor_id>", methods=["DELETE"])
def delete_doctor_route(doctor_id):
    """Delete a doctor profile.
    
    Used when:
    - Doctor leaves the hospital/clinic
    - Doctor exits their position
    - Doctor account removal
    """
    
    try:
        result = delete_doctor(doctor_id)
        
        if result.get("success"):
            return jsonify({
                "success": True,
                "message": result.get("message")
            }), 200
        else:
            return jsonify({
                "success": False,
                "error": result.get("error")
            }), 400
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==============================
# ML PREDICTION API
# ==============================

@app.route("/predict", methods=["POST"])
def predict():
    data = request.json or {}

    # ---------- Input validation ----------
    required_fields = [
        "bp_systolic",
        "bp_diastolic",
        "heart_rate",
        "respiratory_rate",
        "temperature",
        "oxygen_saturation",
        "med_adherence",
        "symptom_severity",
    ]

    missing = [f for f in required_fields if f not in data or data.get(f) in [None, ""]]
    if missing:
        return jsonify({"success": False, "error": f"Missing or empty fields: {', '.join(missing)}"}), 400

    # Convert / normalize inputs
    try:
        bp_systolic = float(data["bp_systolic"])
        bp_diastolic = float(data["bp_diastolic"])
        heart_rate = float(data["heart_rate"])
        respiratory_rate = float(data["respiratory_rate"])
        temperature = float(data["temperature"])
        oxygen_saturation = float(data["oxygen_saturation"])
    except Exception:
        return jsonify({"success": False, "error": "Vital sign values must be numeric."}), 400

    def map_med_adherence(val):
        if isinstance(val, (int, float)):
            if 0 <= val <= 3:
                return int(val)
        if isinstance(val, str):
            normalized = val.strip().lower()
            if normalized == "excellent":
                return 3
            if normalized == "good":
                return 2
            if normalized == "fair":
                return 1
            if normalized == "poor":
                return 0
        raise ValueError("Invalid med_adherence value")

    def map_symptom_severity(val):
        if isinstance(val, (int, float)):
            if 0 <= val <= 3:
                return int(val)
        if isinstance(val, str):
            normalized = val.strip().lower()
            if normalized == "none":
                return 0
            if normalized == "mild":
                return 1
            if normalized == "moderate":
                return 2
            if normalized == "severe":
                return 3
        raise ValueError("Invalid symptom_severity value")

    try:
        med_adherence = map_med_adherence(data["med_adherence"])
        symptom_severity = map_symptom_severity(data["symptom_severity"])
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    # ---------- Data preprocessing ----------
    # Ensure feature ordering matches training pipeline
    feature_names = [
        "bp_systolic",
        "bp_diastolic",
        "heart_rate",
        "respiratory_rate",
        "temperature",
        "oxygen_saturation",
        "med_adherence",
        "symptom_severity",
    ]

    df_input = pd.DataFrame([{  # keep column names for scaler
        "bp_systolic": bp_systolic,
        "bp_diastolic": bp_diastolic,
        "heart_rate": heart_rate,
        "respiratory_rate": respiratory_rate,
        "temperature": temperature,
        "oxygen_saturation": oxygen_saturation,
        "med_adherence": med_adherence,
        "symptom_severity": symptom_severity,
    }])

    try:
        X_scaled = scaler.transform(df_input[feature_names])
    except Exception as e:
        return jsonify({"success": False, "error": f"Error during input scaling: {e}"}), 400

    # ---------- ML prediction ----------
    ml_prediction = int(model.predict(X_scaled)[0])
    confidence = float(model.predict_proba(X_scaled).max()) * 100

    # ---------- NEWS2 calculation ----------
    def compute_news2_score(rr, spo2, temp, sbp, hr):
        score = 0
        # Respiratory rate
        if rr <= 8:
            score += 3
        elif rr <= 11:
            score += 1
        elif rr <= 20:
            score += 0
        elif rr <= 24:
            score += 2
        else:
            score += 3

        # Oxygen saturation
        if spo2 <= 91:
            score += 3
        elif spo2 <= 93:
            score += 2
        elif spo2 <= 95:
            score += 1
        else:
            score += 0

        # Temperature
        if temp <= 35.0:
            score += 3
        elif temp <= 36.0:
            score += 1
        elif temp <= 38.0:
            score += 0
        elif temp <= 39.0:
            score += 1
        else:
            score += 2

        # Systolic blood pressure
        if sbp <= 90:
            score += 3
        elif sbp <= 100:
            score += 2
        elif sbp <= 110:
            score += 1
        elif sbp <= 219:
            score += 0
        else:
            score += 3

        # Heart rate
        if hr <= 40:
            score += 3
        elif hr <= 50:
            score += 1
        elif hr <= 90:
            score += 0
        elif hr <= 110:
            score += 1
        elif hr <= 130:
            score += 2
        else:
            score += 3

        return score

    news2_score = compute_news2_score(respiratory_rate, oxygen_saturation, temperature, bp_systolic, heart_rate)
    
    # Identify patient for history-based insights
    patient_id = session.get("user_id")

    # ---------- Trend Analysis (Phase 2) ----------
    trends = {}
    if patient_id:
        prev_history = get_patient_history(patient_id, limit=1)
        if prev_history:
            prev = prev_history[0]
            def calc_trend(curr, old, key):
                if old and old != 0:
                    change = ((curr - old) / old) * 100
                    return f"{'+' if change > 0 else ''}{round(change, 1)}%"
                return "Stable"

            trends = {
                "bp_systolic": calc_trend(bp_systolic, prev.get("bp_systolic"), "bp_systolic"),
                "heart_rate": calc_trend(heart_rate, prev.get("heart_rate"), "heart_rate"),
                "oxygen_saturation": calc_trend(oxygen_saturation, prev.get("oxygen_saturation"), "oxygen_saturation")
            }

    # ---------- Combine results (Safety First & History Logic) ----------
    
    # Fetch patient's registered history for smart escalation
    patient = None
    if patient_id:
        patient = get_patient_by_id(patient_id)
    
    history_text = (patient.get("family_history") or "none").lower() if patient else "none"
    meds_text = (patient.get("medications") or "none").lower() if patient else "none"

    # Base risk determination
    if news2_score >= 7:
        final_risk = "High"
        ml_prediction = 1 # Force ML prediction to 1 for clinical emergencies
    elif ml_prediction == 1 and (confidence >= 75 or news2_score >= 5):
        final_risk = "High"
    elif ml_prediction == 1 or news2_score >= 5:
        final_risk = "Medium"
    else:
        final_risk = "Low"

    # Smart Risk Escalation based on History
    # Example: If patient has Hypertension and current Systolic BP is high (>140)
    if "hypertension" in history_text and bp_systolic > 140:
        if final_risk == "Low": final_risk = "Medium"
        elif final_risk == "Medium": final_risk = "High"
        print(f"[SMART RISK] Escalated due to Hypertension history and BP: {bp_systolic}")

    # Example: If patient has Asthma or COPD and breathing rate is high (>20)
    if ("asthma" in history_text or "copd" in history_text) and respiratory_rate > 20:
        if final_risk == "Low": final_risk = "Medium"
        elif final_risk == "Medium": final_risk = "High"
        print(f"[SMART RISK] Escalated due to Respiratory history and RR: {respiratory_rate}")
    
    # Example: Heart Rate risk with Heart Medication history
    if "heart_meds" in meds_text and (heart_rate > 100 or heart_rate < 50):
        if final_risk == "Low": final_risk = "Medium"
        elif final_risk == "Medium": final_risk = "High"
        print(f"[SMART RISK] Escalated due to Heart Meds history and HR: {heart_rate}")

    # Logging
    print("[PREDICT] input=", {
        "bp_systolic": bp_systolic,
        "bp_diastolic": bp_diastolic,
        "heart_rate": heart_rate,
        "respiratory_rate": respiratory_rate,
        "temperature": temperature,
        "oxygen_saturation": oxygen_saturation,
        "med_adherence": med_adherence,
        "symptom_severity": symptom_severity,
    })
    print("[PREDICT] ml_prediction=", ml_prediction, "confidence=", confidence)
    print("[PREDICT] news2_score=", news2_score, "final_risk=", final_risk)

    # ---------- Explainability Logic (Phase 2) ----------
    def get_top_factors(bp_s, bp_d, hr, rr, temp, spo2, med, symp, importances):
        # Normal ranges (Simplified clinical defaults)
        normals = {
            "bp_systolic": 120,
            "bp_diastolic": 80,
            "heart_rate": 75,
            "respiratory_rate": 16,
            "temperature": 37.0,
            "oxygen_saturation": 98,
            "med_adherence": 3,
            "symptom_severity": 0
        }
        
        contributions = []
        feature_list = [
            ("Blood Pressure (Systolic)", bp_s, "bp_systolic", importances[0]),
            ("Blood Pressure (Diastolic)", bp_d, "bp_diastolic", importances[1]),
            ("Heart Rate", hr, "heart_rate", importances[2]),
            ("Respiratory Rate", rr, "respiratory_rate", importances[3]),
            ("Body Temperature", temp, "temperature", importances[4]),
            ("Oxygen Saturation", spo2, "oxygen_saturation", importances[5]),
            ("Medication Adherence", med, "med_adherence", importances[6]),
            ("Symptom Severity", symp, "symptom_severity", importances[7])
        ]
        
        for name, val, key, imp in feature_list:
            # Difference from normal, weighted by model importance
            diff = abs(val - normals[key])
            # Special logic for SpO2 (lower is worse)
            if key == "oxygen_saturation" and val < 98:
                diff = (98 - val) * 2 # Double weight for low oxygen
            
            # Simple contribution score
            score = diff * imp
            contributions.append({"name": name, "score": score, "value": val})
            
        # Sort by contribution score
        contributions.sort(key=lambda x: x["score"], reverse=True)
        return contributions[:3]

    top_factors = []
    if hasattr(model, 'feature_importances_'):
        top_factors = get_top_factors(
            bp_systolic, bp_diastolic, heart_rate, respiratory_rate, 
            temperature, oxygen_saturation, med_adherence, symptom_severity,
            model.feature_importances_
        )

    if patient_id:
        log_audit_action(patient_id, session.get("role", "patient"), "VITALS_ASSESSMENT", details=f"Risk: {final_risk}, NEWS2: {news2_score}")
        
        # Real-time and Email Alerts for High Risk (Phase 3)
        if final_risk == "High":
            # Emit socket alert
            socketio.emit("critical_alert", {
                "patient_id": patient_id,
                "patient_name": patient["name"] if patient else "Unknown",
                "risk": "High",
                "news2": news2_score
            }, namespace="/")
            
            # Send Emergency Broadcast to Patient + ALL Doctors
            if patient:
                emergency_body = f"""
                <div style="font-family: Arial, sans-serif; border: 2px solid #ef4444; border-radius: 12px; padding: 20px; max-width:600px;">
                    <h2 style="color: #ef4444;">🚨 EMERGENCY ALERT: Critical Patient Assessment</h2>
                    <table style="width:100%; border-collapse:collapse; margin-top:12px;">
                        <tr><td style="padding:6px 12px; font-weight:bold;">Patient</td><td style="padding:6px 12px;">{patient['name']} (ID: {patient_id})</td></tr>
                        <tr style="background:#fef2f2;"><td style="padding:6px 12px; font-weight:bold;">Risk Status</td><td style="padding:6px 12px; color:#dc2626; font-weight:bold;">CRITICAL — Immediate Review Required</td></tr>
                        <tr><td style="padding:6px 12px; font-weight:bold;">NEWS2 Score</td><td style="padding:6px 12px;">{news2_score}</td></tr>
                        <tr style="background:#fef2f2;"><td style="padding:6px 12px; font-weight:bold;">Assessment Time</td><td style="padding:6px 12px;">{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</td></tr>
                    </table>
                    <p style="margin-top:16px; font-size:13px; color:#64748b;">This is an automated alert from MediScope AI. Please take immediate clinical action.</p>
                </div>
                """

                # 1. Notify the patient
                send_email(f"🚨 EMERGENCY: Your Health Assessment is Critical", patient["email"], emergency_body, app)

                # 2. Broadcast to ALL verified doctors
                all_doctors = get_all_doctors()
                for doc in all_doctors:
                    doctor_body = f"""
                    <div style="font-family: Arial, sans-serif; border: 2px solid #ef4444; border-radius: 12px; padding: 20px; max-width:600px;">
                        <h2 style="color: #ef4444;">🚨 EMERGENCY ALERT — Clinical Action Required</h2>
                        <p>Dear Dr. {doc['name']},</p>
                        <p>Your immediate attention is required for the following patient:</p>
                        <table style="width:100%; border-collapse:collapse; margin-top:12px;">
                            <tr><td style="padding:6px 12px; font-weight:bold;">Patient</td><td style="padding:6px 12px;">{patient['name']} (ID: {patient_id})</td></tr>
                            <tr style="background:#fef2f2;"><td style="padding:6px 12px; font-weight:bold;">Risk Status</td><td style="padding:6px 12px; color:#dc2626; font-weight:bold;">CRITICAL</td></tr>
                            <tr><td style="padding:6px 12px; font-weight:bold;">NEWS2 Score</td><td style="padding:6px 12px;">{news2_score}</td></tr>
                            <tr style="background:#fef2f2;"><td style="padding:6px 12px; font-weight:bold;">Time</td><td style="padding:6px 12px;">{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</td></tr>
                        </table>
                        <p style="margin-top:16px; font-size:13px; color:#64748b;">Please log in to the MediScope dashboard to review the full assessment report.</p>
                    </div>
                    """
                    send_email(f"🚨 EMERGENCY: Patient {patient['name']} is CRITICAL", doc["email"], doctor_body, app)

    if patient_id and session.get("role") == "patient":
        try:
            save_patient_record(
                patient_id=patient_id,
                bp_systolic=bp_systolic,
                bp_diastolic=bp_diastolic,
                heart_rate=heart_rate,
                respiratory_rate=respiratory_rate,
                temperature=temperature,
                oxygen_saturation=oxygen_saturation,
                med_adherence=med_adherence,
                symptom_severity=symptom_severity,
                prediction=ml_prediction,
                confidence=confidence,
                news2_score=news2_score,
                risk_level=final_risk,
                recommended_doctor="Cardiologist" if final_risk == "High" else "General Physician",
            )
        except Exception:
            pass

    recommended_doctor = "Emergency Specialist / Cardiologist" if final_risk == "High" else "General Physician"
    recommendations = (
        "PRIORITIZED ATTENTION REQUIRED: Please seek immediate medical attention or visit the emergency department." if final_risk == "High"
        else "Monitor your symptoms closely and follow your treatment plan. Schedule a consultation if symptoms persist."
    )

    return jsonify({
        "success": True,
        "ml_prediction": ml_prediction,
        "news2_score": news2_score,
        "final_risk": final_risk,
        "confidence": confidence,
        "recommended_doctor": recommended_doctor,
        "recommendations": recommendations,
        "top_factors": top_factors,
        "trends": trends
    })


@app.route("/patients", methods=["GET"])
def patients():
    if "user_id" not in session or session.get("role") != "doctor":
        return jsonify({"error": "Unauthorized"}), 401

    patients_data = get_patients_with_latest_record_audited(session["user_id"], session["role"])
    return jsonify({"patients": patients_data})


@app.route("/patient-history/<int:patient_id>", methods=["GET"])
def patient_history_by_id(patient_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    if session.get("role") == "patient" and session.get("user_id") != patient_id:
        return jsonify({"error": "Forbidden"}), 403

    history = get_patient_history(patient_id, limit=50)
    log_audit_action(session["user_id"], session["role"], "VIEW_PATIENT_HISTORY", target_id=patient_id)
    return jsonify({"history": history})


@app.route("/patient-history", methods=["GET"])
def patient_history():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    patient_id = request.args.get("patient_id", type=int)
    # Use session user_id for patient, or validate doctor access
    if session.get("role") == "patient":
        pid = session["user_id"]
    else:
        if not patient_id:
            return jsonify({"error": "patient_id is required for doctors"}), 400
        pid = patient_id

    history = get_patient_history(pid, limit=50)
    # Return chronological (oldest first for charts)
    history = history[::-1]
    return jsonify({"history": history})


# ==============================
# PDF REPORT GENERATION


def _format_field(value, empty="—"):
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return empty
    return str(value)


def _build_report_buffer(patient_id: int, record: dict) -> io.BytesIO:
    """Builds a PDF report for a single patient record."""

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=50,
        bottomMargin=50,
    )

    styles = getSampleStyleSheet()
    
    # Custom styles
    header_style = ParagraphStyle(
        name="Header",
        fontName="Helvetica-Bold",
        fontSize=24,
        textColor=colors.HexColor("#0ea5e9"),
        alignment=TA_CENTER,
        spaceAfter=20,
    )

    section_headingStyles = ParagraphStyle(
        name="SectionHeading",
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=10,
        spaceBefore=15,
        borderPadding=(0, 0, 4, 0),
    )

    body_style = ParagraphStyle(
        name="Body",
        fontName="Helvetica",
        fontSize=10,
        textColor=colors.HexColor("#334155"),
        spaceAfter=6,
        leading=14,
    )
    
    risk_title_style = ParagraphStyle(
        name="RiskTitle",
        fontName="Helvetica-Bold",
        fontSize=14,
        textColor=colors.HexColor("#0f172a"),
        alignment=TA_CENTER,
        spaceAfter=10,
    )

    created_at = record.get("created_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    risk_level = (record.get("risk_level") or "Unknown").upper()
    
    # Styling variables
    if risk_level == "HIGH":
        risk_bg = colors.HexColor("#fef2f2")
        risk_fg = colors.HexColor("#dc2626")
    elif risk_level == "MODERATE" or risk_level == "MEDIUM":
        risk_bg = colors.HexColor("#fff7ed")
        risk_fg = colors.HexColor("#ea580c")
    else:
        risk_bg = colors.HexColor("#f0fdf4")
        risk_fg = colors.HexColor("#16a34a")

    recommendations = record.get("recommendations") or (
        "Please seek immediate medical attention and consult your specialist." if risk_level == "HIGH" else
        "Maintain current health management and monitor vitals regularly."
    )

    items = []
    
    # Header Section
    items.append(Paragraph("MediScope Assessment Report", header_style))
    items.append(Spacer(1, 10))
    
    # Patient Info Table
    info_data = [
        [Paragraph("<b>Patient ID:</b>", body_style), Paragraph(str(patient_id), body_style)],
        [Paragraph("<b>Date of Assessment:</b>", body_style), Paragraph(created_at, body_style)]
    ]
    info_table = Table(info_data, colWidths=[120, 380], hAlign="LEFT")
    info_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#e2e8f0")),
    ]))
    items.append(info_table)
    items.append(Spacer(1, 20))

    # Assessment Results
    
    # 1. Vital Signs Summary
    items.append(Paragraph("Vital Signs Summary", section_headingStyles))
    
    vitals_data = [
        ["Blood Pressure", f"{_format_field(record.get('bp_systolic'))}/{_format_field(record.get('bp_diastolic'))} mmHg"],
        ["Heart Rate", f"{_format_field(record.get('heart_rate'))} bpm"],
        ["Respiratory Rate", f"{_format_field(record.get('respiratory_rate'))} /min"],
        ["Temperature", f"{_format_field(record.get('temperature'))} °C"],
        ["Oxygen Saturation", f"{_format_field(record.get('oxygen_saturation'))}%"]
    ]
    
    vitals_table = Table(vitals_data, colWidths=[200, 300], hAlign="LEFT")
    vitals_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0f172a")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
    ]))
    items.append(vitals_table)
    items.append(Spacer(1, 20))

    # 1.1 Clinical Trends (Phase 4)
    if record.get("trends"):
        items.append(Paragraph("Clinical Trends (vs Previous Assessment)", section_headingStyles))
        trend_data = []
        for key, trend in record.get("trends", {}).items():
            label = key.replace("_", " ").title()
            trend_data.append([label, trend])
        
        if trend_data:
            trend_table = Table(trend_data, colWidths=[200, 300], hAlign="LEFT")
            trend_table.setStyle(TableStyle([
                ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#0ea5e9")),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
            ]))
            items.append(trend_table)
            items.append(Spacer(1, 20))

    # 2. Risk Evaluation Box
    items.append(Paragraph("Risk Evaluation", section_headingStyles))
    
    risk_data = [
        [Paragraph("OVERALL RISK LEVEL", risk_title_style)],
        [Paragraph(f'<font color="{risk_fg.hexval()}"><b>{risk_level}</b></font>', ParagraphStyle(name="RiskVal", fontName="Helvetica-Bold", fontSize=20, alignment=TA_CENTER))]
    ]
    risk_box = Table(risk_data, colWidths=[500], hAlign="CENTER")
    risk_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), risk_bg),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 15),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 15),
        ("BOX", (0, 0), (-1, -1), 1.5, risk_fg),
    ]))
    items.append(risk_box)
    items.append(Spacer(1, 25))

    # 3. AI Insights
    items.append(Paragraph("AI Diagnostic Summary", section_headingStyles))
    
    prediction_text = str(record.get("prediction") or "Analysis completed with available data.")
    ai_data = [
        [Paragraph("<b>Status:</b>", body_style), Paragraph(prediction_text, body_style)],
        [Paragraph("<b>NEWS2 Score:</b>", body_style), Paragraph(str(_format_field(record.get('news2_score'))), body_style)],
    ]
    ai_table = Table(ai_data, colWidths=[120, 380], hAlign="LEFT")
    ai_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    items.append(ai_table)
    items.append(Spacer(1, 20))

    # 3.1 Top Contributing Factors (Explainability Phase 4)
    if record.get("top_factors"):
        items.append(Paragraph("Top Risk Contributors", section_headingStyles))
        factors_text = ""
        for factor in record.get("top_factors", []):
            factors_text += f"&bull; <b>{factor['name']}:</b> Clinical deviation identified.<br/>"
        
        items.append(Paragraph(factors_text, body_style))
        items.append(Spacer(1, 20))

    # 4. Recommendations
    items.append(Paragraph("AI-Generated Recommendation", section_headingStyles))
    
    rec_box = Table(
        [[Paragraph(recommendations, body_style)]],
        colWidths=[500],
        hAlign="CENTER"
    )
    rec_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 15),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 15),
        ("LEFTPADDING", (0, 0), (-1, -1), 15),
        ("RIGHTPADDING", (0, 0), (-1, -1), 15),
    ]))
    items.append(rec_box)
    items.append(Spacer(1, 8))
    
    disclaimer_style = ParagraphStyle(
        name="Disclaimer",
        fontName="Helvetica",
        fontSize=8,
        textColor=colors.HexColor("#64748b"),
        alignment=TA_LEFT,
        leading=11,
    )
    items.append(Paragraph("<b>Note:</b> This is an AI-generated recommendation based on your current health data "
                           "and does not constitute a medical diagnosis. Please consult a qualified doctor.", disclaimer_style))
    

    doc.build(items)
    buffer.seek(0)
    return buffer


@app.route("/download-report", methods=["GET"])
@app.route("/download-report/patient/<int:patient_id>", methods=["GET"])
def generate_report(patient_id=None):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    # If a record_id is provided, generate for that specific record.
    record_id = request.args.get("record_id", type=int)

    # If no patient_id is passed, use the currently logged in patient.
    if patient_id is None:
        patient_id = session.get("user_id")

    # Patients may only access their own records (handle string/int session types)
    if session.get("role") == "patient":
        try:
            session_user_id = int(session.get("user_id"))
            patient_id_int = int(patient_id)
        except (TypeError, ValueError):
            return jsonify({"error": "Forbidden"}), 403

        if session_user_id != patient_id_int:
            return jsonify({"error": "Forbidden"}), 403

    record = None
    if record_id:
        record = get_patient_record(record_id)
        if not record:
            return jsonify({"error": "Record not found"}), 404
        if session.get("role") == "patient" and record.get("patient_id") != session.get("user_id"):
            return jsonify({"error": "Forbidden"}), 403

    if not record:
        history = get_patient_history(patient_id, limit=1)
        if not history:
            return jsonify({"error": "No records found for this patient"}), 404
        record = history[0]

    try:
        pdf_buffer = _build_report_buffer(patient_id, record)
    except Exception as e:
        return jsonify({"error": f"Failed to generate report: {e}"}), 500

    record_tag = record.get("id") or record_id or patient_id
    filename = f"patient_report_{record_tag}.pdf"
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@app.route("/download-report/<int:record_id>", methods=["GET"])
def generate_report_by_record(record_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    record = get_patient_record(record_id)
    if not record:
        return jsonify({"error": "Record not found"}), 404

    # Ensure patient users can only access their own records (handle string/int session types)
    if session.get("role") == "patient":
        try:
            session_user_id = int(session.get("user_id"))
            record_owner_id = int(record.get("patient_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "Forbidden"}), 403

        if record_owner_id != session_user_id:
            return jsonify({"error": "Forbidden"}), 403

    try:
        pdf_buffer = _build_report_buffer(record.get("patient_id"), record)
    except Exception as e:
        return jsonify({"error": f"Failed to generate report: {e}"}), 500

    filename = f"patient_report_{record_id}.pdf"
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@app.route("/doctor/report/<int:patient_id>")
def doctor_report_page(patient_id):
    # Primary security check: user must be a doctor
    user_role = session.get("role")
    if "user_id" not in session or user_role != "doctor":
        if "user_id" not in session:
            return redirect("/login?role=doctor")
        return abort(403)

    patient = get_patient_by_id(patient_id)
    if not patient:
        abort(404)

    latest_history = get_patient_history(patient_id, limit=1)
    record = latest_history[0] if latest_history else None

    if not record:
        # Fallback: render with patient info and no assessment data
        return render_template("report.html", patient=patient, record={})

    return render_template("report.html", patient=patient, record=record)


@app.route("/report/<int:record_id>")
def report_page(record_id):
    if "user_id" not in session:
        return redirect("/login?role=patient")

    record = get_patient_record(record_id)
    if not record:
        abort(404)

    # Ensure patient users can only view their own records (handle string/int session types)
    if session.get("role") == "patient":
        try:
            session_user_id = int(session.get("user_id"))
            record_owner_id = int(record.get("patient_id"))
        except (TypeError, ValueError):
            abort(403)

        if record_owner_id != session_user_id:
            abort(403)

    patient = get_patient_by_id(record.get("patient_id"))
    return render_template("report.html", record=record, patient=patient)


@app.route("/doctor/alerts", methods=["GET"])
def doctor_alerts():
    if "user_id" not in session or session.get("role") != "doctor":
        return jsonify({"error": "Unauthorized"}), 401

    patients_data = get_patients_with_latest_record()
    alerts = []

    for patient in patients_data:
        if patient.get("latest_risk_level") and patient["latest_risk_level"].lower() in ["high", "medium"]:
            alerts.append({
                "patient_id": patient.get("id"),
                "patient_name": patient.get("name"),
                "risk_level": patient.get("latest_risk_level"),
                "message": f"{patient.get('name')} has {patient.get('latest_risk_level').lower()} risk level.",
                "created_at": patient.get("latest_created_at")
            })

    return jsonify({"alerts": alerts})


@app.route("/view-report-file/<filename>")
def view_report_file(filename):
    if "user_id" not in session:
        return redirect("/login")
    
    # Optional: Add security check to ensure patient only views their own file
    # For now, allow doctor access or patient access
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ==============================
# RUN SERVER

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") != "production"
    socketio.run(app, host="0.0.0.0", port=port, debug=debug, allow_unsafe_werkzeug=True)
