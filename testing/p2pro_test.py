#!/usr/bin/env python3
"""
p2pro_test.py - Standalone connectivity/decode test for the InfiRay P2 Pro.

Path A approach: treat the camera as a plain UVC video device, disable OpenCV's
RGB conversion, and decode the raw temperature half of the frame ourselves.
This is the same mechanism PyThermalCamera uses for the Topdon TC001, since
both cameras share the InfiRay frame format.

Frame layout (256 x 384, 2 bytes per pixel):
    rows   0-191  -> visible thermal image (YUYV)
    rows 192-383  -> raw temperature data (16-bit little-endian)

Temperature decode:
    raw_kelvin_x64 = byte0 + (byte1 * 256)
    celsius        = raw_kelvin_x64 / 64.0 - 273.15

Usage:
    python3 p2pro_test.py --scan            # find which /dev/videoN is the camera
    python3 p2pro_test.py --device 0        # run the test on /dev/video0
    python3 p2pro_test.py --device 0 --display   # also show a live window
"""

import argparse
import sys
import time

try:
    import cv2
except ImportError:
    sys.exit("ERROR: OpenCV not found. Run: sudo apt-get install python3-opencv")

try:
    import numpy as np
except ImportError:
    sys.exit("ERROR: numpy not found. Run: pip install numpy")


EXPECTED_W = 256
EXPECTED_H = 384          # 192 image rows + 192 temperature rows
IMG_ROWS = 192


def open_camera(device):
    """Open a video device in raw mode (no RGB conversion)."""
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None
    # Critical: stop OpenCV from mangling the raw temperature bytes into RGB.
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0.0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, EXPECTED_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, EXPECTED_H)
    return cap


def scan_devices(max_index=10):
    """Try each /dev/videoN and report which one returns a 256x384 frame."""
    print("Scanning /dev/video0 .. /dev/video%d ...\n" % (max_index - 1))
    found = []
    for i in range(max_index):
        cap = open_camera(i)
        if cap is None:
            continue
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            print("  /dev/video%-2d : opened, but no frame" % i)
            continue
        shape = frame.shape
        is_match = shape[0] == EXPECTED_H and shape[1] == EXPECTED_W
        tag = "  <-- THERMAL CAMERA" if is_match else ""
        print("  /dev/video%-2d : frame shape %s%s" % (i, shape, tag))
        if is_match:
            found.append(i)

    print()
    if found:
        print("Thermal camera found on device index: %s" %
              ", ".join(str(f) for f in found))
        print("Run: python3 p2pro_test.py --device %d" % found[0])
    else:
        print("No 256x384 device found. Check the cable, then run: lsusb")
    return found


def decode_temperatures(frame):
    """Return a 192x256 array of temperatures in Celsius."""
    thermal = frame[IMG_ROWS:, :, :].astype(np.uint16)
    raw = thermal[:, :, 0] + (thermal[:, :, 1] * 256)
    return raw / 64.0 - 273.15


def run_test(device, duration, show):
    cap = open_camera(device)
    if cap is None:
        sys.exit("ERROR: could not open /dev/video%d. Try --scan." % device)

    ok, frame = cap.read()
    if not ok or frame is None:
        cap.release()
        sys.exit("ERROR: opened /dev/video%d but got no frame. Try --scan."
                 % device)

    print("Opened /dev/video%d" % device)
    print("Frame shape: %s (expected (%d, %d, 2))"
          % (frame.shape, EXPECTED_H, EXPECTED_W))

    if frame.shape[0] != EXPECTED_H or frame.shape[1] != EXPECTED_W:
        cap.release()
        sys.exit("ERROR: unexpected frame size - this is probably the wrong "
                 "device node. Run --scan to find the right one.")

    print("Frame size OK. Reading for %d seconds...\n" % duration)

    frames = 0
    start = time.time()
    try:
        while time.time() - start < duration:
            ok, frame = cap.read()
            if not ok or frame is None:
                print("WARNING: dropped frame")
                continue
            frames += 1

            temps = decode_temperatures(frame)
            centre = temps[IMG_ROWS // 2, EXPECTED_W // 2]

            print("\rframe %4d | centre %6.2f C | min %6.2f C | max %6.2f C"
                  % (frames, centre, temps.min(), temps.max()), end="")

            if show:
                grey = frame[:IMG_ROWS, :, 0]
                big = cv2.resize(grey, (EXPECTED_W * 3, IMG_ROWS * 3),
                                 interpolation=cv2.INTER_CUBIC)
                colour = cv2.applyColorMap(big, cv2.COLORMAP_INFERNO)
                cv2.imshow("P2 Pro test - press q to quit", colour)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        elapsed = time.time() - start
        cap.release()
        if show:
            cv2.destroyAllWindows()

    print("\n")
    if frames == 0:
        print("RESULT: FAIL - no frames captured.")
        return 1

    print("RESULT: PASS")
    print("  frames captured : %d" % frames)
    print("  elapsed         : %.1f s" % elapsed)
    print("  average rate    : %.1f fps  (expect ~25)" % (frames / elapsed))
    print("\nSanity check: cover the lens with your hand - the centre "
          "temperature should rise toward ~30-35 C.")
    return 0


def main():
    p = argparse.ArgumentParser(description="InfiRay P2 Pro connectivity test")
    p.add_argument("--device", type=int, default=None,
                   help="video device index, e.g. 0 for /dev/video0")
    p.add_argument("--scan", action="store_true",
                   help="scan all video devices and identify the camera")
    p.add_argument("--duration", type=int, default=10,
                   help="seconds to capture (default 10)")
    p.add_argument("--display", action="store_true",
                   help="show a live window (needs a desktop, not SSH)")
    args = p.parse_args()

    if args.scan or args.device is None:
        found = scan_devices()
        if args.scan:
            return 0
        if not found:
            return 1
        args.device = found[0]
        print()

    return run_test(args.device, args.duration, args.display)


if __name__ == "__main__":
    sys.exit(main())