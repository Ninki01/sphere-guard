#!/usr/bin/env python3
"""
p2pro_live.py - Live thermal viewer with image enhancement for the InfiRay
                P2 Pro (also works with the Topdon TC001 - same frame format).

IMPORTANT: all enhancement below is applied to the DISPLAY image only.
The raw temperature array is never modified, so anything you log or feed to
a defect-detection model stays radiometrically valid.

Viewing modes:
  --web     MJPEG stream over HTTP, viewable in a browser. Works headless,
            so use this when the Pi is sealed inside the robot. (default)
  --window  Local OpenCV window. Needs a desktop, not plain SSH.

Enhancement options:
  --range MIN MAX   lock the palette to a fixed temperature span (biggest
                    single improvement in apparent sharpness)
  --denoise         bilateral filter, removes sensor grain, keeps edges
  --sharpen [A]     unsharp mask, default amount 1.0
  --interp cubic|lanczos|nearest   upscaler (lanczos is sharpest)

Examples:
  python3 p2pro_live.py --device 0 --denoise --sharpen
  python3 p2pro_live.py --device 0 --range 30 35 --denoise --sharpen 1.5
  python3 p2pro_live.py --device 0 --window --interp lanczos

Window keys:  c colormap   d denoise   s sharpen   r auto/lock range   q quit
Web endpoints:  /  viewer    /stream  MJPEG    /temps  JSON    /set  controls
"""

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

try:
    import cv2
except ImportError:
    sys.exit("ERROR: OpenCV not found. Run: sudo apt-get install python3-opencv")

try:
    import numpy as np
except ImportError:
    sys.exit("ERROR: numpy not found. Run: pip install numpy")


EXPECTED_W = 256
EXPECTED_H = 384
IMG_ROWS = 192

COLORMAPS = [
    ("inferno", cv2.COLORMAP_INFERNO),
    ("jet", cv2.COLORMAP_JET),
    ("hot", cv2.COLORMAP_HOT),
    ("bone", cv2.COLORMAP_BONE),
    ("rainbow", cv2.COLORMAP_RAINBOW),
    ("grey", None),
]

INTERP = {
    "nearest": cv2.INTER_NEAREST,
    "cubic": cv2.INTER_CUBIC,
    "lanczos": cv2.INTER_LANCZOS4,
}


class Settings:
    """Live-tunable display settings. Raw temperatures are never touched."""

    def __init__(self):
        self.colormap_index = 0
        self.denoise = False
        self.sharpen = 0.0          # 0 = off, typical 0.5 - 2.0
        self.range_lock = None      # None = auto, or (tmin, tmax)
        self.interp = cv2.INTER_CUBIC
        self.scale = 3

    def as_dict(self):
        return {
            "colormap": COLORMAPS[self.colormap_index % len(COLORMAPS)][0],
            "denoise": self.denoise,
            "sharpen": round(self.sharpen, 2),
            "range_lock": list(self.range_lock) if self.range_lock else None,
        }


class Shared:
    def __init__(self):
        self.lock = threading.Lock()
        self.jpeg = None
        self.stats = {"centre": 0.0, "min": 0.0, "max": 0.0, "fps": 0.0}
        self.running = True


shared = Shared()
settings = Settings()


# ----------------------------------------------------------------------------
# Camera
# ----------------------------------------------------------------------------


def open_camera(device):
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0.0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, EXPECTED_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, EXPECTED_H)
    return cap


def find_device(max_index=10):
    for i in range(max_index):
        cap = open_camera(i)
        if cap is None:
            continue
        ok, frame = cap.read()
        cap.release()
        if ok and frame is not None and \
                frame.shape[0] == EXPECTED_H and frame.shape[1] == EXPECTED_W:
            return i
    return None


def decode_temperatures(frame):
    """Return a 192x256 array of temperatures in Celsius. Never modified."""
    thermal = frame[IMG_ROWS:, :, :].astype(np.uint16)
    raw = thermal[:, :, 0] + (thermal[:, :, 1] * 256)
    return raw / 64.0 - 273.15


