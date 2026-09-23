
# Raspberry Pi Spherical Robot Control Script
# This script connects to Firebase Realtime Database, listens for motor commands and settings,
# and controls a servo motor accordingly. It also implements an auto-stop feature for safety.

# Updated: 2026-03-05

import os
import time
# imports
from control.servo_motor import DriveServo, SteeringServo
from sensors.imu_bno055 import IMUBNO055
from sensors.bme280_sensor import BME280Sensor
from sensors.scd41_sensor import SCD41Sensor
from sensors.ina219_sensor import INA219Sensor
from sensors.ps1_voc import PS1VOCSensor
from sensors.sht45 import SHT45Sensor
from sensors.sdp810 import SDP810Sensor

from firebase_client.db_manager import FirebaseManager
from firebase_client.storage_manager import StorageManager
from local_storage import LocalStorage

# from sensors.camera import CameraManager

# --- Configurations ---
DRIVE_CHANNEL = 0    # Plug the continuous servo into port 0 on the HAT
STEERING_CHANNEL = 1 # Plug the 180 servo into port 1 on the HAT
DB_URL = "https://sphere-guard-2025-default-rtdb.asia-southeast1.firebasedatabase.app/"

# Calculate the exact path to the JSON file
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # This gets the src/ folder path
CRED_PATH = os.path.join(BASE_DIR, "..", "serviceAccountKey.json") # Looks in sg01/

# --- Global State Variables ---
run_mode = 0                # 0=Stop, 1-3=Forward, 4-6=Reverse
steering_angle = 90         # 90 degrees is dead center for the pendulum
max_speed = 3               # The maximum allowed speed gear
auto_stop_timeout = 5000        # How many milliseconds before the robot stops itself if connection drops
last_command_time = time.time() * 1000  # A stopwatch tracking the exact moment the last command arrived

# --- Timers ---
last_imu_update = 0         
IMU_UPDATE_INTERVAL = 500 # milliseconds

last_bme280_update = 0
BME280_UPDATE_INTERVAL = 5000

last_scd41_update = 0        
SCD41_UPDATE_INTERVAL = 5000

last_battery_update = 0
BATTERY_UPDATE_INTERVAL = 10000

last_voc_update = 0
VOC_UPDATE_INTERVAL = 5000

last_sht45_update = 0
SHT45_UPDATE_INTERVAL = 5000

last_sdp810_update = 0
SDP810_UPDATE_INTERVAL = 1000

# --- Initialize Hardware and DB ---
# boot up" the hardware based on the classes in other files
drive_motor = DriveServo(channel=DRIVE_CHANNEL)
steering_motor = SteeringServo(channel=STEERING_CHANNEL)
imu_bno055 = IMUBNO055()
bme280_sensor = BME280Sensor()
scd41_sensor = SCD41Sensor()
ina219_sensor = INA219Sensor()
voc_sensor = PS1VOCSensor()
sht45_sensor = SHT45Sensor()
sdp810_sensor = SDP810Sensor()
# This logs into Firebase
db = FirebaseManager(cred_path=CRED_PATH, db_url=DB_URL)

# --- Initialize Camera ---
# camera = CameraManager()

# --- Initialize Storage ---
storage_mgr = StorageManager()
local = LocalStorage()
current_session_id = None

# Create a dictionary to map React string commands to internal motor integers
COMMAND_MAP = {
    'stop': 0,
    'fwd_slow': 1,
    'fwd_med': 2,
    'fwd_fast': 3,
    'rev_slow': 4,
    'rev_med': 5,
    'rev_fast': 6
}

