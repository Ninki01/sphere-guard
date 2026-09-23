from adafruit_servokit import ServoKit
import sys
import board
import busio
import time  

PULSE_MIN = 500
PULSE_MAX = 2500

def reset_pca9685():
    i2c = busio.I2C(board.SCL, board.SDA)
    while not i2c.try_lock():
        pass
    try:
        i2c.writeto(0x00, bytes([0x06]))
        print("✅ PCA9685 reset")
    except Exception as e:
        print(f"⚠️ Reset warning: {e}")
    finally:
        i2c.unlock()
        i2c.deinit()  # ✅ released immediately after reset
    time.sleep(0.1)

# ✅ Reset first, then initialize ONCE with error handling
reset_pca9685()

try:
    kit = ServoKit(channels=16)
    print("✅ PCA9685 initialized successfully")
except Exception as e:
    print(f"❌ CRITICAL: PCA9685 hardware not found: {e}")
    print("Check I2C wiring and run: sudo i2cdetect -y 1")
    sys.exit(1)

class DriveServo:
    def __init__(self, channel=0):
        self.channel = channel
        self.servo = None
        if kit:
            self.servo = kit.continuous_servo[self.channel]
            self.servo.set_pulse_width_range(PULSE_MIN, PULSE_MAX)
            self.stop()

    def drive(self, run_mode):
        if not self.servo: return
        try:
            throttle_map = {
                0: 0.0,
                1: 0.30, 2: 0.60, 3: 0.90,
                4: -0.30, 5: -0.60, 6: -0.90
            }
            value = throttle_map.get(run_mode, 0.0)
            print(f"🔧 Setting throttle to: {value}")  # debug code temp
            self.servo.throttle = value
            print(f"✅ Throttle set successfully: {self.servo.throttle}")  # debug code temp
        except Exception as e:
            print(f"❌ Drive motor error: {e}")

    def stop(self):
        if self.servo:
            self.servo.throttle = 0.0

    def cleanup(self):
        print("Parking drive motor safely...")
        self.stop()
        if self.servo:
            self.servo.throttle = None  # ✅ stops PWM signal


class SteeringServo:
    def __init__(self, channel=1):
        self.channel = channel
        self.servo = None
        if kit:
            self.servo = kit.servo[self.channel]
            self.servo.set_pulse_width_range(PULSE_MIN, PULSE_MAX)
            self.set_angle(90)

    def set_angle(self, angle):
        if not self.servo: return
        try:
            safe_angle = max(0, min(180, float(angle)))
            self.servo.angle = safe_angle
        except Exception as e:
            print(f"❌ Steering motor error: {e}")

    def cleanup(self):
        print("Centering steering motor safely...")
        self.set_angle(90)
        self.servo.angle = None  # ✅ stops PWM signal 