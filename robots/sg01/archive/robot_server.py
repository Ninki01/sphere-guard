"""
Robot Server (Joystick) - Raspberry Pi
=======================================
Pin reference:
  Channel 0 → SPT5535LV  drive motor  (continuous_servo, throttle -1.0 to 1.0)
  Channel 1 → PTK7465WMG weight servo (standard servo,   angle 0–180°)

Commands accepted via POST /command:
  { "action": "forward" | "backward" | "left" | "right" | "stop" }
  { "action": "set_speed", "forward": 0.5, "backward": 0.4, "spin": 0.25 }
  { "action": "set_servo", "center": 90, "left": 135, "right": 45 }

Joystick via POST /joystick:
  { "x": -1.0 to 1.0, "y": -1.0 to 1.0 }
  x = steering (-1 full left, +1 full right)
  y = throttle  (-1 full back, +1 full forward)
  Spin boost: when |x| > deadzone and |y| < deadzone,
              a minimum forward throttle is applied so the
              ball keeps rolling and momentum is maintained.

Recording via POST /record:
  { "action": "start" | "stop" }
  Creates sensor_log/session_YYYY-MM-DD_HH-MM-SS/ with:
    meta.json, sensors.csv, commands.csv, frames.csv, video.avi

Lock inventory (never nest in reverse order):
  _sensor_lock  — _sensor_cache dict (sampling thread writes, /sensors reads)
  _session_lock — session dict, all CSV handles, counters (sampling + camera
                  threads write; HTTP threads start/stop; always outermost
                  except when nested inside _cmd_lock)
  _vid_lock     — _vid_writer (camera thread writes, stop_recording releases)
  _cam_lock     — _cam_frame bytes (camera thread writes, /stream reads)
  _cmd_lock     — commands.csv + _last_joy state (multiple HTTP threads);
                  always acquired BEFORE _session_lock when nesting

  last_joystick_ms — plain int, no lock (CPython GIL makes int r/w atomic);
                     written by HTTP threads, read by watchdog thread

Run:
  python robot_server.py

Open on tablet:
  http://sg01.local:5000
"""

import json
import time
import os
import csv
import socket
import threading
from pathlib import Path
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
try:
    from http.server import ThreadingHTTPServer
except ImportError:
    from socketserver import ThreadingMixIn
    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        pass
import board
import busio
from adafruit_servokit import ServoKit
try:
    import cv2
    CV2_OK = True
except ImportError:
    CV2_OK = False
    print("cv2 not available — camera stream disabled")

# ── Helpers ───────────────────────────────────────────────────────────────────
_MYT = timedelta(hours=8)

def now_ms():
    return int(time.time() * 1000)

def _ms_to_myt(ms):
    dt = datetime.utcfromtimestamp(ms / 1000) + _MYT
    return dt.strftime("%Y-%m-%d %H:%M:%S MYT")

# ── PCA9685 reset ─────────────────────────────────────────────────────────────
def reset_pca9685():
    i2c = busio.I2C(board.SCL, board.SDA)
    while not i2c.try_lock():
        pass
    try:
        i2c.writeto(0x00, bytes([0x06]))
        print("PCA9685 reset OK")
    except Exception as e:
        print(f"Reset warning: {e}")
    finally:
        i2c.unlock()
        i2c.deinit()
    time.sleep(0.1)

reset_pca9685()

# ── ServoKit init ─────────────────────────────────────────────────────────────
kit = ServoKit(channels=16)

drive_servo  = kit.continuous_servo[0]  # SPT5535LV
weight_servo = kit.servo[1]             # PTK7465WMG

drive_servo.set_pulse_width_range(500, 2500)
weight_servo.set_pulse_width_range(500, 2500)

# ── Live-adjustable settings ──────────────────────────────────────────────────
settings = {
    "forward_speed":  0.40,
    "backward_speed": 0.40,
    "spin_speed":     0.25,
    "servo_center":   90,
    "servo_left":     135,
    "servo_right":    45,
}