# --- The Listener (Triggered instantly by Firebase) ---
def firebase_listener(event):
    """Callback function triggered ONLY when Firebase data changes"""
    # Start the stopwatch the exact millisecond the Pi receives the RTDB shout!
    event_arrival_time = time.time() * 1000
    
    # pull in the global variables so we can change them
    global run_mode, steering_angle, max_speed, auto_stop_timeout, last_command_time, current_session_id
    
    # 1. --- Handle Settings Updates ---
    if event.path == '/' or event.path.startswith('/settings'):
        # If the whole tree updates, safely extract nested settings
        if isinstance(event.data, dict) and 'settings' in event.data:
            max_speed = event.data['settings'].get('max_speed', max_speed)
            auto_stop_timeout = event.data['settings'].get('auto_stop_timeout', auto_stop_timeout)
        # If just one specific setting updates
        elif event.path == '/settings/max_speed':
            max_speed = event.data
        elif event.path == '/settings/auto_stop_timeout':
            auto_stop_timeout = event.data

    # 2. --- Handle Drive Command ---
    if event.path == '/' or event.path.startswith('/control/movement'):
        direction_str = 'stop'
        dashboard_timestamp = 0
        # Extract the string command from the nested object React sends
        if isinstance(event.data, dict):
            if 'control' in event.data and 'movement' in event.data['control']:
                direction_str = event.data['control']['movement'].get('direction', 'stop')
                dashboard_timestamp = event.data['control']['movement'].get('timestamp', 0)
            elif 'direction' in event.data:
                direction_str = event.data.get('direction', 'stop')
                dashboard_timestamp = event.data.get('timestamp', 0)
                
        # Calculate Latency 1: Dashboard -> Pi
        dash_to_pi_latency = round(event_arrival_time - dashboard_timestamp, 2) if dashboard_timestamp > 0 else 0
                
        new_cmd = COMMAND_MAP.get(direction_str, 0)
            
        try:
            is_valid = False
            if 0 <= new_cmd <= 6:
                if (1 <= new_cmd <= 3 and new_cmd <= max_speed) or \
                   (4 <= new_cmd <= 6 and (new_cmd - 3) <= max_speed) or \
                   new_cmd == 0:
                    is_valid = True

            if is_valid and new_cmd != run_mode:
                run_mode = new_cmd
                last_command_time = time.time() * 1000
                
                # EXECUTE THE HARDWARE MOVEMENT
                drive_motor.drive(run_mode) 
                db.update_status(run_mode, steering_angle)
                
                # 2. Stop the stopwatch exactly after the hardware command is sent
                execution_finish_time = time.time() * 1000
                internal_exec_latency = round(execution_finish_time - event_arrival_time, 2)
                
                # --- NEW: LOG TO FIRESTORE ---
                storage_mgr.log_command("drive", direction_str, dash_to_pi_latency, internal_exec_latency)
                print(f"Drive Command executed: Mode {run_mode} ({direction_str})")
            elif not is_valid:
                print(f"Command '{direction_str}' exceeds max_speed setting, ignored")
        except (ValueError, TypeError):
            pass

    # 3. --- Handle Steering Command ---
    if event.path == '/' or event.path.startswith('/control/steering_command'):
        new_angle = steering_angle
        dashboard_timestamp = 0
        
        # Extract the angle AND the timestamp from the new React object
        if isinstance(event.data, dict):
            if 'control' in event.data and 'steering_command' in event.data['control']:
                cmd_data = event.data['control']['steering_command']
                if isinstance(cmd_data, dict):
                    new_angle = cmd_data.get('angle', steering_angle)
                    dashboard_timestamp = cmd_data.get('timestamp', 0)
                else:
                    new_angle = cmd_data
            elif 'angle' in event.data:
                new_angle = event.data.get('angle', steering_angle)
                dashboard_timestamp = event.data.get('timestamp', 0)
        else:
            # Fallback if React just sends a raw number
            new_angle = event.data if event.path == '/control/steering_command' else steering_angle
            
        # Calculate Latency: Dashboard -> Pi
        dash_to_pi_latency = round(event_arrival_time - dashboard_timestamp, 2) if dashboard_timestamp > 0 else 0
            
        try:
            new_angle = int(new_angle)
            if 0 <= new_angle <= 180 and new_angle != steering_angle:
                steering_angle = new_angle
                
                # EXECUTE THE HARDWARE MOVEMENT
                steering_motor.set_angle(steering_angle)
                db.update_status(run_mode, steering_angle)
                
                # Stop the stopwatch exactly after the hardware command is sent
                execution_finish_time = time.time() * 1000
                internal_exec_latency = round(execution_finish_time - event_arrival_time, 2)
                
                # Pass ALL the latencies to the Storage Manager
                storage_mgr.log_command("steering", steering_angle, dash_to_pi_latency, internal_exec_latency)
                
                print(f"Steering Command executed: Angle {steering_angle}°")
        except (ValueError, TypeError):
            pass
        
    # 4. --- Handle Session Updates (From React Dashboard) ---
    if event.path == '/' or event.path.startswith('/system'):
        new_session_id = current_session_id
        
        # Safely extract the session ID whether it's a root update or direct update
        if isinstance(event.data, dict) and 'system' in event.data:
            new_session_id = event.data['system'].get('activeSessionId')
        elif isinstance(event.data, dict) and 'activeSessionId' in event.data:
            new_session_id = event.data.get('activeSessionId')
        elif event.path == '/system/activeSessionId':
            new_session_id = event.data

        # If the session changed (e.g., button was pressed on the dashboard)
        if new_session_id != current_session_id:
            current_session_id = new_session_id
            
            # Tell the Storage Managers to switch folders
            storage_mgr.set_active_session(current_session_id)
            local.set_active_session(current_session_id)
            
            if current_session_id:
                print(f"🔴 Inspection Recording STARTED: {current_session_id}")
            else:
                print("⏹️ Inspection Recording STOPPED.")

