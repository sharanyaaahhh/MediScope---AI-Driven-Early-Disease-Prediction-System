# db.py
import os
from sqlalchemy import create_engine, Table, Column, Integer, String, Float, MetaData, ForeignKey, select, inspect, text
from sqlalchemy.sql import insert
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

# SQLite database setup (can be overridden via environment variable)
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///mediscope.db")
engine = create_engine(DATABASE_URL, echo=False)
metadata = MetaData()

# Doctors Table
doctors = Table(
    "doctors", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String, nullable=False),
    Column("age", Integer, nullable=False),
    Column("specialization", String, nullable=False),
    Column("email", String, unique=True, nullable=False),
    Column("password", String, nullable=False),
    Column("created_at", String, default=str(datetime.utcnow()))
)

# Patients Table
patients = Table(
    "patients", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String, nullable=False),
    Column("age", Integer, nullable=False),
    Column("gender", String, nullable=False),
    Column("family_history", String),
    Column("medications", String),
    Column("email", String, unique=True, nullable=False),
    Column("password", String, nullable=False),
    Column("registered_at", String, default=lambda: str(datetime.utcnow()))
)

# Patient Records Table
patient_records = Table(
    "patient_records", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("patient_id", Integer, ForeignKey("patients.id"), nullable=False),
    Column("bp_systolic", Float),
    Column("bp_diastolic", Float),
    Column("heart_rate", Float),
    Column("respiratory_rate", Float),
    Column("temperature", Float),
    Column("oxygen_saturation", Float),
    Column("med_adherence", Integer),
    Column("symptom_severity", Integer),
    Column("prediction", Integer),
    Column("confidence", Float),
    Column("news2_score", Integer),
    Column("risk_level", String),  # High Risk / Low Risk
    Column("recommended_doctor", String),
    Column("created_at", String, default=lambda: str(datetime.utcnow()))
)
#save records table
records = Table(
    "health_records", metadata,
    Column("id", Integer, primary_key=True),
    Column("patient_email", String),
    Column("systolic", Integer),
    Column("diastolic", Integer),
    Column("heart_rate", Integer),
    Column("temperature", Float),
    Column("oxygen", Integer),
    Column("risk_level", String),
    Column("created_at", String)
)

# Create all tables (this does not alter existing tables; we migrate missing columns separately)
metadata.create_all(engine)

# Ensure required columns exist for patient_records (migration helper)
from sqlalchemy import text


def _ensure_patient_records_columns():
    """Ensure new columns exist in patient_records for newer schema versions."""
    with engine.connect() as conn:
        existing_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(patient_records)"))
        }

        # SQLite does not support dropping columns; we only add missing ones.
        if "news2_score" not in existing_columns:
            conn.execute(text("ALTER TABLE patient_records ADD COLUMN news2_score INTEGER"))
        if "created_at" not in existing_columns:
            conn.execute(text("ALTER TABLE patient_records ADD COLUMN created_at TEXT"))


# Run migration once at module import time
try:
    _ensure_patient_records_columns()
except Exception as e:
    # If migration fails (e.g., table not created yet), ignore and let create_all handle it.
    pass

def register_doctor(name, age, specialization, email, password):

    with engine.connect() as conn:

        # check existing doctor
        existing = conn.execute(
            select(doctors).where(doctors.c.email == email)
        ).fetchone()

        if existing:
            return {"error": "Doctor already exists"}

        stmt = insert(doctors).values(
            name=name,
            age=age,
            specialization=specialization,
            email=email,
            password=generate_password_hash(password),
            created_at=str(datetime.utcnow())
        )

        conn.execute(stmt)
        conn.commit()

        return {"message": "Doctor registered successfully"}

def register_patient(name, age, gender, email, password, family_history, medications):

    with engine.connect() as conn:

        existing = conn.execute(
            select(patients).where(patients.c.email == email)
        ).fetchone()

        if existing:
            raise Exception("Patient already exists")

        stmt = insert(patients).values(
            name=name,
            age=age,
            gender=gender,
            email=email,
            password=generate_password_hash(password),
            family_history=family_history,
            medications=medications,
            registered_at=str(datetime.utcnow())
        )

        result = conn.execute(stmt)
        conn.commit()

        return {
            "message": "Patient registered successfully",
            "patient_id": result.inserted_primary_key[0]
        }


