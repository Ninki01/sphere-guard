import os
import firebase_admin
from firebase_admin import credentials, db
import sys

# --- Configurations ---
# Ensure your serviceAccountKey.json is in the same folder as this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # This gets the src/ folder path
CRED_PATH = os.path.join(BASE_DIR, "..", "serviceAccountKey.json")
DB_URL = "https://sphere-guard-2025-default-rtdb.asia-southeast1.firebasedatabase.app/"

def init_firebase():
    try:
        cred = credentials.Certificate(CRED_PATH)
        firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})
        return db.reference('/spherical_robot')
    except Exception as e:
        print(f"Error connecting to Firebase: {e}")
        print("Did you put the serviceAccountKey.json in the same folder?")
        sys.exit(1)

def main():
    print("=== Sphere Guard: Dashboard Simulator ===")
    ref = init_firebase()
    print("Connected to Firebase! Ready to send commands.\n")

    while True:
        print("\n--- Command Menu ---")
        print("1. Set Drive Command (0=Stop, 1-3=CW, 4-6=CCW)")
        print("2. Set Steering Angle (0 to 180)")
        print("3. Set Max Speed Limit (1 to 3)")
        print("0. Exit Simulator")
        
        choice = input("Select an option (0-3): ").strip()

        if choice == '1':
            cmd = input("Enter drive command (0-6): ").strip()
            try:
                ref.child('motor_command').set(int(cmd))
                print(f"--> Sent Drive Command: {cmd}")
            except ValueError:
                print("Invalid input. Please enter a number.")
                
        elif choice == '2':
            angle = input("Enter steering angle (0-180): ").strip()
            try:
                ref.child('steering_command').set(int(angle))
                print(f"--> Sent Steering Angle: {angle}°")
            except ValueError:
                print("Invalid input. Please enter a number.")
                
        elif choice == '3':
            speed = input("Enter max speed limit (1-3): ").strip()
            try:
                ref.child('settings/max_speed').set(int(speed))
                print(f"--> Sent Max Speed: {speed}")
            except ValueError:
                print("Invalid input.")
                
        elif choice == '0':
            print("Exiting simulator...")
            break
        else:
            print("Invalid choice.")

if __name__ == "__main__":
    main()