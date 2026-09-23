"""
HTTP request handler — all endpoints for the robot server.

All responses include CORS headers (Access-Control-Allow-Origin: *).
The handler class is created via make_handler() which closes over all
shared objects so no global state is needed.

Endpoints:
  GET  /             → serve control.html
  GET  /config       → config.html (calibration page)
  GET  /api/config   → current config as JSON (?cal=1 adds BNO055 calibration)
  POST /api/config   → validate + write config.yaml + live-apply safe values
  GET  /settings     → current drive/servo values (includes deadzone)
  GET  /sensors      → latest sensor cache as JSON
  GET  /record       → {recording, session_id, filename}
  GET  /stream       → MJPEG rgb (alias for /stream/rgb)
  GET  /stream/rgb   → MJPEG rgb
  GET  /stream/thermal → MJPEG thermal (image half only)
  GET  /stream/fusion  → MJPEG blended thermal+rgb overlay (experimental)
  GET  /fusion         → serve fusion.html (experimental)
  GET  /api/fusion     → current fusion homography + blend settings
  POST /api/fusion     → save blend_alpha / colormap to config.yaml
  GET  /api/nettest    → latest speed test result {status, download_mbps, ...}
  POST /api/nettest    → start on-demand speed test; returns {status:"running"}
  POST /joystick     → {x, y} → joystick_to_drive → apply → log
  POST /command      → {action, ...} → handle_action → log
  POST /record       → {action: start|stop}
  OPTIONS *          → CORS 204
"""

import json
import os
import time
from http.server import BaseHTTPRequestHandler
from pathlib     import Path
from urllib.parse import urlparse, parse_qs

from shared.drive.mixer    import joystick_to_drive
from shared.config.writer  import write_config, apply_live
from shared.util.log       import warn

try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False

_WEB_DIR = Path(__file__).parent / "web"
_CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _current_settings(cfg) -> dict:
    return {
        "forward_speed":  cfg.drive.forward_speed,
        "backward_speed": cfg.drive.backward_speed,
        "spin_speed":     cfg.drive.spin_speed,
        "deadzone":       cfg.drive.deadzone,
        "servo_center":   cfg.steering.servo_center,
        "servo_left":     cfg.steering.servo_left,
        "servo_right":    cfg.steering.servo_right,
    }


