import board
from adafruit_bme280 import basic as adafruit_bme280

class BME280Sensor:
    def __init__(self, address=0x77):
        """Initializes the BME280 Temperature, Humidity, and Pressure sensor."""
        self.connected = False
        try:
            i2c = board.I2C()
            # Note: Many generic BME280 boards use 0x76. If you get an error, change the address above!
            self.sensor = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=address)
            self.connected = True
            print(f"✅ BME280 connected successfully at {hex(address)}.")
        except Exception as e:
            print(f"⚠️ Warning: BME280 not found at {hex(address)}. Running without it. Error: {e}")

    def get_readings(self):
        """Returns Temperature (C), Humidity (%), and Pressure (hPa)."""
        if not self.connected:
            return 0.0, 0.0, 0.0

        try:
            temp = round(self.sensor.temperature, 2)
            hum = round(self.sensor.relative_humidity, 2)
            press = round(self.sensor.pressure, 2)
            return temp, hum, press
        except Exception as e:
            # Catches Errno 121 if the I2C wires get bumped while driving
            print(f"⚠️ BME280 reading error: {e}")
            return 0.0, 0.0, 0.0

    def cleanup(self):
        """Placeholder for cleanup to match the overall SG02 sensor architecture."""
        pass