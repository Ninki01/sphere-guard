"""
SteeringServo: wraps a PCA9685 positional servo channel (PTK7465WMG weight-shift).

Angle range: 0–180°. Pulse range: 500–2500 µs.
Channel and center/left/right angles are read from cfg.drive/steering.
"""

_PULSE_MIN = 500
_PULSE_MAX = 2500


class SteeringServo:
    def __init__(self, cfg):
        self._channel = cfg.drive.steering_channel
        self._cfg     = cfg
        self._angle   = cfg.steering.servo_center
        self._servo   = None

        try:
            from adafruit_servokit import ServoKit
            kit = ServoKit(channels=16)
            self._servo = kit.servo[self._channel]
            self._servo.set_pulse_width_range(_PULSE_MIN, _PULSE_MAX)
        except Exception:
            pass

    @property
    def angle(self) -> float:
        return self._angle

    def set_angle(self, deg: float) -> None:
        deg = max(0.0, min(180.0, float(deg)))
        self._angle = deg
        if self._servo is not None:
            try:
                self._servo.angle = deg
            except Exception:
                pass

    def center(self) -> None:
        self.set_angle(self._cfg.steering.servo_center)

    def _reinit_servo(self) -> None:
        """Re-create the ServoKit connection after a PCA9685 hardware reset."""
        from adafruit_servokit import ServoKit
        kit = ServoKit(channels=16)
        self._servo = kit.servo[self._channel]
        self._servo.set_pulse_width_range(_PULSE_MIN, _PULSE_MAX)
