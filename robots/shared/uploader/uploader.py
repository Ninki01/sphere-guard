"""
FIFO store-and-forward Firebase uploader for SphereGuard session data.

Data model:
  Cloud Storage  — all session files (CSV, JSON, MP4).
                   Path: robots/{robot_id}/sessions/{session_id}/{filename}
  Firestore      — one document per session in the "sessions" collection.
                   The dashboard queries only Firestore; files are fetched via
                   the Firebase SDK using the storage_paths in the document.
  RTDB           — NOT used. The old RTDB telemetry path is retired.

Credentials (from environment / EnvironmentFile, never from the repo):
  SG_FIREBASE_KEY    — path to service account JSON
  SG_STORAGE_BUCKET  — e.g. sphere-guard-2025.firebasestorage.app

Resume state per session: upload_state.json written atomically after every step.
Safety: /tmp/sphereguard_upload_in_progress lock file while uploading so the
robot server's auto speed test can detect and defer.

Failure taxonomy (controls whether the session is retried):
  Transient — network error, Firebase 5xx, upload timeout.
              Caller backs off and retries.  Increments attempts counter.
  Permanent — session has no usable data (empty/header-only sensors.csv),
              meta.json missing or unparseable, or sensors.csv unreadable
              after CSV repair.  No retry.  A Firestore doc is written with
              the appropriate status so the dashboard can show/filter it.
              Does NOT increment the attempts counter.
"""

import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from shared.util.clock import now_ms, ms_to_local_str, MYT_OFFSET
from shared.util.log   import info, warn, error as log_error

UPLOADER_VERSION  = "1.0.0"
_LOCK_FILE        = Path("/tmp/sphereguard_upload_in_progress")
_INACTIVE_AFTER_S = 120   # session is inactive when newest file mtime exceeds this
_MAX_ATTEMPTS     = 10    # skip session in queue after this many consecutive failures

# ── Canonical file list and legacy filename aliases ───────────────────────────
# Pre-dual-camera sessions use "video.avi" and "frames.csv".  The uploader maps
# these to their canonical names and uploads to the canonical storage paths.
_CANONICAL_FILES = (
    "meta.json",
    "sensors.csv",
    "commands.csv",
    "frames_rgb.csv",
    "frames_thermal.csv",
    "video_rgb.avi",
    "video_thermal.avi",
    "video_rgb.mp4",
    "video_thermal.mp4",
)
# canonical_name → legacy_filename (checked only when canonical is absent)
_LEGACY_FILENAME_MAP = {
    "video_rgb.avi":  "video.avi",   # single-camera pre-dual era
    "frames_rgb.csv": "frames.csv",  # matching legacy frames CSV
}

_SESSION_NAME_RE = re.compile(
    r"session_(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})$"
)

# ── Firebase initialisation ───────────────────────────────────────────────────

_fb_app  = None
_bucket  = None
_fs_db   = None


def _init_firebase(key_path: str, bucket_name: str) -> bool:
    """Initialise firebase-admin once.  Safe to call repeatedly."""
    global _fb_app, _bucket, _fs_db
    if _fb_app is not None:
        return True
    try:
        import firebase_admin
        from firebase_admin import credentials, storage, firestore
        cred    = credentials.Certificate(key_path)
        _fb_app = firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})
        _bucket = storage.bucket()
        _fs_db  = firestore.client()
        info("[UPLOADER] Firebase initialised")
        return True
    except Exception as exc:
        log_error(f"[UPLOADER] Firebase init failed: {exc}")
        return False


# ── Connectivity probe ────────────────────────────────────────────────────────

def _check_connectivity() -> bool:
    """Return True if internet is reachable (TCP probe — fast, no DNS required)."""
    import socket
    for host, port in [("8.8.8.8", 53), ("1.1.1.1", 443), ("142.250.80.46", 443)]:
        try:
            with socket.create_connection((host, port), timeout=3):
                return True
        except OSError:
            pass
    return False


# ── Upload state persistence ──────────────────────────────────────────────────

def _load_state(session_dir: Path) -> dict:
    p = session_dir / "upload_state.json"
    if p.exists():
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "uploaded_files":   [],
        "firestore_written": False,
        "video_status":     {},
        "attempts":         0,
        "last_error":       "",
    }


def _save_state(session_dir: Path, state: dict) -> None:
    p   = session_dir / "upload_state.json"
    tmp = str(p) + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, str(p))
    except Exception as exc:
        warn(f"[UPLOADER] Could not save upload_state.json: {exc}")


