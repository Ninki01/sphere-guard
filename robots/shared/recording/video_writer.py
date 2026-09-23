"""
Per-camera VideoWriter wrapper.

fps is taken from the camera's configured fps (e.g. 30), NOT hardcoded to 20.
This fixes the existing slow-motion bug where the old server opened VideoWriter
at 20 fps while the RGB camera delivered ~30 fps actual (verified: 754 frames
in 25.24 s in session_2026-07-03_16-20-27 → ~29.9 fps).

frames_{role}.csv remains the authoritative timeline for data sync regardless
of the recorded video playback speed.
"""

try:
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False


class VideoWriter:
    def __init__(self):
        self._writer = None
        self._path   = None

    def open(self, path: str, fps: float, width: int, height: int) -> None:
        if not _CV2_OK:
            return
        try:
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            self._writer = cv2.VideoWriter(path, fourcc, fps, (width, height))
            self._path   = path
        except Exception:
            self._writer = None

    def write(self, frame) -> bool:
        if self._writer is None or frame is None:
            return False
        try:
            self._writer.write(frame)
            return True
        except Exception:
            return False

    def release(self) -> None:
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception:
                pass
            self._writer = None

    @property
    def is_open(self) -> bool:
        return self._writer is not None