# ── Sensor init (BNO055 IMU + BME280) ────────────────────────────────────────
_i2c = busio.I2C(board.SCL, board.SDA)

try:
    import adafruit_bno055
    _bno = adafruit_bno055.BNO055_I2C(_i2c)
    BNO_OK = True
    print("BNO055 ready")
except Exception as e:
    BNO_OK = False
    print(f"BNO055 not available: {e}")

try:
    import adafruit_bme280.basic as adafruit_bme280
    _bme = adafruit_bme280.Adafruit_BME280_I2C(_i2c)
    BME_OK = True
    print("BME280 ready")
except Exception as e:
    BME_OK = False
    print(f"BME280 not available: {e}")

# ── Session folder root ───────────────────────────────────────────────────────
LOG_DIR = str(Path(__file__).resolve().parent.parent.parent / "data" / "sensor_log")
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

# ── CSV column definitions ────────────────────────────────────────────────────
SENSOR_COLS         = ["pitch", "roll", "heading",
                        "lin_acc_x", "lin_acc_y", "lin_acc_z",
                        "gyro_x",    "gyro_y",    "gyro_z",
                        "temp", "humidity", "pressure", "pi_temp", "wifi_dbm",
                        "internet"]
SENSORS_CSV_HEADER  = ["t_ms"] + SENSOR_COLS
COMMANDS_CSV_HEADER = ["t_ms", "source", "action", "x", "y",
                        "servo_angle", "throttle", "extra"]
FRAMES_CSV_HEADER   = ["frame_index", "t_ms"]

# ── Sensor cache (shared between sampling thread and /sensors endpoint) ───────
_sensor_cache = {k: 0 for k in SENSOR_COLS}
_sensor_lock  = threading.Lock()

# ── Session state (all CSV handles and counters) ──────────────────────────────
session = {
    "active":          False,
    "id":              None,
    "folder":          None,
    "start_ms":        None,
    "settings_snap":   None,
    "sensors_fh":      None,
    "sensors_writer":  None,
    "commands_fh":     None,
    "commands_writer": None,
    "frames_fh":       None,
    "frames_writer":   None,
    "row_counts":      {"sensors": 0, "commands": 0, "frames": 0},
    "frame_index":     0,
}
_session_lock = threading.Lock()

_vid_writer   = None
_vid_lock     = threading.Lock()

_cmd_lock        = threading.Lock()
_last_joy        = {"servo_angle": None, "throttle": None}
last_joystick_ms = now_ms()   # refreshed by every /joystick and /command POST

# ── IMU sampling thread (20 Hz) ───────────────────────────────────────────────
def _sampling_loop():
    bme_tick = 0
    while True:
        t0 = time.monotonic()
        ms = now_ms()
        snap = {}

        if BNO_OK:
            try:
                e = _bno.euler
                snap["heading"] = round(e[0] or 0, 1)
                snap["roll"]    = round(e[1] or 0, 1)
                snap["pitch"]   = round(e[2] or 0, 1)
            except Exception:
                pass
            try:
                la = _bno.linear_acceleration
                snap["lin_acc_x"] = round(la[0] or 0, 3)
                snap["lin_acc_y"] = round(la[1] or 0, 3)
                snap["lin_acc_z"] = round(la[2] or 0, 3)
            except Exception:
                pass
            try:
                gy = _bno.gyro
                snap["gyro_x"] = round(gy[0] or 0, 4)
                snap["gyro_y"] = round(gy[1] or 0, 4)
                snap["gyro_z"] = round(gy[2] or 0, 4)
            except Exception:
                pass

        if bme_tick == 0:
            if BME_OK:
                try:
                    snap["temp"]     = round(_bme.temperature, 1)
                    snap["humidity"] = round(_bme.humidity, 1)
                    snap["pressure"] = round(_bme.pressure, 1)
                except Exception:
                    pass
            try:
                with open("/sys/class/thermal/thermal_zone0/temp") as _tf:
                    snap["pi_temp"] = round(int(_tf.read().strip()) / 1000.0, 1)
            except Exception:
                pass
            try:
                with open("/proc/net/wireless") as _wf:
                    for _wl in _wf:
                        if "wlan0" in _wl:
                            snap["wifi_dbm"] = round(float(_wl.split()[3].rstrip(".")), 1)
                            break
            except Exception:
                pass
        bme_tick = (bme_tick + 1) % 40

        snap["internet"] = 1 if _internet_ok else 0

        with _sensor_lock:
            _sensor_cache.update(snap)
            current = dict(_sensor_cache)

        with _session_lock:
            if session["active"] and session["sensors_writer"] is not None:
                session["sensors_writer"].writerow(
                    [ms] + [current.get(k, 0) for k in SENSOR_COLS]
                )
                session["row_counts"]["sensors"] += 1
                if session["row_counts"]["sensors"] % 20 == 0:
                    session["sensors_fh"].flush()

        elapsed = time.monotonic() - t0
        time.sleep(max(0.0, 0.050 - elapsed))