# ── Session eligibility ───────────────────────────────────────────────────────

def _is_inactive(session_dir: Path) -> bool:
    """True if the session is not currently being written to by the robot server."""
    meta_path = session_dir / "meta.json"
    if meta_path.exists():
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            if meta.get("end_time_ms"):
                return True  # cleanly stopped
        except Exception:
            pass
    # Fallback: newest file mtime > threshold
    try:
        newest = max(
            (p.stat().st_mtime for p in session_dir.iterdir() if p.is_file()),
            default=0.0,
        )
        return (time.time() - newest) > _INACTIVE_AFTER_S
    except Exception:
        return False


def _find_sessions(data_dir: Path):
    """
    Return all incomplete (firestore_written=False) session folders sorted
    FIFO (oldest first, by folder name which encodes timestamp).
    Includes stuck sessions — callers handle them by inspecting attempt count.
    """
    if not data_dir.exists():
        return []
    candidates = sorted(
        [d for d in data_dir.iterdir()
         if d.is_dir() and d.name.startswith("session_")],
        key=lambda d: d.name,
    )
    result = []
    for s in candidates:
        state = _load_state(s)
        if state.get("firestore_written"):
            continue       # successfully uploaded (or empty session resolved)
        if state.get("permanently_skipped"):
            continue       # unresolvable — no meta.json; skip forever
        if not _is_inactive(s):
            continue       # still recording — never touch active sessions
        result.append(s)
    return result


# ── Session file discovery ───────────────────────────────────────────────────

def _parse_session_start_ms(session_dir: Path) -> int | None:
    """
    Derive start_time_ms from the folder name (format: session_YYYY-MM-DD_HH-MM-SS).
    The folder timestamp is MYT (UTC+8).  Returns epoch ms UTC, or None if the
    folder name does not match the expected pattern.
    """
    m = _SESSION_NAME_RE.match(session_dir.name)
    if not m:
        return None
    try:
        y, mo, d, h, mi, s = (int(x) for x in m.groups())
        dt_local = datetime(y, mo, d, h, mi, s)
        # MYT is UTC+8; subtract to get UTC, then get epoch ms
        dt_utc = dt_local - MYT_OFFSET
        return int(dt_utc.replace(tzinfo=timezone.utc).timestamp() * 1000)
    except (ValueError, OverflowError):
        return None


def _map_session_files(session_dir: Path) -> tuple[dict, set]:
    """
    Resolve canonical filenames to their actual paths on disk, handling legacy names.
    Returns:
      file_map  — {canonical_name: Path | None}  (None = absent)
      legacy_used — set of canonical names that resolved via a legacy filename
    """
    file_map    = {}
    legacy_used = set()
    for name in _CANONICAL_FILES:
        std = session_dir / name
        if std.exists():
            file_map[name] = std
        elif name in _LEGACY_FILENAME_MAP:
            legacy = session_dir / _LEGACY_FILENAME_MAP[name]
            if legacy.exists():
                file_map[name] = legacy
                legacy_used.add(name)
            else:
                file_map[name] = None
        else:
            file_map[name] = None
    return file_map, legacy_used


# ── CSV repair (crash recovery) ───────────────────────────────────────────────

def _repair_csv_tail(path: Path) -> None:
    """Drop a truncated final line left by a crash mid-write."""
    if not path.exists():
        return
    try:
        data = path.read_bytes()
        if not data:
            return
        if data[-1:] != b"\n":
            last_nl = data.rfind(b"\n")
            if last_nl > 0:
                warn(f"[UPLOADER] Dropping truncated last line from {path.name}")
                path.write_bytes(data[: last_nl + 1])
    except Exception as exc:
        warn(f"[UPLOADER] Could not repair {path.name}: {exc}")


# ── Partial-session metadata recovery ─────────────────────────────────────────

