import os
import threading
from firebase_admin import storage, firestore 

class StorageManager:
    def __init__(self, bucket_name='sphere-guard-2025.firebasestorage.app'):
        self.bucket = storage.bucket(bucket_name)
        self.firestore_db = firestore.client()

    def upload_and_cleanup_async(self, session_id, filepath):
        """Runs the upload in the background so the robot can keep driving."""
        thread = threading.Thread(
            target=self._upload_routine, 
            args=(session_id, filepath)
        )
        thread.start()

    def _upload_routine(self, session_id, filepath):
        if not filepath or not os.path.exists(filepath):
            print("❌ STORAGE: File not found for upload.")
            return

        filename = os.path.basename(filepath)
        print(f"☁️ STORAGE: Uploading {filename}...")
        
        try:
            # 1. Upload the MP4
            blob = self.bucket.blob(f"inspection_footage/{filename}")
            blob.upload_from_filename(filepath)
            blob.make_public()
            video_url = blob.public_url
            print("✅ STORAGE: Upload complete!")

            # 2. Link URL to the Firestore session
            doc_ref = self.firestore_db.collection('inspection_sessions').doc(session_id)
            doc_ref.set({'video_url': video_url}, merge=True)

            # 3. Delete the local file to save SD card space
            os.remove(filepath)
            print(f"🗑️ STORAGE: Cleaned up local file {filename}")

        except Exception as e:
            print(f"❌ STORAGE: Upload failed: {e}")