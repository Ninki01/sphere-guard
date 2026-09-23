import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import board
from adafruit_bme280 import basic as adafruit_bme280

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
session_ref.set({
    'test_start_time': firestore.SERVER_TIMESTAMP,
    'device_id': 'sg01',
    'environment': 'lab_test', 
    'sensors_active': ['BME280']
})
print(f"📁 Created Test Session: testing/{session_id}")
# ==========================================

# --- SENSOR SETUP ---
try:
    i2c = board.I2C()
    # Note: Most generic BME280 sensors use address 0x76. 
    # If this fails, change the address below to 0x77.
    bme280 = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=0x77)
    print("✅ BME280 Setup Complete!")
except Exception as e:
    print(f"❌ Sensor Setup Failed: {e}")
    exit(1)

# --- MAIN LOOP ---
try:
    print("Starting measurements...")
    while True:
        try:
            # Create a clean time string (e.g., "15-30-05")
            doc_id = datetime.now().strftime("%H-%M-%S")
            
            # Get the local time (as a float for math)
            t_start = time.time() 
            local_pi_time = datetime.now().isoformat()
            doc_id = datetime.now().strftime("%H-%M-%S")
            
            # Read data from the sensor
            temp_val = bme280.temperature
            hum_val = bme280.relative_humidity
            press_val = bme280.pressure
            
            # Package and Send
            data_payload = {
                'temperature_c': round(bme280.temperature, 2),
                'humidity_percent': round(bme280.relative_humidity, 2),
                'pressure_hpa': round(bme280.pressure, 2),
                'local_pi_time': local_pi_time,
                'timestamp': firestore.SERVER_TIMESTAMP # Server-side time 
            }
            
            # Send to Firestore
            doc_ref = session_ref.collection('readings_bme280').document(doc_id)
            doc_ref.set(data_payload)
            
            # Calculate how long the 'set' operation took
            # This measures how long the '.set()' took to finish (Round Trip)
            t_end = time.time()
            network_delay = round(t_end - t_start, 3) # Delay in seconds
            
            # Add the delay back to the same document
            doc_ref.update({'wifi_delay_sec': network_delay})
            
            print(f"☁️ Sent [{doc_id}] | Delay: {network_delay}s | Signal: {'Good' if network_delay < 1 else 'Weak'}")
        
            print(f"☁️ Sent [{doc_id}] -> Temp: {temp_val:.1f}°C | Hum: {hum_val:.1f}% | Press: {press_val:.1f}hPa")
            
        except OSError as e:
            # If Errno 121 happens, catch it here instead of crashing!
            print(f"⚠️ I2C Glitch ignored: {e}. Retrying on next loop...")
        
        # Always sleep for 5 seconds, whether the read succeeded or failed
        time.sleep(5) 

except KeyboardInterrupt:
    # Log when the test ended
    session_ref.update({'test_end_time': firestore.SERVER_TIMESTAMP})
    print("\nMeasurement stopped. Test session closed.")