def _recover_partial_meta(session_dir: Path):
    """
    For sessions that crashed before stop() wrote end_time_ms.
    Repairs truncated CSV tails, then reads the last t_ms from sensors.csv as
    the effective end time.

    Return values:
      dict (non-empty) — success; contains recovered end_time_ms etc.
      None             — PERMANENT: sensors.csv absent, empty, or header-only
                         (zero data rows).  Caller should treat as empty session.
      {}  (empty dict) — TRANSIENT: sensors.csv exists but could not be read
                         (IO/permission error).  Caller should retry later.
    """
    sensors_csv = session_dir / "sensors.csv"
    if not sensors_csv.exists():
        return None   # permanent — no data file at all

    _repair_csv_tail(sensors_csv)
    for fname in ("commands.csv", "frames_rgb.csv", "frames_thermal.csv"):
        _repair_csv_tail(session_dir / fname)

    last_t_ms   = None
    sensor_rows = 0
    try:
        with open(sensors_csv, newline="") as f:
            for row in csv.DictReader(f):
                sensor_rows += 1
                try:
                    last_t_ms = int(row["t_ms"])
                except (KeyError, ValueError):
                    pass
    except Exception as exc:
        warn(f"[UPLOADER] Could not read sensors.csv: {exc}")
        return {}   # transient — IO error, retry later

    if last_t_ms is None:
        return None   # permanent — file exists but has zero data rows

    start_ms = None
    try:
        with open(session_dir / "meta.json") as f:
            meta = json.load(f)
        start_ms = meta.get("start_time_ms")
    except Exception:
        pass

    recovery = {
        "end_time_ms":           last_t_ms,
        "end_time_local":        ms_to_local_str(last_t_ms),
        "recovered":             True,
        "effective_sensor_rows": sensor_rows,
    }
    if start_ms:
        recovery["duration_s"] = round((last_t_ms - start_ms) / 1000.0, 2)
    return recovery


# ── Video conversion ──────────────────────────────────────────────────────────

