import os
import sys # <-- Import sys to allow exiting on failure
import time
from pathlib import Path
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db
import RPi.GPIO as GPIO

# --- PATH CONFIGURATION ---
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"
JSON_KEY_PATH = BASE_DIR / "serviceAccountKey.json"
load_dotenv(dotenv_path=ENV_PATH)
# 1. Load Credentials
load_dotenv(dotenv_path=ENV_PATH)
DB_URL = os.getenv(
    'FIREBASE_URL', 
    'https://sphere-guard-2025-default-rtdb.asia-southeast1.firebasedatabase.app/'
) 

# 2. Initialize Firebase
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(JSON_KEY_PATH))
        firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})
    print("✅ Firebase Connected")
except Exception as e:
    print(f"❌ Firebase Connection Failed: {e}")
    sys.exit(1) # <-- Added this: stop the script if Firebase doesn't connect

# 3. Setup GPIO (Testing an LED or Pin)
TEST_PIN = 18 
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(TEST_PIN, GPIO.OUT)

try:
    print("🤖 Robot Brain Online. Sending heartbeat to Firebase...")
    while True:
        # Toggle Hardware
        GPIO.output(TEST_PIN, GPIO.HIGH)
        
        # Update Firebase Status
        ref = db.reference('robot_status')
        ref.update({
            'heartbeat': time.time(),
            'status': 'active',
            'location': 'Selangor/KL'
        })
        
        print(f"Heartbeat sent at {time.ctime()}...")
        time.sleep(5)
        GPIO.output(TEST_PIN, GPIO.LOW)
        time.sleep(5)

except KeyboardInterrupt:
    print("Cleanup and shutting down.")
    GPIO.cleanup()