threading.Thread(target=_sampling_loop, daemon=True).start()

# ── Meta JSON helpers ─────────────────────────────────────────────────────────
def _write_meta(folder, session_id, start_ms, settings_snap, extra=None):
    meta = {
        "session_id":        session_id,
        "device_id":         "sg01",
        "start_time_ms":     start_ms,
        "start_time_local":  _ms_to_myt(start_ms),
        "settings":          settings_snap,
    }
    if extra:
        meta.update(extra)
    tmp = os.path.join(folder, "meta.json.tmp")
    with open(tmp, "w") as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp, os.path.join(folder, "meta.json"))

# ── Session start / stop ──────────────────────────────────────────────────────
def start_recording():
    global _vid_writer

    ts            = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_id    = f"session_{ts}"
    folder        = os.path.join(LOG_DIR, session_id)
    start_ms      = now_ms()
    settings_snap = dict(settings)

    os.makedirs(folder, exist_ok=True)

    with _session_lock:
        if session["active"]:
            return  # guard double-start

        sfh = open(os.path.join(folder, "sensors.csv"),  "w", newline="")
        sw  = csv.writer(sfh)
        sw.writerow(SENSORS_CSV_HEADER)

        cfh = open(os.path.join(folder, "commands.csv"), "w", newline="")
        cw  = csv.writer(cfh)
        cw.writerow(COMMANDS_CSV_HEADER)

        ffh = open(os.path.join(folder, "frames.csv"),   "w", newline="")
        fw  = csv.writer(ffh)
        fw.writerow(FRAMES_CSV_HEADER)

        session.update({
            "active":          True,
            "id":              session_id,
            "folder":          folder,
            "start_ms":        start_ms,
            "settings_snap":   settings_snap,
            "sensors_fh":      sfh,  "sensors_writer":  sw,
            "commands_fh":     cfh,  "commands_writer": cw,
            "frames_fh":       ffh,  "frames_writer":   fw,
            "row_counts":      {"sensors": 0, "commands": 0, "frames": 0},
            "frame_index":     0,
        })

        # Write initial meta inside the lock so stop can't race with this write
        _write_meta(folder, session_id, start_ms, settings_snap)

    # VideoWriter acquired separately to avoid _session_lock ↔ _vid_lock nesting
    if _cam_ok and CV2_OK:
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        with _vid_lock:
            _vid_writer = cv2.VideoWriter(
                os.path.join(folder, "video.avi"), fourcc, 20.0, (640, 480)
            )
        print(f"[REC] Video  → {session_id}/video.avi")

    print(f"[REC] Session started → {session_id}")


