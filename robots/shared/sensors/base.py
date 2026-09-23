import time
from abc import ABC, abstractmethod

from shared.util.log import info, warn


class Sensor(ABC):
    """
    Interface every sensor driver must implement.

    Hardware classes must never do file I/O or HTTP.
    read() must not raise while the sensor is in a "not yet connected" state
    (_sensor/_device/_bus is None) — return the placeholder ("" or None) for
    the columns instead.  But once hardware is open, real read failures (I2C
    errors, stale driver objects, CRC mismatch) MUST propagate: the sampler
    turns a raised read into record_failure() and, after OFFLINE_AFTER
    consecutive failures, drives attempt_reconnect() to re-initialise the
    sensor.  A driver that swallows its exceptions would never be marked
    offline and could never recover.

    Reconnect behaviour is provided by this base class via lazy-initialised
    instance state.  Subclasses do NOT need to call super().__init__() — the
    online and fail_streak properties use getattr() defaults so they work even
    if the subclass __init__ never touches them.
    """

    name:     str   # human label used in logs and meta.json, e.g. "BNO055"
    addr:     int   # I2C address; 0 for non-I2C sensors (UART, sysfs)
    is_fixed: bool  # True → loud warning if absent; False → silently skip

    # ── Per-driver reconnect configuration ────────────────────────────────────
    # Subclass can override as a class attribute (e.g. post_init_delay_s = 0.5)
    post_init_delay_s:    float = 0.0   # seconds to wait after init() before first read
    OFFLINE_AFTER:        int   = 5     # consecutive read failures before marking offline
    RECONNECT_INTERVAL_S: float = 5.0   # minimum seconds between reconnect attempts

    # ── Reconnect state (lazy properties — no __init__ required in base) ──────

    @property
    def online(self) -> bool:
        return getattr(self, '_online', True)

    @online.setter
    def online(self, val: bool) -> None:
        self._online = val

    @property
    def fail_streak(self) -> int:
        return getattr(self, '_fail_streak', 0)

    @fail_streak.setter
    def fail_streak(self, val: int) -> None:
        self._fail_streak = val

    def record_failure(self) -> bool:
        """
        Increment the consecutive failure counter.  When OFFLINE_AFTER is
        reached, mark the sensor offline and log once.
        Returns True on that offline transition (never again until reconnect).
        """
        self.fail_streak += 1
        if self.fail_streak >= self.OFFLINE_AFTER and self.online:
            self.online = False
            warn(f"SENSOR OFFLINE: {self.name} — {self.fail_streak} consecutive failures")
            return True
        return False

    def record_success(self) -> None:
        """Reset the consecutive failure counter after a successful read."""
        self.fail_streak = 0

    def attempt_reconnect(self, cfg) -> bool:
        """
        If offline and RECONNECT_INTERVAL_S have elapsed since the last attempt,
        re-call init() to create a fresh driver object (discarding any stale state),
        optionally sleep post_init_delay_s to let the hardware settle, then verify
        with one read().

        Returns True when the sensor is back online.

        Called by the sampler on every tick while the sensor is offline; most calls
        are instant no-ops because the time guard hasn't elapsed yet.
        """
        if self.online:
            return True
        now = time.monotonic()
        if now - getattr(self, '_last_reconnect_s', 0.0) < self.RECONNECT_INTERVAL_S:
            return False
        self._last_reconnect_s = now
        old_streak = self.fail_streak
        try:
            self.init(cfg)
            if self.post_init_delay_s > 0:
                # Hardware-specific settle time (e.g. BNO055 fusion engine).
                time.sleep(self.post_init_delay_s)
            self.read()            # discard — just verify the sensor responds
            self.online      = True
            self.fail_streak = 0
            info(f"[{self.name}] reconnected after {old_streak} failed reads")
            return True
        except Exception:
            return False

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    def probe(self, bus) -> bool:
        """Return True if the sensor is reachable. bus is smbus2.SMBus(1) or None."""

    @abstractmethod
    def init(self, cfg) -> None:
        """Open the device and apply any one-time configuration. Called once after probe,
        and again by attempt_reconnect() on each reconnect attempt."""

    @abstractmethod
    def read(self) -> dict:
        """
        Read latest values. Returns {col_name: value} for every col in cols().
        On partial failure, return what is available; missing cols get value None.
        Must not raise while hardware is not yet open (return placeholders), but
        MUST raise on real read failures after init() so offline detection and
        reconnect can work.
        """

    @abstractmethod
    def cols(self) -> list:
        """Ordered list of CSV column names this sensor contributes."""
