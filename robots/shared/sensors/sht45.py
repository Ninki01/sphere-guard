"""
SHT45 high-precision temperature & humidity sensor — SWAPPABLE sensor.
"""

import board
import adafruit_sht4x

from shared.sensors.base import Sensor


class SHT45(Sensor):
    name     = "SHT45"
    addr     = 0x44
    is_fixed = False

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
        self._sensor = adafruit_sht4x.SHT4x(i2c, address=self.addr)
        self._sensor.mode = adafruit_sht4x.Mode.NOHEAT_HIGHPRECISION

    def cols(self) -> list:
        return ["sht_temp", "sht_hum"]

    def read(self) -> dict:
        if self._sensor is None:
            return {c: "" for c in self.cols()}
        # A hardware/I2C failure must propagate so the sampler's record_failure()
        # marks the sensor offline and attempt_reconnect() can re-initialise it.
        return {
            "sht_temp": round(self._sensor.temperature,       2),
            "sht_hum":  round(self._sensor.relative_humidity, 2),
        }