def make_handler(cfg, sampler, drive, steering, watchdog, session, cameras, active_sensors, hw=None):
    """
    Return a handler class with all dependencies closed over.

    cameras: list of Camera instances
    active_sensors: list of Sensor instances (for calibration status)
    """
    # PiInternal instance — used for speed test endpoints.
    _pi = next((s for s in active_sensors if type(s).__name__ == "PiInternal"), None)

    class RobotHandler(BaseHTTPRequestHandler):
        log_message = lambda self, *a: None  # suppress access log

        def _send_cors(self, code: int, content_type: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            for k, v in _CORS_HEADERS.items():
                self.send_header(k, v)
            self.end_headers()

        def _json(self, data: dict, code: int = 200) -> None:
            body = json.dumps(data).encode()
            self._send_cors(code)
            self.wfile.write(body)

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length))

        # ── OPTIONS ───────────────────────────────────────────────────────
        def do_OPTIONS(self):
            self._send_cors(204)

        # ── GET ───────────────────────────────────────────────────────────
        def do_GET(self):
            parsed  = urlparse(self.path)
            path    = parsed.path.rstrip("/") or "/"
            params  = parse_qs(parsed.query)

            if path == "/":
                self._serve_file(_WEB_DIR / "control.html", "text/html; charset=utf-8")

            elif path == "/config":
                self._serve_file(_WEB_DIR / "config.html", "text/html; charset=utf-8")

            elif path == "/settings":
                self._json({"settings": _current_settings(cfg)})

            elif path == "/api/config":
                data = {
                    "robot": {"id": cfg.robot.id, "name": cfg.robot.name,
                              "description": getattr(cfg.robot, "description", "")},
                    "drive": vars(cfg.drive) if hasattr(cfg.drive, "__dict__") else {},
                    "steering": vars(cfg.steering) if hasattr(cfg.steering, "__dict__") else {},
                    "body":    vars(cfg.body)    if hasattr(cfg.body, "__dict__")    else {},
                    "logging": vars(cfg.logging) if hasattr(cfg.logging, "__dict__") else {},
                    "cameras": [vars(c) if hasattr(c, "__dict__") else {} for c in
                                (cfg.cameras if hasattr(cfg, "cameras") else [])],
                    "sensors": [
                        {"name": s.name, "address": hex(s.addr) if s.addr else "n/a",
                         "fixed": s.is_fixed, "online": s.online}
                        for s in active_sensors
                    ],
                }
                if params.get("cal"):
                    for s in active_sensors:
                        if hasattr(s, "calibration_status"):
                            sys, gyro, accel, mag = s.calibration_status()
                            data["calibration"] = {"sys": sys, "gyro": gyro,
                                                   "accel": accel, "mag": mag}
                            break
                self._json(data)

            elif path == "/sensors":
                row = sampler.sensor_cache()
                row["robot_id"]   = cfg.robot.id
                row["robot_name"] = cfg.robot.name
                row["_hardware"]  = {
                    "sensors": [
                        {"name": s.name, "online": s.online,
                         "fail_streak": s.fail_streak}
                        for s in active_sensors
                    ],
                    "cameras": [
                        {"role": c.role, "online": c.online}
                        for c in cameras
                    ],
                    "drive": {"online": hw.online if hw is not None else True},
                }
                self._json(row)

            elif path == "/record":
                self._json({
                    "recording":  session.active,
                    "session_id": session.session_id,
                    "filename":   session.session_id,
                })

            elif path in ("/stream", "/stream/rgb"):
                self._serve_mjpeg("rgb")

            elif path == "/stream/thermal":
                self._serve_mjpeg("thermal")

            elif path == "/stream/fusion":
                self._serve_mjpeg("fusion")

            elif path == "/fusion":
                self._serve_file(_WEB_DIR / "fusion.html", "text/html; charset=utf-8")

            elif path == "/api/fusion":
                self._handle_fusion_get()

            elif path == "/api/nettest":
                self._handle_nettest_get()

            else:
                self._send_cors(404, "text/plain")
                self.wfile.write(b"Not found")

        # ── POST ──────────────────────────────────────────────────────────
        def do_POST(self):
            parsed = urlparse(self.path)
            path   = parsed.path.rstrip("/")
            data   = self._read_body()

            if path == "/joystick":
                self._handle_joystick(data)
            elif path == "/command":
                self._handle_command(data)
            elif path == "/record":
                self._handle_record(data)
            elif path == "/api/config":
                self._handle_config_save(data)
            elif path == "/api/fusion":
                self._handle_fusion_save(data)
            elif path == "/api/nettest":
                self._handle_nettest_post()
            else:
                self._json({"status": "unknown endpoint"}, 404)

        # ── Endpoint implementations ───────────────────────────────────────
        def _handle_joystick(self, data: dict) -> None:
            x = max(-1.0, min(1.0, float(data.get("x", 0))))
            y = max(-1.0, min(1.0, float(data.get("y", 0))))
            angle, throttle = joystick_to_drive(x, y, cfg)
            steering.set_angle(angle)
            drive.set_throttle(throttle)
            watchdog.heartbeat()
            if session.active:
                session.log_command("joystick", "move",
                                    x=x, y=y, angle=angle, throttle=throttle)
            self._json({"status": "ok", "settings": _current_settings(cfg)})

        def _handle_command(self, data: dict) -> None:
            action  = data.get("action", "stop")
            watchdog.heartbeat()

            if action == "forward":
                steering.set_angle(cfg.steering.servo_center)
                drive.set_throttle(cfg.drive.forward_speed)
            elif action == "backward":
                steering.set_angle(cfg.steering.servo_center)
                drive.set_throttle(-cfg.drive.backward_speed)
            elif action == "left":
                steering.set_angle(cfg.steering.servo_left)
                drive.set_throttle(cfg.drive.forward_speed)
            elif action == "right":
                steering.set_angle(cfg.steering.servo_right)
                drive.set_throttle(cfg.drive.forward_speed)
            elif action == "set_speed":
                for k in ("forward_speed", "backward_speed", "spin_speed"):
                    if k in data:
                        setattr(cfg.drive, k, max(0.0, min(1.0, float(data[k]))))
            elif action == "set_servo":
                for k in ("servo_center", "servo_left", "servo_right"):
                    if k in data:
                        setattr(cfg.steering, k, max(0, min(180, int(data[k]))))
                steering.center()
            else:  # stop
                drive.stop()
                steering.center()

            if session.active:
                session.log_command("button", action,
                                    angle=steering.angle, throttle=drive.throttle,
                                    extra=str({k: v for k, v in data.items()
                                               if k != "action"}))
            self._json({"status": "ok", "settings": _current_settings(cfg)})

        def _handle_record(self, data: dict) -> None:
            action = data.get("action", "")
            if action == "start" and not session.active:
                enabled_cams = [c for c in cameras if c.enabled and c._cap is not None]
                session.start(cfg, active_sensors, enabled_cams)
            elif action == "stop" and session.active:
                session.stop()
            self._json({
                "status":     "ok",
                "recording":  session.active,
                "session_id": session.session_id,
                "filename":   session.session_id,
            })

        def _handle_config_save(self, data: dict) -> None:
            if not _YAML_OK:
                self._json({"status": "error", "message": "PyYAML not available"}, 500)
                return
            try:
                from shared.config.loader import load_config, _assert
                # Validate the incoming data before writing
                # Basic checks (full validation happens by reloading)
                drive_d    = data.get("drive", {})
                steering_d = data.get("steering", {})
                body_d     = data.get("body", {})
                for k in ("forward_speed", "backward_speed", "spin_speed"):
                    if k in drive_d:
                        v = float(drive_d[k])
                        if not (0 < v <= 1.0):
                            raise ValueError(f"drive.{k} must be in (0,1]")
                for k in ("servo_center", "servo_left", "servo_right"):
                    if k in steering_d:
                        v = int(steering_d[k])
                        if not (0 <= v <= 180):
                            raise ValueError(f"steering.{k} must be 0-180")

                # Load current YAML, merge incoming data, write atomically
                with open(cfg.paths._config_path) as f:
                    current = yaml.safe_load(f) or {}
                for section, updates in data.items():
                    if isinstance(updates, dict) and section in current:
                        current[section].update(updates)
                    elif (section == "cameras" and isinstance(updates, list)
                          and isinstance(current.get(section), list)):
                        for cam_update in updates:
                            role = cam_update.get("role")
                            for cam in current[section]:
                                if cam.get("role") == role:
                                    cam.update({k: v for k, v in cam_update.items()
                                                if k != "role"})
                write_config(cfg.paths._config_path, current)

                # Apply live-safe changes
                applied = apply_live(cfg, data, drive, steering)

                self._json({
                    "status":          "ok",
                    "applied_live":    applied,
                    "restart_required": [k for section in data
                                         for k in (data[section] if isinstance(data[section], dict) else {})
                                         if f"{section}.{k}" not in applied],
                })
            except Exception as e:
                self._json({"status": "error", "message": str(e)}, 400)

        def _handle_nettest_get(self) -> None:
            if _pi is None:
                self._json({"status": "unavailable"}, 503)
                return
            self._json(_pi.speed_test_result)

        def _handle_nettest_post(self) -> None:
            if _pi is None:
                self._json({"status": "error", "message": "Pi sensor unavailable"}, 503)
                return
            started = _pi.run_speed_test("manual")
            if started:
                self._json({"status": "running"})
            else:
                is_rec = session.active
                msg = (
                    "Recording in progress — stop recording before running a speed test"
                    if is_rec else "Test already running"
                )
                self._json({"status": "error", "message": msg}, 409)

        def _handle_fusion_get(self) -> None:
            fcfg = getattr(cfg, "fusion", None)
            self._json({
                "homography":             getattr(fcfg, "homography", None),
                "calibration_date":       getattr(fcfg, "calibration_date", None),
                "calibration_distance_m": getattr(fcfg, "calibration_distance_m", None),
                "blend_alpha":            float(getattr(fcfg, "blend_alpha", 0.4)),
                "colormap":               str(getattr(fcfg, "colormap", "INFERNO")),
            })

        def _handle_fusion_save(self, data: dict) -> None:
            if not _YAML_OK:
                self._json({"status": "error", "message": "PyYAML not available"}, 500)
                return
            try:
                with open(cfg.paths._config_path) as f:
                    current = yaml.safe_load(f) or {}
                if not isinstance(current.get("fusion"), dict):
                    current["fusion"] = {}
                if "blend_alpha" in data:
                    current["fusion"]["blend_alpha"] = float(data["blend_alpha"])
                if "colormap" in data:
                    current["fusion"]["colormap"] = str(data["colormap"])
                write_config(cfg.paths._config_path, current)
                # Live-apply without restart
                fcfg = getattr(cfg, "fusion", None)
                if fcfg is not None:
                    if "blend_alpha" in data:
                        fcfg.blend_alpha = float(data["blend_alpha"])
                    if "colormap" in data:
                        fcfg.colormap = str(data["colormap"])
                self._json({"status": "ok"})
            except Exception as e:
                self._json({"status": "error", "message": str(e)}, 400)

        def _serve_file(self, path, content_type: str) -> None:
            try:
                with open(path, "rb") as f:
                    body = f.read()
                self._send_cors(200, content_type)
                self.wfile.write(body)
            except FileNotFoundError:
                self._send_cors(404, "text/plain")
                self.wfile.write(b"Not found")

        def _serve_mjpeg(self, role: str = "rgb") -> None:
            # Fusion is computed by the sampler — skip the camera-object check.
            if role != "fusion":
                cam = next((c for c in cameras if c.role == role), None)
                if cam is None or cam._cap is None or not cam.online:
                    self._send_cors(503, "text/plain")
                    self.wfile.write(f"Camera '{role}' unavailable".encode())
                    return

            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            for k, v in _CORS_HEADERS.items():
                self.send_header(k, v)
            self.end_headers()

            sampler.inc_stream_client(role)
            try:
                while True:
                    jpeg = sampler.get_jpeg(role)
                    if jpeg:
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                            + jpeg + b"\r\n"
                        )
                    time.sleep(0.033)
            except Exception:
                pass
            finally:
                sampler.dec_stream_client(role)

    return RobotHandler
