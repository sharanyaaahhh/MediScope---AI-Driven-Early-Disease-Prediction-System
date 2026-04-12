import sqlite3
import os

db_path = r'c:/Users/HP/Medi Final/mediscope.db'

print(f"DB exists: {os.path.exists(db_path)}")
print(f"DB size: {os.path.getsize(db_path) if os.path.exists(db_path) else 0} bytes")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # List tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("Tables:", [t[0] for t in tables])
    
    # Counts
    for table in ['patients', 'doctors', 'patient_records']:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table};")
            count = cursor.fetchone()[0]
            print(f"{table}: {count} records")
            
            # Sample data
            cursor.execute(f"SELECT * FROM {table} LIMIT 1;")
            sample = cursor.fetchone()
            print(f"Sample {table}: {sample}")
        except sqlite3.Error as e:
            print(f"Error querying {table}: {e}")
    
    conn.close()
except Exception as e:
    print(f"DB Error: {e}")

