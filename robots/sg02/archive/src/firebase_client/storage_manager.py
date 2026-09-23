import os
import time
import threading
from firebase_admin import storage, firestore
from datetime import datetime, timezone, timedelta

# Create a timezone object for Malaysia (UTC+8)
MYT = timezone(timedelta(hours=8))

class StorageManager:
    def __init__(self, bucket_name='sphere-guard-2025.appspot.com', robot_id="sg02"):
        self.robot_id = robot_id
        
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
    # FIRESTORE: SENSOR & LATENCY LOGGING
    # ==========================================
    def log_environment_data(self, bme_t, bme_h, bme_p, sht_t, sht_h, dp_pressure, co2, scd_t, scd_h, voc_ppm):
        """Logs all SG02 environment sensors to Firestore and measures Pi upload latency."""
        
        local_pi_time = datetime.now(MYT).strftime("%Y-%m-%d %H:%M:%S")
        dispatch_time_ms = int(time.time() * 1000)

        if self.active_session_id:
            session_ref = self.firestore_db.collection('inspection_sessions').document(self.active_session_id)
            doc_ref = session_ref.collection('sensor_data_collection').document() 
        else:
            day_folder = datetime.now(MYT).strftime("%Y-%m-%d")
            time_doc = datetime.now(MYT).strftime("%H-%M-%S")
            doc_ref = self.firestore_db.collection('background_sensor_sg02_logs').document(day_folder).collection('readings').document(time_doc)

        payload = {
            'robot_id': self.robot_id,
            'bme280': {'temp_c': bme_t, 'hum_pct': bme_h, 'press_hpa': bme_p},
            'sht45': {'temp_c': sht_t, 'hum_pct': sht_h},
            'sdp810': {'diff_pressure_pa': dp_pressure},
            'scd41': {'co2_ppm': co2, 'temp_c': scd_t, 'hum_pct': scd_h},
            'ps1_voc': {'voc_ppm': voc_ppm}, 
            'timing': {
                'local_pi_time': local_pi_time,
                'dispatch_timestamp_ms': dispatch_time_ms, 
                'server_timestamp': firestore.SERVER_TIMESTAMP 
            },
            'latency': {
                'pi_to_firestore_log_ms': 0 
            },
            'session_id': self.active_session_id or 'IDLE_BACKGROUND_MODE'
        }

        t_start = time.time()
        try:
            doc_ref.set(payload)
            t_end = time.time()
            pi_to_fs_latency_ms = round((t_end - t_start) * 1000, 2)
            doc_ref.update({'latency.pi_to_firestore_log_ms': pi_to_fs_latency_ms})
        except Exception as e:
            print(f"❌ Failed to log environment data to Firestore: {e}")
            
            
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