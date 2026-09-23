"""
Robot Server GPIO - Raspberry Pi 5 (No PCA9685 / No ServoKit)
==============================================================
Uses Pi 5 hardware PWM directly via lgpio (no extra HAT needed).

Pin wiring:
  GPIO 12 (Pin 32) → SPT5535LV  drive motor  (continuous servo)
  GPIO 13 (Pin 33) → PTK7465WMG weight servo  (standard servo, 0–180°)

  Servo power (red)   → External 5V supply (NOT Pi GPIO 5V pin)
  Servo ground (black/brown) → Shared GND with Pi

Commands accepted via POST /command:
  { "action": "forward" }
  { "action": "backward" }
  { "action": "left" }
  { "action": "right" }
  { "action": "stop" }
  { "action": "set_speed", "forward": 0.5, "backward": 0.4 }
  { "action": "set_servo", "center": 90, "left": 135, "right": 45 }

Install dependency (once):
  pip install lgpio

Run:
  python robot_server_gpio.py

Open on tablet:
  http://<your-pi-ip>:5000
"""

import json
import time
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import lgpio

# ── GPIO / PWM config ─────────────────────────────────────────────────────────
DRIVE_PIN  = 12   # Hardware PWM0 — continuous servo (SPT5535LV)
WEIGHT_PIN = 13   # Hardware PWM1 — standard servo   (PTK7465WMG)

PWM_FREQ   = 50   # 50 Hz standard servo frequency
PULSE_MIN  = 500   # µs — minimum pulse width  (0° / full reverse)
PULSE_MAX  = 2500  # µs — maximum pulse width  (180° / full forward)
PULSE_MID  = 1500  # µs — centre / stop

h = lgpio.gpiochip_open(0)

def us_to_duty(pulse_us: float) -> float:
    """Convert pulse width in microseconds to duty-cycle percent (0–100)."""
    period_us = 1_000_000 / PWM_FREQ   # 20 000 µs for 50 Hz
    return (pulse_us / period_us) * 100.0

def start_pwm(pin: int, duty: float):
    lgpio.tx_pwm(h, pin, PWM_FREQ, duty)

def set_pwm(pin: int, duty: float):
    lgpio.tx_pwm(h, pin, PWM_FREQ, duty)

# ── Servo helpers ─────────────────────────────────────────────────────────────
def angle_to_duty(angle: float) -> float:
    """Map 0–180° to duty-cycle percent."""
    pulse = PULSE_MIN + (angle / 180.0) * (PULSE_MAX - PULSE_MIN)
    return us_to_duty(pulse)

def throttle_to_duty(throttle: float) -> float:
    """
    Map throttle -1.0 → +1.0 to duty-cycle percent.
      -1.0 → PULSE_MIN  (full reverse)
       0.0 → PULSE_MID  (stop)
      +1.0 → PULSE_MAX  (full forward)
    """
    pulse = PULSE_MID + throttle * (PULSE_MAX - PULSE_MIN) / 2.0
    pulse = max(PULSE_MIN, min(PULSE_MAX, pulse))
    return us_to_duty(pulse)

def set_weight_angle(angle: float):
    set_pwm(WEIGHT_PIN, angle_to_duty(angle))

def set_drive_throttle(throttle: float):
    set_pwm(DRIVE_PIN, throttle_to_duty(throttle))

# ── Initialise both PWM channels ──────────────────────────────────────────────
start_pwm(DRIVE_PIN,  us_to_duty(PULSE_MID))   # stop
start_pwm(WEIGHT_PIN, angle_to_duty(90))        # centre
print("PWM initialised — drive stopped, weight centred.")

# ── Live-adjustable settings (tablet can update these) ───────────────────────
settings = {
    "forward_speed":  0.40,
    "backward_speed": 0.40,
    "servo_center":   90,
    "servo_left":     135,
    "servo_right":    45,
}

# ── Action handler ────────────────────────────────────────────────────────────
def handle_action(data: dict) -> dict:
    action = data.get("action", "stop").lower()

    if action == "forward":
        set_weight_angle(settings["servo_center"])
        set_drive_throttle(settings["forward_speed"])

    elif action == "backward":
        set_weight_angle(settings["servo_center"])
        set_drive_throttle(-settings["backward_speed"])

    elif action == "left":
        set_weight_angle(settings["servo_left"])
        set_drive_throttle(settings["forward_speed"])

    elif action == "right":
        set_weight_angle(settings["servo_right"])
        set_drive_throttle(settings["forward_speed"])

    elif action == "set_speed":
        if "forward" in data:
            settings["forward_speed"]  = max(0.0, min(1.0, float(data["forward"])))
        if "backward" in data:
            settings["backward_speed"] = max(0.0, min(1.0, float(data["backward"])))
        print(f"  Speed → fwd:{settings['forward_speed']:.2f}  bwd:{settings['backward_speed']:.2f}")

    elif action == "set_servo":
        if "center" in data:
            settings["servo_center"] = max(0, min(180, int(data["center"])))
        if "left" in data:
            settings["servo_left"]   = max(0, min(180, int(data["left"])))
        if "right" in data:
            settings["servo_right"]  = max(0, min(180, int(data["right"])))
        set_weight_angle(settings["servo_center"])
        print(f"  Servo → center:{settings['servo_center']}°  left:{settings['servo_left']}°  right:{settings['servo_right']}°")

    else:  # stop / unknown
        set_drive_throttle(0.0)
        set_weight_angle(settings["servo_center"])

    print(f"[CMD] {action.upper()}")
    return settings

# ── HTTP server ───────────────────────────────────────────────────────────────
CONTROLLER_HTML = os.path.join(os.path.dirname(__file__), "robot_controller.html")

class RobotHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # suppress default access log spam

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
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
            data             = json.loads(body)
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
    set_weight_angle(settings["servo_center"])
    set_drive_throttle(0.0)
    time.sleep(0.5)

    server = HTTPServer(("0.0.0.0", PORT), RobotHandler)
    print(f"Robot server running → http://<your-pi-ip>:{PORT}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down — emergency stop...")
        set_drive_throttle(0.0)
        set_weight_angle(settings["servo_center"])
        time.sleep(0.3)
        lgpio.tx_pwm(h, DRIVE_PIN,  PWM_FREQ, 0)
        lgpio.tx_pwm(h, WEIGHT_PIN, PWM_FREQ, 0)
        lgpio.gpiochip_close(h)
        server.server_close()
