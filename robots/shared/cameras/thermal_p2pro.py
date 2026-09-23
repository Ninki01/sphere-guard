"""
InfiRay P2 Pro thermal camera — UVC device delivering a 256x384 combined frame.

Frame layout (from P2 Pro documentation — NOT empirically verified against hardware):
  - Top half    (rows 0..191):  visible thermal image (BGR, displayable directly)
  - Bottom half (rows 192..383): raw temperature data

Temperature decoding (UNVERIFIED):
  Each pixel in the bottom half is a uint16, big-endian, in units of 0.01 K.
  Convert to °C: temp_c = (uint16_value * 0.01) - 273.15

  ⚠️  WARNING: temperature decoding has NOT been tested against the actual hardware.
  A one-time warning is logged on the first call to read_temp_at().
  See CHANGELOG Known Issues: "P2 Pro temperature decoding untested against hardware."

The image half (top) is a standard BGR frame and is safe for streaming/recording.
Missing/unplugged camera: open() returns False without blocking startup.
"""

import struct
import threading

from shared.cameras.base import Camera
from shared.util.log     import warn, info

try:
    import cv2
    import numpy as np
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

_FRAME_W      = 256
_COMBINED_H   = 384
_IMAGE_H      = 192  # top half
_TEMP_H       = 192  # bottom half


class ThermalP2Pro(Camera):
    role    = "thermal"
    enabled = True

    def __init__(self, cam_cfg):
        self._device  = cam_cfg.device
        self.enabled  = getattr(cam_cfg, "enabled", False)
        self._cap     = None
        self._frame   = None
        self._temp_half = None
        self._temp_lock = threading.Lock()
        self._temp_warned = False

    def open(self) -> bool:
        if not _CV2_OK:
            warn("ThermalP2Pro: cv2 not available")
            return False
        try:
            cap = cv2.VideoCapture(self._device)
            if not cap.isOpened():
                warn(f"ThermalP2Pro: cannot open device {self._device}")
                return False
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  _FRAME_W)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, _COMBINED_H)
            self._cap = cap
            info(f"ThermalP2Pro: opened device {self._device} ({_FRAME_W}x{_COMBINED_H} combined)")
            return True
        except Exception as e:
            warn(f"ThermalP2Pro: open failed: {e}")
            return False

    def read_frame(self):
        """Returns the image half (top 256x192 BGR), or None."""
        if self._cap is None:
            return None
        try:
            ok, combined = self._cap.read()
            if not ok or combined is None:
                return None
            image_half, temp_half = self.split_frame(combined)
            with self._temp_lock:
                self._temp_half = temp_half
            self._frame = image_half
            return image_half
        except Exception:
            return None

    def split_frame(self, combined_frame):
        """Split 256x384 combined frame into (image_half, temp_half)."""
        image_half = combined_frame[:_IMAGE_H, :, :]
        temp_half  = combined_frame[_IMAGE_H:, :, :]
        return image_half, temp_half

    def read_temp_at(self, px_x: int, px_y: int):
        """
        Return temperature in °C at pixel (px_x, px_y) of the thermal image.

        UNVERIFIED against hardware. Assumes each 2-byte value in the bottom
        half is a big-endian uint16 in units of 0.01 K (P2 Pro documentation).
        Returns None on any error or if no frame has been captured yet.
        """
        if not self._temp_warned:
            warn("ThermalP2Pro.read_temp_at(): temperature decoding is UNVERIFIED "
                 "against hardware — see CHANGELOG Known Issues.")
            self._temp_warned = True

        with self._temp_lock:
            half = self._temp_half

        if half is None or not _CV2_OK:
            return None
        try:
            # BGR pixel → reconstruct uint16 big-endian from blue+green channels
            b = int(half[px_y, px_x, 0])
            g = int(half[px_y, px_x, 1])
            raw = (b << 8) | g
            return round(raw * 0.01 - 273.15, 2)
        except Exception:
            return None

    def try_reopen(self) -> bool:
        """
        On reconnect: try the configured device first.  If that fails, scan
        indices 0–9 for a device that reports the P2 Pro's distinctive 256×384
        combined frame size (image + temperature halves).
        """
        self.release()
        if self.open():
            return True
        if not _CV2_OK or not isinstance(self._device, int):
            return False
        orig = self._device
        for idx in range(10):
            if idx == orig:
                continue
            try:
                probe = cv2.VideoCapture(idx)
                if probe.isOpened():
                    w = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    probe.release()
                    if w == _FRAME_W and h == _COMBINED_H:
                        self._device = idx
                        if self.open():
                            info(f"ThermalP2Pro: reconnected on device {idx} "
                                 f"(configured: {orig})")
                            return True
                else:
                    probe.release()
            except Exception:
                pass
        self._device = orig
        return False

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
