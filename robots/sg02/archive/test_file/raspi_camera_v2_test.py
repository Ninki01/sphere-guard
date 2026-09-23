# Test script for Raspberry Pi Camera Module v2 on Raspberry Pi 5
# Uses picamera2 (the modern library for Pi 5, replacing legacy picamera)
#
# Install dependencies:
#   sudo apt update && sudo apt install -y python3-picamera2 python3-opencv libcamera-apps
#
# Run:
#   python3 raspi_camera_v2_test.py

import time
import os
from datetime import datetime

try:
    from picamera2 import Picamera2
    from picamera2.previews.qt import QGlPreview
    PICAMERA2_AVAILABLE = True
except ImportError:
    PICAMERA2_AVAILABLE = False
    print("[WARN] picamera2 not found. Falling back to OpenCV V4L2 mode.")

import cv2

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raspi_cam_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def test_with_picamera2():
    """Test using picamera2 — recommended for Raspberry Pi 5."""
    print("\n=== Picamera2 Test ===")
    cam = Picamera2()

    # Print available camera properties
    print(f"Camera model : {cam.camera_properties.get('Model', 'unknown')}")
    print(f"Sensor modes : {len(cam.sensor_modes)} available")

    # Configure for preview + still capture
    config = cam.create_still_configuration(
        main={"size": (1920, 1080), "format": "RGB888"},
        lores={"size": (640, 480), "format": "YUV420"},
        display="lores"
    )
    cam.configure(config)
    cam.start()
    print("Camera started — warming up for 2 s...")
    time.sleep(2)

    # --- Still image capture ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    still_path = os.path.join(OUTPUT_DIR, f"still_{timestamp}.jpg")
    cam.capture_file(still_path)
    print(f"Still image saved → {still_path}")

    # --- Live preview via OpenCV ---
    print("Live preview: press 'q' to quit, 's' to save a frame.")
    try:
        while True:
            frame = cam.capture_array("lores")
            # YUV420 → BGR for OpenCV
            bgr = cv2.cvtColor(frame, cv2.COLOR_YUV420p2BGR)
            bgr = cv2.resize(bgr, (640, 480))

            cv2.putText(bgr, "Pi Cam v2 | 'q' quit | 's' save",
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.imshow("Raspberry Pi Camera v2", bgr)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('s'):
                snap_path = os.path.join(OUTPUT_DIR, f"snap_{datetime.now().strftime('%H%M%S')}.jpg")
                cv2.imwrite(snap_path, bgr)
                print(f"Snapshot saved → {snap_path}")
    finally:
        cam.stop()
        cv2.destroyAllWindows()
        print("Camera released.")


def test_with_opencv_v4l2():
    """Fallback: access Pi Camera v2 via V4L2 + OpenCV (no picamera2 required)."""
    print("\n=== OpenCV V4L2 Fallback Test ===")
    print("Tip: if /dev/video0 is wrong, run  ls /dev/video*  to find the correct index.")

    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    if not cap.isOpened():
        print("[ERROR] Could not open /dev/video0. Check camera connection and enable it via raspi-config.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 30)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"Resolution : {actual_w}x{actual_h} @ {actual_fps:.1f} fps")

    print("Live preview: press 'q' to quit, 's' to save a frame.")
    frame_count = 0
    start = time.time()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[ERROR] Failed to read frame.")
                break

            frame_count += 1
            elapsed = time.time() - start
            fps = frame_count / elapsed if elapsed > 0 else 0

            cv2.putText(frame, f"FPS: {fps:.1f} | 'q' quit | 's' save",
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.imshow("Pi Camera v2 (V4L2)", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('s'):
                snap_path = os.path.join(OUTPUT_DIR, f"snap_v4l2_{datetime.now().strftime('%H%M%S')}.jpg")
                cv2.imwrite(snap_path, frame)
                print(f"Snapshot saved → {snap_path}")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        elapsed = time.time() - start
        print(f"Captured {frame_count} frames in {elapsed:.1f}s ({frame_count/elapsed:.1f} fps avg)")


def check_camera_detected():
    """Quick check: list cameras found by libcamera."""
    import subprocess
    print("\n=== libcamera-hello detection check ===")
    result = subprocess.run(
        ["libcamera-hello", "--list-cameras"],
        capture_output=True, text=True, timeout=10
    )
    output = (result.stdout + result.stderr).strip()
    if output:
        print(output)
    else:
        print("[WARN] No output from libcamera-hello — is libcamera-apps installed?")
    return "Available cameras" in output


if __name__ == "__main__":
    print("Raspberry Pi Camera v2 — Test Suite")
    print(f"Output folder: {OUTPUT_DIR}")

    # Step 1: verify camera is visible to libcamera
    try:
        detected = check_camera_detected()
        if not detected:
            print("[WARN] Camera may not be detected. Check cable and enable camera in raspi-config.")
    except FileNotFoundError:
        print("[WARN] libcamera-hello not found. Skipping detection check.")
    except Exception as e:
        print(f"[WARN] Detection check error: {e}")

    # Step 2: run picamera2 test (preferred) or V4L2 fallback
    if PICAMERA2_AVAILABLE:
        test_with_picamera2()
    else:
        test_with_opencv_v4l2()
