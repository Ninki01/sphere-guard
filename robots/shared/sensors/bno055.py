"""
BNO055 9-DOF absolute orientation sensor — FIXED sensor.

Runs in IMUPLUS mode (0x08) — gyro + accelerometer fusion, no magnetometer.
Magnetometer is unusable inside the metal duct housing.  See CHANGELOG for rationale.

BNO055 IMUPLUS mode constant: datasheet Table 3-5, value 0x08.

Columns produced (see schema.py for units):
  Euler: pitch, roll, heading   — display only; use quaternion for analysis
  Quaternion: quat_w/x/y/z     — gimbal-lock-free
  Linear accel: lin_acc_x/y/z
  Gyro: gyro_x/y/z
  Calibration: cal_sys/gyro/accel/cal_mag  — cached from last successful read
"""

import board
import adafruit_bno055

from shared.sensors.base import Sensor


class BNO055(Sensor):
    name     = "BNO055"
    addr     = 0x28
    is_fixed = True

    _IMUPLUS_MODE     = 0x08  # BNO055 datasheet Table 3-5
    # The fusion engine needs ~500 ms to stabilise after a mode change.
    # First reads without this delay return None or garbage Euler/quaternion values.
    post_init_delay_s = 0.5

    def __init__(self):
        self._sensor = None
        self._cal    = (0, 0, 0, 0)

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
        self._sensor = adafruit_bno055.BNO055_I2C(i2c, address=self.addr)
        self._sensor.mode = self._IMUPLUS_MODE
        # post_init_delay_s = 0.5 on this class; Sensor.attempt_reconnect() applies it.

    def cols(self) -> list:
        return [
            "pitch", "roll", "heading",
            "quat_w", "quat_x", "quat_y", "quat_z",
            "lin_acc_x", "lin_acc_y", "lin_acc_z",
            "gyro_x", "gyro_y", "gyro_z",
            "cal_sys", "cal_gyro", "cal_accel", "cal_mag",
        ]

    def read(self) -> dict:
        if self._sensor is None:
            return {c: "" for c in self.cols()}
        # A hardware/I2C failure (or a stale driver object) must propagate so the
        # sampler's record_failure() marks the sensor offline and
        # attempt_reconnect() creates a FRESH BNO055 driver object.
        euler = self._sensor.euler
        if euler is None or any(v is None for v in euler):
            raise ValueError("euler None")
        heading, roll, pitch = euler

        q = self._sensor.quaternion or (1.0, 0.0, 0.0, 0.0)
        la = self._sensor.linear_acceleration or (0.0, 0.0, 0.0)
        gy = self._sensor.gyro or (0.0, 0.0, 0.0)

        try:
            self._cal = self._sensor.calibration_status or (0, 0, 0, 0)
        except Exception:
            pass

        return {
            "pitch":     round(pitch,   1),
            "roll":      round(roll,    1),
            "heading":   round(heading, 1),
            "quat_w":    round(q[0], 5),
            "quat_x":    round(q[1], 5),
            "quat_y":    round(q[2], 5),
            "quat_z":    round(q[3], 5),
            "lin_acc_x": round(la[0], 3),
            "lin_acc_y": round(la[1], 3),
            "lin_acc_z": round(la[2], 3),
            "gyro_x":    round(gy[0], 4),
            "gyro_y":    round(gy[1], 4),
            "gyro_z":    round(gy[2], 4),
            "cal_sys":   self._cal[0],
            "cal_gyro":  self._cal[1],
            "cal_accel": self._cal[2],
            "cal_mag":   self._cal[3],
        }

    def calibration_status(self) -> tuple:
        """Returns (sys, gyro, accel, mag) each 0-3.  Cached from last read()."""
        return self._cal
