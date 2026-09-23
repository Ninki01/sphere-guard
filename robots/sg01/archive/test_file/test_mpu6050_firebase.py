import time
import math
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import board
import adafruit_mpu6050

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
session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
session_ref = db.collection('testing').document(session_id)

session_ref.set({
    'test_start_time': firestore.SERVER_TIMESTAMP,
    'device_id': 'sg01',
    'environment': 'lab_test', 
    'sensors_active': ['MPU6050']
})
print(f"📁 Created Test Session: testing/{session_id}")

# --- SENSOR SETUP ---
try:
    i2c = board.I2C()
    mpu = adafruit_mpu6050.MPU6050(i2c, address=0x68)
    print("✅ MPU6050 Setup Complete!")
except Exception as e:
    print(f"❌ Sensor Setup Failed: {e}")
    exit(1)

# ==========================================
# --- COMPLEMENTARY FILTER SETUP ---
# ==========================================
RAD_TO_DEG = 180 / math.pi
ALPHA = 0.98  

current_pitch = 0.0
current_roll = 0.0
last_filter_time = time.time()

def calculate_angles(accel_x, accel_y, accel_z, gyro_x, gyro_y):
    global current_pitch, current_roll, last_filter_time
    
    now = time.time()
    dt = now - last_filter_time
    last_filter_time = now
    
    # Prevent giant spikes on the very first loop or after a glitch
    if dt > 1.0: 
        dt = 0.01

    # Accelerometer Angles
    accel_pitch = math.atan2(accel_y, math.sqrt(accel_x**2 + accel_z**2)) * RAD_TO_DEG
    accel_roll = math.atan2(-accel_x, accel_z + 0.001) * RAD_TO_DEG

    # Gyro Rates
    gyro_pitch_rate = gyro_x * RAD_TO_DEG
    gyro_roll_rate = gyro_y * RAD_TO_DEG

    # Fusion
    current_pitch = ALPHA * (current_pitch + gyro_pitch_rate * dt) + (1 - ALPHA) * accel_pitch
    current_roll = ALPHA * (current_roll + gyro_roll_rate * dt) + (1 - ALPHA) * accel_roll

    return round(current_pitch, 1), round(current_roll, 1)


# --- MAIN LOOP ---
last_db_upload = time.time()

try:
    print("Starting measurements...")
    while True:
        try:
            # ---------------------------------------------------------
            # 1. FAST LOOP: Sensor Reading & Angle Math (Runs constantly)
            # ---------------------------------------------------------
            accel_x, accel_y, accel_z = mpu.acceleration
            gyro_x, gyro_y, gyro_z = mpu.gyro
            temp_val = mpu.temperature
            
            # Update the pitch and roll constantly to keep them accurate
            pitch_deg, roll_deg = calculate_angles(accel_x, accel_y, accel_z, gyro_x, gyro_y)

            # ---------------------------------------------------------
            # 2. SLOW LOOP: Database Upload (Runs every 5 seconds)
            # ---------------------------------------------------------
            current_time = time.time()
            if current_time - last_db_upload >= 5.0:
                
                t_start = time.time() 
                local_pi_time = datetime.now().isoformat()
                doc_id = datetime.now().strftime("%H-%M-%S")
                
                data_payload = {
                    'accel_x': round(accel_x, 2),
                    'accel_y': round(accel_y, 2),
                    'accel_z': round(accel_z, 2),
                    'gyro_x': round(gyro_x, 2),
                    'gyro_y': round(gyro_y, 2),
                    'gyro_z': round(gyro_z, 2),
                    'pitch_deg': pitch_deg,      # <-- Added Filtered Pitch
                    'roll_deg': roll_deg,        # <-- Added Filtered Roll
                    'temperature_c': round(temp_val, 2),
                    'local_pi_time': local_pi_time,
                    'timestamp': firestore.SERVER_TIMESTAMP 
                }
                
                doc_ref = session_ref.collection('readings_mpu6050').document(doc_id)
                doc_ref.set(data_payload)
                
                t_end = time.time()
                network_delay = round(t_end - t_start, 3)
                doc_ref.update({'wifi_delay_sec': network_delay})
                
                # Terminal Output
                print(f"☁️ Sent [{doc_id}] | Delay: {network_delay}s | Signal: {'Good' if network_delay < 1 else 'Weak'}")
                print(f"   -> Angles: Pitch {pitch_deg}° | Roll {roll_deg}°")
                
                # Reset the upload timer
                last_db_upload = current_time

        except OSError as e:
            print(f"⚠️ I2C Glitch ignored: {e}. Retrying on next loop...")
        
        # Tiny sleep for the Fast Loop (20 times per second)
        time.sleep(0.05) 

except KeyboardInterrupt:
    session_ref.update({'test_end_time': firestore.SERVER_TIMESTAMP})
    print("\nMeasurement stopped. Test session closed.")