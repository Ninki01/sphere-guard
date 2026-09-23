import time
from adafruit_servokit import ServoKit
import board
import busio

# ✅ Force reset the PCA9685 before initializing
def reset_pca9685():
    i2c = busio.I2C(board.SCL, board.SDA)
    # Wait for I2C to be ready
    while not i2c.try_lock():
        pass
    try:
        # General call reset — resets ALL I2C devices on the bus
        i2c.writeto(0x00, bytes([0x06]))
        print("✅ PCA9685 reset successfully")
    except Exception as e:
        print(f"⚠️ Reset warning: {e}")
    finally:
        i2c.unlock()
        i2c.deinit()
    
    time.sleep(0.1)  # Give chip time to restart

# Call this FIRST before anything else
reset_pca9685()

# Now safe to initialize
kit = ServoKit(channels=16)

# Setup Servos
# Channel 1: Steering (Standard)
# Channel 0: Drive (Continuous)
main_servo = kit.servo[1]
drive_servo = kit.continuous_servo[0]

# Calibration for both
main_servo.set_pulse_width_range(500, 2500)
drive_servo.set_pulse_width_range(500, 2500)

def set_motor_speed(run_mode):
    """Maps run modes (0-6) to throttle values (-1.0 to 1.0)"""
    if run_mode == 0:
        drive_servo.throttle = 0.0
        return "STOPPED"
    elif run_mode == 1: 
        drive_servo.throttle = 0.30
        return "FORWARD (Slow)"
    elif run_mode == 2: 
        drive_servo.throttle = 0.60
        return "FORWARD (Medium)"
    elif run_mode == 3: 
        drive_servo.throttle = 0.90
        return "FORWARD (Fast)"
    elif run_mode == 4: 
        drive_servo.throttle = -0.30
        return "REVERSE (Slow)"
    elif run_mode == 5: 
        drive_servo.throttle = -0.60
        return "REVERSE (Medium)"
    elif run_mode == 6: 
        drive_servo.throttle = -0.90
        return "REVERSE (Fast)"
    else:
        drive_servo.throttle = 0.0
        return "Invalid mode. STOPPED."

def combined_test():
    print("--- Combined PTK7465MG & SPT5535LV Test ---")
    print("Steering: 0-180 | Drive Modes: 0-6")
    print("Enter 'q' to quit.")

    while True:
        print("\n" + "="*30)
        u_input = input("Enter [Angle],[Mode] (e.g. 90,1) or 'q': ")
        
        if u_input.lower() == 'q':
            print("Exiting and resetting...")
            main_servo.angle = 90
            drive_servo.throttle = 0.0
            break
            
        try:
            # Memisahkan input menggunakan koma
            parts = u_input.split(',')
            angle = float(parts[0])
            mode = int(parts[1])
            
            # Update Steering
            if 0 <= angle <= 180:
                main_servo.angle = angle
                print(f"Steering: {angle}°")
            else:
                print("Error: Angle must be 0-180")

            # Update Drive
            status = set_motor_speed(mode)
            print(f"Drive Status: {status}")
                
        except (ValueError, IndexError):
            print("Invalid format. Please use: angle,mode (e.g. 90,0)")

if __name__ == "__main__":
    try:
        combined_test()
    except KeyboardInterrupt:
        print("\nEmergency Stop...")
        main_servo.angle = 90
        drive_servo.throttle = 0.050