# ----------------------------------------------------------------------------
# Display pipeline
# ----------------------------------------------------------------------------


def normalise(temps, range_lock):
    """Map temperatures to 0-255 for display. Returns (uint8, tmin, tmax)."""
    tmin, tmax = float(temps.min()), float(temps.max())
    if range_lock is not None:
        lo, hi = range_lock
    else:
        lo, hi = tmin, tmax
    span = max(hi - lo, 0.1)
    norm = np.clip((temps - lo) / span * 255.0, 0, 255).astype(np.uint8)
    return norm, tmin, tmax


def enhance(norm, s):
    """Denoise -> upscale -> sharpen, all on the display image only."""
    if s.denoise:
        # Small spatial sigma keeps edges; runs on the 256x192 image so it
        # stays cheap enough for 25 fps on a Pi.
        norm = cv2.bilateralFilter(norm, d=5, sigmaColor=25, sigmaSpace=5)

    w, h = EXPECTED_W * s.scale, IMG_ROWS * s.scale
    big = cv2.resize(norm, (w, h), interpolation=s.interp)

    if s.sharpen > 0:
        blur = cv2.GaussianBlur(big, (0, 0), sigmaX=2.0)
        big = cv2.addWeighted(big, 1.0 + s.sharpen, blur, -s.sharpen, 0)

    return big