def login_user(email, password, role):
    """Authenticate doctor or patient based on role.

    Returns a dict with either "user_id" on success or "error" on failure.
    """

    if role not in ("doctor", "patient"):
        return {"error": "Invalid role"}

    table = doctors if role == "doctor" else patients

    with engine.connect() as conn:
        user = conn.execute(
            select(table).where(table.c.email == email)
        ).fetchone()

        if not user:
            return {"error": "Invalid credentials"}

        if not check_password_hash(user.password, password):
            return {"error": "Invalid credentials"}

        return {"user_id": user.id}


def save_patient_record(patient_id, bp_systolic, bp_diastolic, heart_rate,
                        respiratory_rate, temperature, oxygen_saturation,
                        med_adherence, symptom_severity, prediction,
                        confidence, news2_score, risk_level, recommended_doctor):
    """Store a patient measurement record.

    This function supports older database schemas (without `news2_score` and
    `created_at`) by falling back to a minimal column set when insertion fails.
    """

    values = {
        "patient_id": patient_id,
        "bp_systolic": bp_systolic,
        "bp_diastolic": bp_diastolic,
        "heart_rate": heart_rate,
        "respiratory_rate": respiratory_rate,
        "temperature": temperature,
        "oxygen_saturation": oxygen_saturation,
        "med_adherence": med_adherence,
        "symptom_severity": symptom_severity,
        "prediction": prediction,
        "confidence": confidence,
        "news2_score": news2_score,
        "risk_level": risk_level,
        "recommended_doctor": recommended_doctor,
        "created_at": str(datetime.utcnow()),
    }

    with engine.connect() as conn:
        try:
            stmt = insert(patient_records).values(**values)
            conn.execute(stmt)
            conn.commit()
        except Exception as e:
            # Fallback for older schema versions that do not include the new columns.
            minimal_keys = {
                "patient_id",
                "bp_systolic",
                "bp_diastolic",
                "heart_rate",
                "respiratory_rate",
                "temperature",
                "oxygen_saturation",
                "med_adherence",
                "symptom_severity",
                "prediction",
                "confidence",
                "risk_level",
                "recommended_doctor",
            }
            fallback_values = {k: v for k, v in values.items() if k in minimal_keys}
            stmt = insert(patient_records).values(**fallback_values)
            conn.execute(stmt)
            conn.commit()
            print(f"[WARN] Record saved with fallback schema (missing columns): {e}")
        else:
            print(f"Record saved for patient ID {patient_id}.")


def get_patient_history(patient_id, limit=20):
    with engine.connect() as conn:
        rows = conn.execute(
            select(patient_records)
            .where(patient_records.c.patient_id == patient_id)
            .order_by(patient_records.c.id.desc())
            .limit(limit)
        ).fetchall()

    history = []
    for r in rows:
        history.append(
            {
                "id": r.id,
                "bp_systolic": r.bp_systolic,
                "bp_diastolic": r.bp_diastolic,
                "heart_rate": r.heart_rate,
                "respiratory_rate": r.respiratory_rate,
                "temperature": r.temperature,
                "oxygen_saturation": r.oxygen_saturation,
                "med_adherence": r.med_adherence,
                "symptom_severity": r.symptom_severity,
                "prediction": r.prediction,
                "confidence": r.confidence,
                "news2_score": getattr(r, "news2_score", None),
                "risk_level": r.risk_level,
                "recommended_doctor": r.recommended_doctor,
                "created_at": (getattr(r, "created_at", None) or "").split('.')[0] if getattr(r, "created_at", None) else None,
            }
        )
    return history


def get_patient_record(record_id):
    """Return a single patient record by its PK (patient_records.id)."""
    with engine.connect() as conn:
        row = conn.execute(
            select(patient_records).where(patient_records.c.id == record_id)
        ).fetchone()

    if not row:
        return None

    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "bp_systolic": row.bp_systolic,
        "bp_diastolic": row.bp_diastolic,
        "heart_rate": row.heart_rate,
        "respiratory_rate": row.respiratory_rate,
        "temperature": row.temperature,
        "oxygen_saturation": row.oxygen_saturation,
        "med_adherence": row.med_adherence,
        "symptom_severity": row.symptom_severity,
        "prediction": row.prediction,
        "confidence": row.confidence,
        "news2_score": getattr(row, "news2_score", None),
        "risk_level": row.risk_level,
        "recommended_doctor": row.recommended_doctor,
                "created_at": (getattr(row, "created_at", None) or "").split('.')[0] if getattr(row, "created_at", None) else None,
    }


