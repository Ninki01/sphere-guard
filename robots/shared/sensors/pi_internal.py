"""
Pi-internal sensor: CPU temperature, network identity, latency, connectivity.

Background thread (10 s interval) measures:
  TCP latency to 1.1.1.1:443 (also drives internet_ok), active interface info,
  negotiated link speed, wifi signal + quality.

On-demand speed test (run_speed_test()) downloads ~5 MB and uploads ~0.5 MB over
HTTPS, timing each leg.  Also fires automatically once per internet reconnection,
subject to:
  - 15 s debounce (connection must be stable before the test starts)
  - 10 min cooldown between auto-tests
  - skipped (deferred) while a recording session is active
  - no retry on failure — wait for next reconnection event

run.py wires set_session() after both objects are created so the auto-test can
check recording state.

TODO (uploader): also skip auto-test while an upload is in progress.
  When shared/uploader/ is implemented, call set_uploader_checker(fn) and add
  `or self._is_uploading()` to the recording guard in _maybe_auto_test().

CSV columns (cols()):
  pi_temp, wifi_dbm, internet, net_type, net_name, ip_address,
  latency_ms, link_speed_mbps, wifi_quality

Live-only (in read(), not cols() — excluded from sensors.csv):
  net_iface
"""

import socket
import subprocess
import threading
import time
import urllib.request

from shared.sensors.base import Sensor
from shared.util.log     import info, warn

_CHECK_INTERVAL   = 10          # seconds between background ticks
_LATENCY_HOST     = "1.1.1.1"
_LATENCY_PORT     = 443
_LATENCY_TIMEOUT  = 2
_DEBOUNCE_S       = 15          # stable-online time before auto-test fires
_COOLDOWN_S       = 600         # 10 min between auto-tests
_TEST_TOTAL_S     = 10          # hard cap on speed test duration
_DL_URL = "https://speed.cloudflare.com/__down?bytes=5000000"
_UL_URL = "https://speed.cloudflare.com/__up"
_WIFI_QUALITY_MAX = 70          # /proc/net/wireless link quality denominator
                                # (most Linux drivers; normalised to 0–100 %)


# ──────────────────────────────────────────────────────────────────────────────
# Stateless helpers — module-level, no shared state
# ──────────────────────────────────────────────────────────────────────────────

def _get_default_iface() -> "str | None":
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "00000000":
                    return parts[0]
    except Exception:
        pass
    return None


def _iface_type(iface: str) -> str:
    """wifi if iface appears in /proc/net/wireless, ethernet otherwise."""
    if not iface:
        return "none"
    try:
        with open("/proc/net/wireless") as f:
            for line in f:
                if iface in line:
                    return "wifi"
    except Exception:
        pass
    return "ethernet"


def _get_wifi_dbm(iface: str) -> "float | None":
    try:
        with open("/proc/net/wireless") as f:
            for line in f:
                if iface in line:
                    return round(float(line.split()[3].rstrip(".")), 1)
    except Exception:
        pass
    return None


def _get_wifi_quality(iface: str) -> "float | None":
    """Link quality percentage (raw / _WIFI_QUALITY_MAX * 100, capped at 100)."""
    try:
        with open("/proc/net/wireless") as f:
            for line in f:
                if iface in line:
                    raw = float(line.split()[2].rstrip("."))
                    return min(100.0, round(raw / _WIFI_QUALITY_MAX * 100, 1))
    except Exception:
        pass
    return None


def _get_ip(iface: str) -> "str | None":
    try:
        out = subprocess.check_output(
            ["ip", "-4", "addr", "show", iface],
            timeout=2, stderr=subprocess.DEVNULL
        ).decode()
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                return line.split()[1].split("/")[0]
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            ["hostname", "-I"], timeout=2, stderr=subprocess.DEVNULL
        ).decode().strip()
        if out:
            return out.split()[0]
    except Exception:
        pass
    return None


def _get_ssid(iface: str) -> "str | None":
    try:
        out = subprocess.check_output(
            ["iwgetid", iface, "-r"],
            timeout=2, stderr=subprocess.DEVNULL
        ).decode().strip()
        return out if out else None
    except Exception:
        return None


def _get_link_speed(iface: str, net_type: str) -> "float | None":
    if net_type == "ethernet":
        try:
            with open(f"/sys/class/net/{iface}/speed") as f:
                v = int(f.read().strip())
                return float(v) if v > 0 else None
        except Exception:
            pass
    elif net_type == "wifi":
        try:
            out = subprocess.check_output(
                ["iw", "dev", iface, "link"],
                timeout=2, stderr=subprocess.DEVNULL
            ).decode()
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("tx bitrate:"):
                    return float(line.split()[2])
        except Exception:
            pass
    return None


