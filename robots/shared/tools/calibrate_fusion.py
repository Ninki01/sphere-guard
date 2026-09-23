#!/usr/bin/env python3
"""
calibrate_fusion.py — interactive homography calibration for RGB/thermal fusion.

Run MANUALLY on the Pi when the main robot server is NOT running.

    cd /path/to/sphere-guard/robots
    python shared/tools/calibrate_fusion.py --config sg01/config.yaml

Controls
--------
  Left-click in RGB window     → add next RGB point
  Left-click in THERMAL window → add matching thermal point  (alternate)
  u  →  undo last point or incomplete pair
  c  →  compute homography and open live preview
  s  →  save homography to config.yaml (prompts for calibration distance)
  q  →  quit without saving

Target tip
----------
Use a target visible in BOTH spectra. A printed checkerboard briefly warmed with
a lamp or hairdryer works well: dark squares absorb more heat and appear brighter
in thermal. Keep the target at the distance you most care about (record it when
saving) — parallax from the camera separation causes misalignment at other distances.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

try:
    import cv2
    import numpy as np
except ImportError:
    print("ERROR: opencv-python and numpy are required.")
    print("       pip install opencv-python numpy")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required.  pip install pyyaml")
    sys.exit(1)


# ──────────────────────────────────────────────────────────────────────────────
# Config helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _save(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    os.replace(tmp, path)


def _camera_info(cfg: dict, role: str):
    """Return (device, width, height) for camera role, or None."""
    for cam in cfg.get("cameras", []):
        if cam.get("role") == role:
            return cam["device"], cam.get("width", 640), cam.get("height", 480)
    return None


# ──────────────────────────────────────────────────────────────────────────────
# UI helpers
# ──────────────────────────────────────────────────────────────────────────────

_COLORS = [
    (0, 255, 0), (0, 160, 255), (255, 0, 255), (255, 200, 0),
    (0, 255, 255), (255, 80,  80), (160, 255, 160), (80, 80, 255),
]


def _draw_points(img, pts: list, prefix: str = ""):
    out = img.copy()
    for i, (x, y) in enumerate(pts):
        col = _COLORS[i % len(_COLORS)]
        cv2.circle(out, (x, y), 6, col, -1)
        cv2.circle(out, (x, y), 6, (255, 255, 255), 1)
        cv2.putText(out, f"{prefix}{i + 1}", (x + 8, y - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)
    return out


def _status(img, text: str, color=(200, 255, 200)):
    cv2.putText(img, text, (8, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

WIN_RGB     = "RGB  (click to add points)"
WIN_THERMAL = "THERMAL  (click matching points)"
WIN_PREVIEW = "FUSION PREVIEW  (press s to save)"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calibrate RGB/thermal homography for fusion overlay"
    )
    parser.add_argument(
        "--config", default="sg01/config.yaml",
        help="Path to robot config.yaml (relative to robots/ directory)"
    )
    args = parser.parse_args()

    # Resolve config path
    cfg_path = args.config
    if not os.path.isfile(cfg_path):
        here = os.path.dirname(os.path.abspath(__file__))
        cfg_path = os.path.normpath(os.path.join(here, "..", "..", args.config))
    if not os.path.isfile(cfg_path):
        print(f"ERROR: config not found: {args.config}")
        print(f"       Run this script from the robots/ directory.")
        sys.exit(1)

    cfg = _load(cfg_path)
    rgb_info     = _camera_info(cfg, "rgb")
    thermal_info = _camera_info(cfg, "thermal")

    if rgb_info is None:
        print("ERROR: no 'rgb' camera entry found in config.yaml")
        sys.exit(1)
    if thermal_info is None:
        print("ERROR: no 'thermal' camera entry found in config.yaml")
        sys.exit(1)

    rgb_dev, rgb_w, rgb_h = rgb_info
    th_dev,  th_w,  th_h  = thermal_info
    th_img_h = th_h // 2   # P2 Pro: top half is image, bottom is temp data

    print("=" * 60)
    print("  SphereGuard Fusion Calibration")
    print("=" * 60)
    print(f"  RGB     camera: device {rgb_dev}  ({rgb_w}×{rgb_h})")
    print(f"  Thermal camera: device {th_dev}  ({th_w}×{th_h},"
          f" image half: {th_w}×{th_img_h})")
    print()
    print("  IMPORTANT: the main robot server must NOT be running.")
    print("  If cameras fail to open, stop the server first:")
    print("    sudo systemctl stop robot_server")
    print()
    print("  TARGET TIP: warm a checkerboard briefly with a lamp —")
    print("  dark squares absorb heat and appear bright in thermal.")
    print()
    print("  CONTROLS:")
    print("    Left-click RGB window     → add RGB point")
    print("    Left-click THERMAL window → add matching thermal point")
    print("    u → undo last point (or incomplete pair)")
    print("    c → compute homography + open live preview")
    print("    s → save to config.yaml (prompts for calibration distance)")
    print("    q → quit without saving")
    print("=" * 60)
    print()

    rgb_cap = cv2.VideoCapture(rgb_dev)
    if not rgb_cap.isOpened():
        print(f"ERROR: cannot open RGB camera (device {rgb_dev}).")
        print("       Is the server already running?")
        sys.exit(1)
    rgb_cap.set(cv2.CAP_PROP_FRAME_WIDTH,  rgb_w)
    rgb_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, rgb_h)

    th_cap = cv2.VideoCapture(th_dev)
    if not th_cap.isOpened():
        print(f"ERROR: cannot open thermal camera (device {th_dev}).")
        rgb_cap.release()
        sys.exit(1)
    th_cap.set(cv2.CAP_PROP_FRAME_WIDTH,  th_w)
    th_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, th_h)

    print("Both cameras opened. Starting calibration UI...")
    print("(Close any window or press q to quit)")
    print()

    cv2.namedWindow(WIN_RGB,     cv2.WINDOW_NORMAL)
    cv2.namedWindow(WIN_THERMAL, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN_RGB,     rgb_w, rgb_h)
    cv2.resizeWindow(WIN_THERMAL, th_w,  th_img_h)

    rgb_pts: list = []
    th_pts:  list = []
    # Invariant: |rgb_pts| == |th_pts|  OR  |rgb_pts| == |th_pts| + 1

    H:           np.ndarray | None = None
    show_preview: bool             = False

    def on_rgb_click(event, x, y, flags, param):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        if len(rgb_pts) > len(th_pts):
            print("  → click THERMAL window first to match the pending RGB point")
            return
        rgb_pts.append((x, y))
        print(f"  RGB point {len(rgb_pts)}: ({x}, {y})"
              f"  — now click the matching thermal point")

    def on_thermal_click(event, x, y, flags, param):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        if len(th_pts) >= len(rgb_pts):
            print("  → click RGB window first to start the next pair")
            return
        th_pts.append((x, y))
        n = len(th_pts)
        print(f"  Thermal point {n}: ({x}, {y})  —  pair {n} complete"
              + ("" if n >= 4 else f"  ({4 - n} more needed)"))

    cv2.setMouseCallback(WIN_RGB,     on_rgb_click)
    cv2.setMouseCallback(WIN_THERMAL, on_thermal_click)

    while True:
        ok_r, rgb_raw = rgb_cap.read()
        ok_t, th_raw  = th_cap.read()

        if not ok_r:
            rgb_raw = np.zeros((rgb_h, rgb_w, 3), dtype=np.uint8)
            cv2.putText(rgb_raw, "RGB READ FAILED", (20, rgb_h // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

        if not ok_t:
            th_raw = np.zeros((th_h, th_w, 3), dtype=np.uint8)

        # Take the image half of the thermal frame
        th_frame = th_raw[:th_img_h] if th_raw.shape[0] >= th_img_h else th_raw

        # Build display frames with annotations
        rgb_disp = _draw_points(rgb_raw,  rgb_pts, "R")
        th_disp  = _draw_points(th_frame, th_pts,  "T")

        pairs = min(len(rgb_pts), len(th_pts))
        _status(rgb_disp,
                f"Pairs: {pairs}/4+  |  u=undo  c=compute  s=save  q=quit")
        if len(rgb_pts) > len(th_pts):
            cv2.putText(rgb_disp, "Waiting for THERMAL point...", (8, 36),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1, cv2.LINE_AA)

        cv2.imshow(WIN_RGB,     rgb_disp)
        cv2.imshow(WIN_THERMAL, th_disp)

        if show_preview and H is not None:
            th_gray    = cv2.cvtColor(th_frame, cv2.COLOR_BGR2GRAY)
            th_colored = cv2.applyColorMap(th_gray, cv2.COLORMAP_INFERNO)
            th_warped  = cv2.warpPerspective(th_colored, H, (rgb_w, rgb_h))
            preview    = cv2.addWeighted(rgb_raw, 0.6, th_warped, 0.4, 0)
            cv2.putText(preview, "FUSION PREVIEW  alpha=0.4  (c=recompute  s=save  q=quit)",
                        (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 255, 200), 1, cv2.LINE_AA)
            cv2.imshow(WIN_PREVIEW, preview)

        key = cv2.waitKey(30) & 0xFF

        if key == ord('q') or key == 27:   # q or Escape
            print("Quitting without saving.")
            break

        elif key == ord('u'):
            if len(rgb_pts) > len(th_pts):
                rgb_pts.pop()
                print(f"  Undid unpaired RGB point.  RGB={len(rgb_pts)}  Thermal={len(th_pts)}")
            elif rgb_pts:
                rgb_pts.pop()
                th_pts.pop()
                print(f"  Undid last pair.  Now {len(rgb_pts)} pair(s).")
            else:
                print("  Nothing to undo.")

        elif key == ord('c'):
            n = min(len(rgb_pts), len(th_pts))
            if n < 4:
                print(f"  Need ≥4 pairs (have {n}).  Keep clicking points.")
            else:
                src = np.array(th_pts[:n],  dtype=np.float32)
                dst = np.array(rgb_pts[:n], dtype=np.float32)
                H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
                if H is None:
                    print("  Homography computation FAILED. Try more or better-spread points.")
                else:
                    inliers = int(mask.sum()) if mask is not None else n
                    print(f"  Homography computed — inliers: {inliers}/{n}")
                    print(f"  Matrix (row-major):\n{H}")
                    if not show_preview:
                        cv2.namedWindow(WIN_PREVIEW, cv2.WINDOW_NORMAL)
                        cv2.resizeWindow(WIN_PREVIEW, rgb_w, rgb_h)
                        show_preview = True
                    else:
                        print("  Preview window updated.")

        elif key == ord('s'):
            if H is None:
                print("  No homography yet. Press 'c' first to compute.")
            else:
                dist_str = input("  Calibration distance (m) — how far was the target? ").strip()
                try:
                    dist_m = float(dist_str)
                except ValueError:
                    dist_m = None
                    print("  (invalid input — saving distance as null)")

                H_list = H.flatten().tolist()
                date_str = datetime.now().isoformat(timespec="seconds")

                cfg = _load(cfg_path)
                if "fusion" not in cfg or not isinstance(cfg.get("fusion"), dict):
                    cfg["fusion"] = {}
                cfg["fusion"]["homography"]              = H_list
                cfg["fusion"]["calibration_date"]        = date_str
                cfg["fusion"]["calibration_distance_m"]  = dist_m
                _save(cfg_path, cfg)

                print(f"  Saved to {cfg_path}")
                print(f"  Date: {date_str}")
                print(f"  Distance: {dist_m} m")
                print("  Start the server and open /fusion to view the result.")

    rgb_cap.release()
    th_cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
