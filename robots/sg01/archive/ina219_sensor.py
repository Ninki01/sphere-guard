import board
from adafruit_ina219 import INA219

class INA219Sensor:
    def __init__(self, address=0x40): # 0x40 is default, but check i2cdetect!
        self.connected = False
        try:
            i2c = board.I2C()
            self.sensor = INA219(i2c, addr=address)
            self.connected = True
            print("✅ INA219 (Power Monitor) connected successfully.")
        except Exception as e:
            print(f"⚠️ Warning: INA219 not found. Running without it. Error: {e}")

    def calculate_percentage(self, voltage):
        """
        Maps the raw voltage of a 2S 7.4V LiPo to a 0-100% scale.
        """
        max_v = 8.4 # 100% Fully Charged
        min_v = 6.6 # 0% Safe Dead (Do not drain below this!)
        
        if voltage >= max_v:
            return 100.0
        elif voltage <= min_v:
            return 0.0
        else:
            # Calculate the percentage based on the safe discharge window
            percent = ((voltage - min_v) / (max_v - min_v)) * 100
            return round(percent, 1)

    def get_readings(self):
        """Returns Voltage (V), Current (mA), Power (mW), and calculated %."""
        if not self.connected:
            return 0.0, 0.0, 0.0, 0.0

        try:
            voltage = round(self.sensor.bus_voltage, 2)
            current = round(self.sensor.current, 2) # in milliamps
            power = round(self.sensor.power, 2)     # in milliwatts
            percentage = self.calculate_percentage(voltage)
            
            return voltage, current, power, percentage
        except Exception as e:
            print(f"⚠️ INA219 reading error: {e}")
            return 0.0, 0.0, 0.0, 0.0