def get_patients_with_latest_record():
    """Return a list of patients with their latest recorded vitals.

    This function is used by the doctor dashboard to display recent patient
    readings.
    """

    results = []
    with engine.connect() as conn:
        patients_rows = conn.execute(select(patients)).fetchall()

        for p in patients_rows:
            latest = conn.execute(
                select(patient_records)
                .where(patient_records.c.patient_id == p.id)
                .order_by(patient_records.c.id.desc())
                .limit(1)
            ).fetchone()

            patient_info = {
                "id": p.id,
                "name": p.name,
                "email": p.email,
                "age": p.age,
                "gender": p.gender,
                "family_history": p.family_history,
                "medications": p.medications,
            }

            if latest:
                patient_info.update({
                    "latest_bp_systolic": latest.bp_systolic,
                    "latest_bp_diastolic": latest.bp_diastolic,
                    "latest_heart_rate": latest.heart_rate,
                    "latest_respiratory_rate": latest.respiratory_rate,
                    "latest_temperature": latest.temperature,
                    "latest_oxygen_saturation": latest.oxygen_saturation,
                    "latest_prediction": latest.prediction,
                    "latest_confidence": latest.confidence,
                    "latest_news2_score": getattr(latest, "news2_score", None),
                    "latest_risk_level": latest.risk_level,
                    "latest_recommended_doctor": latest.recommended_doctor,
                    "latest_created_at": (getattr(latest, "created_at", None) or "").split('.')[0] if getattr(latest, "created_at", None) else None,
                    "latest_record_id": latest.id,
                })

            results.append(patient_info)

    return results


def get_patient_by_id(patient_id):
    """Return patient metadata by patient ID."""
    with engine.connect() as conn:
        row = conn.execute(select(patients).where(patients.c.id == patient_id)).fetchone()

    if not row:
        return None

    return {
        "id": row.id,
        "name": row.name,
        "age": row.age,
        "gender": row.gender,
        "family_history": row.family_history,
        "medications": row.medications,
        "email": row.email,
        "registered_at": row.registered_at,
    }


def delete_patient(patient_id):
    """Delete a patient and all their medical records.
    
    This is used when a patient is deceased or permanently removes their account.
    Cascades to delete all patient_records associated with the patient.
    """
    from sqlalchemy import delete
    
    try:
        with engine.connect() as conn:
            # Delete all patient records first (cascade)
            conn.execute(
                delete(patient_records).where(patient_records.c.patient_id == patient_id)
            )
            
            # Delete the patient
            conn.execute(
                delete(patients).where(patients.c.id == patient_id)
            )
            
            conn.commit()
            return {"success": True, "message": f"Patient ID {patient_id} and all records deleted successfully"}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_doctor(doctor_id):
    """Delete a doctor profile.
    
    This is used when a doctor leaves the hospital/clinic or exits their position.
    """
    from sqlalchemy import delete
    
    try:
        with engine.connect() as conn:
            # Check if doctor exists
            doctor = conn.execute(
                select(doctors).where(doctors.c.id == doctor_id)
            ).fetchone()
            
            if not doctor:
                return {"success": False, "error": "Doctor not found"}
            
            # Delete the doctor
            conn.execute(
                delete(doctors).where(doctors.c.id == doctor_id)
            )
            
            conn.commit()
            return {"success": True, "message": f"Doctor ID {doctor_id} profile deleted successfully"}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_doctor_by_id(doctor_id):
    """Return doctor metadata by doctor ID."""
    with engine.connect() as conn:
        row = conn.execute(select(doctors).where(doctors.c.id == doctor_id)).fetchone()

    if not row:
        return None

    return {
        "id": row.id,
        "name": row.name,
        "age": row.age,
        "specialization": row.specialization,
        "email": row.email,
        "created_at": row.created_at,
    }
