import firebase_admin
from firebase_admin import credentials, db
import time

class FirebaseManager:
    def __init__(self, cred_path, db_url):
        # Initialize Firebase Admin SDK
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {
            'databaseURL': db_url
        })
        self.ref = db.reference('/robots/sg01')

    # ---> ADDED steering_angle parameter here
    def update_status(self, run_mode, steering_angle):
        speed_names = {
            0: "stop", 1: "fwd_slow", 2: "fwd_med", 3: "fwd_fast",
            4: "rev_slow", 5: "rev_med", 6: "rev_fast"
        }
        
        # is_moving = run_mode > 0
        speed_name = speed_names.get(run_mode, "stop")
        
        # 1. Update motor/steering status (Optional, but good for logs)
        self.ref.child('control/status').update({
            'is_moving': run_mode > 0,
            'current_speed': speed_name,
            'current_steering_angle': steering_angle, 
            # 'last_update': int(time.time() * 1000) # Current time in ms
        })
        
        # 2. Update the connection status exactly where React expects it
        self.ref.child('system/connection').update({
            'status': "ONLINE",
            'rssi': -50, # Placeholder until you add actual WiFi strength reading
            'last_update': int(time.time() * 1000)
        })

    def reset_motor_command(self):
        # Reset using the React object format
        self.ref.child('control/movement').set({
            'direction': 'stop',
            'timestamp': int(time.time() * 1000)
        })

    def setup_listener(self, callback_function):
        # Listen for any changes in the spherical_robot node
        self.listener = self.ref.listen(callback_function)
        
    def close_listener(self):
        # Tell Firebase to close the connection gracefully
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
        
    def update_imu_data(self, pitch, roll, yaw):
        self.ref.child('telemetry/imu_bno055').update({
            'pitch': pitch,
            'roll': roll,
            'yaw': yaw,
            'last_updated': int(time.time() * 1000)
        })
        
    def update_bme280_data(self, temp, hum, press):
        """Pushes environmental data to the RTDB sensor node."""
        self.ref.child('sensors').update({
            'bme280_temperature_c': temp,
            'bme280_humidity_percent': hum,
            'bme280_pressure_hpa': press,
            'last_updated': int(time.time() * 1000)
        })
        
    def update_scd41_data(self, co2, temp, hum):
        """Pushes CO2 and environmental data to the RTDB sensor node."""
        self.ref.child('sensors').update({
            'scd41_co2_ppm': co2,
            'scd41_temperature_c': temp,
            'scd41_humidity_percent': hum,
            'last_updated': int(time.time() * 1000)
        })
        
    def update_sdp810_data(self, pressure_pa, temp):
        """Pushes SDP810 differential pressure and temperature to the RTDB sensor node."""
        self.ref.child('sensors').update({
            'sdp810_diff_pressure_pa': pressure_pa,
            'sdp810_temperature_c': temp,
            'last_updated': int(time.time() * 1000)
        })

    def update_sht45_data(self, temp, hum):
        """Pushes SHT45 temperature and humidity to the RTDB sensor node."""
        self.ref.child('sensors').update({
            'sht45_temperature_c': temp,
            'sht45_humidity_percent': hum,
            'last_updated': int(time.time() * 1000)
        })

    def update_voc_data(self, voc):
        """Pushes VOC gas concentration to the RTDB sensor node."""
        self.ref.child('sensors').update({
            'gas_ppm': voc,
            'last_updated': int(time.time() * 1000)
        })

    def update_battery_data(self, voltage, current, power, percentage):
        """Pushes power data to the RTDB."""
        self.ref.child('battery').update({
            'voltage_v': voltage,
            'current_ma': current,
            'power_mw': power,
            'percentage': percentage,
            'last_updated': int(time.time() * 1000)
        })