"""
Camera abstract base class.

open() must never raise — return False if the device is absent.
read_frame() returns an np.ndarray or None.
jpeg_frame() encodes the latest frame to JPEG bytes.

Reconnect:
  online is set to False by the sampler camera loop after OFFLINE_AFTER
  consecutive None frames or exceptions.  try_reopen() is called on each
  reconnect attempt; subclasses override it to scan alternative device indices
  rather than only retrying the configured one.
"""

from abc import ABC, abstractmethod


class Camera(ABC):
    role:    str   # "rgb" | "thermal"
    enabled: bool
    online:  bool = True   # managed by sampler; False while camera is offline

    @abstractmethod
    def open(self) -> bool:
        """Open the device. Returns False if unavailable — never raises."""

    @abstractmethod
    def read_frame(self):
        """Capture and return the latest frame (np.ndarray) or None."""

    def try_reopen(self) -> bool:
        """
        Attempt to reconnect after going offline.  Called by the sampler every
        RECONNECT_INTERVAL_S while the camera is offline.

        Default: release existing handle then call open().
        Subclasses override to also scan alternative device indices when the
        camera may have re-enumerated to a different /dev/videoN.
        """
        self.release()
        return self.open()

    def jpeg_frame(self, quality: int = 70):
        """Encode latest frame to JPEG bytes, or None on failure."""
        try:
            import cv2
            frame = self.read_frame()
            if frame is None:
                return None
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            return bytes(buf) if ok else None
        except Exception:
            return None

    @abstractmethod
    def release(self) -> None:
        """Release the device handle."""
