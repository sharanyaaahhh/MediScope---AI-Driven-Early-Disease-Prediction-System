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
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
CORS(app, supports_credentials=True)

# ==============================
# LOAD ML MODEL
# ==============================

model = joblib.load("models/disease_predictor.pkl")
scaler = joblib.load("models/scaler.pkl")

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


# ==============================
# REGISTER DOCTOR
# ==============================

@app.route("/doctor-register", methods=["POST"])
def doctor_register_api():

    data = request.json

    try:
        result = register_doctor(
            data["name"],
            data["age"],
            data["specialization"],
            data["email"],
            data["password"]
        )

        if isinstance(result, dict) and result.get("error"):
            return jsonify({"success": False, "message": result["error"]}), 400

        return jsonify({"success": True, "message": "Doctor registered successfully"})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400


# ==============================
# REGISTER PATIENT
# ==============================


@app.route("/patient-register", methods=["POST"])
def register_patient_api():

    data = request.json

    name = data.get("name")
    age = data.get("age")
    gender = data.get("gender")
    email = data.get("email")
    password = data.get("password")
    family_history = data.get("family_history")
    medications = data.get("medications")

    try:
        result = register_patient(
            name,
            age,
            gender,
            email,
            password,
            family_history,
            medications
        )

        return jsonify({
            "success": True,
            "message": "Patient registered successfully",
            "patient_id": result
        })

    except Exception as e:
        print(e)
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
        return jsonify({"success": False, "message": result["error"]}), 400

    session["user_id"] = result.get("user_id")
    session["role"] = role

    redirect = "/doctor-dashboard" if role == "doctor" else "/patient-dashboard"

    return jsonify({
        "success": True,
        "message": "Login successful",
        "redirect": redirect,
    })


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()

    if request.method == "GET":
        flash("You have been logged out successfully.", "success")
        return redirect("/login")

    return jsonify({"success": True, "message": "Logged out", "redirect": "/login"})


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

    # ---------- Combine results ----------
    if ml_prediction == 1 and (confidence >= 75 or news2_score >= 7):
        final_risk = "High"
    elif ml_prediction == 1 or news2_score >= 5:
        final_risk = "Medium"
    else:
        final_risk = "Low"

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

    patient_id = session.get("user_id")
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

    recommended_doctor = "Cardiologist" if final_risk == "High" else "General Physician"
    recommendations = (
        "Please seek immediate medical attention." if final_risk == "High"
        else "Monitor your symptoms closely and follow your treatment plan."
    )

    return jsonify({
        "success": True,
        "ml_prediction": ml_prediction,
        "news2_score": news2_score,
        "final_risk": final_risk,
        "confidence": confidence,
        "recommended_doctor": recommended_doctor,
        "recommendations": recommendations
    })


@app.route("/patients", methods=["GET"])
def patients():
    if "user_id" not in session or session.get("role") != "doctor":
        return jsonify({"error": "Unauthorized"}), 401

    patients_data = get_patients_with_latest_record()
    return jsonify({"patients": patients_data})


@app.route("/patient-history/<int:patient_id>", methods=["GET"])
def patient_history_by_id(patient_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    if session.get("role") == "patient" and session.get("user_id") != patient_id:
        return jsonify({"error": "Forbidden"}), 403

    history = get_patient_history(patient_id, limit=50)
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

    return render_template("report.html", record=record)


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


# ==============================
# RUN SERVER

if __name__ == "__main__":
    app.run(debug=True)