def stop_recording():
    global _vid_writer

    # Phase 1: deactivate — sampling and camera threads see active=False immediately
    with _session_lock:
        if not session["active"]:
            return  # guard double-stop
        session["active"] = False

    # Phase 2: release VideoWriter (separate lock, no nesting with _session_lock)
    with _vid_lock:
        if _vid_writer is not None:
            _vid_writer.release()
            _vid_writer = None

    # Phase 3: flush/close CSV handles and capture final counters
    with _session_lock:
        session_id    = session["id"]
        folder        = session["folder"]
        start_ms      = session["start_ms"]
        settings_snap = session["settings_snap"]
        row_counts    = dict(session["row_counts"])
        frame_count   = session["frame_index"]

        for fh_key, writer_key in [
            ("sensors_fh",  "sensors_writer"),
            ("commands_fh", "commands_writer"),
            ("frames_fh",   "frames_writer"),
        ]:
            fh = session[fh_key]
            if fh is not None:
                try:
                    fh.flush()
                    fh.close()
                except Exception:
                    pass
            session[fh_key]     = None
            session[writer_key] = None

        session.update({
            "id": None, "folder": None,
            "start_ms": None, "settings_snap": None,
        })

    # Phase 4: write final meta (local copies, no lock needed)
    end_ms = now_ms()
    _write_meta(folder, session_id, start_ms, settings_snap, extra={
        "end_time_ms":    end_ms,
        "end_time_local": _ms_to_myt(end_ms),
        "duration_s":     round((end_ms - start_ms) / 1000, 2),
        "rows":           row_counts,
        "video_frames":   frame_count,
    })
    print(f"[REC] Session stopped → {session_id}")

# ── Command logger ─────────────────────────────────────────────────────────────
def _log_command(source, action, x, y, servo_angle, throttle, extra=""):
    with _cmd_lock:
        with _session_lock:
            if session["active"] and session["commands_writer"] is not None:
                session["commands_writer"].writerow([
                    now_ms(), source, action, x, y, servo_angle, throttle, extra
                ])
                session["row_counts"]["commands"] += 1
                session["commands_fh"].flush()

# ── Camera (Logitech Brio 100 on /dev/video0) ────────────────────────────────
_cam_frame = None
_cam_lock  = threading.Lock()
_cam_ok    = False

if CV2_OK:
    try:
        _cam = cv2.VideoCapture(0)
        _cam.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        _cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        _cam.set(cv2.CAP_PROP_FPS, 30)
        _cam_ok = _cam.isOpened()
        print("Camera ready" if _cam_ok else "Camera not available")
    except Exception as e:
        print(f"Camera error: {e}")

def _camera_loop():
    global _cam_frame
    while _cam_ok:
        ret, frame = _cam.read()
        if not ret:
            continue

        # Update MJPEG stream buffer
        _, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        with _cam_lock:
            _cam_frame = jpg.tobytes()

        # Write AVI frame (separate lock acquisition — never nested with _session_lock)
        wrote_video = False
        with _vid_lock:
            if _vid_writer is not None:
                _vid_writer.write(frame)
                wrote_video = True

        # Log frame timestamp sidecar (separate lock acquisition — no deadlock risk)
        if wrote_video:
            ms = now_ms()
            with _session_lock:
                if session["active"] and session["frames_writer"] is not None:
                    session["frames_writer"].writerow([session["frame_index"], ms])
                    session["frame_index"] += 1
                    session["row_counts"]["frames"] += 1
                    if session["row_counts"]["frames"] % 20 == 0:
                        session["frames_fh"].flush()

if _cam_ok:
    threading.Thread(target=_camera_loop, daemon=True).start()

# ── Dead-man's watchdog (100 ms tick) ────────────────────────────────────────
WATCHDOG_TIMEOUT_MS = 500   # ms of silence before auto-stop
WATCHDOG_INTERVAL   = 0.1   # seconds between checks

def _watchdog_loop():
    while True:
        time.sleep(WATCHDOG_INTERVAL)
        try:
            if (drive_servo.throttle != 0.0 and
                    (now_ms() - last_joystick_ms) > WATCHDOG_TIMEOUT_MS):
                drive_servo.throttle = 0.0
                weight_servo.angle   = settings["servo_center"]
                print("WATCHDOG: input lost, motors stopped")
                _log_command("watchdog", "auto_stop", "", "",
                             settings["servo_center"], 0.0)
        except Exception:
            pass

