"""
SphereGuard robot server — entry point.

Usage (run from the robots/ directory):
    python -m shared.run --config sg01/config.yaml

Startup sequence:
  1. Parse args
  2. Load + validate config
  3. Reset PCA9685
  4. Init drive hardware (DriveServo, SteeringServo)
  5. Auto-detect sensors (I2C scan + UART + Pi-internal)
  6. Init cameras (open each enabled camera; failures are logged, not fatal)
  7. Create Session, Sampler, Watchdog
  8. Start Sampler (sensor + camera threads)
  9. Start Watchdog
 10. Safe init: stop drive, centre steering, 0.5s sleep
 11. Install SIGINT/SIGTERM handlers
 12. Start HTTP server (blocking)

Clean shutdown (Ctrl+C or SIGTERM from systemd):
  motors stop → watchdog stop → sampler stop (joins camera threads) →
  session flush → cameras release → server shutdown → server_close
  Hard fallback: os._exit(1) after 5 s if anything hangs.
"""

import argparse
import os
import signal
import sys
import threading
import time

from shared.config.loader         import load_config
from shared.drive.hardware        import DriveHardware
from shared.drive.drive_servo     import reset_pca9685
from shared.drive.watchdog        import Watchdog
from shared.sensors.registry      import detect
from shared.cameras.rgb_uvc       import RGBCamera
from shared.cameras.thermal_p2pro import ThermalP2Pro
from shared.recording.session     import Session
from shared.recording.sampler     import Sampler
from shared.server.http_server    import RobotHTTPServer
from shared.server.routes         import make_handler
from shared.util.log              import info, warn


def _init_cameras(cfg) -> list:
    cameras = []
    cam_cfgs = getattr(cfg, "cameras", []) or []
    for cam_cfg in cam_cfgs:
        if not getattr(cam_cfg, "enabled", False):
            continue
        role = getattr(cam_cfg, "role", "rgb")
        if role == "rgb":
            cam = RGBCamera(cam_cfg)
        elif role == "thermal":
            cam = ThermalP2Pro(cam_cfg)
        else:
            warn(f"Unknown camera role '{role}' — skipping")
            continue
        ok = cam.open()
        if not ok:
            warn(f"Camera '{role}' could not be opened — running without it")
        cameras.append(cam)
    return cameras


# Module-level references shared between main() and the signal handler
_hw       = None   # DriveHardware (owns both drive and steering)
_drive    = None   # alias → _hw (for shutdown handler .stop())
_steering = None   # alias → _hw (for shutdown handler .center())
_session  = None
_cameras  = []
_sampler  = None
_watchdog = None
_server   = None

_shutdown_started = threading.Event()  # idempotency guard


def _do_shutdown():
    """
    Actual shutdown work, always runs in a background thread so that
    server.shutdown() (which blocks until serve_forever() exits) is never
    called from inside the serve_forever thread itself.
    """
    # Hard fallback: if we're still alive after 5 s, force-exit.
    def _hard_exit():
        time.sleep(5)
        warn("Shutdown timed out — forcing exit")
        os._exit(1)

    t = threading.Thread(target=_hard_exit, daemon=True, name="shutdown_watchdog")
    t.start()

    # 1. Stop motors immediately
    try:
        if _drive:    _drive.stop()
        if _steering: _steering.center()
    except Exception:
        pass

    # 2. Stop watchdog thread
    try:
        if _watchdog: _watchdog.stop()
    except Exception:
        pass

    # 3. Stop sampler — joins camera threads so they stop reading frames
    #    BEFORE cameras are released (prevents VIDIOC_REQBUFS errno=19)
    try:
        if _sampler: _sampler.stop(join_timeout=1.0)
    except Exception:
        pass

    # 4. Flush active session (closes CSVs, releases VideoWriters)
    try:
        if _session and _session.active:
            _session.stop()
    except Exception:
        pass

    # 5. Release cameras (safe now — camera threads have exited)
    for cam in _cameras:
        try:
            cam.release()
        except Exception:
            pass

    # 6. Shut down HTTP server — unblocks serve_forever() in main thread
    try:
        if _server: _server.stop()
    except Exception:
        pass


def _shutdown(signum, frame):
    if _shutdown_started.is_set():
        return  # second Ctrl+C: ignore, hard fallback will fire
    _shutdown_started.set()
    info("Shutting down…")
    # Run in a background thread: server.shutdown() must not be called from
    # the serve_forever thread (deadlock) or from a signal handler that
    # interrupted serve_forever (also deadlocks on __is_shut_down.wait()).
    t = threading.Thread(target=_do_shutdown, daemon=True, name="shutdown")
    t.start()


def main():
    global _hw, _drive, _steering, _session, _cameras, _sampler, _watchdog, _server

    parser = argparse.ArgumentParser(description="SphereGuard robot server")
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    args = parser.parse_args()

    info(f"Loading config: {args.config}")
    cfg = load_config(args.config)
    info(f"Robot: {cfg.robot.id} — {cfg.robot.name}")
    info(f"Data dir: {cfg.paths.data_dir}")
    if not os.path.exists(cfg.paths.data_dir):
        warn(f"Data dir does not exist yet (will be created on first recording): {cfg.paths.data_dir}")

    # Drive hardware (DriveHardware wraps DriveServo + SteeringServo with health tracking)
    reset_pca9685()
    _hw       = DriveHardware(cfg)
    _drive    = _hw   # shutdown handler calls _drive.stop()
    _steering = _hw   # shutdown handler calls _steering.center()

    # Sensors
    info("Detecting sensors…")
    active_sensors = detect(cfg)
    info(f"Active sensors: {[s.name for s in active_sensors]}")

    # Cameras
    info("Initialising cameras…")
    _cameras = _init_cameras(cfg)
    info(f"Active cameras: {[c.role for c in _cameras if c._cap is not None]}")

    # Recording infrastructure
    _session  = Session()
    _sampler  = Sampler(active_sensors, _session, _cameras, cfg)
    _watchdog = Watchdog(_hw, _hw, _session, hardware=_hw)

    # Give the Pi sensor a session reference so the auto speed test can check
    # whether recording is in progress before firing.
    _pi = next((s for s in active_sensors if type(s).__name__ == "PiInternal"), None)
    if _pi is not None:
        _pi.set_session(_session)

    # Start background threads
    _sampler.start()
    _watchdog.start()

    # Safe hardware init
    _drive.stop()
    _steering.center()
    time.sleep(0.5)

    # Signal handlers — SIGTERM is what systemd sends on stop
    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # HTTP server — blocks until _server.stop() is called from _do_shutdown()
    handler_cls = make_handler(
        cfg, _sampler, _drive, _steering, _watchdog,
        _session, _cameras, active_sensors, hw=_hw
    )
    _server = RobotHTTPServer(cfg.server.host, cfg.server.port, handler_cls)
    info(f"Serving on http://{cfg.server.host}:{cfg.server.port}")
    _server.start(block=True)
    # serve_forever() returns here after _server.stop() calls shutdown()
    info("Server stopped — bye")


if __name__ == "__main__":
    main()
