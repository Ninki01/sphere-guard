"""
SDP810 differential pressure sensor — SWAPPABLE sensor.

Uses raw I2C via adafruit_bus_device. CRC-8 validated (polynomial 0x31, init 0xFF).
Scale factor is read from the sensor itself on each sample; defaults to 240 (500Pa variant).
"""

import struct
import time
import board
from adafruit_bus_device.i2c_device import I2CDevice

from shared.sensors.base import Sensor


def _crc8(data):
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc << 1) ^ 0x31 if crc & 0x80 else crc << 1
            crc &= 0xFF
    return crc


class SDP810(Sensor):
    name     = "SDP810"
    addr     = 0x25
    is_fixed = False

    def __init__(self):
        self._device       = None
        self._scale_factor = 240  # SDP810-500Pa default; sensor overwrites on first read

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
        self._device = I2CDevice(i2c, self.addr)
        with self._device:
            self._device.write(bytes([0x36, 0x03]))  # continuous averaging mode
        time.sleep(0.1)

    def cols(self) -> list:
        return ["diff_press"]

    def read(self) -> dict:
        if self._device is None:
            return {"diff_press": ""}
        # An I2C/CRC failure must propagate so the sampler's record_failure()
        # marks the sensor offline and attempt_reconnect() can re-initialise it.
        buf = bytearray(9)
        with self._device:
            self._device.readinto(buf)

        if buf[2] != _crc8(buf[0:2]) or buf[5] != _crc8(buf[3:5]) or buf[8] != _crc8(buf[6:8]):
            raise ValueError("SDP810 CRC mismatch")

        raw_dp    = struct.unpack('>h', bytes(buf[0:2]))[0]
        raw_scale = struct.unpack('>h', bytes(buf[6:8]))[0]

        if raw_scale != 0:
            self._scale_factor = raw_scale

        return {"diff_press": round(raw_dp / self._scale_factor, 3)}

    def cleanup(self) -> None:
        if self._device is not None:
            try:
                with self._device:
                    self._device.write(bytes([0x3F, 0xF9]))  # stop continuous measurement
            except Exception:
                pass
