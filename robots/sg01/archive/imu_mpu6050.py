from mpu6050 import mpu6050
import math

class IMUSensor:
    def __init__(self, address=0x68):
        self.connected = False
        try:
            # Try to connect to the sensor
            self.sensor = mpu6050(address)
            self.connected = True
            print("IMU connected successfully.")
        except Exception as e:
            # If it fails (e.g., unplugged), catch the error and print a warning
            print(f"Warning: IMU not found at address {hex(address)}. Running without IMU. Error: {e}")

    def get_angles(self):
        """Returns the calculated Pitch and Roll in degrees."""
        # If the sensor never connected, just return 0.0 so the main script doesn't crash
        if not self.connected:
            return 0.0, 0.0

        try:
            accel_data = self.sensor.get_accel_data()
            x = accel_data['x']
            y = accel_data['y']
            z = accel_data['z']

            # Calculate Pitch and Roll
            pitch = math.degrees(math.atan2(y, math.sqrt(x*x + z*z)))
            roll  = math.degrees(math.atan2(-x, math.sqrt(y*y + z*z)))

            return round(pitch, 2), round(roll, 2)
        except Exception as e:
            print(f"IMU reading error: {e}")
            return 0.0, 0.0

    def get_raw_gyro(self):
        """Returns raw gyroscope data if you need rotation speed later."""
        if not self.connected:
            return {'x': 0, 'y': 0, 'z': 0}
            
        try:
            return self.sensor.get_gyro_data()
        except Exception:
            return {'x': 0, 'y': 0, 'z': 0}