def _convert_video(avi_path: Path | None, mp4_path: Path) -> str:
    """
    Transcode AVI → H.264 MP4 via ffmpeg with niceness 10.
    Returns "ok" | "unrecoverable" | "none" (no source avi).
    `avi_path` may be None (e.g. absent from file_map) — treated same as missing.
    """
    if avi_path is None or not avi_path.exists():
        return "none"
    if mp4_path.exists() and mp4_path.stat().st_size > 0:
        info(f"[UPLOADER] {mp4_path.name} already exists — skipping conversion")
        return "ok"

    info(f"[UPLOADER] Converting {avi_path.name} → {mp4_path.name}")
    cmd = [
        "nice", "-n", "10",
        "ffmpeg", "-y",
        "-i", str(avi_path),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-movflags", "+faststart",
        str(mp4_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            timeout=900,  # 15 min hard deadline
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode == 0:
            info(f"[UPLOADER] Conversion OK: {mp4_path.name}")
            return "ok"
        snippet = result.stderr[-300:].decode(errors="replace").strip()
        warn(f"[UPLOADER] ffmpeg rc={result.returncode} for {avi_path.name}: {snippet}")
        return "unrecoverable"
    except subprocess.TimeoutExpired:
        warn(f"[UPLOADER] ffmpeg timeout for {avi_path.name}")
        return "unrecoverable"
    except FileNotFoundError:
        warn("[UPLOADER] ffmpeg not found — video conversion unavailable")
        return "unrecoverable"
    except Exception as exc:
        warn(f"[UPLOADER] ffmpeg error for {avi_path.name}: {exc}")
        return "unrecoverable"


# ── Cloud Storage upload ──────────────────────────────────────────────────────

def _upload_file(local_path: Path, storage_path: str, dry_run: bool) -> bool:
    if dry_run:
        info(f"[UPLOADER] DRY-RUN upload: {local_path.name} → gs://{storage_path}")
        return True
    if not local_path.exists():
        return False
    try:
        blob = _bucket.blob(storage_path)
        blob.upload_from_filename(str(local_path))
        # Do NOT call blob.make_public() — dashboard authenticates via Firebase SDK
        info(f"[UPLOADER] Uploaded: {local_path.name}")
        return True
    except Exception as exc:
        warn(f"[UPLOADER] Upload failed [{local_path.name}]: {exc}")
        return False


# ── Firestore document ────────────────────────────────────────────────────────

def _build_firestore_doc(meta: dict, state: dict, robot_id: str,
                         recovery: dict, storage_prefix: str,
                         status: str = None) -> dict:
    """
    Build the Firestore document for a session.

    `status` overrides the auto-detected value ("complete"/"partial") when set
    explicitly — pass "empty" for sessions with no data rows.
    """
    from firebase_admin import firestore as fs

    end_time_ms = meta.get("end_time_ms") or recovery.get("end_time_ms")
    duration_s  = meta.get("duration_s")  or recovery.get("duration_s")

    # Row counts: from meta.json when complete; recovered sensor count for partial
    rows = dict(meta.get("rows", {}))
    if recovery.get("effective_sensor_rows"):
        rows["sensors"] = recovery["effective_sensor_rows"]
    cameras_meta = meta.get("cameras", [])
    for cam in cameras_meta:
        key = f"frames_{cam.get('role', '')}"
        if key not in rows:
            rows[key] = cam.get("frames_written", 0)

    # Cameras list with video_status from upload state
    video_status = state.get("video_status", {})
    cameras = [
        {
            "role":           cam.get("role", ""),
            "fps":            cam.get("fps"),
            "frames_written": cam.get("frames_written",
                                      rows.get(f"frames_{cam.get('role','')}", 0)),
            "video_status":   video_status.get(cam.get("role", ""), "none"),
        }
        for cam in cameras_meta
    ]

    # Storage path map — only files that were actually uploaded
    storage_paths = {
        fname: f"{storage_prefix}{fname}"
        for fname in state.get("uploaded_files", [])
    }

    if status is None:
        status = "complete" if meta.get("end_time_ms") else "partial"

    doc = {
        "session_id":       meta.get("session_id"),
        "device_id":        robot_id,
        "status":           status,
        "schema_version":   meta.get("schema_version", 3),
        "start_time_ms":    meta.get("start_time_ms"),
        "start_time_local": meta.get("start_time_local"),
        "end_time_ms":      end_time_ms,
        "end_time_local":   (
            meta.get("end_time_local")
            or (ms_to_local_str(end_time_ms) if end_time_ms else None)
        ),
        "duration_s":       duration_s,
        "rows":             rows,
        "sensors_present":  [s["name"] for s in meta.get("sensors", [])],
        "sensor_events":    meta.get("sensor_events", []),
        "camera_events":    meta.get("camera_events", []),
        "cameras":          cameras,
        "settings":         meta.get("settings", {}),
        "storage_paths":    storage_paths,
        "uploaded_at":      fs.SERVER_TIMESTAMP,
        "device_clock_ms":  now_ms(),
        "uploader_version": UPLOADER_VERSION,
    }

    # Optional fields — only include when present
    if meta.get("network_test"):
        doc["network_test"] = meta["network_test"]
    fusion = meta.get("fusion", {})
    if fusion and fusion.get("homography"):
        doc["homography"] = fusion["homography"]
    # Record legacy filename use so the dashboard knows the original filenames
    lf = meta.get("legacy_filenames") or recovery.get("legacy_filenames")
    if lf:
        doc["legacy_filenames"] = lf

    return doc


def _write_firestore(session_id: str, doc: dict, dry_run: bool) -> bool:
    if dry_run:
        info(f"[UPLOADER] DRY-RUN Firestore: would write sessions/{session_id}")
        return True
    try:
        _fs_db.collection("sessions").document(session_id).set(doc)
        info(f"[UPLOADER] Firestore doc written: sessions/{session_id}")
        return True
    except Exception as exc:
        warn(f"[UPLOADER] Firestore write failed [{session_id}]: {exc}")
        return False


# ── Session pipeline ──────────────────────────────────────────────────────────

def _fail_transient(state: dict, session_dir: Path, msg: str) -> None:
    """
    Record a TRANSIENT failure (network, Firebase 5xx, upload timeout).
    Increments the attempts counter so the main loop applies back-off and
    eventually marks the session stuck after _MAX_ATTEMPTS.
    """
    state["attempts"]   = state.get("attempts", 0) + 1
    state["last_error"] = msg
    warn(f"[UPLOADER] {session_dir.name}: {msg}")
    _save_state(session_dir, state)


def _mark_permanently_skipped(state: dict, session_dir: Path, msg: str) -> None:
    """
    Mark a session as permanently unresolvable WITHOUT writing a Firestore doc.
    Used only when meta.json is absent or unparseable (so there is no session_id
    to use as a Firestore document key).  Does NOT increment attempts.
    """
    warn(f"[UPLOADER] {session_dir.name}: permanent skip — {msg}")
    state["permanently_skipped"] = True
    state["last_error"]          = msg
    _save_state(session_dir, state)


def _handle_empty_session(session_dir: Path, meta: dict, state: dict,
                           robot_id: str, dry_run: bool) -> bool:
    """
    Permanently resolve an empty session (zero data rows in sensors.csv).
    Uploads meta.json (best-effort), writes a Firestore doc with status="empty",
    and marks the session done.

    Returns True once the Firestore doc is written.
    Returns False only if the Firestore write fails (transient network error) —
    in that case the attempts counter IS incremented so we retry later.
    Does NOT increment attempts for discovering that the session is empty.
    """
    session_id     = meta.get("session_id") or session_dir.name
    storage_prefix = f"robots/{robot_id}/sessions/{session_id}/"

    info(
        f"[UPLOADER] Session {session_id} is empty (aborted recording) "
        f"— recording metadata only"
    )
    state["session_status"] = "empty"
    _save_state(session_dir, state)

    # Upload meta.json — best-effort; skip if absent or upload fails
    meta_path = session_dir / "meta.json"
    if meta_path.exists() and "meta.json" not in state.get("uploaded_files", []):
        if _upload_file(meta_path, f"{storage_prefix}meta.json", dry_run):
            uploaded = set(state.get("uploaded_files", []))
            uploaded.add("meta.json")
            state["uploaded_files"] = sorted(uploaded)
            _save_state(session_dir, state)

    # Write Firestore doc with status="empty" — this IS the commit marker
    if not state.get("firestore_written"):
        doc = _build_firestore_doc(meta, state, robot_id, {}, storage_prefix,
                                   status="empty")
        if not _write_firestore(session_id, doc, dry_run):
            _fail_transient(state, session_dir, "firestore write failed (empty session)")
            return False
        state["firestore_written"] = True
        state["last_error"]        = ""
        _save_state(session_dir, state)

    info(f"[UPLOADER] ── Empty session resolved: {session_id} ──")
    return True


def _handle_video_only_session(session_dir: Path, state: dict, file_map: dict,
                                legacy_used: set, robot_id: str,
                                dry_run: bool) -> bool:
    """
    Resolve a session that has a video file but no meta.json and no CSVs.
    Converts and uploads the video; writes a Firestore doc with status="video_only"
    and start_time_ms derived from the folder name.

    Returns True once the Firestore doc is written.
    Returns False only on transient failures (upload / Firestore network error).
    Does NOT increment attempts for discovering the video-only condition.
    """
    session_id     = session_dir.name
    storage_prefix = f"robots/{robot_id}/sessions/{session_id}/"
    start_ms       = _parse_session_start_ms(session_dir)

    info(
        f"[UPLOADER] Session {session_id}: video-only (no sensor data) "
        f"— converting and uploading video"
    )
    state["session_status"] = "video_only"
    _save_state(session_dir, state)

    # Convert video (avi_path may be legacy e.g. video.avi → canonical video_rgb.avi)
    video_status = state.get("video_status", {})
    if video_status.get("rgb") not in ("ok", "unrecoverable"):
        avi = file_map.get("video_rgb.avi")
        mp4 = session_dir / "video_rgb.mp4"
        video_status["rgb"] = _convert_video(avi, mp4)
        state["video_status"] = video_status
        _save_state(session_dir, state)

    # Upload converted video (canonical storage name, regardless of legacy source)
    uploaded = set(state.get("uploaded_files", []))
    if video_status.get("rgb") == "ok":
        mp4_path = session_dir / "video_rgb.mp4"
        if "video_rgb.mp4" not in uploaded:
            if not _upload_file(mp4_path, f"{storage_prefix}video_rgb.mp4", dry_run):
                _fail_transient(state, session_dir, "upload failed: video_rgb.mp4")
                return False
            uploaded.add("video_rgb.mp4")
            state["uploaded_files"] = sorted(uploaded)
            _save_state(session_dir, state)

    # Write Firestore doc with status="video_only"
    if not state.get("firestore_written"):
        synthetic_meta: dict = {
            "session_id":       session_id,
            "start_time_ms":    start_ms,
            "start_time_local": ms_to_local_str(start_ms) if start_ms else None,
        }
        if legacy_used:
            synthetic_meta["legacy_filenames"] = {
                k: file_map[k].name for k in legacy_used if k in file_map
            }
        doc = _build_firestore_doc(
            synthetic_meta, state, robot_id, {}, storage_prefix,
            status="video_only",
        )
        if not _write_firestore(session_id, doc, dry_run):
            _fail_transient(state, session_dir, "firestore write failed (video_only)")
            return False
        state["firestore_written"] = True
        state["last_error"]        = ""
        _save_state(session_dir, state)

    info(f"[UPLOADER] ── Video-only session resolved: {session_id} ──")
    return True


def process_session(session_dir: Path, robot_id: str, dry_run: bool) -> bool:
    """
    Execute the full upload pipeline for one session.

    Returns True on ANY permanent resolution:
      • full upload complete (status "complete" or "partial")
      • empty session resolved (status "empty")
      • unresolvable session permanently skipped (no Firestore doc)
    Returns False only on transient failures (network, Firebase 5xx) —
    the main loop will back off and retry.

    Only transient failures increment the attempts counter; detecting that a
    session is empty or corrupt does not consume retry budget.
    State is checkpointed after each step so interrupted uploads resume cleanly.
    """
    session_id = session_dir.name
    info(f"[UPLOADER] ── Starting session: {session_id} ──")

    state                  = _load_state(session_dir)
    file_map, legacy_used  = _map_session_files(session_dir)

    # Load meta.json — required for the full pipeline and for most Firestore fields
    meta_path = file_map["meta.json"]
    if meta_path is None:
        # No meta.json — check whether there is still something worth uploading
        if file_map.get("video_rgb.avi") is not None:
            return _handle_video_only_session(
                session_dir, state, file_map, legacy_used, robot_id, dry_run)
        # Nothing recognisable — permanently skip
        reason = (
            "session folder has no recognisable files"
            if not any(v for v in file_map.values())
            else "meta.json missing"
        )
        _mark_permanently_skipped(state, session_dir, reason)
        return True
    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except Exception as exc:
        _mark_permanently_skipped(state, session_dir, f"cannot parse meta.json: {exc}")
        return True

    # Recover partial session metadata or detect empty session
    recovery = {}
    if not meta.get("end_time_ms"):
        info(f"[UPLOADER] Partial session — recovering metadata from files")
        recovery = _recover_partial_meta(session_dir)
        if recovery is None:
            # Permanent — zero data rows (empty/aborted session)
            return _handle_empty_session(session_dir, meta, state, robot_id, dry_run)
        if not recovery:
            # Transient — could not read sensors.csv (IO error)
            _fail_transient(state, session_dir,
                            "partial recovery failed (cannot read sensors.csv)")
            return False

    # Annotate any legacy filenames so _build_firestore_doc can surface them
    if legacy_used:
        recovery["legacy_filenames"] = {
            k: file_map[k].name for k in legacy_used if k in file_map
        }

    # ── Step 1: Video conversion ──────────────────────────────────────────────
    video_status = state.get("video_status", {})
    for role in ("rgb", "thermal"):
        if video_status.get(role) in ("ok", "unrecoverable"):
            continue   # already decided in a previous attempt
        avi = file_map.get(f"video_{role}.avi")   # None when absent
        mp4 = session_dir / f"video_{role}.mp4"
        video_status[role] = _convert_video(avi, mp4)
        state["video_status"] = video_status
        _save_state(session_dir, state)

    # ── Step 2: Upload files in order ─────────────────────────────────────────
    storage_prefix = f"robots/{robot_id}/sessions/{session_id}/"
    upload_order = [
        "meta.json",
        "sensors.csv",
        "commands.csv",
        "frames_rgb.csv",
        "frames_thermal.csv",
    ]
    for role in ("rgb", "thermal"):
        if video_status.get(role) == "ok":
            upload_order.append(f"video_{role}.mp4")

    uploaded = set(state.get("uploaded_files", []))
    for fname in upload_order:
        if fname in uploaded:
            continue  # resume: already uploaded in a previous run
        # MP4s are generated in session_dir; everything else uses file_map
        # (which transparently handles legacy filenames).
        if fname.endswith(".mp4"):
            local = session_dir / fname
            if not local.exists():
                continue
        else:
            local = file_map.get(fname)
            if not local:
                continue  # file absent for this session
        if not _upload_file(local, f"{storage_prefix}{fname}", dry_run):
            _fail_transient(state, session_dir, f"upload failed: {fname}")
            return False
        uploaded.add(fname)
        state["uploaded_files"] = sorted(uploaded)
        _save_state(session_dir, state)

    # ── Step 3: Firestore commit marker ───────────────────────────────────────
    if not state.get("firestore_written"):
        doc = _build_firestore_doc(meta, state, robot_id, recovery, storage_prefix)
        if not _write_firestore(session_id, doc, dry_run):
            _fail_transient(state, session_dir, "firestore write failed")
            return False
        state["firestore_written"] = True
        state["last_error"]        = ""
        _save_state(session_dir, state)

    info(f"[UPLOADER] ── Session complete: {session_id} ──")
    return True


# ── Lock file context manager ─────────────────────────────────────────────────

class _UploadLock:
    def __enter__(self):
        try:
            _LOCK_FILE.write_text(str(os.getpid()))
        except Exception:
            pass
        return self

    def __exit__(self, *_):
        try:
            _LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass


# ── Dry-run analysis and table ───────────────────────────────────────────────

def _analyze_session(session_dir: Path, robot_id: str) -> dict:
    """
    Non-destructive summary of what the uploader would do for this session.
    Does NOT repair CSV tails or read the full sensors.csv — uses a two-row
    probe to decide "empty vs partial" without any side effects.
    """
    state              = _load_state(session_dir)
    file_map, legacy_used = _map_session_files(session_dir)
    already_uploaded   = set(state.get("uploaded_files", []))

    # Files present, with legacy annotation where applicable
    files_present = []
    for name in _CANONICAL_FILES:
        path = file_map.get(name)
        if path is None or name.endswith(".mp4"):
            continue   # absent or not-yet-generated
        label = f"{name} ← {path.name}" if name in legacy_used else name
        files_present.append(label)

    # Determine session status (non-destructive)
    if state.get("firestore_written"):
        status = state.get("session_status") or "complete"
    elif state.get("permanently_skipped"):
        status = "perm_skip"
    elif state.get("session_status"):
        status = state["session_status"]    # "empty" / "video_only" set earlier
    elif file_map["meta.json"] is None:
        status = "video_only" if file_map.get("video_rgb.avi") else "empty"
    else:
        try:
            with open(file_map["meta.json"]) as f:
                meta = json.load(f)
            if meta.get("end_time_ms"):
                status = "complete"
            else:
                scsv = file_map.get("sensors.csv")
                if not scsv:
                    status = "empty"
                else:
                    with open(scsv, newline="") as f:
                        reader = csv.reader(f)
                        try:
                            next(reader)   # header
                            next(reader)   # first data row — proves non-empty
                            status = "partial"
                        except StopIteration:
                            status = "empty"
        except Exception:
            status = "corrupt_meta"

    # Files that would be uploaded (rough — video conversion outcome is unknown)
    would_upload: list[str] = []
    if not state.get("firestore_written") and status not in ("perm_skip",):
        for name in _CANONICAL_FILES:
            path = file_map.get(name)
            if path is None:
                continue
            if name in already_uploaded:
                continue
            if name.endswith(".avi"):
                mp4_name = name.replace(".avi", ".mp4")
                src = path.name if name in legacy_used else name
                would_upload.append(f"{mp4_name} (converted from {src})")
            elif not name.endswith(".mp4"):
                label = name if name not in legacy_used else f"{name} (from {path.name})"
                would_upload.append(label)

    return {
        "session_id":       session_dir.name,
        "status":           status,
        "files_present":    files_present,
        "already_uploaded": sorted(already_uploaded),
        "would_upload":     sorted(would_upload),
        "attempts":         state.get("attempts", 0),
    }


def _print_session_table(summaries: list) -> None:
    """Print a formatted per-session dry-run summary table."""
    if not summaries:
        print("[UPLOADER] DRY-RUN: no sessions found.")
        return

    W_ID = 42
    W_ST = 13
    W_FI = 42
    sep  = "─" * (W_ID + W_ST + W_FI + 3 + 16)
    hdr  = (
        f"{'SESSION':<{W_ID}} "
        f"{'STATUS':<{W_ST}} "
        f"{'FILES FOUND':<{W_FI}} "
        f"WOULD UPLOAD"
    )
    print(f"\n[UPLOADER] DRY-RUN — {len(summaries)} session(s)")
    print(sep)
    print(hdr)
    print(sep)
    for s in summaries:
        files_str  = ", ".join(s["files_present"])
        upload_str = ", ".join(s["would_upload"]) if s["would_upload"] else "(none)"
        if len(files_str) > W_FI - 1:
            files_str = files_str[:W_FI - 4] + "..."
        print(
            f"{s['session_id']:<{W_ID}} "
            f"{s['status'].upper():<{W_ST}} "
            f"{files_str:<{W_FI}} "
            f"{upload_str}"
        )
        indent = " " * (W_ID + 1)
        if s["already_uploaded"]:
            print(f"{indent}↳ already uploaded: {', '.join(s['already_uploaded'])}")
        if s["attempts"]:
            print(f"{indent}↳ prior transient attempts: {s['attempts']}")
    print(sep)
    print()


# ── Status command ────────────────────────────────────────────────────────────

def print_status(data_dir: Path) -> None:
    sessions = sorted(
        [d for d in data_dir.iterdir()
         if d.is_dir() and d.name.startswith("session_")],
        key=lambda d: d.name,
    ) if data_dir.exists() else []

    if not sessions:
        print("No sessions found.")
        return

    print(f"{'SESSION':<42} {'STATUS':<12} {'ATTS':<6} UPLOADED")
    print("─" * 80)
    for s in sessions:
        state = _load_state(s)
        meta_status = "?"
        try:
            with open(s / "meta.json") as f:
                m = json.load(f)
            meta_status = m.get("status", "?")
        except Exception:
            meta_status = "no meta"

        if state.get("firestore_written"):
            ss      = state.get("session_status", "")
            display = f"DONE ({ss})" if ss else "DONE"
        elif state.get("permanently_skipped"):
            display = "PERM_SKIP"
        elif state.get("session_status") == "empty":
            display = "EMPTY"       # detected as empty; Firestore write pending
        elif state.get("session_status") == "video_only":
            display = "VIDEO_ONLY"  # has video but no sensor data
        elif state.get("attempts", 0) >= _MAX_ATTEMPTS:
            display = "STUCK"
        elif not _is_inactive(s):
            display = "ACTIVE"
        else:
            display = meta_status.upper()

        err = state.get("last_error", "")
        err_str = f"  [{err}]" if err and display not in ("DONE", "DONE (empty)") else ""
        print(
            f"{s.name:<42} {display:<12} "
            f"{state.get('attempts',0):<6} "
            f"{len(state.get('uploaded_files', []))} files{err_str}"
        )


# ── Main run loop ─────────────────────────────────────────────────────────────

def run(data_dir: str, robot_id: str, key_path: str, bucket: str,
        once: bool = False, dry_run: bool = False) -> None:
    """
    Main uploader loop.  Processes one session at a time (FIFO), with
    connectivity checks and per-session back-off on failure.
    """
    data_path = Path(data_dir)
    _stuck_warned: dict = {}   # session_id → monotonic time of last hourly warning

    # Firebase init with retry — the service may start before NTP/network settles
    fb_ok = False
    if not dry_run:
        for attempt in range(1, 6):
            if _init_firebase(key_path, bucket):
                fb_ok = True
                break
            warn(f"[UPLOADER] Firebase init attempt {attempt}/5 failed — retry in 10s")
            time.sleep(10)
        if not fb_ok:
            log_error("[UPLOADER] Firebase init failed after 5 attempts — exiting")
            sys.exit(1)

    info(f"[UPLOADER] Started — robot={robot_id}, data={data_dir}"
         + (" [DRY-RUN]" if dry_run else ""))

    _dry_run_table_printed = False  # print once per --once run; each pass if continuous

    while True:
        # Connectivity gate
        if not dry_run and not _check_connectivity():
            info("[UPLOADER] No connectivity — sleeping 30s")
            if once:
                break
            time.sleep(30)
            continue

        # Dry-run: print a full session table before processing starts each pass
        if dry_run and (not _dry_run_table_printed or not once):
            all_inactive = sorted(
                [d for d in data_path.iterdir()
                 if d.is_dir() and d.name.startswith("session_") and _is_inactive(d)],
                key=lambda d: d.name,
            ) if data_path.exists() else []
            summaries = [_analyze_session(s, robot_id) for s in all_inactive]
            _print_session_table(summaries)
            _dry_run_table_printed = True

        sessions = _find_sessions(data_path)
        if not sessions:
            info("[UPLOADER] Queue empty — sleeping 60s")
            if once:
                break
            time.sleep(60)
            continue

        # Walk FIFO list; skip stuck sessions (warn hourly), process first eligible
        processed_any = False
        for session_dir in sessions:
            state    = _load_state(session_dir)
            attempts = state.get("attempts", 0)

            if attempts >= _MAX_ATTEMPTS:
                # Stuck — skip but warn hourly
                sid  = session_dir.name
                now  = time.monotonic()
                last = _stuck_warned.get(sid, 0.0)
                if now - last > 3600:
                    warn(
                        f"[UPLOADER] Session {sid} has {attempts} failed attempts "
                        f"and is blocked — manual intervention required"
                    )
                    _stuck_warned[sid] = now
                continue

            with _UploadLock():
                success = process_session(session_dir, robot_id, dry_run=dry_run)
            processed_any = True

            if not success:
                new_attempts = _load_state(session_dir).get("attempts", 1)
                backoff      = min(60 * new_attempts, 600)
                warn(f"[UPLOADER] Backing off {backoff}s after attempt {new_attempts}")
                if once:
                    break
                time.sleep(backoff)
                break   # restart outer loop after back-off
            break  # processed one session; loop back to re-scan (maintain FIFO)

        if once:
            break
        if not processed_any:
            # All sessions are stuck
            time.sleep(60)
