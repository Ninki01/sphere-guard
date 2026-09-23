import board
import adafruit_scd4x

class SCD41Sensor:
    def __init__(self, address=0x62): 
        """Initializes the SCD41 True-CO2 sensor."""
        self.connected = False
        try:
            i2c = board.I2C()
            self.sensor = adafruit_scd4x.SCD4X(i2c, address=address)
            
            # Print serial number for hardware verification
            serial = [hex(i) for i in self.sensor.serial_number]
            print(f"✅ SCD41 (CO2) connected. Serial: {serial}. Warming up (~5s)...")
            
            # The sensor must be told to start its internal 5-second laser loop
            self.sensor.start_periodic_measurement()
            self.connected = True
            
        except Exception as e:
            print(f"⚠️ Warning: SCD41 not found. Running without it. Error: {e}")

    def get_readings(self):
        """Returns CO2 (ppm), Temperature (C), and Humidity (%)."""
        # Return -1 for CO2 so the main loop knows the data isn't ready/valid
        if not self.connected:
            return -1, 0.0, 0.0

        try:
            # We ONLY read the sensor if it has finished its 5-second breath
            if self.sensor.data_ready:
                co2 = self.sensor.CO2
                temp = round(self.sensor.temperature, 2)
                hum = round(self.sensor.relative_humidity, 2)
                return co2, temp, hum
            else:
                # If queried too fast, just return -1 and let the main loop skip this cycle
                return -1, 0.0, 0.0 
                
        except Exception as e:
            print(f"⚠️ SCD41 I2C reading error: {e}")
            return -1, 0.0, 0.0

    def cleanup(self):
        """CRITICAL: Stops the laser to prevent I2C lockups on the next boot."""
        if self.connected:
            try:
                self.sensor.stop_periodic_measurement()
                print("🛑 SCD41 internal measurement cycle stopped cleanly.")
            except Exception:
                pass