# Raspberry Pi 5 Spherical Robot Sensor & Telemetry Hub (SG02)
# Focus: I2C Sensors, Camera Status, RTDB + Firestore Logging

import os
import time
import psutil

# --- Imports from your modular folders ---
from sensors.bme280 import BME280Sensor
from sensors.scd41 import SCD41Sensor
from sensors.sht45 import SHT45Sensor
from sensors.ps1_voc import PS1VOCSensor
# from sensors.sdp810_500Pa import SDP810Sensor  <-- ON HOLD
from sensors.imu_bno055 import IMUBNO055

from firebase_client.db_manager import FirebaseManager
from firebase_client.storage_manager import StorageManager

# --- Configurations ---
DB_URL = "https://sphere-guard-2025-default-rtdb.asia-southeast1.firebasedatabase.app/"

# Calculate the exact path to the JSON file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CRED_PATH = os.path.join(BASE_DIR, "..", "serviceAccountKey.json")

# --- Timers (Update Intervals in milliseconds) ---
last_fast_update = 0
FAST_UPDATE_INTERVAL = 500   # IMU, Pi Temp, Status

last_env_update = 0
ENV_UPDATE_INTERVAL = 1000   # BME280, SCD41, SHT45, SDP810

# --- Initialize Hardware and DB ---
print("Initializing I2C Sensors...")
bme280_sensor = BME280Sensor()
scd41_sensor = SCD41Sensor()
sht45_sensor = SHT45Sensor()
voc_sensor = PS1VOCSensor()
# sdp810_sensor = SDP810Sensor()                 <-- ON HOLD
imu_bno055 = IMUBNO055()

print("Connecting to Firebase...")
# We pass "sg02" to the managers so they write to the correct database node
db = FirebaseManager(cred_path=CRED_PATH, db_url=DB_URL, robot_id="sg02")
storage_mgr = StorageManager(robot_id="sg02")

current_session_id = None

# --- Helper Function for Pi 5 Temp ---
def get_pi_cpu_temp():
    """Reads the actual hardware temperature of the Raspberry Pi 5"""
    try:
        temp = psutil.sensors_temperatures()['cpu_thermal'][0].current
        return round(temp, 1)
    except:
        return 0.0

# --- The Firebase Listener (Watches for Session Changes from React) ---
def firebase_listener(event):
    """Callback function triggered when Firebase data changes"""
    global current_session_id
    
    # Listen for Inspection Session start/stop
    if event.path == '/' or event.path.startswith('/system'):
        new_session_id = current_session_id
        
        if isinstance(event.data, dict) and 'system' in event.data:
            new_session_id = event.data['system'].get('activeSessionId')
        elif isinstance(event.data, dict) and 'activeSessionId' in event.data:
            new_session_id = event.data.get('activeSessionId')
        elif event.path == '/system/activeSessionId':
            new_session_id = event.data

        if new_session_id != current_session_id:
            current_session_id = new_session_id
            storage_mgr.set_active_session(current_session_id)
            
            if current_session_id:
                print(f"🔴 Inspection Recording STARTED: {current_session_id}")
            else:
                print("⏹️ Inspection Recording STOPPED.")

def main():
    global last_fast_update
    global last_env_update
    
    print("=== SG02 Sensor Telemetry Hub ===")
    
    # Start the Firebase listener on a background thread
    db.setup_listener(firebase_listener)
    print("Firebase connected and listening for session commands...")
    
    # Announce Online to RTDB
    db.set_connection_status("ONLINE")

    try:
        while True:
            current_time = time.time() * 1000
            
            # --- 1. Fast Update Loop (IMU & System Health) ---
            if (current_time - last_fast_update) > FAST_UPDATE_INTERVAL:
                # Read IMU
                pitch, roll, yaw = imu_bno055.get_angles()
                
                # Read Pi Temp
                pi_temp = get_pi_cpu_temp()
                
                # Push Fast Data to RTDB 
                db.update_fast_telemetry(pitch, roll, yaw, pi_temp)
                
                last_fast_update = current_time
                
            # --- 2. Environment Update Loop (Gas, Temp, Pressure) ---
            if (current_time - last_env_update) > ENV_UPDATE_INTERVAL:
                # Read physical sensors
                bme_t, bme_h, bme_p = bme280_sensor.get_readings()
                sht_t, sht_h = sht45_sensor.get_readings()
                co2, scd_t, scd_h = scd41_sensor.get_readings()
                voc = voc_sensor.get_readings()
                
                # Read Diff Pressure (ON HOLD - Feeding Dummy Value)
                # dp_pressure = sdp810_sensor.get_readings()
                dp_pressure = 0.0
                
                # Push to RTDB for the Live React Dashboard
                db.update_environment_data(bme_t, bme_h, bme_p, sht_t, sht_h, dp_pressure, co2, scd_t, scd_h, voc)
                
                # Log to Firestore for historical analysis 
                storage_mgr.log_environment_data(bme_t, bme_h, bme_p, sht_t, sht_h, dp_pressure, co2, scd_t, scd_h, voc)
                
                last_env_update = current_time
                print(f"[{time.strftime('%H:%M:%S')}] Env Synced | Pi: {get_pi_cpu_temp()}°C | CO2: {co2} ppm | VOC: {voc} ppm")

            # Small delay to prevent maxing out the Pi 5's CPU
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\nSetting robot status to OFFLINE in Firebase...")
    finally:
        # Graceful cleanup
        db.set_connection_status("OFFLINE")
        db.close_listener()
        scd41_sensor.cleanup()
        print("✅ Shutdown complete.")

if __name__ == "__main__":
    main()