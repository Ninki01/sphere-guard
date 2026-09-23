import os
import time
import threading
from firebase_admin import storage, firestore
from datetime import datetime, timezone, timedelta

# Create a timezone object for Malaysia (UTC+8)
MYT = timezone(timedelta(hours=8))

class StorageManager:
    def __init__(self, bucket_name='sphere-guard-2025.appspot.com'):
        # NOTE: Firebase bucket names usually end in .appspot.com, not .firebasestorage.app
        # Make sure to check your Firebase Console -> Storage tab for the exact bucket URL!
        
        # 1. The "File Cabinet" (For MP4s)
        self.bucket = storage.bucket(bucket_name)
        
        # 2. The "Logbook" (For Latency & Telemetry)
        self.firestore_db = firestore.client()
        
        # Keep track of the React dashboard's active inspection
        self.active_session_id = None

    def set_active_session(self, session_id):
        """Links all subsequent uploads and logs to the React dashboard session."""
        self.active_session_id = session_id
        if session_id:
            print(f"📁 Storage Manager linked to session: {session_id}")

    # ==========================================
    # FIRESTORE: TEXT & LATENCY LOGGING
    # ==========================================
    def log_command(self, cmd_type, value, dash_to_pi_latency_ms, internal_exec_latency_ms):
        """Logs a drive or steering command and calculates network delay."""

        # 1. Determine exactly where to save this data
        if self.active_session_id:
            # Official run: Save inside the specific session's sub-folder
            session_ref = self.firestore_db.collection('inspection_sessions').document(self.active_session_id)
            doc_ref = session_ref.collection('command_logs').document()
        else:
            # Background run: Save to a master testing folder so no data is lost
            doc_ref = self.firestore_db.collection('background_latency_logs').document()
            
        # Generate readable local time in Malaysia
        local_pi_time = datetime.now(MYT).strftime("%Y-%m-%d %H:%M:%S")
        
        payload = {
            'command_type': cmd_type,      
            'value': value,
            'timing': {
                'local_pi_time': local_pi_time,
                'server_timestamp': firestore.SERVER_TIMESTAMP # Continuous server time
            },
            'latency': {
                'dash_to_pi_ms': dash_to_pi_latency_ms, 
                'pi_execution_delay_ms': internal_exec_latency_ms, # NEW: How fast the Pi processed the command
                'pi_to_firestore_log_ms': 0 # Placeholder, updated below
            },
            'session_id': self.active_session_id or 'none'
        }

        # Measure Pi -> Firestore Latency
        t_start = time.time()
        try:
            doc_ref.set(payload)
            t_end = time.time()
            
            pi_to_fs_latency_ms = round((t_end - t_start) * 1000, 2)
            doc_ref.update({'latency.pi_to_firestore_log_ms': pi_to_fs_latency_ms})
            
            print(f"📊 {cmd_type.upper()} logged | MYT: {local_pi_time} | Exec: {internal_exec_latency_ms}ms | FS_Delay: {pi_to_fs_latency_ms}ms")
        except Exception as e:
            print(f"❌ Failed to log to Firestore: {e}")
            
    def log_imu_data(self, pitch, roll, yaw):
        """Logs BNO055 orientation data to Firestore for analysis."""
        if self.active_session_id:
            session_ref = self.firestore_db.collection('inspection_sessions').document(self.active_session_id)
            doc_ref = session_ref.collection('imu_logs').document()
        else:
            doc_ref = self.firestore_db.collection('background_imu_logs').document()

        local_pi_time = datetime.now(MYT).strftime("%Y-%m-%d %H:%M:%S")

        payload = {
            'pitch': pitch,
            'roll': roll,
            'yaw': yaw,
            'timing': {
                'local_pi_time': local_pi_time,
                'server_timestamp': firestore.SERVER_TIMESTAMP
            },
            'session_id': self.active_session_id or 'none'
        }

        try:
            doc_ref.set(payload)
        except Exception as e:
            print(f"❌ Failed to log IMU to Firestore: {e}")

    def log_bme280_data(self, temp, hum, press):
        """Logs environmental data to Firestore and calculates network delay."""
        
        # 1. Determine exactly where to save this data
        if self.active_session_id:
            session_ref = self.firestore_db.collection('inspection_sessions').document(self.active_session_id)
            doc_ref = session_ref.collection('sensors').document() # Saved under 'sensors'
        else:
            doc_ref = self.firestore_db.collection('background_sensor_logs').document()
            
        local_pi_time = datetime.now(MYT).strftime("%Y-%m-%d %H:%M:%S")

        payload = {
            'bme280_temperature_c': temp,
            'bme280_humidity_percent': hum,
            'bme280_pressure_hpa': press,
            'timing': {
                'local_pi_time': local_pi_time,
                'server_timestamp': firestore.SERVER_TIMESTAMP 
            },
            'latency': {
                'pi_to_firestore_log_ms': 0 # Placeholder
            },
            'session_id': self.active_session_id or 'none'
        }

        # 2. Measure Pi -> Firestore Latency
        t_start = time.time()
        try:
            doc_ref.set(payload)
            t_end = time.time()
            
            pi_to_fs_latency_ms = round((t_end - t_start) * 1000, 2)
            doc_ref.update({'latency.pi_to_firestore_log_ms': pi_to_fs_latency_ms})
            
            # Optional: Uncomment to see it in terminal
            # print(f"☁️ Env Logged | MYT: {local_pi_time} | FS_Delay: {pi_to_fs_latency_ms}ms")
        except Exception as e:
            print(f"❌ Failed to log BME280 to Firestore: {e}")
            
    def log_scd41_data(self, co2, temp, hum):
        """Logs SCD41 data to Firestore and calculates network delay."""
        
        if self.active_session_id:
            session_ref = self.firestore_db.collection('inspection_sessions').document(self.active_session_id)
            doc_ref = session_ref.collection('sensors').document() 
        else:
            doc_ref = self.firestore_db.collection('background_sensor_logs').document()
            
        local_pi_time = datetime.now(MYT).strftime("%Y-%m-%d %H:%M:%S")

        payload = {
            'scd41_co2_ppm': co2,
            'scd41_temperature_c': temp,
            'scd41_humidity_percent': hum,
            'timing': {
                'local_pi_time': local_pi_time,
                'server_timestamp': firestore.SERVER_TIMESTAMP 
            },
            'latency': {
                'pi_to_firestore_log_ms': 0 
            },
            'session_id': self.active_session_id or 'none'
        }

        t_start = time.time()
        try:
            doc_ref.set(payload)
            t_end = time.time()
            
            pi_to_fs_latency_ms = round((t_end - t_start) * 1000, 2)
            doc_ref.update({'latency.pi_to_firestore_log_ms': pi_to_fs_latency_ms})
            
        except Exception as e:
            print(f"❌ Failed to log SCD41 to Firestore: {e}")
            
    def log_sdp810_data(self, pressure_pa, temp):
        """Logs SDP810 differential pressure and temperature to Firestore."""
        if self.active_session_id:
            session_ref = self.firestore_db.collection('inspection_sessions').document(self.active_session_id)
            doc_ref = session_ref.collection('sensors').document()
        else:
            doc_ref = self.firestore_db.collection('background_sensor_logs').document()

        local_pi_time = datetime.now(MYT).strftime("%Y-%m-%d %H:%M:%S")

        payload = {
            'sdp810_diff_pressure_pa': pressure_pa,
            'sdp810_temperature_c': temp,
            'timing': {
                'local_pi_time': local_pi_time,
                'server_timestamp': firestore.SERVER_TIMESTAMP
            },
            'session_id': self.active_session_id or 'none'
        }

        try:
            doc_ref.set(payload)
        except Exception as e:
            print(f"❌ Failed to log SDP810 to Firestore: {e}")

    def log_sht45_data(self, temp, hum):
        """Logs SHT45 temperature and humidity to Firestore."""
        if self.active_session_id:
            session_ref = self.firestore_db.collection('inspection_sessions').document(self.active_session_id)
            doc_ref = session_ref.collection('sensors').document()
        else:
            doc_ref = self.firestore_db.collection('background_sensor_logs').document()

        local_pi_time = datetime.now(MYT).strftime("%Y-%m-%d %H:%M:%S")

        payload = {
            'sht45_temperature_c': temp,
            'sht45_humidity_percent': hum,
            'timing': {
                'local_pi_time': local_pi_time,
                'server_timestamp': firestore.SERVER_TIMESTAMP
            },
            'session_id': self.active_session_id or 'none'
        }

        try:
            doc_ref.set(payload)
        except Exception as e:
            print(f"❌ Failed to log SHT45 to Firestore: {e}")

    def log_voc_data(self, voc):
        """Logs VOC gas concentration to Firestore."""
        if self.active_session_id:
            session_ref = self.firestore_db.collection('inspection_sessions').document(self.active_session_id)
            doc_ref = session_ref.collection('sensors').document()
        else:
            doc_ref = self.firestore_db.collection('background_sensor_logs').document()

        local_pi_time = datetime.now(MYT).strftime("%Y-%m-%d %H:%M:%S")

        payload = {
            'gas_ppm': voc,
            'timing': {
                'local_pi_time': local_pi_time,
                'server_timestamp': firestore.SERVER_TIMESTAMP
            },
            'session_id': self.active_session_id or 'none'
        }

        try:
            doc_ref.set(payload)
        except Exception as e:
            print(f"❌ Failed to log VOC to Firestore: {e}")

    def log_battery_data(self, voltage, current, power, percentage):
        """Logs battery consumption to Firestore."""
        if self.active_session_id:
            session_ref = self.firestore_db.collection('inspection_sessions').document(self.active_session_id)
            doc_ref = session_ref.collection('power_logs').document() 
        else:
            doc_ref = self.firestore_db.collection('background_power_logs').document()
            
        local_pi_time = datetime.now(MYT).strftime("%Y-%m-%d %H:%M:%S")

        payload = {
            'voltage_v': voltage,
            'current_ma': current,
            'power_mw': power,
            'percentage': percentage,
            'timing': {
                'local_pi_time': local_pi_time,
                'server_timestamp': firestore.SERVER_TIMESTAMP 
            },
            'session_id': self.active_session_id or 'none'
        }

        try:
            doc_ref.set(payload)
        except Exception as e:
            print(f"❌ Failed to log Battery to Firestore: {e}")


    # ==========================================
    # FIREBASE STORAGE: VIDEO FILE HANDLING
    # ==========================================
    def upload_and_cleanup_async(self, filepath):
        """Runs the upload in the background so the robot can keep driving."""
        if not self.active_session_id:
            print("⚠️ STORAGE: No active session. Video will not be uploaded.")
            return

        # Pass the CURRENT active session into the thread
        thread = threading.Thread(
            target=self._upload_routine, 
            args=(self.active_session_id, filepath)
        )
        thread.start()

    def _upload_routine(self, session_id, filepath):
        if not filepath or not os.path.exists(filepath):
            print("❌ STORAGE: File not found for upload.")
            return

        filename = os.path.basename(filepath)
        print(f"☁️ STORAGE: Uploading {filename}...")
        
        try:
            # 1. Upload the MP4 to the File Cabinet
            blob = self.bucket.blob(f"inspection_footage/{session_id}/{filename}")
            blob.upload_from_filename(filepath)
            blob.make_public()
            video_url = blob.public_url
            print("✅ STORAGE: Upload complete!")

            # 2. Write the resulting URL into the Logbook
            doc_ref = self.firestore_db.collection('inspection_sessions').document(session_id)
            doc_ref.set({'video_url': video_url}, merge=True)

            # 3. Delete the local file to save SD card space
            os.remove(filepath)
            print(f"🗑️ STORAGE: Cleaned up local file {filename}")

        except Exception as e:
            print(f"❌ STORAGE: Upload failed: {e}")