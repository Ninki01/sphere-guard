"""
Fusion overlay: warp thermal frame onto RGB frame and blend.

Pure image processing — no camera I/O, no server state.
Called by Sampler._camera_loop (RGB branch) when at least one client is
connected to GET /stream/fusion.

Homography convention: maps thermal pixel coordinates → RGB pixel coordinates.
Computed by tools/calibrate_fusion.py; stored in config.yaml as fusion.homography
(3×3 row-major flat list of 9 floats).

Handles all absence / misconfiguration gracefully — blend() always returns a
BGR numpy array and never raises.
"""

try:
    import cv2 as _cv2
    import numpy as _np
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

_COLORMAPS = {
    "INFERNO": 9,   # cv2.COLORMAP_INFERNO
    "JET":     2,   # cv2.COLORMAP_JET
    "HOT":     11,  # cv2.COLORMAP_HOT
    "MAGMA":   16,  # cv2.COLORMAP_MAGMA
    "TURBO":   20,  # cv2.COLORMAP_TURBO
    "BONE":    1,   # cv2.COLORMAP_BONE
}

_FONT = 0  # cv2.FONT_HERSHEY_SIMPLEX


def _text_overlay(frame, msg: str, color=(255, 200, 50)):
    """Write a centred warning message on a copy of frame."""
    if not _CV2_OK:
        return frame
    out = frame.copy()
    h, w = out.shape[:2]
    scale = max(0.45, w / 640)
    thick = max(1, int(scale * 1.5))
    (tw, th), _ = _cv2.getTextSize(msg, _FONT, scale, thick)
    x = (w - tw) // 2
    y = (h + th) // 2
    _cv2.rectangle(out, (x - 6, y - th - 6), (x + tw + 6, y + 6), (0, 0, 0), -1)
    _cv2.putText(out, msg, (x, y), _FONT, scale, color, thick, 16)  # 16=LINE_AA
    return out


def _blank(h=480, w=640):
    if not _CV2_OK:
        return None
    return _np.zeros((h, w, 3), dtype=_np.uint8)


class FusionOverlay:
    """
    Stateless per-call; instantiate once per Sampler.
    Caches the parsed homography matrix so it is not re-allocated every frame.
    """

    def __init__(self):
        self._H      = None   # np.ndarray (3,3) — cached
        self._H_key  = None   # str(homography list) used as cache key

    def blend(self,
              rgb_frame,          # np.ndarray BGR, camera native size — or None
              thermal_frame,      # np.ndarray BGR 256×192 image half — or None
              homography,         # list[float] len 9 (row-major) | None
              alpha: float = 0.4,
              colormap: str = "INFERNO") -> object:
        """
        Return a blended BGR frame the same size as rgb_frame.
        Always returns a frame, never raises.
        """
        try:
            return self._blend_inner(rgb_frame, thermal_frame, homography, alpha, colormap)
        except Exception as exc:
            base = rgb_frame if rgb_frame is not None else _blank()
            if base is None:
                return None
            return _text_overlay(base, f"FUSION ERR: {exc}", color=(0, 80, 255))

    def _blend_inner(self, rgb, thermal, homography, alpha, colormap):
        if not _CV2_OK:
            return rgb  # pass-through when cv2 missing

        if rgb is None and thermal is None:
            return _text_overlay(_blank(), "NO CAMERAS AVAILABLE")

        if rgb is None:
            h, w = thermal.shape[:2]
            return _text_overlay(thermal, "RGB CAMERA MISSING")

        if thermal is None:
            return _text_overlay(rgb, "THERMAL CAMERA MISSING")

        if not homography:
            return _text_overlay(rgb, "NOT CALIBRATED -- run calibrate_fusion.py")

        h_rgb, w_rgb = rgb.shape[:2]

        # Parse + cache homography matrix
        H_key = repr(homography)
        if H_key != self._H_key:
            self._H     = _np.array(homography, dtype=_np.float64).reshape(3, 3)
            self._H_key = H_key

        # Colorise thermal (expects single-channel input for applyColorMap)
        if thermal.ndim == 3:
            gray = _cv2.cvtColor(thermal, _cv2.COLOR_BGR2GRAY)
        else:
            gray = thermal
        cmap_id = _COLORMAPS.get(str(colormap).upper(), 9)  # default INFERNO
        thermal_colored = _cv2.applyColorMap(gray, cmap_id)

        # Warp thermal → RGB frame size
        thermal_warped = _cv2.warpPerspective(thermal_colored, self._H, (w_rgb, h_rgb))

        # Blend
        a = float(max(0.0, min(1.0, alpha)))
        return _cv2.addWeighted(rgb, 1.0 - a, thermal_warped, a, 0)
