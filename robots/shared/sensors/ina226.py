"""
INA226 bidirectional current/power monitor — FIXED sensor.

Uses smbus2 + raw register access (no Adafruit library dependency).

Address: 0x41 (A0 bridged). NOTE: 0x40 is the PCA9685 — do not confuse them.

Calibration formula (INA226 datasheet §8.6.3):
    current_lsb = max_expected_A / 2^15       (we use max_expected_A = 10 A)
    CAL         = floor(0.00512 / (current_lsb * shunt_ohms))
    power_lsb   = 25 * current_lsb

shunt_ohms is read from cfg.ina226.shunt_ohms (default 0.005 Ω).

Exposed columns: bus_v (V), current_a (A), power_w (W).
"""

import math
import struct

from shared.sensors.base import Sensor

try:
    import smbus2
    _SMBUS_OK = True
except ImportError:
    _SMBUS_OK = False

_REG_CONFIG      = 0x00
_REG_SHUNT_V     = 0x01
_REG_BUS_V       = 0x02
_REG_POWER       = 0x03
_REG_CURRENT     = 0x04
_REG_CALIBRATION = 0x05

_MAX_EXPECTED_A  = 10.0


def _read16(bus, addr, reg) -> int:
    data = bus.read_i2c_block_data(addr, reg, 2)
    return struct.unpack('>H', bytes(data))[0]


def _read16_signed(bus, addr, reg) -> int:
    data = bus.read_i2c_block_data(addr, reg, 2)
    return struct.unpack('>h', bytes(data))[0]


def _write16(bus, addr, reg, val: int) -> None:
    bus.write_i2c_block_data(addr, reg, [(val >> 8) & 0xFF, val & 0xFF])


class INA226(Sensor):
    name     = "INA226"
    is_fixed = True

    def __init__(self):
        self._bus         = None
        self._current_lsb = None
        self._power_lsb   = None
        self.addr         = 0x41  # overridden by init() from config

    def probe(self, bus) -> bool:
        if not _SMBUS_OK or bus is None:
            return False
        try:
            bus.read_byte(self.addr)
            return True
        except Exception:
            return False

    def init(self, cfg) -> None:
        self.addr = getattr(getattr(cfg, "ina226", None), "address", 0x41)
        shunt_ohms = getattr(getattr(cfg, "ina226", None), "shunt_ohms", 0.005)

        self._current_lsb = _MAX_EXPECTED_A / 32768.0
        cal_val = int(math.floor(0.00512 / (self._current_lsb * shunt_ohms)))
        self._power_lsb = 25.0 * self._current_lsb

        self._bus = smbus2.SMBus(1)
        # Write calibration register
        _write16(self._bus, self.addr, _REG_CALIBRATION, cal_val)
        # Default config: avg=4, bus conv=1100µs, shunt conv=1100µs, continuous
        _write16(self._bus, self.addr, _REG_CONFIG, 0x4527)

    def cols(self) -> list:
        return ["bus_v", "current_a", "power_w"]

    def read(self) -> dict:
        if self._bus is None or self._current_lsb is None:
            return {c: None for c in self.cols()}
        # An I2C failure must propagate so the sampler's record_failure() marks
        # the sensor offline and attempt_reconnect() can re-initialise it.
        bus_v    = _read16(self._bus, self.addr, _REG_BUS_V)    * 1.25e-3
        current  = _read16_signed(self._bus, self.addr, _REG_CURRENT) * self._current_lsb
        power_r  = _read16(self._bus, self.addr, _REG_POWER)    * self._power_lsb
        return {
            "bus_v":     round(bus_v,   3),
            "current_a": round(current, 4),
            "power_w":   round(power_r, 3),
        }
