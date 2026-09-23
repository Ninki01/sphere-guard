import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import board
import adafruit_scd4x

# --- PATH CONFIGURATION ---
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"
JSON_KEY_PATH = BASE_DIR / "serviceAccountKey.json"

# --- FIREBASE SETUP ---
load_dotenv(dotenv_path=ENV_PATH)

try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(JSON_KEY_PATH))
        firebase_admin.initialize_app(cred) 
    db = firestore.client()
    print("✅ Firestore Connected!")
except Exception as e:
    print(f"❌ Firebase Connection Failed: {e}")
    exit(1)

# ==========================================
# --- PRO SETUP: SESSION-BASED LOGGING ---
# ==========================================
# 1. Generate a human-readable timestamp for the "folder" name
session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# 2. Create a reference to this specific test session
session_ref = db.collection('testing').document(session_id)

# 3. Write "Metadata" to the session document. 
# This tells you WHAT this test was, without having to look at the data.
session_ref.set({
    'test_start_time': firestore.SERVER_TIMESTAMP,
    'robot_id': 'sg01',
    'environment': 'lab_test', # Change this when you move to the HVAC ducts
    'sensors_active': ['SCD41']
})
print(f"📁 Created Test Session: testing/{session_id}")
# ==========================================

# --- SENSOR SETUP ---
try:
    i2c = board.I2C()
    scd4x = adafruit_scd4x.SCD4X(i2c)
    print("Serial number:", [hex(i) for i in scd4x.serial_number])
    scd4x.start_periodic_measurement()
    print("Waiting for first measurement (takes ~5 seconds)...")
except Exception as e:
    print(f"❌ Sensor Setup Failed: {e}")
    exit(1)

# --- MAIN LOOP ---
try:
    while True:
        if scd4x.data_ready:
            co2_val = scd4x.CO2
            temp_val = scd4x.temperature
            hum_val = scd4x.relative_humidity
            
            data_payload = {
                'co2_ppm': co2_val,
                'temperature_c': temp_val,
                'humidity_percent': hum_val,
                'timestamp': firestore.SERVER_TIMESTAMP, 
            }
            
            # Add the data to the 'readings' subcollection of the current session
            session_ref.collection('readings_scd41').add(data_payload)
            
            print(f"☁️ Sent to {session_id} -> CO2: {co2_val}ppm | Temp: {temp_val:.1f}°C")
            
        time.sleep(5) 

except KeyboardInterrupt:
    scd4x.stop_periodic_measurement()
    
    # Optional Pro-Tip: Log when the test ended
    session_ref.update({'test_end_time': firestore.SERVER_TIMESTAMP})
    
    print("\nMeasurement stopped. Test session closed.")