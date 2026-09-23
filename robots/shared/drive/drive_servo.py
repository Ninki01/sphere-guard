"""
DriveServo: wraps a PCA9685 continuous_servo channel (SPT5535LV).

Throttle range: -1.0 (full reverse) to +1.0 (full forward), 0.0 = stop.
Pulse range: 500–2500 µs (matches the SPT5535LV spec).
Channel is read from cfg.drive.drive_channel.
"""

import smbus2

_PULSE_MIN = 500
_PULSE_MAX = 2500

# PCA9685 all-call I2C reset: addr 0x00, command byte 0x06
_PCA_RESET_ADDR = 0x00
_PCA_RESET_CMD  = 0x06


def reset_pca9685() -> None:
    """Send hardware all-call reset to PCA9685. Call once before ServoKit init."""
    try:
        bus = smbus2.SMBus(1)
        bus.write_byte(_PCA_RESET_ADDR, _PCA_RESET_CMD)
        bus.close()
    except Exception:
        pass  # Not on Pi — silently skip


class DriveServo:
    def __init__(self, cfg):
        self._channel  = cfg.drive.drive_channel
        self._throttle = 0.0
        self._servo    = None

        try:
            from adafruit_servokit import ServoKit
            kit = ServoKit(channels=16)
            self._servo = kit.continuous_servo[self._channel]
            self._servo.set_pulse_width_range(_PULSE_MIN, _PULSE_MAX)
        except Exception:
            pass  # hardware unavailable — degraded mode

    @property
    def throttle(self) -> float:
        return self._throttle

    def set_throttle(self, val: float) -> None:
        val = max(-1.0, min(1.0, float(val)))
        self._throttle = val
        if self._servo is not None:
            try:
                self._servo.throttle = val
            except Exception:
                pass

    def stop(self) -> None:
        self.set_throttle(0.0)

    def _reinit_servo(self) -> None:
        """Re-create the ServoKit connection after a PCA9685 hardware reset."""
        from adafruit_servokit import ServoKit
        kit = ServoKit(channels=16)
        self._servo = kit.continuous_servo[self._channel]
        self._servo.set_pulse_width_range(_PULSE_MIN, _PULSE_MAX)
