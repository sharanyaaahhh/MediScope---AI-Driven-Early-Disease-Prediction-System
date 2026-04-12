import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

# In a production app, the ENCRYPTION_KEY should be a 32-byte base64 string
# stored in a secure environment variable.
# For this project, we prioritize stability and will generate a key if missing.
_ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")

if not _ENCRYPTION_KEY:
    # Development fallback
    _ENCRYPTION_KEY = Fernet.generate_key().decode()
    print("[SECURITY] WARNING: ENCRYPTION_KEY not found in environment. Using generated key.")

cipher_suite = Fernet(_ENCRYPTION_KEY.encode())

def encrypt_data(data: str) -> str:
    """Encrypt a string and return the base64 encoded result."""
    if not data:
        return data
    return cipher_suite.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data: str) -> str:
    """Decrypt a base64 encoded string result."""
    if not encrypted_data:
        return encrypted_data
    try:
        return cipher_suite.decrypt(encrypted_data.encode()).decode()
    except Exception:
        # If decryption fails (e.g. data was not encrypted), return as is
        return encrypted_data
