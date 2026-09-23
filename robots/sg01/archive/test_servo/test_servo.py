import time
from board import SCL, SDA
import busio
from adafruit_pca9685 import PCA9685
from adafruit_motor import servo

i2c = busio.I2C(SCL, SDA)
pca = PCA9685(i2c)
pca.frequency = 50

# Define the servo on Channel 0
robot_servo = servo.Servo(pca.channels[0])

print("Moving servo to 0 degrees...")
robot_servo.angle = 0
time.sleep(2)

print("Moving servo to 180 degrees...")
robot_servo.angle = 180
time.sleep(2)

print("Returning to 90 degrees (center)...")
robot_servo.angle = 90

pca.deinit()