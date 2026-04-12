def recommend_doctor(prediction):

    mapping = {
        0: "General Physician",
        1: "Cardiologist",
        2: "Pulmonologist",
        3: "Infectious Disease Specialist"
    }

    return mapping.get(prediction, "General Physician")