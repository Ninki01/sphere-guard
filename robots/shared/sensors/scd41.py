# """
# SCD41 True-CO2 sensor (photoacoustic NDIR) — SWAPPABLE sensor.

# Requires ~5s warmup after init(); produces one reading every 5s.
# Returns -1 for CO2 when data is not yet ready.
# CRITICAL: cleanup() must be called on shutdown to stop the laser and
# prevent I2C lockup on the next boot.
# """

# import board
# import adafruit_scd4x

# from shared.sensors.base import Sensor


# class SCD41(Sensor):
#     name     = "SCD41"
#     addr     = 0x62
#     is_fixed = False

#     def __init__(self):
#         self._sensor = None

#     def probe(self, bus) -> bool:
#         if bus is None:
#             return False
#         try:
#             bus.read_byte(self.addr)
#             return True
#         except Exception:
#             return False

#     def init(self, cfg) -> None:
#         i2c = board.I2C()
#         self._sensor = adafruit_scd4x.SCD4X(i2c, address=self.addr)
#         self._sensor.start_periodic_measurement()

#     def cols(self) -> list:
#         return ["co2", "scd_temp", "scd_hum"]

#     def read(self) -> dict:
#         if self._sensor is None:
#             return {c: "" for c in self.cols()}
#         try:
#             if not self._sensor.data_ready:
#                 return {c: "" for c in self.cols()}
#             return {
#                 "co2":      self._sensor.CO2,
#                 "scd_temp": round(self._sensor.temperature,       2),
#                 "scd_hum":  round(self._sensor.relative_humidity, 2),
#             }
#         except Exception:
#             return {c: "" for c in self.cols()}

#     def cleanup(self) -> None:
#         if self._sensor is not None:
#             try:
#                 self._sensor.stop_periodic_measurement()
#             except Exception:
#                 pass
"""
SCD41 True-CO2 sensor (photoacoustic NDIR) — SWAPPABLE sensor.

Requires ~5s warmup after init(); produces one reading every 5s.
Caches the last valid reading so fast logging loops (e.g. 2s ticks)
always return valid data instead of empty strings.
"""

import board
import adafruit_scd4x

from shared.sensors.base import Sensor


class SCD41(Sensor):
    name     = "SCD41"
    addr     = 0x62
    is_fixed = False

    def __init__(self):
        self._sensor    = None
        self._last_read = {
            "co2":      "",
            "scd_temp": "",
            "scd_hum":  "",
        }

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
        self._sensor = adafruit_scd4x.SCD4X(i2c, address=self.addr)
        self._sensor.start_periodic_measurement()

    def cols(self) -> list:
        return ["co2", "scd_temp", "scd_hum"]

    def read(self) -> dict:
        if self._sensor is None:
            return self._last_read

        # A real I2C failure (data_ready / register access) must propagate so the
        # sampler's record_failure() marks the sensor offline and
        # attempt_reconnect() can re-initialise it.  "Not ready yet" is normal
        # (measurement period >= 2 s) and keeps returning the last good reading.
        if self._sensor.data_ready:
            self._last_read = {
                "co2":      self._sensor.CO2,
                "scd_temp": round(self._sensor.temperature,       2),
                "scd_hum":  round(self._sensor.relative_humidity, 2),
            }

        return self._last_read

    def cleanup(self) -> None:
        if self._sensor is not None:
            try:
                self._sensor.stop_periodic_measurement()
            except Exception:
                pass