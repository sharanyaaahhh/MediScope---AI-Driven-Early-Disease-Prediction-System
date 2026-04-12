# utils/validation.py

REQUIRED_FIELDS = [
    "bp_systolic",
    "bp_diastolic",
    "heart_rate",
    "respiratory_rate",
    "temperature",
    "oxygen_saturation",
    "med_adherence",
    "symptom_severity"
]


def check_missing_fields(data):
    """
    Check if any required fields are missing
    """
    missing = []

    for field in REQUIRED_FIELDS:
        if field not in data:
            missing.append(field)

    return missing


def convert_types(data):
    """
    Convert incoming values to correct numeric types
    """

    float_fields = [
        "bp_systolic",
        "bp_diastolic",
        "heart_rate",
        "respiratory_rate",
        "temperature",
        "oxygen_saturation"
    ]

    int_fields = [
        "med_adherence",
        "symptom_severity"
    ]

    for field in float_fields:
        data[field] = float(data[field])

    for field in int_fields:
        data[field] = int(data[field])

    return data


def validate_ranges(data):
    """
    Validate medically reasonable ranges (aligned with app.py/app.py mapping)
    """
    if not 60 <= data["bp_systolic"] <= 250:
        return "Systolic BP must be 60-250 mmHg"

    if not 40 <= data["bp_diastolic"] <= 150:
        return "Diastolic BP must be 40-150 mmHg"

    if not 30 <= data["heart_rate"] <= 200:
        return "Heart rate must be 30-200 bpm"

    if not 8 <= data["respiratory_rate"] <= 40:
        return "Respiratory rate must be 8-40 breaths/min"

    if not 35 <= data["temperature"] <= 42:
        return "Temperature must be 35-42°C"

    if not 70 <= data["oxygen_saturation"] <= 100:
        return "O₂ saturation must be 70-100%"

    if not 0 <= data["med_adherence"] <= 3:
        return "Medication adherence must be 0-3"

    if not 0 <= data["symptom_severity"] <= 3:
        return "Symptom severity must be 0-3"

    return None


def validate_input(data):
    """
    Complete validation pipeline
    """

    # check missing fields
    missing = check_missing_fields(data)
    if missing:
        return False, {"error": f"Missing fields: {missing}"}

    # convert types
    try:
        data = convert_types(data)
    except Exception:
        return False, {"error": "Invalid data types. Numeric values required."}

    # validate ranges
    range_error = validate_ranges(data)
    if range_error:
        return False, {"error": range_error}

    return True, data
