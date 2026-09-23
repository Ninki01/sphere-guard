
# Servo: PTK7465MG
# library: adafruit-circuitpython-servokit

# check i2cdetect for the correct address (default is 0x40 for PCA9685)
# run: i2cdetect -y 1

# activate conda env run:
# conda activate robot-env
# python test_PTK7465MG.py

# tolong checkkan:
# Center angle:
# Max Left angle:
# Max Right angle:

import time
from adafruit_servokit import ServoKit

# Initialize the PCA9685
kit = ServoKit(channels=16)

# Steering servo Channel: sekarang 1
main_servo = kit.servo[1]

def manual_test():
    print("Enter an angle between 0 and 180 (or 'q' to quit)")

    # main_servo.set_pulse_width_range(500, 2500)

    while True:
        user_input = input("\nTarget Angle: ")
        
        if user_input.lower() == 'q':
            print("Exiting and centering servo...")
            main_servo.angle = 90 # assume
            break
            
        try:
            angle = float(user_input)
            
            if 0 <= angle <= 180:
                print(f"Moving to {angle}°...")
                main_servo.angle = angle
            else:
                print("Error: Please enter a value between 0 and 180.")
                
        except ValueError:
            print("Invalid input. Please enter a number or 'q'.")

if __name__ == "__main__":
    try:
        manual_test()
    except KeyboardInterrupt:
        print("\nStopping...")