"""
BME280 environmental sensor (temperature, humidity, pressure) — FIXED sensor.
"""

import board
from adafruit_bme280 import basic as adafruit_bme280

from shared.sensors.base import Sensor


class BME280(Sensor):
    name     = "BME280"
    addr     = 0x77
    is_fixed = True

    def __init__(self):
        self._sensor = None

    def probe(self, bus) -> bool:
        if bus is None:
            return False
        try:
            bus.read_byte(self.addr)
            return True
        except Exception:
            return False

    def init(self, cfg) -> None:
        i2c = board.I2C()
        self._sensor = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=self.addr)

    def cols(self) -> list:
        return ["bme_temp", "bme_hum", "bme_press"]

    def read(self) -> dict:
        if self._sensor is None:
            return {c: "" for c in self.cols()}
        # A hardware/I2C failure must propagate so the sampler's record_failure()
        # marks the sensor offline and attempt_reconnect() can re-initialise it.
        return {
            "bme_temp":  round(self._sensor.temperature,       1),
            "bme_hum":   round(self._sensor.relative_humidity, 1),
            "bme_press": round(self._sensor.pressure,          1),
        }
