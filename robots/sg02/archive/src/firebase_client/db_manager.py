import firebase_admin
from firebase_admin import credentials, db
import time

class FirebaseManager:
    def __init__(self, cred_path, db_url, robot_id="sg02"):
        """Initialize Firebase Admin SDK dynamically based on robot_id"""
        cred = credentials.Certificate(cred_path)
        
        # Prevent re-initialization error if the script restarts quickly
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {'databaseURL': db_url})
            
        # Dynamically point to /robots/sg02 (or whatever ID is passed)
        self.ref = db.reference(f'/robots/{robot_id}')
        print(f"[{robot_id.upper()}] Firebase Client Initialized.")

    # --- LISTENER & SYSTEM STATUS ---
    def setup_listener(self, callback_function):
        """Listen for any changes in the robot node (like Session IDs)"""
        self.listener = self.ref.listen(callback_function)
        
    def close_listener(self):
        """Tell Firebase to close the connection gracefully"""
        if hasattr(self, 'listener'):
            self.listener.close()
            
    def set_connection_status(self, status):
        """Updates the robot's online/offline status for the React dashboard."""
        try:
            self.ref.child('system/connection').update({
                'status': status,
                'last_update': int(time.time() * 1000)
            })
            print(f"📡 System status set to: {status}")
        except Exception as e:
            print(f"❌ Failed to update connection status: {e}")

    # --- SENSOR TELEMETRY UPDATES ---
    def update_fast_telemetry(self, pitch, roll, yaw, pi_temp):
        """Pushes high-frequency data (IMU and CPU Temp) to RTDB."""
        updates = {
            'telemetry/imu_bno055/pitch': pitch,
            'telemetry/imu_bno055/roll': roll,
            'telemetry/imu_bno055/yaw': yaw,
            'system/temperature/mcu': pi_temp,
            'telemetry/last_updated': int(time.time() * 1000)
        }
        self.ref.update(updates)

    def update_environment_data(self, bme_t, bme_h, bme_p, sht_t, sht_h, dp_pressure, co2, scd_t, scd_h, voc_ppm):
        """Pushes lower-frequency environmental sensor data to RTDB."""
        updates = {
            'sensors/bme280_temperature_c': bme_t,
            'sensors/bme280_humidity_percent': bme_h,
            'sensors/bme280_pressure_hpa': bme_p,
            'sensors/sht45_temperature_c': sht_t,
            'sensors/sht45_humidity_percent': sht_h,
            'sensors/sdp810_differential_pa': dp_pressure,
            'sensors/scd41_co2_ppm': co2,
            'sensors/scd41_temperature_c': scd_t,
            'sensors/scd41_humidity_percent': scd_h,
            'sensors/voc_ppm': voc_ppm,
            'sensors/last_updated': int(time.time() * 1000)
        }
        self.ref.update(updates)
        
    def update_battery_data(self, voltage, current, power, percentage):
        """Pushes INA219 power data to the RTDB."""
        self.ref.child('battery').update({
            'voltage_v': voltage,
            'current_ma': current,
            'power_mw': power,
            'percentage': percentage,
            'last_updated': int(time.time() * 1000)
        })