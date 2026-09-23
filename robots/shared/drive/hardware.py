"""
DriveHardware: unified wrapper for DriveServo + SteeringServo with PCA9685 health
tracking and automatic recovery.

Usage in run.py:
    hw = DriveHardware(cfg)
    # hw exposes .stop(), .set_throttle(), .throttle (drive interface)
    # hw exposes .center(), .set_angle(), .angle (steering interface)
    # hw.online — False while PCA9685 is unresponsive
    # hw.attempt_recovery() — called by watchdog every CHECK_INTERVAL

Safety contract on recovery:
  1. reset_pca9685() — hardware all-call reset
  2. _reinit_servo() on both drive and steering — fresh ServoKit objects
  3. throttle = 0.0 and steering = servo_center — safe state FIRST
  4. hw.online = True
  The operator may not be watching when recovery fires; resuming the previously
  commanded throttle would cause unexpected motion.
"""

import threading
import time

from shared.drive.drive_servo    import DriveServo, reset_pca9685
from shared.drive.steering_servo import SteeringServo
from shared.util.log             import info, warn

_FAIL_OFFLINE        = 3    # consecutive write failures to mark drive offline
_RECOVERY_INTERVAL_S = 5.0  # minimum seconds between recovery attempts


class DriveHardware:
    """
    Thin wrapper around DriveServo + SteeringServo that adds health tracking.

    All write methods are guarded: if online is False they return immediately
    without attempting hardware I/O.  The watchdog calls attempt_recovery()
    periodically; successful recovery applies safe state before going back online.
    """

    def __init__(self, cfg):
        self._cfg     = cfg
        self.drive    = DriveServo(cfg)
        self.steering = SteeringServo(cfg)
        self.online   = True
        self._streak  = 0
        self._last_recovery_s = 0.0
        self._lock    = threading.Lock()

    # ── Drive interface ───────────────────────────────────────────────────────

    @property
    def throttle(self) -> float:
        return self.drive.throttle

    def set_throttle(self, val: float) -> None:
        if not self.online:
            return
        try:
            self.drive.set_throttle(val)
            self._on_success()
        except Exception:
            self._on_failure()

    def stop(self) -> None:
        """Always attempt to stop even when hardware is flagged offline (safety)."""
        try:
            self.drive.stop()
            if self.online:
                self._on_success()
        except Exception:
            if self.online:
                self._on_failure()

    # ── Steering interface ────────────────────────────────────────────────────

    @property
    def angle(self) -> float:
        return self.steering.angle

    def set_angle(self, deg: float) -> None:
        if not self.online:
            return
        try:
            self.steering.set_angle(deg)
            self._on_success()
        except Exception:
            self._on_failure()

    def center(self) -> None:
        """Always attempt to centre even when hardware is offline (safety)."""
        try:
            self.steering.center()
            if self.online:
                self._on_success()
        except Exception:
            if self.online:
                self._on_failure()

    # ── Health tracking ───────────────────────────────────────────────────────

    def _on_success(self) -> None:
        with self._lock:
            self._streak = 0

    def _on_failure(self) -> None:
        with self._lock:
            self._streak += 1
            if self._streak >= _FAIL_OFFLINE and self.online:
                self.online = False
                warn(f"DRIVE HARDWARE OFFLINE — PCA9685 not responding "
                     f"({_FAIL_OFFLINE} consecutive write failures)")

    def attempt_recovery(self) -> bool:
        """
        Called by the watchdog loop.  If offline and RECOVERY_INTERVAL_S have
        elapsed, attempt:
          1. PCA9685 hardware reset
          2. Re-create ServoKit objects
          3. Apply safe state (throttle=0, steering=center)
          4. Mark online

        Returns True when back online; False if still offline.
        Most calls are instant no-ops (time guard not elapsed or already online).
        """
        if self.online:
            return True
        now = time.monotonic()
        if now - self._last_recovery_s < _RECOVERY_INTERVAL_S:
            return False
        self._last_recovery_s = now
        try:
            reset_pca9685()
            self.drive._reinit_servo()
            self.steering._reinit_servo()
            # CRITICAL: force safe state before declaring online.
            # Do NOT resume the previously commanded throttle — the operator
            # may not be watching and spontaneous motion after a fault is dangerous.
            self.drive._servo.throttle = 0.0
            self.drive._throttle       = 0.0
            self.steering._servo.angle = float(self._cfg.steering.servo_center)
            self.steering._angle       = float(self._cfg.steering.servo_center)
            with self._lock:
                self.online  = True
                self._streak = 0
            info("DRIVE HARDWARE RECOVERED — safe state applied "
                 "(throttle=0, steering=center)")
            return True
        except Exception as e:
            warn(f"DRIVE recovery attempt failed: {e}")
            return False
