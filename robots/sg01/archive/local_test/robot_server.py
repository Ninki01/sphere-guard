"""
Robot Server - Raspberry Pi (No Flask / No extra dependencies)
===============================================================
Pin reference:
  Channel 0 → SPT5535LV  drive motor  (continuous_servo, throttle -1.0 to 1.0)
  Channel 1 → PTK7465WMG weight servo (standard servo,   angle 0–180°)

Commands accepted via POST /command:
  { "action": "forward" }
  { "action": "backward" }
  { "action": "left" }
  { "action": "right" }
  { "action": "stop" }
  { "action": "set_speed", "forward": 0.5, "backward": 0.4 }
  { "action": "set_servo", "center": 90, "left": 135, "right": 45 }

Run:
  python robot_server.py

Open on tablet:
  http://<your-pi-ip>:5000
"""

import json
import time
import os
import csv
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import board
import busio
from adafruit_servokit import ServoKit

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

# ── Live-adjustable settings (tablet can update these) ───────────────────────
settings = {
    "forward_speed":  0.40,   # throttle 0.0 – 1.0
    "backward_speed": 0.40,   # throttle 0.0 – 1.0
    "servo_center":   90,     # degrees
    "servo_left":     135,    # degrees
    "servo_right":    45,     # degrees
}

# ── Sensor init (BNO055 IMU + BME280 temp/humidity) ──────────────────────────
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

# ── Local sensor log ─────────────────────────────────────────────────────────
LOG_DIR     = os.path.join(os.path.dirname(__file__), "sensor_log")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE    = os.path.join(LOG_DIR, "sensor_log.csv")
LOG_HEADERS = ["timestamp", "pitch", "roll", "heading", "temp", "humidity", "pressure"]

def _init_log():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow(LOG_HEADERS)

_init_log()

def read_sensors():
    data = {"pitch": 0, "roll": 0, "heading": 0, "temp": 0, "humidity": 0, "pressure": 0}
    if BNO_OK:
        try:
            euler = _bno.euler
            data["heading"] = round(euler[0] or 0, 1)
            data["roll"]    = round(euler[1] or 0, 1)
            data["pitch"]   = round(euler[2] or 0, 1)
        except Exception:
            pass
    if BME_OK:
        try:
            data["temp"]     = round(_bme.temperature, 1)
            data["humidity"] = round(_bme.humidity, 1)
            data["pressure"] = round(_bme.pressure, 1)
        except Exception:
            pass
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S")] + [data[k] for k in LOG_HEADERS[1:]])
    return data

# ── Action handler ────────────────────────────────────────────────────────────
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
        # Update forward and/or backward speed
        if "forward" in data:
            val = float(data["forward"])
            settings["forward_speed"] = max(0.0, min(1.0, val))
        if "backward" in data:
            val = float(data["backward"])
            settings["backward_speed"] = max(0.0, min(1.0, val))
        print(f"  Speed updated → fwd:{settings['forward_speed']:.2f}  bwd:{settings['backward_speed']:.2f}")

    elif action == "set_servo":
        # Update servo angle presets and optionally move to center immediately
        if "center" in data:
            settings["servo_center"] = max(0, min(180, int(data["center"])))
        if "left" in data:
            settings["servo_left"]   = max(0, min(180, int(data["left"])))
        if "right" in data:
            settings["servo_right"]  = max(0, min(180, int(data["right"])))
        # Move servo to current center so user sees the effect
        weight_servo.angle = settings["servo_center"]
        print(f"  Servo updated → center:{settings['servo_center']}°  left:{settings['servo_left']}°  right:{settings['servo_right']}°")

    else:  # stop
        drive_servo.throttle = 0.0
        weight_servo.angle   = settings["servo_center"]

    print(f"[CMD] {action.upper()}")
    return settings   # return current settings so UI can sync

# ── HTTP server ───────────────────────────────────────────────────────────────
CONTROLLER_HTML = os.path.join(os.path.dirname(__file__), "robot_controller.html")

class RobotHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/settings":
            resp = json.dumps(settings).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self._cors()
            self.end_headers()
            self.wfile.write(resp)
            return

        if self.path == "/sensors":
            resp = json.dumps(read_sensors()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self._cors()
            self.end_headers()
            self.wfile.write(resp)
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
        if self.path != "/command":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)

        try:
            data         = json.loads(body)
            current_settings = handle_action(data)
            resp = json.dumps({"status": "ok", "settings": current_settings}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self._cors()
            self.end_headers()
            self.wfile.write(resp)
        except Exception as e:
            err = json.dumps({"status": "error", "message": str(e)}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.end_headers()
            self.wfile.write(err)

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    PORT = 5000

    print("Initialising — centering weight servo, stopping drive...")
    weight_servo.angle   = settings["servo_center"]
    drive_servo.throttle = 0.0
    time.sleep(0.5)

    server = HTTPServer(("0.0.0.0", PORT), RobotHandler)
    print(f"Robot server running → http://<your-pi-ip>:{PORT}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down — emergency stop...")
        drive_servo.throttle = 0.0
        weight_servo.angle   = settings["servo_center"]
        server.server_close()
