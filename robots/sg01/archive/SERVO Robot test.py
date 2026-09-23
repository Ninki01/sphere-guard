from adafruit_servokit import ServoKit
import time

kit = ServoKit(channels=16)

PITCH_CH = 0
YAW_CH = 1

kit.servo[PITCH_CH].angle = 90
kit.servo[YAW_CH].angle = 90

time.sleep(1)

kit.servo[PITCH_CH].angle = 60
time.sleep(1)

kit.servo[PITCH_CH].angle = 120
time.sleep(1)

kit.servo[PITCH_CH].angle = 90
kit.servo[YAW_CH].angle = 90

print("Servo PCA test done")