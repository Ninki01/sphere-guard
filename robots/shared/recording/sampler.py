"""
Sampler: 20 Hz sensor sampling daemon thread.

Reads all active sensors every tick; reads "slow" sensors (BME280, SHT45, etc.)
only every cfg.logging.env_every_n ticks (default 40 = every 2 s at 20 Hz).

Failure tracking (sensors):
  Delegated to Sensor.record_failure() / record_success() / attempt_reconnect().
  Base class marks a sensor offline after 5 consecutive failures and retries every
  5 s with a fresh driver object.

Failure tracking (cameras):
  Tracked locally in the camera thread: 10 consecutive None frames or exceptions
  mark the camera offline.  try_reopen() is called every 5 s while offline.
  On reconnect, resolution is checked against the open VideoWriter; mismatched
  frames are discarded so the existing VideoWriter is not corrupted.

Camera loop is separate (driven by camera.read_frame() blocking call rate).
"""

import threading
import time

try:
    import cv2 as _cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

try:
    from shared.cameras.fusion import FusionOverlay
    _FUSION_OK = True
except Exception:
    _FUSION_OK = False

from shared.util.clock import now_ms
from shared.util.log   import info, warn

# Camera-specific thresholds (sensors use their own base-class constants)
_CAM_OFFLINE_AFTER        = 10
_CAM_RECONNECT_INTERVAL_S = 5.0

# Sensors that are read every tick (fast sensors).  Everything else is read
# only every cfg.logging.env_every_n ticks (e.g. SCD41 — spec measurement
# period is >= 2 s, it cannot be sampled at 20 Hz).
_FAST_NAMES = {"BNO055", "INA226", "Pi", "BME280", "SHT45"}


def _encode_jpeg(frame, quality: int = 70) -> bytes | None:
    """Encode a numpy frame to JPEG bytes without re-reading the camera."""
    if not _CV2_OK or frame is None:
        return None
    try:
        ok, buf = _cv2.imencode(".jpg", frame, [_cv2.IMWRITE_JPEG_QUALITY, quality])
        return bytes(buf) if ok else None
    except Exception:
        return None


