"""
Dead-man's watchdog: stops the drive motor if no joystick heartbeat is received
within TIMEOUT_MS milliseconds.

Checks every CHECK_INTERVAL seconds. When triggered, sets throttle=0 and
steering to center, then logs an auto_stop command to the active session.

If a DriveHardware instance is passed as hardware=, the watchdog also calls
hardware.attempt_recovery() on each check interval so the drive comes back
online without any separate recovery thread.  When drive is offline the
watchdog does NOT keep retrying writes — it simply calls attempt_recovery()
and waits.
"""

import threading
import time

from shared.util.clock import now_ms
from shared.util.log   import warn

TIMEOUT_MS     = 1000
CHECK_INTERVAL = 0.1


class Watchdog:
    def __init__(self, drive, steering, session, hardware=None):
        self._drive    = drive
        self._steering = steering
        self._session  = session
        self._hardware = hardware  # optional DriveHardware for recovery
        self._last_ms  = now_ms()
        self._thread   = None
        self._running  = False

    def heartbeat(self) -> None:
        """Call this on every joystick or command POST to reset the timer."""
        self._last_ms = now_ms()

    def start(self) -> None:
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="watchdog"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            hw = self._hardware

            # Drive hardware recovery — attempt every CHECK_INTERVAL; most
            # calls return instantly (time guard or already online).
            if hw is not None and not hw.online:
                hw.attempt_recovery()
                # Skip the timeout check while drive is offline — no commands
                # can reach the hardware anyway and re-sending is pointless.
                time.sleep(CHECK_INTERVAL)
                continue

            if (self._drive.throttle != 0.0 and
                    now_ms() - self._last_ms > TIMEOUT_MS):
                self._drive.stop()
                self._steering.center()
                warn("Watchdog triggered — auto_stop")
                if self._session is not None:
                    try:
                        self._session.log_command(
                            source="watchdog", action="auto_stop",
                            x=0.0, y=0.0,
                            angle=self._steering.angle,
                            throttle=0.0,
                        )
                    except Exception:
                        pass

            time.sleep(CHECK_INTERVAL)