def main():
    global run_mode
    global last_imu_update
    global last_bme280_update
    global last_scd41_update
    global last_battery_update
    global last_voc_update
    global last_sht45_update
    global last_sdp810_update
    
    print("=== Sphere Guard Control Center ===")
    
    # Clear any stale command left in Firebase from the previous session
    # before starting the listener, so the robot never moves on boot
    db.reset_motor_command()

    # Start the Firebase listener on a background thread
    db.setup_listener(firebase_listener)
    print("Firebase connected and listening for commands...")

    db.set_connection_status("ONLINE")

    try:
        # Main loop handles the Auto-Stop logic 
        while True:
            current_time = time.time() * 1000
            
            # --- 1. Auto-Stop Safety (Motor) ---
            # If the robot is currently moving...
            if run_mode > 0 and auto_stop_timeout > 0:
                if (current_time - last_command_time) > auto_stop_timeout:
                    print("Auto-stop triggered")
                    run_mode = 0        # Forget the drive command
                    drive_motor.stop()  # Physically stop the motor
                    db.update_status(run_mode, steering_angle) # tell firebase to stop
                    db.reset_motor_command() # reset the dashboard gauge to 0
            
            # --- 2. Telemetry Pacing (IMU & Firebase) ---
            if (current_time - last_imu_update) > IMU_UPDATE_INTERVAL:
                pitch, roll, yaw = imu_bno055.get_angles()
                db.update_imu_data(pitch, roll, yaw)
                storage_mgr.log_imu_data(pitch, roll, yaw)
                local.log_imu(pitch, roll, yaw)
                last_imu_update = current_time
                
            # --- 3. Telemetry Pacing (BME280 & Firebase) ---
            if (current_time - last_bme280_update) > BME280_UPDATE_INTERVAL:
                
                # 1. Read the physical sensor
                t, h, p = bme280_sensor.get_readings()
                db.update_bme280_data(t, h, p)
                storage_mgr.log_bme280_data(t, h, p)
                local.log_bme280(t, h, p)
                last_bme280_update = current_time
                
            # --- 4. Telemetry Pacing (SCD41 & Firebase) ---
            if (current_time - last_scd41_update) > SCD41_UPDATE_INTERVAL:
                co2, scd_t, scd_h = scd41_sensor.get_readings()
                # If co2 is -1, the sensor isn't ready yet. Skip this loop.
                if co2 >= 0:
                    # 2. Push to RTDB for the live React dashboard
                    db.update_scd41_data(co2, scd_t, scd_h)
                    storage_mgr.log_scd41_data(co2, scd_t, scd_h)
                    local.log_scd41(co2, scd_t, scd_h)
                    last_scd41_update = current_time
                    
            # --- 5. Telemetry Pacing (PS1-VOC) ---
            if (current_time - last_voc_update) > VOC_UPDATE_INTERVAL:
                voc = voc_sensor.get_readings()
                db.update_voc_data(voc)
                storage_mgr.log_voc_data(voc)
                local.log_voc(voc)
                last_voc_update = current_time

            # --- 6. Telemetry Pacing (SHT45) ---
            if (current_time - last_sht45_update) > SHT45_UPDATE_INTERVAL:
                sht_t, sht_h = sht45_sensor.get_readings()
                db.update_sht45_data(sht_t, sht_h)
                storage_mgr.log_sht45_data(sht_t, sht_h)
                local.log_sht45(sht_t, sht_h)
                last_sht45_update = current_time

            # --- 7. Telemetry Pacing (SDP810 Differential Pressure) ---
            if (current_time - last_sdp810_update) > SDP810_UPDATE_INTERVAL:
                dp, dp_temp = sdp810_sensor.get_readings()
                db.update_sdp810_data(dp, dp_temp)
                storage_mgr.log_sdp810_data(dp, dp_temp)
                local.log_sdp810(dp, dp_temp)
                last_sdp810_update = current_time

            # --- 8. Telemetry Pacing (INA219 Battery) ---
            if (current_time - last_battery_update) > BATTERY_UPDATE_INTERVAL:

                # Read the power monitor
                v, c, p, pct = ina219_sensor.get_readings()

                # Push to live dashboard and logbook
                db.update_battery_data(v, c, p, pct)
                storage_mgr.log_battery_data(v, c, p, pct)
                local.log_battery(v, c, p, pct)

                last_battery_update = current_time
                
            # Small delay to prevent maxing out the Pi's CPU
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("Setting robot status to OFFLINE in Firebase...")
        db.set_connection_status("OFFLINE")
    finally:
        drive_motor.cleanup()
        steering_motor.cleanup()
        db.close_listener()
        scd41_sensor.cleanup()
        voc_sensor.cleanup()
        sdp810_sensor.cleanup()
        local.close()
        print("✅ Robot shut down cleanly")

if __name__ == "__main__":
    main()