class Sampler:
    def __init__(self, sensors: list, session, cameras: list, cfg):
        self._sensors     = sensors
        self._session     = session
        self._cameras     = cameras
        self._cfg         = cfg
        self._running     = False
        self._thread      = None
        self._cam_threads = []  # one per active camera
        # Shared JPEG cache per camera role (bytes, updated by camera thread)
        self._cam_frames  = {}   # role → bytes | None
        # Raw numpy frame cache per camera role (used by fusion overlay)
        self._cam_raw     = {}   # role → np.ndarray | None
        self._cam_lock    = threading.Lock()
        # Active MJPEG stream client count per role (inc/dec by routes.py)
        self._stream_clients = {}  # role → int
        # Latest merged sensor row from the 20 Hz sampler loop — served by
        # /sensors so HTTP responses never block on live hardware reads.
        self._cache       = {}
        self._cache_lock  = threading.Lock()
        # Fusion overlay — shared instance (stateful homography cache only)
        self._fusion_overlay = FusionOverlay() if _FUSION_OK else None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._sensor_loop, daemon=True, name="sampler"
        )
        self._thread.start()
        for cam in self._cameras:
            if cam.enabled and cam._cap is not None:
                t = threading.Thread(
                    target=self._camera_loop, args=(cam,),
                    daemon=True, name=f"camera_{cam.role}"
                )
                t.start()
                self._cam_threads.append(t)

    def stop(self, join_timeout: float = 1.0) -> None:
        """Signal all loops to exit and wait for camera threads to finish.

        Camera threads must finish before cameras are released — otherwise
        a concurrent read_frame() races against cap.release() and triggers
        VIDIOC_REQBUFS errno=19 errors from the V4L2 driver.
        """
        self._running = False
        for t in self._cam_threads:
            t.join(timeout=join_timeout)

    def get_jpeg(self, role: str = "rgb"):
        """Return latest JPEG bytes for the given camera role, or None."""
        with self._cam_lock:
            return self._cam_frames.get(role)

    def inc_stream_client(self, role: str) -> None:
        """Called by routes.py when a MJPEG client connects to /stream/{role}."""
        with self._cam_lock:
            self._stream_clients[role] = self._stream_clients.get(role, 0) + 1

    def dec_stream_client(self, role: str) -> None:
        """Called by routes.py when a MJPEG client disconnects."""
        with self._cam_lock:
            self._stream_clients[role] = max(0, self._stream_clients.get(role, 0) - 1)

    # ──────────────────────────────────────────────────────────────────────
    def _sensor_loop(self) -> None:
        period    = 1.0 / self._cfg.logging.sample_hz
        env_every = self._cfg.logging.env_every_n
        env_tick  = 0
        next_tick = time.monotonic()

        while self._running:
            t_now = time.monotonic()
            if t_now < next_tick:
                time.sleep(next_tick - t_now)
            next_tick += period

            row = {}
            for s in self._sensors:
                if not s.online:
                    # attempt_reconnect() is time-gated — most calls are instant no-ops
                    reconnected = s.attempt_reconnect(self._cfg)
                    if reconnected and self._session.active:
                        self._session.log_sensor_event(s.name, "reconnected", now_ms())
                    continue

                is_slow = s.name not in _FAST_NAMES
                if is_slow and env_tick != 0:
                    continue

                try:
                    data = s.read()
                    row.update(data)
                    s.record_success()
                except Exception:
                    just_went_offline = s.record_failure()
                    if just_went_offline and self._session.active:
                        self._session.log_sensor_event(s.name, "offline", now_ms())

            if self._session.active:
                self._session.log_sensor(row)

            env_tick = (env_tick + 1) % env_every

            # Publish the freshest row for the /sensors endpoint.
            with self._cache_lock:
                self._cache = row

    # ──────────────────────────────────────────────────────────────────────
    def _camera_loop(self, cam) -> None:
        fail_streak       = 0
        last_reconnect_s  = 0.0
        resolution_ok     = True  # False when reconnected with different dims than open VideoWriter

        while self._running:
            # ── Reconnect path ────────────────────────────────────────────
            if not cam.online:
                now_s = time.monotonic()
                if now_s - last_reconnect_s >= _CAM_RECONNECT_INTERVAL_S:
                    last_reconnect_s = now_s
                    if cam.try_reopen():
                        cam.online   = True
                        fail_streak  = 0
                        info(f"CAMERA {cam.role}: reconnected")
                        if self._session.active:
                            self._session.log_camera_event(cam.role, "reconnected", now_ms())
                        # Check resolution against the open VideoWriter
                        dims = self._session.get_video_writer_dims(cam.role)
                        if dims is not None:
                            w = getattr(cam, "_width",  None)
                            h = getattr(cam, "_height", None)
                            if w is not None and h is not None and (w, h) != dims:
                                warn(
                                    f"CAMERA {cam.role}: resolution mismatch after reconnect "
                                    f"({w}x{h} vs writer {dims[0]}x{dims[1]}) "
                                    f"— frames will not be written to session"
                                )
                                resolution_ok = False
                            else:
                                resolution_ok = True
                        else:
                            resolution_ok = True  # no writer open; camera absent at session start
                time.sleep(0.033)
                continue

            # ── Normal read path ──────────────────────────────────────────
            try:
                frame = cam.read_frame()
            except Exception:
                frame = None

            if frame is None:
                fail_streak += 1
                if fail_streak >= _CAM_OFFLINE_AFTER and cam.online:
                    cam.online = False
                    warn(f"CAMERA OFFLINE: {cam.role} — {fail_streak} consecutive failures")
                    if self._session.active:
                        self._session.log_camera_event(cam.role, "offline", now_ms())
                time.sleep(0.033)
                continue

            # Successful frame — reset streak
            fail_streak = 0

            # Update raw frame cache (used by fusion overlay).
            # Read fusion client count and thermal frame here, under one lock
            # acquisition, to avoid a second lock for the fusion path.
            with self._cam_lock:
                self._cam_raw[cam.role]  = frame
                has_clients              = self._stream_clients.get(cam.role, 0) > 0
                has_fusion               = (cam.role == "rgb"
                                            and self._stream_clients.get("fusion", 0) > 0)
                thermal_raw              = self._cam_raw.get("thermal") if has_fusion else None

            # JPEG-encode only when streaming clients are connected for this role.
            if has_clients:
                jpeg = _encode_jpeg(frame)
                with self._cam_lock:
                    self._cam_frames[cam.role] = jpeg

            # Fusion overlay — computed only on the RGB loop, only when clients watch it.
            # Fusion is live-view only; frames are never written to any session file.
            if has_fusion and _FUSION_OK and self._fusion_overlay is not None:
                fcfg       = getattr(self._cfg, "fusion", None)
                homography = getattr(fcfg, "homography", None)
                alpha      = float(getattr(fcfg, "blend_alpha", 0.4))
                colormap   = str(getattr(fcfg, "colormap", "INFERNO"))
                fused = self._fusion_overlay.blend(
                    frame, thermal_raw, homography, alpha, colormap
                )
                fused_jpeg = _encode_jpeg(fused)
                with self._cam_lock:
                    self._cam_frames["fusion"] = fused_jpeg

            # Write to session if recording (fusion stream and resolution mismatches excluded)
            if self._session.active and resolution_ok:
                self._session.log_frame(cam.role, frame)

    # ──────────────────────────────────────────────────────────────────────
    def sensor_cache(self) -> dict:
        """Return the latest merged sensor row produced by the sampler loop.

        Serves pre-sampled values (refreshed at 20 Hz in the background thread)
        so the /sensors HTTP handler never blocks on live hardware reads.  Slow
        or misbehaving sensors no longer inflate response latency — previously
        each /sensors request read every sensor synchronously, so the 200 ms
        page poll stacked blocking I2C/serial reads until responses exceeded
        the client timeout, flipping the status between CONNECTED and CONN ERROR.
        """
        with self._cache_lock:
            if self._cache:
                return dict(self._cache)
        # Cold start: sampler hasn't produced a row yet — read synchronously once.
        row = {}
        for s in self._sensors:
            if s.online:
                try:
                    row.update(s.read())
                except Exception:
                    pass
        return row