def render(temps, s):
    """Turn the temperature array into a colourised image with a HUD."""
    norm, tmin, tmax = normalise(temps, s.range_lock)
    big = enhance(norm, s)

    name, cmap = COLORMAPS[s.colormap_index % len(COLORMAPS)]
    img = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR) if cmap is None \
        else cv2.applyColorMap(big, cmap)

    h, w = img.shape[:2]
    centre = float(temps[IMG_ROWS // 2, EXPECTED_W // 2])

    cx, cy = w // 2, h // 2
    cv2.line(img, (cx - 10, cy), (cx + 10, cy), (255, 255, 255), 1)
    cv2.line(img, (cx, cy - 10), (cx, cy + 10), (255, 255, 255), 1)
    _label(img, "%.1fC" % centre, (cx + 12, cy + 4), 0.5)

    my, mx = np.unravel_index(int(np.argmax(temps)), temps.shape)
    cv2.circle(img, (int(mx * s.scale), int(my * s.scale)), 5, (0, 0, 255), 1)

    bits = ["min %.1fC" % tmin, "max %.1fC" % tmax, name]
    if s.range_lock:
        bits.append("lock %.0f-%.0fC" % s.range_lock)
    if s.denoise:
        bits.append("dn")
    if s.sharpen > 0:
        bits.append("sh%.1f" % s.sharpen)
    _label(img, "  ".join(bits), (8, 18), 0.45)

    return img, {"centre": round(centre, 2),
                 "min": round(tmin, 2),
                 "max": round(tmax, 2)}


def _label(img, text, org, scale):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale,
                (255, 255, 255), 1)


# ----------------------------------------------------------------------------
# Capture loop
# ----------------------------------------------------------------------------


def capture_loop(device, quality):
    cap = open_camera(device)
    if cap is None:
        print("ERROR: could not open /dev/video%d" % device)
        shared.running = False
        return

    print("Streaming from /dev/video%d ... press Ctrl-C to stop" % device)
    frames, t0, fps = 0, time.time(), 0.0

    while shared.running:
        ok, frame = cap.read()
        if not ok or frame is None:
            time.sleep(0.01)
            continue
        if frame.shape[0] != EXPECTED_H:
            print("ERROR: wrong frame size %s - wrong device?" % (frame.shape,))
            break

        temps = decode_temperatures(frame)     # raw, never modified
        img, stats = render(temps, settings)

        frames += 1
        elapsed = time.time() - t0
        if elapsed >= 1.0:
            fps = frames / elapsed
            frames, t0 = 0, time.time()
        stats["fps"] = round(fps, 1)

        ok, buf = cv2.imencode(".jpg", img,
                               [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if ok:
            with shared.lock:
                shared.jpeg = buf.tobytes()
                shared.stats = stats

    cap.release()
    shared.running = False


# ----------------------------------------------------------------------------
# Web server
# ----------------------------------------------------------------------------


PAGE = b"""<!doctype html>
<html><head><meta charset="utf-8"><title>SG01 Thermal</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{background:#111;color:#eee;font-family:system-ui,sans-serif;
      margin:0;padding:14px;text-align:center}
 img{max-width:100%;border-radius:8px}
 .row{margin-top:10px}
 .k{color:#888;font-size:12px}
 .v{font-weight:600;font-size:17px}
 span.box{display:inline-block;min-width:80px;margin:0 6px}
 button{background:#222;color:#eee;border:1px solid #444;border-radius:6px;
        padding:7px 12px;margin:3px;font-size:13px;cursor:pointer}
 button:hover{background:#333}
 input{background:#222;color:#eee;border:1px solid #444;border-radius:6px;
       padding:6px;width:64px;margin:0 3px}
</style></head><body>
<img src="/stream" alt="thermal stream">
<div class="row">
 <span class="box"><span class="k">centre</span><br><span class="v" id="c">-</span></span>
 <span class="box"><span class="k">min</span><br><span class="v" id="n">-</span></span>
 <span class="box"><span class="k">max</span><br><span class="v" id="x">-</span></span>
 <span class="box"><span class="k">fps</span><br><span class="v" id="f">-</span></span>
</div>
<div class="row">
 <button onclick="s('denoise','toggle')">denoise</button>
 <button onclick="s('sharpen','toggle')">sharpen</button>
 <button onclick="s('colormap','next')">colormap</button>
 <button onclick="s('range','auto')">auto range</button>
</div>
<div class="row">
 lock <input id="lo" type="number" step="0.5" placeholder="min">
 to <input id="hi" type="number" step="0.5" placeholder="max">
 <button onclick="s('range', lo.value+','+hi.value)">apply</button>
 <button onclick="lockNarrow()">lock around centre</button>
</div>
<div class="row"><span class="k" id="st"></span></div>
<script>
async function s(k,v){ await fetch('/set?'+k+'='+encodeURIComponent(v)); }
async function lockNarrow(){
  const r = await fetch('/temps'); const d = await r.json();
  const a=(d.centre-2).toFixed(1), b=(d.centre+2).toFixed(1);
  lo.value=a; hi.value=b; await s('range', a+','+b);
}
setInterval(async()=>{
  try{
    const d = await (await fetch('/temps')).json();
    c.textContent=d.centre.toFixed(1)+' C'; n.textContent=d.min.toFixed(1)+' C';
    x.textContent=d.max.toFixed(1)+' C';   f.textContent=d.fps.toFixed(1);
    const g = await (await fetch('/set')).json();
    st.textContent = 'colormap '+g.colormap+
      ' | denoise '+(g.denoise?'on':'off')+
      ' | sharpen '+(g.sharpen>0?g.sharpen:'off')+
      ' | range '+(g.range_lock?g.range_lock[0]+'-'+g.range_lock[1]+' C':'auto');
  }catch(e){}
}, 500);
</script>
</body></html>"""


def apply_setting(q):
    """Apply a query-string setting change to the live settings object."""
    if "denoise" in q:
        v = q["denoise"][0]
        settings.denoise = (not settings.denoise) if v == "toggle" \
            else v in ("1", "true", "on")
    if "sharpen" in q:
        v = q["sharpen"][0]
        if v == "toggle":
            settings.sharpen = 0.0 if settings.sharpen > 0 else 1.0
        else:
            try:
                settings.sharpen = max(0.0, float(v))
            except ValueError:
                pass
    if "colormap" in q:
        v = q["colormap"][0]
        if v == "next":
            settings.colormap_index += 1
        else:
            try:
                settings.colormap_index = int(v)
            except ValueError:
                pass
    if "range" in q:
        v = q["range"][0]
        if v == "auto":
            settings.range_lock = None
        else:
            try:
                lo, hi = [float(x) for x in v.split(",")]
                settings.range_lock = (lo, hi) if hi > lo else None
            except ValueError:
                pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._send(PAGE, "text/html")

        elif path == "/temps":
            with shared.lock:
                body = json.dumps(shared.stats).encode()
            self._send(body, "application/json")

        elif path == "/set":
            apply_setting(parse_qs(parsed.query))
            self._send(json.dumps(settings.as_dict()).encode(),
                       "application/json")

        elif path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while shared.running:
                    with shared.lock:
                        jpeg = shared.jpeg
                    if jpeg is None:
                        time.sleep(0.05)
                        continue
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(
                        ("Content-Length: %d\r\n\r\n" % len(jpeg)).encode())
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                    time.sleep(1 / 30.0)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_error(404)


def run_web(device, port, quality):
    t = threading.Thread(target=capture_loop, args=(device, quality),
                         daemon=True)
    t.start()
    time.sleep(1.0)
    if not shared.running:
        return 1

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("\nOpen in a browser on your tablet or laptop:")
    print("    http://<pi-ip-address>:%d\n" % port)
    print("Find the Pi's address with:  hostname -I")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        shared.running = False
        server.shutdown()
    return 0


# ----------------------------------------------------------------------------
# Window mode
# ----------------------------------------------------------------------------


def run_window(device):
    cap = open_camera(device)
    if cap is None:
        sys.exit("ERROR: could not open /dev/video%d" % device)

    print("Live window.  keys: c colormap  d denoise  s sharpen  "
          "r auto/lock range  q quit")
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            if frame.shape[0] != EXPECTED_H:
                sys.exit("ERROR: wrong frame size %s - wrong device?"
                         % (frame.shape,))

            temps = decode_temperatures(frame)
            img, stats = render(temps, settings)
            cv2.imshow("P2 Pro live", img)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("c"):
                settings.colormap_index += 1
            elif key == ord("d"):
                settings.denoise = not settings.denoise
            elif key == ord("s"):
                settings.sharpen = 0.0 if settings.sharpen > 0 else 1.0
            elif key == ord("r"):
                if settings.range_lock:
                    settings.range_lock = None
                else:
                    c = stats["centre"]
                    settings.range_lock = (c - 2.0, c + 2.0)
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        cv2.destroyAllWindows()
    return 0


# ----------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description="Live thermal viewer")
    p.add_argument("--device", type=int, default=None)
    p.add_argument("--window", action="store_true")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--scale", type=int, default=3)
    p.add_argument("--quality", type=int, default=90)
    p.add_argument("--range", nargs=2, type=float, metavar=("MIN", "MAX"),
                   help="lock palette to a fixed temperature span")
    p.add_argument("--denoise", action="store_true")
    p.add_argument("--sharpen", nargs="?", type=float, const=1.0, default=0.0,
                   metavar="AMOUNT")
    p.add_argument("--interp", choices=list(INTERP.keys()), default="cubic")
    args = p.parse_args()

    settings.scale = args.scale
    settings.denoise = args.denoise
    settings.sharpen = args.sharpen
    settings.interp = INTERP[args.interp]
    if args.range:
        lo, hi = args.range
        settings.range_lock = (lo, hi) if hi > lo else None

    device = args.device
    if device is None:
        print("Auto-detecting thermal camera...")
        device = find_device()
        if device is None:
            sys.exit("ERROR: no 256x384 device found. Check the cable, "
                     "then run: lsusb")
        print("Found on /dev/video%d" % device)

    if args.window:
        return run_window(device)
    return run_web(device, args.port, args.quality)


if __name__ == "__main__":
    sys.exit(main())