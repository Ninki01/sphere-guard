# Servo: SPT5535LV - Continuous Rotation
# Drive Servo for basic forward/reverse testing
# library: adafruit-circuitpython-servokit



import time
from adafruit_servokit import ServoKit

kit = ServoKit(channels=16)

# Setup the continuous servo on Channel 0
drive_servo = kit.continuous_servo[0]

# Calibrate for the SPT5535LV High-Torque Servo
drive_servo.set_pulse_width_range(500, 2500)

# Start: motor stopped
drive_servo.throttle = 0.0

def set_motor_speed(run_mode):
    """Maps run modes (0-6) to throttle values (-1.0 to 1.0)"""
    if run_mode == 0:
        drive_servo.throttle = 0.0
        print("Status: STOPPED")
        
    # Forward
    elif run_mode == 1: 
        drive_servo.throttle = 0.30
        print("Status: FORWARD (Slow)")
    elif run_mode == 2: 
        drive_servo.throttle = 0.60
        print("Status: FORWARD (Medium)")
    elif run_mode == 3: 
        drive_servo.throttle = 0.90
        print("Status: FORWARD (Fast)")
        
    # Reverse
    elif run_mode == 4: 
        drive_servo.throttle = -0.30
        print("Status: REVERSE (Slow)")
    elif run_mode == 5: 
        drive_servo.throttle = -0.60
        print("Status: REVERSE (Medium)")
    elif run_mode == 6: 
        drive_servo.throttle = -0.90
        print("Status: REVERSE (Fast)")
        
    else:
        print("Invalid mode. Defaulting to STOP.")
        drive_servo.throttle = 0.0

def main():
    print("--- SPT5535LV Basic Drive Test ---")
    print("Modes: 0 (Stop)")
    print("Forward: 1 (Slow), 2 (Medium), 3 (Fast)")
    print("Reverse: 4 (Slow), 5 (Medium), 6 (Fast)")
    print("Enter 'q' to quit.")

    while True:
        user_input = input("\nEnter Run Mode (0-6): ")
        
        if user_input.lower() == 'q':
            print("Stopping motor and exiting...")
            drive_servo.throttle = 0.0
            break
            
        try:
            mode = int(user_input)
            set_motor_speed(mode)
        except ValueError:
            print("Please enter a valid number (0-6) or 'q'.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Safety catch: Stop the motor if you press Ctrl+C
        drive_servo.throttle = 0.0
        print("\nEmergency Stop Triggered.")