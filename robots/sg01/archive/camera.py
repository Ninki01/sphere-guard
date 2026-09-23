import os
import shutil

class CameraManager:
    def __init__(self, video_folder="/home/pi/videos/"):
        self.video_folder = video_folder
        self.is_recording = False
        self.current_file = None
        self.min_free_space_gb = 2.0
        
        # Ensure directory exists
        os.makedirs(self.video_folder, exist_ok=True)

    def _check_storage(self):
        """Emergency check to prevent Pi from crashing."""
        total, used, free = shutil.disk_usage("/")
        free_gb = free / (1024 ** 3)
        if free_gb < self.min_free_space_gb:
            print(f"⚠️ CRITICAL: Only {free_gb:.2f}GB left on SD card!")
            # Logic to delete oldest files could go here

    def start_recording(self, session_id):
        self._check_storage()
        self.current_file = os.path.join(self.video_folder, f"inspection_{session_id}.mp4")
        self.is_recording = True
        
        print(f"🎥 CAMERA: Starting recording to {self.current_file}")
        # TODO: Add your PiCamera2 or subprocess FFmpeg command here

    def stop_recording(self):
        if not self.is_recording:
            return None
            
        print("🛑 CAMERA: Stopping recording.")
        self.is_recording = False
        # TODO: Add command to safely stop the camera stream/recording here
        
        return self.current_file