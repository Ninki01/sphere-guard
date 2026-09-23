import board
import adafruit_bno055

class IMUBNO055:
    def __init__(self, address=0x28):
        self.connected = False
        try:
            i2c = board.I2C()
            self.sensor = adafruit_bno055.BNO055_I2C(i2c, address=address)
            self.connected = True
            print(f"✅ BNO055 connected successfully at {hex(address)}.")
        except Exception as e:
            print(f"⚠️ Warning: BNO055 not found at {hex(address)}. Running without it. Error: {e}")

    def get_angles(self):
        """Returns Pitch, Roll, Yaw (heading) in degrees from the BNO055 fusion engine."""
        if not self.connected:
            return 0.0, 0.0, 0.0

        try:
            euler = self.sensor.euler
            if euler is None or any(v is None for v in euler):
                return 0.0, 0.0, 0.0
            # BNO055 euler order: (heading, roll, pitch)
            heading, roll, pitch = euler
            return round(pitch, 2), round(roll, 2), round(heading, 2)
        except Exception as e:
            print(f"⚠️ BNO055 reading error: {e}")
            return 0.0, 0.0, 0.0

    def get_calibration_status(self):
        """Returns (sys, gyro, accel, mag) calibration status (0=uncal, 3=fully cal)."""
        if not self.connected:
            return 0, 0, 0, 0

        try:
            return self.sensor.calibration_status
        except Exception:
            return 0, 0, 0, 0

    def cleanup(self):
        pass
