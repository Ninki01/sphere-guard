"""
Session: manages one recording session folder.

Thread-safety model (mirrors original robot_server.py lock discipline):
  _lock covers session state + CSV handles
  _vid_lock covers VideoWriter instances (never acquired while _lock is held)

Files created per session:
  meta.json            — start/stop metadata, schema_version, sensor manifest,
                         sensor_events (offline/reconnected during session)
  sensors.csv          — FIXED schema (schema.COLUMNS), 20 Hz rows; absent sensor → ""
  commands.csv         — fixed header, joystick + button + watchdog events
  frames_{role}.csv    — per camera: frame_index, t_ms
  video_{role}.avi     — per camera via VideoWriter
"""

import csv
import json
import os
import threading
from pathlib import Path

from shared.recording.video_writer import VideoWriter
from shared.sensors.schema         import COLUMNS, SCHEMA_VERSION
from shared.util.clock             import now_ms, now_local_str, ms_to_local_str


class Session:
    def __init__(self):
        self._lock       = threading.Lock()
        self._vid_lock   = threading.Lock()
        self.active      = False
        self.session_id  = None
        self.folder      = None

        # CSV handles (guarded by _lock)
        self._sensor_fh  = None
        self._sensor_wr  = None
        self._cmd_fh     = None
        self._cmd_wr     = None
        self._frame_fhs  = {}   # role → file handle
        self._frame_wrs  = {}   # role → csv.writer

        # Row counters (guarded by _lock)
        self._sensor_rows = 0
        self._frame_rows  = {}  # role → int
        self._frame_idx   = {}  # role → int (cumulative frame count)

        # VideoWriters (guarded by _vid_lock)
        self._vid_writers = {}  # role → VideoWriter
        self._vid_dims    = {}  # role → (width, height) at open time

        self._flush_every       = 20
        self._cam_roles         = []
        self._start_ms          = 0
        self._meta_path         = None
        self._settings_snapshot = {}
        self._robot_id          = None
        self._sensor_manifest   = []
        self._sensor_events     = []   # [{t_ms, sensor, event}] appended during session
        self._camera_events     = []   # [{t_ms, camera, event}] appended during session
        self._cam_manifest         = []   # [{role, device, width, height, fps}]
        self._fusion_snapshot      = None  # fusion config snapshot at session start
        self._network_test_snapshot = None  # latest speed test result at session start

    # ──────────────────────────────────────────────────────────────────────
    def start(self, cfg, active_sensors: list, cameras: list) -> None:
        """
        Create session folder, open all CSV handles, write initial meta.json.

        active_sensors: list of Sensor instances
        cameras:        list of Camera instances
        """
        self._flush_every = cfg.logging.flush_every
        self._robot_id    = cfg.robot.id
        self._cam_roles   = [cam.role for cam in cameras if cam.enabled and cam._cap is not None]
        self._sensor_events  = []
        self._camera_events  = []
        self._vid_dims       = {}

        # Session folder name uses local time (MYT) for human readability
        ts = now_local_str().replace(" MYT", "").replace(" ", "_").replace(":", "-")
        session_id = f"session_{ts}"
        folder = Path(cfg.paths.data_dir) / session_id
        folder.mkdir(parents=True, exist_ok=True)

        self._start_ms  = now_ms()
        self.session_id = session_id
        self.folder     = str(folder)
        self._meta_path = str(folder / "meta.json")

        # Snapshot current drive/steering settings
        self._settings_snapshot = {
            "forward_speed":  cfg.drive.forward_speed,
            "backward_speed": cfg.drive.backward_speed,
            "spin_speed":     cfg.drive.spin_speed,
            "deadzone":       cfg.drive.deadzone,
            "servo_center":   cfg.steering.servo_center,
            "servo_left":     cfg.steering.servo_left,
            "servo_right":    cfg.steering.servo_right,
        }

        # Sensor manifest (sensors present and online at session start —
        # pre-registered offline sensors that reconnect mid-session are recorded
        # via sensor_events and their columns start filling in from that row).
        self._sensor_manifest = [
            {"name": s.name, "address": hex(s.addr) if s.addr else "n/a",
             "driver": type(s).__name__, "fixed": s.is_fixed}
            for s in active_sensors if s.online
        ]

        # Fusion config snapshot at session start (for offline reproduction)
        fcfg = getattr(cfg, "fusion", None)
        if fcfg is not None:
            self._fusion_snapshot = {
                "homography":             getattr(fcfg, "homography", None),
                "calibration_date":       getattr(fcfg, "calibration_date", None),
                "calibration_distance_m": getattr(fcfg, "calibration_distance_m", None),
                "blend_alpha":            getattr(fcfg, "blend_alpha", 0.4),
                "colormap":               getattr(fcfg, "colormap", "INFERNO"),
            }

        # Speed test snapshot (latest result if one has been run)
        pi = next((s for s in active_sensors if type(s).__name__ == "PiInternal"), None)
        if pi is not None:
            result = getattr(pi, "_speed_test_result", {})
            if result.get("status") not in (None, "idle", "running"):
                self._network_test_snapshot = dict(result)

        # Camera manifest (active cameras at session start)
        self._cam_manifest = [
            {
                "role":   cam.role,
                "device": getattr(cam, "_device", "?"),
                "width":  getattr(cam, "_width",  "?"),
                "height": getattr(cam, "_height", "?"),
                "fps":    getattr(cam, "_fps",    "?"),
            }
            for cam in cameras
            if cam.enabled and cam._cap is not None and cam.role in self._cam_roles
        ]

        # Write initial meta.json
        self._write_meta(self._build_meta(complete=False))

        with self._lock:
            # sensors.csv — fixed schema: always all COLUMNS, absent → ""
            sf = open(folder / "sensors.csv", "w", newline="")
            sw = csv.DictWriter(sf, fieldnames=COLUMNS,
                                extrasaction="ignore", restval="")
            sw.writeheader()
            self._sensor_fh  = sf
            self._sensor_wr  = sw
            self._sensor_rows = 0

            # commands.csv
            cmd_cols = ["t_ms", "source", "action", "x", "y", "servo_angle", "throttle", "extra"]
            cf = open(folder / "commands.csv", "w", newline="")
            cw = csv.DictWriter(cf, fieldnames=cmd_cols, extrasaction="ignore")
            cw.writeheader()
            self._cmd_fh = cf
            self._cmd_wr = cw

            # frames_{role}.csv
            for role in self._cam_roles:
                ff = open(folder / f"frames_{role}.csv", "w", newline="")
                fw = csv.DictWriter(ff, fieldnames=["frame_index", "t_ms"])
                fw.writeheader()
                self._frame_fhs[role] = ff
                self._frame_wrs[role] = fw
                self._frame_rows[role] = 0
                self._frame_idx[role]  = 0

            self.active = True

        # VideoWriters — opened with _vid_lock only
        with self._vid_lock:
            for cam in cameras:
                if not cam.enabled or cam._cap is None or cam.role not in self._cam_roles:
                    continue
                vw = VideoWriter()
                vid_path = str(folder / f"video_{cam.role}.avi")
                w   = getattr(cam, "_width",  256)
                h   = getattr(cam, "_height", 192) if cam.role == "thermal" else getattr(cam, "_height", 480)
                fps = getattr(cam, "_fps", 30)
                vw.open(vid_path, fps, w, h)
                self._vid_writers[cam.role]  = vw
                self._vid_dims[cam.role]     = (w, h)

    # ──────────────────────────────────────────────────────────────────────
    def stop(self) -> None:
        """Three-phase stop preserving original lock discipline."""
        with self._lock:
            self.active = False

        with self._vid_lock:
            for vw in self._vid_writers.values():
                vw.release()
            self._vid_writers.clear()

        with self._lock:
            sensor_rows = self._sensor_rows
            frame_rows  = dict(self._frame_rows)
            for fh in [self._sensor_fh, self._cmd_fh] + list(self._frame_fhs.values()):
                if fh:
                    try:
                        fh.flush()
                        fh.close()
                    except Exception:
                        pass
            self._sensor_fh = None
            self._sensor_wr = None
            self._cmd_fh    = None
            self._cmd_wr    = None
            self._frame_fhs.clear()
            self._frame_wrs.clear()

        self._write_meta(self._build_meta(
            complete=True,
            sensor_rows=sensor_rows,
            frame_rows=frame_rows,
        ))

    # ──────────────────────────────────────────────────────────────────────
    def log_sensor(self, row: dict) -> None:
        """Write one sensor row.  Missing columns are written as "" by DictWriter."""
        with self._lock:
            if not self.active or self._sensor_wr is None:
                return
            row["t_ms"] = now_ms()
            self._sensor_wr.writerow(row)
            self._sensor_rows += 1
            if self._sensor_rows % self._flush_every == 0:
                self._sensor_fh.flush()

    def log_command(self, source: str, action: str,
                    x: float = 0.0, y: float = 0.0,
                    angle: float = 0.0, throttle: float = 0.0,
                    extra: str = "") -> None:
        with self._lock:
            if not self.active or self._cmd_wr is None:
                return
            self._cmd_wr.writerow({
                "t_ms": now_ms(), "source": source, "action": action,
                "x": x, "y": y, "servo_angle": angle, "throttle": throttle,
                "extra": extra,
            })
            self._cmd_fh.flush()

    def log_frame(self, role: str, frame) -> None:
        """Write frame to video and log the frame index + timestamp."""
        with self._vid_lock:
            vw = self._vid_writers.get(role)
            if vw and vw.is_open:
                vw.write(frame)
            else:
                return

        with self._lock:
            if not self.active or role not in self._frame_wrs:
                return
            idx = self._frame_idx.get(role, 0)
            self._frame_wrs[role].writerow({"frame_index": idx, "t_ms": now_ms()})
            self._frame_idx[role]  = idx + 1
            self._frame_rows[role] = self._frame_rows.get(role, 0) + 1
            if self._frame_rows[role] % self._flush_every == 0:
                self._frame_fhs[role].flush()

    def log_sensor_event(self, sensor_name: str, event: str, t_ms: int) -> None:
        """
        Record a sensor lifecycle event (offline / reconnected) into meta.json.

        event: "offline" | "reconnected"
        Called by Sampler when a sensor transitions state.  Only appended while
        session is active; meta.json is rewritten atomically after each event so
        a partial session still has the event list.
        """
        entry = {"t_ms": t_ms, "sensor": sensor_name, "event": event}
        with self._lock:
            if not self.active:
                return
            self._sensor_events.append(entry)
        # Rewrite meta outside the lock (atomic write, slow I/O)
        self._write_meta(self._build_meta(complete=False))

    def log_camera_event(self, role: str, event: str, t_ms: int) -> None:
        """
        Record a camera lifecycle event (offline / reconnected) into meta.json.

        event: "offline" | "reconnected"
        Parallel to log_sensor_event(); called by the sampler camera loop.
        """
        entry = {"t_ms": t_ms, "camera": role, "event": event}
        with self._lock:
            if not self.active:
                return
            self._camera_events.append(entry)
        self._write_meta(self._build_meta(complete=False))

    def get_video_writer_dims(self, role: str):
        """
        Return (width, height) of the open VideoWriter for this camera role,
        or None if no writer was opened (camera was absent at session start).

        Used by the sampler camera loop to detect resolution mismatches when a
        camera reconnects with different dimensions.
        """
        return self._vid_dims.get(role)

    # ──────────────────────────────────────────────────────────────────────
    def _build_meta(self, complete: bool,
                    sensor_rows: int = 0,
                    frame_rows: dict = None) -> dict:
        end_ms = now_ms()
        meta = {
            "session_id":        self.session_id,
            "robot_id":          self._robot_id,
            "schema_version":    SCHEMA_VERSION,
            "start_time_ms":     self._start_ms,
            "start_time_local":  ms_to_local_str(self._start_ms),
            "settings":          self._settings_snapshot,
            "sensors":           self._sensor_manifest,
            "sensor_events":     list(self._sensor_events),
            "cameras":           self._cam_manifest,
            **({"camera_events": list(self._camera_events)} if self._camera_events else {}),
        }
        if self._fusion_snapshot is not None:
            meta["fusion"] = self._fusion_snapshot
        if self._network_test_snapshot is not None:
            meta["network_test"] = self._network_test_snapshot
        if complete:
            meta.update({
                "end_time_ms":   end_ms,
                "end_time_local": ms_to_local_str(end_ms),
                "duration_s":    round((end_ms - self._start_ms) / 1000.0, 2),
                "status":        "complete",
                "rows": {
                    "sensors": sensor_rows,
                    **{f"frames_{r}": (frame_rows or {}).get(r, 0) for r in self._cam_roles},
                },
                # frames_written mirrors rows for Firebase contract
                "cameras": [
                    {**c, "frames_written": (frame_rows or {}).get(c["role"], 0)}
                    for c in self._cam_manifest
                ],
            })
        else:
            meta["status"] = "partial"
        return meta

    def _write_meta(self, data: dict) -> None:
        """Atomic write of meta.json via temp file + os.replace."""
        if self._meta_path is None:
            return
        tmp = self._meta_path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self._meta_path)
        except Exception:
            pass
