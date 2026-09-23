import board
import adafruit_sht4x

class SHT45Sensor:
    def __init__(self, address=0x44):
        """Initializes the SHT45 Temperature & Humidity sensor."""
        self.connected = False
        try:
            i2c = board.I2C()
            self.sensor = adafruit_sht4x.SHT4x(i2c, address=address)
            
            # Run in high-precision mode without the built-in heater
            self.sensor.mode = adafruit_sht4x.Mode.NOHEAT_HIGHPRECISION
            
            self.connected = True
            print("✅ SHT45 connected successfully.")
        except Exception as e:
            print(f"⚠️ Warning: SHT45 not found at {hex(address)}. Running without it. Error: {e}")

    def get_readings(self):
        """Returns Temperature (C) and Humidity (%)."""
        if not self.connected:
            return 0.0, 0.0

        try:
            temp = round(self.sensor.temperature, 2)
            hum = round(self.sensor.relative_humidity, 2)
            return temp, hum
        except Exception as e:
            print(f"⚠️ SHT45 reading error: {e}")
            return 0.0, 0.0

    def cleanup(self):
        """Placeholder for cleanup to match other sensor structures."""
        pass