# ──────────────────────────────────────────────────────────────────────────────

class PiInternal(Sensor):
    name     = "Pi"
    addr     = 0        # not I2C
    is_fixed = True

    def __init__(self):
        # Connectivity / latency
        self._internet_ok    = False
        self._latency_ms     = None

        # Network identity
        self._net_iface       = None
        self._net_type        = "none"
        self._net_name        = None
        self._ip_address      = None
        self._wifi_dbm        = None
        self._wifi_quality    = None
        self._link_speed_mbps = None

        # Background thread
        self._thread   = None
        self._stop_evt = threading.Event()

        # Auto-test state machine
        self._online_since_mono   = None          # monotonic when went online
        self._last_auto_test_mono = float("-inf") # never tested sentinel
        self._pending_auto_test   = False         # deferred while recording
        self._session             = None          # injected via set_session()

        # Speed test
        self._speed_test_result  = {"status": "idle"}
        self._speed_test_running = False
        self._speed_test_lock    = threading.Lock()

    # ── Sensor ABC ────────────────────────────────────────────────────────────

    def probe(self, bus) -> bool:
        try:
            with open("/sys/class/thermal/thermal_zone0/temp"):
                return True
        except Exception:
            return False

    def init(self, cfg) -> None:
        # Idempotent: if the background thread is still running (e.g., sampler
        # called init() again during a retry), do nothing — the thread is already
        # refreshing caches and a second thread would duplicate work and corrupt state.
        if self._thread is not None and self._thread.is_alive():
            return
        # Populate caches before the first read() call
        self._measure_latency()
        self._refresh_network()
        if self._internet_ok:
            self._online_since_mono = time.monotonic()
            # Auto-test at startup fires once debounce passes (first loop iteration
            # at ~10 s will still be below the 15 s threshold; second will fire)
        self._thread = threading.Thread(
            target=self._background_loop, daemon=True, name="pi_net_check"
        )
        self._thread.start()

    def cols(self) -> list:
        # net_iface is intentionally excluded — live-only via /sensors
        return [
            "pi_temp", "wifi_dbm", "internet",
            "net_type", "net_name", "ip_address",
            "latency_ms", "link_speed_mbps", "wifi_quality",
        ]

    def read(self) -> dict:
        pi_temp = None
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                pi_temp = round(int(f.read().strip()) / 1000.0, 1)
        except Exception:
            pass
        return {
            "pi_temp":         pi_temp,
            "wifi_dbm":        self._wifi_dbm,
            "internet":        1 if self._internet_ok else 0,
            "net_type":        self._net_type,
            "net_name":        self._net_name,
            "ip_address":      self._ip_address,
            "net_iface":       self._net_iface,       # live-only
            "latency_ms":      self._latency_ms,
            "link_speed_mbps": self._link_speed_mbps,
            "wifi_quality":    self._wifi_quality,
        }

    def cleanup(self) -> None:
        self._stop_evt.set()

    # ── Session injection ─────────────────────────────────────────────────────

    def set_session(self, session) -> None:
        """Called from run.py after Session is created."""
        self._session = session

    # ── Speed test public API (called by routes.py) ───────────────────────────

    def run_speed_test(self, trigger: str = "manual") -> bool:
        """
        Start a speed test background thread.
        Returns False if already running, if a recording session is active, or
        if the uploader is currently uploading (lock file present — upload saturates
        the link and would compete with the speed test).
        """
        import os
        if os.path.exists("/tmp/sphereguard_upload_in_progress"):
            warn(f"speed test deferred: upload in progress (trigger={trigger})")
            return False
        is_rec = self._session.active if self._session is not None else False
        if is_rec:
            warn(f"speed test refused: recording in progress (trigger={trigger})")
            return False
        with self._speed_test_lock:
            if self._speed_test_running:
                return False
            self._speed_test_running = True
        self._speed_test_result = {"status": "running", "trigger": trigger}
        threading.Thread(
            target=self._run_speed_test_sync, args=(trigger,),
            daemon=True, name="pi_speed_test"
        ).start()
        return True

    @property
    def speed_test_result(self) -> dict:
        return dict(self._speed_test_result)

    # ── Background loop ───────────────────────────────────────────────────────

    def _background_loop(self) -> None:
        while not self._stop_evt.is_set():
            self._stop_evt.wait(timeout=_CHECK_INTERVAL)
            if self._stop_evt.is_set():
                break
            prev_online = self._internet_ok
            self._measure_latency()
            self._refresh_network()
            # Track offline→online edge for auto-test trigger
            if not prev_online and self._internet_ok:
                self._online_since_mono = time.monotonic()
            elif not self._internet_ok:
                self._online_since_mono = None
                self._pending_auto_test = False
            self._maybe_auto_test()

    def _measure_latency(self) -> None:
        """TCP connect to 1.1.1.1:443 — drives internet_ok and latency_ms."""
        try:
            t0 = time.monotonic()
            s  = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(_LATENCY_TIMEOUT)
            s.connect((_LATENCY_HOST, _LATENCY_PORT))
            s.close()
            self._latency_ms  = round((time.monotonic() - t0) * 1000)
            self._internet_ok = True
        except Exception:
            self._latency_ms  = None
            self._internet_ok = False

    def _refresh_network(self) -> None:
        try:
            iface    = _get_default_iface()
            net_type = _iface_type(iface) if iface else "none"
            ip       = _get_ip(iface) if iface else None

            if net_type == "wifi":
                wifi_dbm  = _get_wifi_dbm(iface)
                wifi_qual = _get_wifi_quality(iface)
                net_name  = _get_ssid(iface)
            else:
                wifi_dbm  = None
                wifi_qual = None
                net_name  = "Ethernet" if net_type == "ethernet" else None

            link_speed = _get_link_speed(iface, net_type) if iface else None

            self._net_iface       = iface
            self._net_type        = net_type
            self._net_name        = net_name
            self._ip_address      = ip
            self._wifi_dbm        = wifi_dbm
            self._wifi_quality    = wifi_qual
            self._link_speed_mbps = link_speed
        except Exception:
            pass  # keep previous cached values

    # ── Auto-test state machine ───────────────────────────────────────────────

    def _maybe_auto_test(self) -> None:
        if not self._internet_ok or self._online_since_mono is None:
            return
        now = time.monotonic()
        if (now - self._online_since_mono) < _DEBOUNCE_S:
            return  # debouncing
        if (now - self._last_auto_test_mono) < _COOLDOWN_S:
            return  # cooldown — _pending_auto_test is irrelevant until cooldown expires
        is_rec = self._session.active if self._session is not None else False
        if is_rec:
            if not self._pending_auto_test:
                info("auto speed test deferred: recording in progress")
                self._pending_auto_test = True
            return
        self._pending_auto_test = False
        if self.run_speed_test("auto"):
            self._last_auto_test_mono = now
            info("auto speed test started")

    # ── Speed test worker ─────────────────────────────────────────────────────

    def _run_speed_test_sync(self, trigger: str) -> None:
        deadline = time.monotonic() + _TEST_TOTAL_S
        dl_mbps  = None
        ul_mbps  = None

        try:
            # Download ~5 MB; read in chunks so we respect the deadline
            t0       = time.monotonic()
            received = 0
            with urllib.request.urlopen(_DL_URL, timeout=7) as resp:
                while time.monotonic() < deadline - 2.0:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    received += len(chunk)
            dl_s = time.monotonic() - t0
            if dl_s > 0 and received > 0:
                dl_mbps = round((received * 8 / 1_000_000) / dl_s, 2)

            # Upload ~500 KB (if budget remains)
            remaining = deadline - time.monotonic()
            if remaining > 1.5:
                buf = bytes(500_000)
                req = urllib.request.Request(
                    _UL_URL, data=buf, method="POST",
                    headers={
                        "Content-Type":   "application/octet-stream",
                        "Content-Length": str(len(buf)),
                    },
                )
                t0 = time.monotonic()
                with urllib.request.urlopen(req, timeout=min(6, remaining)) as r:
                    r.read()
                ul_s = time.monotonic() - t0
                if ul_s > 0:
                    ul_mbps = round((len(buf) * 8 / 1_000_000) / ul_s, 2)

            self._speed_test_result = {
                "status":        "ok",
                "download_mbps": dl_mbps,
                "upload_mbps":   ul_mbps,
                "latency_ms":    self._latency_ms,
                "tested_at_ms":  int(time.time() * 1000),
                "trigger":       trigger,
            }
            info(
                f"speed test ({trigger}): "
                f"↓{dl_mbps} Mbps  ↑{ul_mbps} Mbps  "
                f"latency={self._latency_ms} ms"
            )
        except Exception as exc:
            self._speed_test_result = {
                "status":       "error",
                "error":        str(exc),
                "tested_at_ms": int(time.time() * 1000),
                "trigger":      trigger,
            }
        finally:
            with self._speed_test_lock:
                self._speed_test_running = False