threading.Thread(target=_watchdog_loop, daemon=True).start()

# ── Internet connectivity check ───────────────────────────────────────────────
_internet_ok = False

def _internet_check_loop():
    global _internet_ok
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(("8.8.8.8", 53))
            s.close()
            _internet_ok = True
        except Exception:
            _internet_ok = False
        time.sleep(10)

threading.Thread(target=_internet_check_loop, daemon=True).start()

# ── Joystick → drive mapping ──────────────────────────────────────────────────
DEADZONE = 0.12

def joystick_to_drive(x, y):
    # Weight servo: x=-1 → servo_left, x=0 → servo_center, x=+1 → servo_right
    half_range  = settings["servo_center"] - settings["servo_right"]
    servo_angle = round(settings["servo_center"] - x * half_range)
    servo_angle = max(0, min(180, servo_angle))

    # Throttle: scale y by forward/backward speed limits
    if y >= 0:
        throttle = y * settings["forward_speed"]
    else:
        throttle = y * settings["backward_speed"]

    # Spin boost: steering without meaningful Y → inject minimum drive so the
    # ball keeps rolling and the weight shift actually causes a pivot
    if abs(x) > DEADZONE and abs(y) < DEADZONE:
        throttle = settings["spin_speed"]

    return servo_angle, throttle

# ── Action handler ─────────────────────────────────────────────────────────────
def handle_action(data):
    action = data.get("action", "stop").lower()

    if action == "forward":
        weight_servo.angle   = settings["servo_center"]
        drive_servo.throttle = settings["forward_speed"]

    elif action == "backward":
        weight_servo.angle   = settings["servo_center"]
        drive_servo.throttle = -settings["backward_speed"]

    elif action == "left":
        weight_servo.angle   = settings["servo_left"]
        drive_servo.throttle = settings["forward_speed"]

    elif action == "right":
        weight_servo.angle   = settings["servo_right"]
        drive_servo.throttle = settings["forward_speed"]

    elif action == "set_speed":
        if "forward" in data:
            settings["forward_speed"]  = max(0.0, min(1.0, float(data["forward"])))
        if "backward" in data:
            settings["backward_speed"] = max(0.0, min(1.0, float(data["backward"])))
        if "spin" in data:
            settings["spin_speed"]     = max(0.0, min(1.0, float(data["spin"])))
        print(f"  Speed → fwd:{settings['forward_speed']:.2f}  bwd:{settings['backward_speed']:.2f}  spin:{settings['spin_speed']:.2f}")

    elif action == "set_servo":
        if "center" in data:
            settings["servo_center"] = max(0, min(180, int(data["center"])))
        if "left" in data:
            settings["servo_left"]   = max(0, min(180, int(data["left"])))
        if "right" in data:
            settings["servo_right"]  = max(0, min(180, int(data["right"])))
        weight_servo.angle = settings["servo_center"]
        print(f"  Servo updated → center:{settings['servo_center']}°  left:{settings['servo_left']}°  right:{settings['servo_right']}°")

    else:  # stop
        drive_servo.throttle = 0.0
        weight_servo.angle   = settings["servo_center"]

    print(f"[CMD] {action.upper()}")
    return settings

# ── HTTP server ───────────────────────────────────────────────────────────────
CONTROLLER_HTML = os.path.join(os.path.dirname(__file__), "robot_controller.html")

class RobotHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_ok(self, payload):
        resp = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self._cors()
        self.end_headers()
        self.wfile.write(resp)

    def _json_err(self, msg, code=400):
        resp = json.dumps({"status": "error", "message": msg}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(resp)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/settings":
            self._json_ok(settings)
            return

        if self.path == "/sensors":
            with _sensor_lock:
                data = dict(_sensor_cache)
            self._json_ok(data)
            return

        if self.path == "/record":
            with _session_lock:
                state = {
                    "recording":  session["active"],
                    "session_id": session["id"],
                    "filename":   session["id"],   # alias for tablet UI compat
                }
            self._json_ok(state)
            return

        if self.path == "/stream":
            if not _cam_ok:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b"Camera not available")
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self._cors()
            self.end_headers()
            try:
                while True:
                    with _cam_lock:
                        frame_data = _cam_frame
                    if frame_data:
                        self.wfile.write(
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(frame_data)).encode() + b"\r\n\r\n" +
                            frame_data + b"\r\n"
                        )
                    time.sleep(0.033)
            except Exception:
                pass
            return

        try:
            with open(CONTROLLER_HTML, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self._cors()
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"robot_controller.html not found.")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)

        if self.path == "/joystick":
            try:
                global last_joystick_ms
                data    = json.loads(body)
                x       = max(-1.0, min(1.0, float(data.get("x", 0))))
                y       = max(-1.0, min(1.0, float(data.get("y", 0))))
                angle, throttle = joystick_to_drive(x, y)
                weight_servo.angle   = angle
                drive_servo.throttle = throttle
                last_joystick_ms     = now_ms()

                # Log on change only (_cmd_lock → _session_lock, consistent nesting)
                if session["active"]:
                    with _cmd_lock:
                        if (angle != _last_joy["servo_angle"] or
                                throttle != _last_joy["throttle"]):
                            _last_joy["servo_angle"] = angle
                            _last_joy["throttle"]    = throttle
                            with _session_lock:
                                if (session["active"] and
                                        session["commands_writer"] is not None):
                                    session["commands_writer"].writerow([
                                        now_ms(), "joystick", "",
                                        x, y, angle, throttle, ""
                                    ])
                                    session["row_counts"]["commands"] += 1
                                    session["commands_fh"].flush()

                self._json_ok({"status": "ok", "settings": settings})
            except Exception as e:
                self._json_err(str(e))
            return

        if self.path == "/record":
            try:
                data   = json.loads(body)
                action = data.get("action", "").lower()
                if action == "start" and not session["active"]:
                    start_recording()
                elif action == "stop" and session["active"]:
                    stop_recording()
                with _session_lock:
                    resp = {
                        "status":     "ok",
                        "recording":  session["active"],
                        "session_id": session["id"],
                        "filename":   session["id"],   # alias for tablet UI compat
                    }
                self._json_ok(resp)
            except Exception as e:
                self._json_err(str(e))
            return

        if self.path == "/command":
            try:
                data             = json.loads(body)
                current_settings = handle_action(data)
                last_joystick_ms = now_ms()
                action           = data.get("action", "stop").lower()

                sa, th, source, extra = "", "", "button", ""
                if action == "forward":
                    sa, th = settings["servo_center"],  settings["forward_speed"]
                elif action == "backward":
                    sa, th = settings["servo_center"], -settings["backward_speed"]
                elif action == "left":
                    sa, th = settings["servo_left"],    settings["forward_speed"]
                elif action == "right":
                    sa, th = settings["servo_right"],   settings["forward_speed"]
                elif action == "stop":
                    sa, th = settings["servo_center"],  0.0
                elif action in ("set_speed", "set_servo"):
                    source = "settings"
                    extra  = json.dumps({k: v for k, v in data.items()
                                         if k != "action"})

                _log_command(source, action, "", "", sa, th, extra)

                self._json_ok({"status": "ok", "settings": current_settings})
            except Exception as e:
                self._json_err(str(e))
            return

        self.send_response(404)
        self.end_headers()

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    PORT = 5000

    print("Initialising — centering weight servo, stopping drive...")
    weight_servo.angle   = settings["servo_center"]
    drive_servo.throttle = 0.0
    time.sleep(0.5)

    server = ThreadingHTTPServer(("0.0.0.0", PORT), RobotHandler)
    print(f"Robot server running → http://<your-pi-ip>:{PORT}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down — emergency stop...")
        drive_servo.throttle = 0.0
        weight_servo.angle   = settings["servo_center"]
        if session["active"]:
            print("Finalising open session...")
            stop_recording()
        server.server_close()
