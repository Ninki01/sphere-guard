"""
RGBCamera: USB RGB camera via OpenCV VideoCapture (MJPEG, UVC).

Config fields consumed:
    cameras[i].device  — device index (int) or /dev/videoN path (str)
    cameras[i].width   — capture width  (default 640)
    cameras[i].height  — capture height (default 480)
    cameras[i].fps     — capture fps    (default 30)
"""

from shared.cameras.base import Camera
from shared.util.log     import warn, info

try:
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False


class RGBCamera(Camera):
    role    = "rgb"
    enabled = True

    def __init__(self, cam_cfg):
        self._device  = cam_cfg.device
        self._width   = getattr(cam_cfg, "width",  640)
        self._height  = getattr(cam_cfg, "height", 480)
        self._fps     = getattr(cam_cfg, "fps",     30)
        self.enabled  = getattr(cam_cfg, "enabled", True)
        self._cap     = None
        self._frame   = None

    def open(self) -> bool:
        if not _CV2_OK:
            warn("RGBCamera: cv2 not available")
            return False
        try:
            cap = cv2.VideoCapture(self._device)
            if not cap.isOpened():
                warn(f"RGBCamera: cannot open device {self._device}")
                return False
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
            cap.set(cv2.CAP_PROP_FPS,          self._fps)
            self._cap = cap
            info(f"RGBCamera: opened device {self._device} @ {self._width}x{self._height}@{self._fps}")
            return True
        except Exception as e:
            warn(f"RGBCamera: open failed: {e}")
            return False

    def read_frame(self):
        if self._cap is None:
            return None
        try:
            ok, frame = self._cap.read()
            if ok:
                self._frame = frame
                return frame
            return None
        except Exception:
            return None

    def try_reopen(self) -> bool:
        """
        On reconnect: try the configured device index first, then scan 0–9.
        USB cameras frequently enumerate to a different /dev/videoN after
        reconnection; scanning finds them and logs the new index.
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
            self._device = idx
            if self.open():
                if idx != orig:
                    info(f"RGBCamera: reconnected on device {idx} (configured: {orig})")
                return True
        self._device = orig   # restore; all indices failed
        return False

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
