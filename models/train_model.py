import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score

# Load dataset
df = pd.read_csv("data/ehr_data.csv")

# Features
X = df[[
    "bp_systolic",
    "bp_diastolic",
    "heart_rate",
    "respiratory_rate",
    "temperature",
    "oxygen_saturation",
    "med_adherence",
    "symptom_severity"
]]

# Target
y = df["progressed_to_critical"]

# Train test split
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

# Scaling
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# Random Forest Model
model = RandomForestClassifier(
    n_estimators=100,
    random_state=42
)

model.fit(X_train_scaled, y_train)

# Predictions
predictions = model.predict(X_test_scaled)

accuracy = accuracy_score(y_test, predictions)

print("Model Accuracy:", accuracy)

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

model_path = os.path.join(BASE_DIR, "disease_predictor.pkl")
scaler_path = os.path.join(BASE_DIR, "scaler.pkl")

joblib.dump(model, model_path)
joblib.dump(scaler, scaler_path)

print("Model trained and saved")