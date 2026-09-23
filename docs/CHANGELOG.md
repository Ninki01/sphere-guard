# SphereGuard Changelog

---

## Change History

Newest entry first. Architecture section below always describes current state.

---

### 2026-09-20 — Uploader: video-only sessions, legacy filenames, dry-run table (`refactor/fleet-structure`)

**Files:** `shared/uploader/uploader.py`, `docs/session_schema.md`

#### Video-only sessions (`status: "video_only"`)

Sessions containing a video file but no `meta.json` (e.g. `session_2026-07-15_15-30-24`
which had only `video.avi`) are now handled instead of permanently skipped.

- `start_time_ms` is derived from the folder name timestamp (MYT UTC+8 → epoch ms UTC
  via `_parse_session_start_ms()`).
- The video is converted (ffmpeg AVI → H.264 MP4) and uploaded to Cloud Storage.
- A Firestore doc is written with `status="video_only"`, rows all zero, and
  `start_time_ms` from the folder name.
- Routing: if `meta.json` is absent but `video_rgb.avi` (or legacy `video.avi`) is
  present → `_handle_video_only_session()`.  If neither exists → `_mark_permanently_skipped()`.

#### Legacy filename support

Pre-dual-camera sessions use `video.avi` (single camera) and `frames.csv` instead of
the current `video_rgb.avi` and `frames_rgb.csv`.  The uploader now maps these
transparently via `_map_session_files()`:

- `video.avi` → treated as `video_rgb.avi`; uploaded as `video_rgb.mp4`
- `frames.csv` → treated as `frames_rgb.csv`

The Firestore document gains a `legacy_filenames` field when legacy names are detected,
e.g. `{"video_rgb.avi": "video.avi"}`.  Original files on disk are never renamed.
Documented in `docs/session_schema.md` under **Legacy filename mapping**.

#### Dry-run session table

`--dry-run` now prints a full per-session summary table at the start of each pass
(via `_analyze_session()` + `_print_session_table()`):

```
SESSION                                    STATUS        FILES FOUND                               WOULD UPLOAD
session_2026-07-15_15-30-24               VIDEO_ONLY    video.avi ← video.avi                    video_rgb.mp4 (converted from video.avi)
session_2026-07-06_18-23-22               EMPTY         meta.json, sensors.csv                   meta.json
session_2026-07-03_16-20-27               PARTIAL       meta.json, sensors.csv, video_rgb.avi    meta.json, sensors.csv, video_rgb.mp4 (...)
```

The table shows: session ID, detected status, which files were found (with legacy
annotation where applicable), what would be uploaded, already-uploaded files, and
prior transient attempt count.  The per-session DRY-RUN log messages continue to
appear during processing; the table provides the upfront full-picture view.

#### Infrastructure changes

- `_map_session_files(session_dir)` — maps all canonical filenames to actual paths,
  resolving legacy names; returns `(file_map, legacy_used)`.
- `_parse_session_start_ms(session_dir)` — parses `session_YYYY-MM-DD_HH-MM-SS`
  folder names to epoch ms UTC.
- `_convert_video` now accepts `None` as `avi_path` (treats as absent).
- `process_session` uses `file_map` for all file path lookups; legacy files are
  uploaded to their canonical storage paths transparently.
- `_build_firestore_doc` surfaces `legacy_filenames` from the `recovery` dict as an
  optional document field.
- `print_status` (CLI `--status`) shows `VIDEO_ONLY` display state alongside the
  existing `DONE`, `EMPTY`, `PERM_SKIP`, `STUCK`, and `ACTIVE` states.

---

### 2026-09-20 — Fix: empty-session uploader loop + permanent vs transient failure separation (`refactor/fleet-structure`)

**File:** `shared/uploader/uploader.py`

**Problem:** A session with a missing, zero-byte, or header-only `sensors.csv`
(e.g. a recording aborted before any data was written) caused `_recover_partial_meta()`
to return `{}`, which was treated the same as a transient failure — it consumed a retry
attempt, triggered back-off, and eventually blocked the queue after `_MAX_ATTEMPTS`.
Empty sessions are permanently unrecoverable data-wise and should never be retried.

**Changes:**

- **`_recover_partial_meta` return-value contract clarified:**
  - `dict` (non-empty) — success; contains recovered `end_time_ms` etc.
  - `None` — **permanent**: `sensors.csv` absent, zero-byte, or header-only (zero data
    rows).  Signals an empty session to the caller.
  - `{}` (empty dict) — **transient**: file exists but could not be read (IO/permission
    error).  Caller retries later.

- **New `_handle_empty_session()`:** Called when `_recover_partial_meta()` returns `None`.
  Logs at INFO: `"session X is empty (aborted recording) — recording metadata only"`.
  Uploads `meta.json` (best-effort), writes a Firestore doc with `status="empty"` and
  all row counts zero, marks the session done in `upload_state.json`.  Does **not**
  increment the attempts counter for the empty detection itself; only increments if the
  Firestore write fails (transient network error).

- **`_build_firestore_doc`:** Added optional `status` parameter so `_handle_empty_session`
  can write `status="empty"` directly without overriding the auto-detection logic for
  normal sessions.

- **New `_fail_transient()`:** Replaces the old `_fail()` helper.  Increments `attempts`,
  sets `last_error`, warns, and saves state.  Only transient failures (network, upload
  timeout, Firebase 5xx) call this.

- **New `_mark_permanently_skipped()`:** Used when `meta.json` is missing or unparseable
  (no session ID → no Firestore doc possible).  Sets `permanently_skipped=True` in
  `upload_state.json`, does **not** increment attempts.  `process_session` returns `True`
  so the main loop treats it as "done" and moves on immediately.

- **`process_session` restructured:**
  - Attempts counter is no longer incremented at entry.  Only `_fail_transient()` can
    increment it, so `_MAX_ATTEMPTS` now counts only genuine transient failures.
  - `meta.json` missing/corrupt → `_mark_permanently_skipped()` → return `True`.
  - `_recover_partial_meta()` returns `None` → `_handle_empty_session()`.
  - `_recover_partial_meta()` returns `{}` → `_fail_transient()` → return `False`.
  - Upload/Firestore failures → `_fail_transient()` → return `False`.

- **`_find_sessions`:** Skips sessions with `permanently_skipped=True` (in addition to
  already-skipping `firestore_written=True`).

- **`print_status`:** New display values:
  - `DONE (empty)` — Firestore written, `session_status="empty"`.
  - `EMPTY` — detected as empty but Firestore not yet written (waiting for network).
  - `PERM_SKIP` — permanently skipped (no `meta.json`).

**Behaviour unchanged for normal sessions** (complete or partial with data rows).

---

### 2026-09-20 — Fix: data_dir resolved to wrong path (`refactor/fleet-structure`)

**Files:** `sg01/config.yaml`, `sg02/config.yaml`, `shared/config/loader.py`,
`shared/uploader/__main__.py`, `shared/run.py`

**Root cause:** `paths.data_dir: "../data/sensor_log"` in both configs navigated
*up* one directory from `sg01/` (or `sg02/`) to `robots/`, then into
`data/sensor_log` — resolving to `robots/data/sensor_log` instead of the intended
`robots/sg01/data/sensor_log`.  The loader itself was already correct: it resolves
relative paths against `Path(config_path).parent` (the directory containing the
config file), not against `os.getcwd()`.  The bug was purely in the config value.

**Fix:**
- `sg01/config.yaml` and `sg02/config.yaml`: changed `"../data/sensor_log"` to
  `"data/sensor_log"`.  Relative to the config file's directory, this now resolves
  to `sg01/data/sensor_log` and `sg02/data/sensor_log` respectively.
- `shared/config/loader.py`: added an explanatory comment and renamed the internal
  variable to `_config_dir` to make the resolution base unambiguous.  The logic
  was already correct; the comment prevents the same mistake from recurring.
- `shared/uploader/__main__.py` and `shared/run.py`: both now log the resolved
  absolute `data_dir` at startup.  If the directory does not exist they emit a
  `WARN` with the config file path, making path-resolution issues obvious in
  `journalctl` rather than silently reporting an empty queue or no recording output.

**Impact:** any session data written to `robots/data/sensor_log/` under the old
config must be moved to `robots/sg01/data/sensor_log/` before the server or
uploader will find it.

---

### 2026-09-20 — FIFO Firebase uploader (`refactor/fleet-structure`)

**Files (new):** `shared/uploader/uploader.py`, `shared/uploader/__main__.py`,
`sg01/deploy/uploader.service`, `sg02/deploy/uploader.service`

**Files (updated):** `sg01/deploy/README.md`, `sg02/deploy/README.md`,
`docs/session_schema.md`

**Firebase products used:**
- **Cloud Storage** — all session files (meta.json, CSVs, MP4 videos).
  Path: `robots/{robot_id}/sessions/{session_id}/{filename}`
- **Firestore** — one document per session in the `sessions` collection (the index
  the dashboard queries).
- **RTDB: not used.** The old Realtime Database telemetry path
  (`archive/main.py`, `archive/firebase_client/db_manager.py`) is retired.
  Rule: Storage holds data, Firestore holds the index.  No per-row documents.

**Design decisions:**

- **FIFO:** sessions processed in folder-name order (which encodes start timestamp).
  A stuck session cannot block the queue after 10 failed attempts — it is skipped
  with an hourly warning while later sessions continue uploading.
- **Resume:** `upload_state.json` (atomically written after every step) tracks which
  files were uploaded and whether the Firestore doc was written.  A crash or network
  drop mid-session is transparent — the next run picks up from the last checkpoint.
- **Partial sessions:** if the robot server crashed before `end_time_ms` was written,
  the uploader still uploads.  It repairs any truncated final CSV line, reads the
  last `t_ms` from `sensors.csv` as the effective end time, and marks the Firestore
  doc `status: "partial"`.
- **Video conversion:** `.avi` → H.264 `.mp4` via `ffmpeg` (niceness 10, 15-min
  timeout per file) before upload.  On failure (corrupt avi from a crash), sets
  `video_status="unrecoverable"` and continues — data is not held back for video.
- **Safety gate:** never converts or uploads while a recording is active (session
  folder whose files have mtime < 120 s).  Also writes
  `/tmp/sphereguard_upload_in_progress` while uploading; the auto speed test in
  `pi_internal.py` checks this file and defers when it exists.
- **Firestore doc last:** the dashboard treats a session as existing only after the
  Firestore document is written.  Uploading files first means no partially-visible
  sessions in the dashboard.
- **`device_clock_ms` + `uploaded_at`:** both fields in the Firestore doc let the
  dashboard detect Pi clock drift (no battery RTC → wrong timestamps after an offline
  boot before NTP sync).

**Credentials:**
- Service account key path: `SG_FIREBASE_KEY` environment variable, read from
  `/etc/sphereguard/uploader.env` (systemd EnvironmentFile).  Never stored in the
  repo directory.
- Bucket: `SG_STORAGE_BUCKET` environment variable, same file.
- `firebase-admin` Python package required; `ffmpeg` system package required.

**CLI flags:** `--once` (one pass, for testing), `--dry-run` (no writes), `--status`
(print queue state per session).

**Security note:** `robots/sg01/serviceAccountKey.json` was tracked in git history.
The file is covered by `.gitignore` (`**/serviceAccountKey.json`) but is still present
in the working tree and in prior commits.  If that service account is still active,
rotate the key immediately in the Firebase console.  The new uploader reads credentials
exclusively from `/etc/sphereguard/firebase-key.json` (outside the repo directory).

---

### 2026-09-20 — Generalised auto-reconnect for all hardware (`refactor/fleet-structure`)

**Files:** `shared/sensors/base.py`, `shared/sensors/bno055.py`, `shared/sensors/voc_ps1.py`,
`shared/sensors/pi_internal.py`, `shared/drive/hardware.py` *(new)*,
`shared/drive/drive_servo.py`, `shared/drive/steering_servo.py`, `shared/drive/watchdog.py`,
`shared/cameras/base.py`, `shared/cameras/rgb_uvc.py`, `shared/cameras/thermal_p2pro.py`,
`shared/recording/session.py`, `shared/recording/sampler.py`, `shared/run.py`,
`shared/server/routes.py`, `shared/server/web/control.html`

**Why:** The BNO055 retry fix (previous entry) was a special-case patch.  This change
generalises the same pattern to every hardware component: sensors, cameras, and drive
hardware all now reconnect automatically after transient failures, log lifecycle events
into `meta.json`, and expose their current status through `/sensors`.

---

**Section 1 — Generic sensor reconnect (`shared/sensors/base.py`)**

`Sensor` base class now manages all reconnect state without requiring `super().__init__()`
in subclasses (lazy properties via `getattr` defaults):

- `online: bool` — `True` on creation; set to `False` when fail streak reaches threshold.
- `fail_streak: int` — consecutive read failure counter.
- `record_failure() -> bool` — increments streak; returns `True` the tick the sensor first
  goes offline (so the sampler knows to fire a `log_sensor_event`); logs `SENSOR OFFLINE`
  once per transition.
- `record_success()` — resets streak; no logging.
- `attempt_reconnect(cfg) -> bool` — time-gated (5 s minimum between attempts); calls
  `init(cfg)` to create a FRESH driver object; applies `post_init_delay_s` sleep; verifies
  with `read()`; marks online and logs `"[{name}] reconnected after N failed reads"`.
- `post_init_delay_s: float = 0.0` class attribute — BNO055 overrides to `0.5`.
- `OFFLINE_AFTER = 5`, `RECONNECT_INTERVAL_S = 5.0` class constants.

`shared/recording/sampler.py` sensor loop now calls `s.record_failure()` / `s.record_success()`
/ `s.attempt_reconnect(cfg)` instead of maintaining its own `_fail_streak`, `_retry_tick`,
`_offline` dicts.  `_try_retry()` method removed.

**Section 2 — VOC UART reconnect (`shared/sensors/voc_ps1.py`)**

- `probe_uart()` now stores `_port` and `_baud`, then delegates to `init()`.
- `init()` closes any stale serial port before opening a new one — safe to call on reconnect.
- `read()` lets `serial.SerialException` and `IOError` propagate to the sampler so
  `record_failure()` counts them.  Previously `read()` swallowed all exceptions.

**Section 3 — PCA9685 / servo recovery (`shared/drive/hardware.py`, new file)**

New `DriveHardware` class wraps `DriveServo` + `SteeringServo` with PCA9685 health tracking:

- `_FAIL_OFFLINE = 3` — 3 consecutive write failures marks the drive offline.
- `attempt_recovery() -> bool` — time-gated (5 s); sequence: `reset_pca9685()` →
  `_reinit_servo()` on both axes → **throttle = 0.0 and steering = center FIRST** →
  `online = True`.  The safe-state is applied before going back online; the operator's
  previous command is never resumed.
- `stop()` and `center()` attempt the hardware write even when offline (best-effort safety).
- `set_throttle()` and `set_angle()` are no-ops when offline.
- Exposes `throttle`, `angle`, `stop()`, `center()`, `set_throttle()`, `set_angle()` so
  `run.py` can use `_hw` in place of both `_drive` and `_steering`.

`shared/drive/drive_servo.py` and `shared/drive/steering_servo.py` gained `_reinit_servo()`
methods that create a new `ServoKit` instance and re-bind the servo channel.

`shared/drive/watchdog.py` gained an optional `hardware=` parameter.  When a `DriveHardware`
is passed and `hw.online == False`, the watchdog calls `hw.attempt_recovery()` and skips
the timeout check for that tick — it does not keep writing zeros to a dead bus.

`shared/run.py`: `DriveHardware(cfg)` replaces the separate `DriveServo` + `SteeringServo`
instantiation.  Both `_drive` and `_steering` module-level aliases point to `_hw`.

**Section 4 — Camera reconnect (`shared/cameras/`)**

- `Camera` base class: added `online: bool = True` class attribute.
- `Camera.try_reopen()` default: `release()` then `open()`.
- `RGBCamera.try_reopen()`: tries configured device first; if that fails, scans `/dev/video0`–`9`
  (USB cameras may re-enumerate to a different index after reconnection); logs the new device.
- `ThermalP2Pro.try_reopen()`: same scan, but identifies the P2 Pro by its distinctive
  256×384 combined frame dimensions — does not grab a device that reports different geometry.

Camera reconnect loop in `shared/recording/sampler.py` `_camera_loop()`:
- 10 consecutive `None` frames or exceptions → `cam.online = False`; fires `log_camera_event`.
- While offline: calls `cam.try_reopen()` at most every 5 s.
- On reconnect: checks resolution against the open `VideoWriter` via
  `session.get_video_writer_dims(role)`.  If mismatch → `resolution_ok = False`; frames are
  not written to the session file (gap in `frames_{role}.csv` is preferable to a corrupt video).
- If reconnect during recording: same `VideoWriter` is reused (no second file opened).

`shared/recording/session.py` additions:
- `_vid_dims: dict[str, tuple]` — records `(width, height)` when a VideoWriter is opened.
- `log_camera_event(role, event, t_ms)` — parallel to `log_sensor_event()`.
- `get_video_writer_dims(role) -> tuple | None` — returns dims for mismatch check.
- `camera_events` list included in `meta.json` (only when non-empty).

**Section 5 — Unified hardware status**

`GET /sensors` now includes a `_hardware` block:
```json
{
  "_hardware": {
    "sensors": [{"name": "BNO055", "online": true, "fail_streak": 0}, …],
    "cameras": [{"role": "rgb", "online": true}],
    "drive":   {"online": true}
  }
}
```

`control.html` additions:
- **DRIVE OFFLINE** sticky banner in the header — shown when `_hardware.drive.online === false`.
- Config drawer gains two new collapsible sections: **CAMERAS** and **DRIVE HARDWARE**, both
  updated on every `fetchSensors()` call (5 Hz).
- `_renderHardwareStatus(hw)` JS function populates all three sections from the `_hardware`
  block.

`GET /api/config` sensor list now uses `s.online` (base class property) instead of the
removed `sampler._offline` set.

`GET /stream/{role}` returns 503 if `cam.online === false` (not just `cam._cap is None`).

---

### 2026-09-20 — BNO055 reconnect robustness, offline threshold tuning (`refactor/fleet-structure`)

**Files:** `shared/sensors/bno055.py`, `shared/sensors/pi_internal.py`,
`shared/recording/sampler.py`

**Source:** Ported from the team's tested `robots/sg01/src/local_test_joystick/robot_server.py`.
That code handled a failure mode the refactored registry rescan was missing.

**Problem:** After an I2C glitch or brownout, the BNO055 Adafruit driver object goes
stale — the chip is still present on the bus but the Python object's internal state is
corrupt.  The old `_try_retry()` only called `s.read()` on the existing instance, so a
stale object would never recover: reads would fail indefinitely even though the chip was
physically fine.  The fix was to also call `s.init()` to create a fresh driver object
before the retry read.

**What changed:**

- **`shared/sensors/bno055.py`** — added `time.sleep(0.5)` in `init()` after setting
  IMUPLUS mode.  The BNO055 fusion engine needs ~500 ms to stabilise after a mode change;
  the first Euler/quaternion reads without this delay return `None` or garbage.

- **`shared/recording/sampler.py`**:
  - `OFFLINE_AFTER` changed from `10` → `5`.  This matches the team's tested value and
    means a sensor is flagged offline after 5 consecutive failures (~0.25 s at 20 Hz)
    rather than 10 (~0.5 s).  Applies to all sensors, not just BNO055.
  - `_try_retry()` now calls `s.init(self._cfg)` before the retry `s.read()`.  This
    creates a fresh driver object, clearing any stale internal state left by the I2C
    glitch.  Only then is `s.read()` called to confirm the sensor responds.
  - Reconnect log message changed from the generic `"SENSOR RECONNECTED: {name}"` to
    `"[{name}] reconnected after {N} failed reads"`, matching the format from the team's
    code and making the failure count visible in journalctl.

- **`shared/sensors/pi_internal.py`** — `init()` made idempotent: if the background
  network-check thread is already running, `init()` returns immediately.  Without this
  guard, the sampler's retry path would call `init()` on PiInternal and start a second
  background thread, duplicating the latency/speed-test work and corrupting state.

**Conflict check — `""` vs `0` for absent sensors:**
Confirmed no conflict.  `bno055.py` returns `{c: "" for c in self.cols()}` both when
`_sensor is None` and on any read exception (lines 59, 95).  `session.py` opens
`sensors.csv` with `DictWriter(restval="")` so columns absent from the row dict also
write `""`.  There is no `0` placeholder anywhere — `0` is a valid measurement for
`bus_v`, `pitch`, etc. and is never written to represent "sensor absent".

**Hot-plug rescan status:**
The retry loop (`_try_retry`, added in the fixed-schema CHANGELOG entry) was already
present, but the critical re-instantiation step was missing until this change.  The
feature is now complete: offline sensors retry every `RETRY_TICKS` ticks (~3 s),
re-create their driver object on each retry attempt, and resume normally on first
successful read.

---

### 2026-08-29 — Network metrics + on-demand speed test (`refactor/fleet-structure`)

**Files:** `shared/sensors/pi_internal.py`, `shared/sensors/schema.py`,
`shared/server/routes.py`, `shared/server/web/control.html`,
`shared/recording/session.py`, `shared/run.py`, `docs/session_schema.md`

**Why:** SG01 operates in metal ducting where connectivity is intermittent.  The uploader
(future) needs to know available bandwidth at the exact moment the robot reconnects —
triggering a speed test automatically at reconnect, rather than on a fixed schedule,
gives the most relevant measurement.  Continuous latency tracking (every 10 s) shows the
operator whether the link is stable before starting a recording session.

**What changed:**

- **`shared/sensors/pi_internal.py`** — continuous background thread (10 s interval) now
  also measures:
  - `latency_ms` — TCP connect timing to `1.1.1.1:443`; replaces the simple
    reachability boolean with a latency value (also serves as the internet-reachable check).
  - `link_speed_mbps` — negotiated link rate: `iw dev <iface> link` for wifi tx bitrate;
    `/sys/class/net/<iface>/speed` for ethernet.
  - `wifi_quality` — link quality normalised to 0–100% from `/proc/net/wireless` quality
    field (max `_WIFI_QUALITY_MAX = 70`).

  On-demand speed test (`run_speed_test(trigger)`):
  - Downloads 5 MB from `speed.cloudflare.com/__down?bytes=5000000` with a 10 s hard
    deadline via chunked `urllib.request.urlopen`.
  - Uploads 500 KB to `speed.cloudflare.com/__up` with remaining time budget.
  - Uses only Python stdlib (`urllib.request`, `socket`, `threading`) — no extra packages.
  - `_speed_test_lock` protects the `_speed_test_running` flag; fire-and-forget thread
    sets it back to `False` in `finally`.
  - `speed_test_result` property returns a copy of `_speed_test_result` dict
    (`{status, download_mbps, upload_mbps, latency_ms, tested_at_ms, trigger}`).

  Auto-trigger state machine:
  - `_DEBOUNCE_S = 15` — test only fires after being online for 15 s (debounces
    connection flapping).
  - `_COOLDOWN_S = 600` — at most one auto-test per 10 min.
  - `float("-inf")` sentinel for `_last_auto_test_mono` so the cooldown is not applied
    on first test after startup.
  - If recording is active when the test would fire, sets `_pending_auto_test = True`
    and defers; next loop iteration after recording stops fires it immediately.
  - `set_session(session)` — injected from `run.py` so `PiInternal` can check
    `session.active` without a circular import.

- **`shared/sensors/schema.py`** — `SCHEMA_VERSION` bumped to `3`.  Three numeric columns
  appended at the END of `COLUMNS`: `latency_ms`, `link_speed_mbps`, `wifi_quality`.

- **`shared/server/routes.py`** — two new endpoints (additive):
  - `GET /api/nettest` → returns `_pi.speed_test_result` (503 if no Pi sensor).
  - `POST /api/nettest` → calls `_pi.run_speed_test("manual")`.  Returns 409 with a
    human-readable message if recording is in progress or a test is already running.

- **`shared/recording/session.py`** — at session start, if a completed speed test result
  is held in `PiInternal`, a copy is written to `meta.json` under `"network_test"`.
  This lets the uploader and dashboard know the available bandwidth at the time the
  session was started.

- **`shared/run.py`** — calls `_pi.set_session(_session)` after both are created, so the
  auto-test recording guard has a live reference to the session.

- **`shared/server/web/control.html`**:
  - NETWORK tile now shows `latency_ms` ms on ethernet (not the static "ETH" label);
    continues to show `wifi_dbm` dBm on wifi.
  - Dynamic tooltip rebuilt on every sensor poll via an IIFE: `addRow()` skips any field
    whose value is `null`, so no blank lines are shown.  Tooltip shows: Type, Name, IP,
    Signal (dBm + quality %) on wifi, Link speed, Latency.
  - Config drawer gains a **⇅ SPEED TEST** collapsible section with: last result display
    (pre-populated on drawer open from `GET /api/nettest`), a spinning indicator while
    running, and a RUN SPEED TEST button.
  - `runSpeedTest()` — POSTs to `/api/nettest`, shows spinner, starts polling.
  - `pollNettestResult()` — polls every 1 s; stops and calls `showNettestResult()` when
    `status !== "running"`.
  - `showNettestResult(d)` — renders download, upload, latency, time, and trigger in the
    result div; shows `"No test run yet."` for idle/unavailable states.
  - CSS `@keyframes sg-spin` + `.nettest-spin` spinner character for the running state.
  - `const NETTEST_URL` constant added alongside other API URL constants.

- **`docs/session_schema.md`** — `schema_version` updated to `3`; three new column rows
  added with units and notes; note added explaining numeric distinction from v2 string
  columns; `network_test` and `fusion` fields added to the meta.json fields table.

**Column order note:** `latency_ms`, `link_speed_mbps`, `wifi_quality` appear after
`ip_address` in COLUMNS (end of Pi internal block) but before `sht_temp` — they were
appended to the position after the v2 additions in the Pi block, not at the absolute end
of the list.  Either position is valid (only "never reorder" is the rule), but dashboard
code must derive position from the CSV header row, not from assumed offsets.

---

### 2026-08-29 — Network identity reporting (`refactor/fleet-structure`)

**Files:** `shared/sensors/pi_internal.py`, `shared/sensors/schema.py`,
`shared/server/web/control.html`, `docs/session_schema.md`

**Why:** The Pi could be on ethernet or WiFi depending on the deployment site, and the
old code hardcoded `wlan0`, so an ethernet-connected Pi showed blank WiFi signal.
Knowing the robot's IP and connection type directly on the drive page removes the need
to check a router admin panel to find it.

**What changed:**

- **`shared/sensors/pi_internal.py`** — major rewrite:
  - Active interface determined from `/proc/net/route` default route — no longer
    assumes `wlan0`.
  - `_iface_type()` checks `/proc/net/wireless`: if the iface appears there → wifi,
    otherwise → ethernet.
  - `wifi_dbm` now uses the actual active interface name instead of hardcoded `wlan0`.
    Returns `None` (not `0`) when not on wifi.
  - New cached fields: `net_type` ("wifi"/"ethernet"/"none"), `net_name` (SSID or
    "Ethernet"), `ip_address` (IPv4 via `ip -4 addr show <iface>`, fallback
    `hostname -I`), `net_iface` (interface name — live-only).
  - SSID read via `iwgetid <iface> -r` (returns `None` if absent or ethernet).
  - Background thread now refreshes both internet reachability and network state every
    10 s (`_stop_evt.wait(timeout=10)` — no busy-loop).  `init()` calls
    `_refresh_network()` once synchronously so `read()` returns real values immediately.
  - `cols()` returns `net_type`, `net_name`, `ip_address`; `net_iface` is excluded
    from `cols()` (not written to CSV) but is included in `read()` for `/sensors`.
  - All helpers wrapped in `try/except`; on failure each field returns `None`.
    Works unchanged on a laptop with no wireless (returns `net_type: "ethernet"` or
    `"none"`).

- **`shared/sensors/schema.py`** — `SCHEMA_VERSION` bumped to `2`.  Three columns
  appended at the END of `COLUMNS`: `net_type`, `net_name`, `ip_address`.  These are
  **strings**, not numerics — dashboard code that casts all columns to `float` must
  skip them.

- **`shared/server/web/control.html`**:
  - "WiFi" sensor tile relabelled **"NETWORK"**.
  - Value shows: `wifi_dbm` (dBm) on wifi; `"ETH"` on ethernet; `"—"` when down.
  - Warn class applied when wifi signal < −70 dBm or when `net_type == "none"`.
  - Tooltip on the NETWORK tile shows Type / Name / IP / Signal (Signal row hidden on
    ethernet).  CSS `@media (hover: hover)` shows on desktop hover; JS
    `toggleNetTooltip()` + `document click` dismiss handles tap toggle on tablets.
  - Config drawer gains a compact **network info bar** at the top (IP / Type / Name),
    updated by `fetchSensors()` every 200 ms — always current when the drawer is open.

- **`docs/session_schema.md`** — `schema_version` updated to `2`; three new column
  rows added; note added explaining string vs numeric column distinction and `net_iface`
  live-only status.

---

### 2026-08-29 — Fusion experimental overlay view (`refactor/fleet-structure`)

**Files:** `shared/cameras/fusion.py` (new), `shared/server/web/fusion.html` (new),
`shared/tools/calibrate_fusion.py` (new), `shared/tools/__init__.py` (new),
`shared/recording/sampler.py`, `shared/recording/session.py`,
`shared/server/routes.py`, `shared/server/web/control.html`,
`robots/sg01/config.yaml`, `robots/sg02/config.yaml`

**Why:** Provide a live thermal/RGB blended view for inspection without affecting the
main drive page, recording pipeline, or existing stream endpoints.

**What changed:**

- **New routes** (additive — nothing existing modified):
  - `GET /fusion` → serve `fusion.html`
  - `GET /stream/fusion` → MJPEG blended view
  - `GET /api/fusion` → JSON: homography, calibration_date, calibration_distance_m, blend_alpha, colormap
  - `POST /api/fusion` → save blend_alpha / colormap to config.yaml; live-applies without restart

- **`shared/cameras/fusion.py`** — `FusionOverlay` class: stateless per-call except for
  a homography matrix cache keyed by `repr(homography)`.  Uses `cv2.warpPerspective` +
  `cv2.applyColorMap` + `cv2.addWeighted`.  Always returns a frame, never raises —
  any exception is shown as text overlay on the base RGB frame.

- **`shared/tools/calibrate_fusion.py`** — interactive homography calibration script.
  Run manually on the Pi when the server is NOT running.  Click matching points in RGB
  and thermal windows; press `c` to compute (RANSAC findHomography), `s` to save,
  `q` to quit.  Saves homography flat list + calibration date + distance to `config.yaml`
  under the `fusion:` key.

- **`shared/server/web/fusion.html`** — standalone blend viewer.  Calibration status
  badge, MJPEG stream, blend-alpha slider (300 ms debounce POST), colormap dropdown.
  Fully isolated: no shared JS with control.html.

- **`shared/recording/sampler.py`** — fusion computed in the RGB camera loop only when
  `_stream_clients["fusion"] > 0`.  Result stored in `_cam_frames["fusion"]` but
  **never passed to `session.log_frame()`** — fusion is live-view only.

- **`shared/recording/session.py`** — fusion config snapshot written to `meta.json` at
  session start so the offline dashboard can reproduce the overlay from source videos +
  stored homography.

- **Config** — top-level `fusion:` key added to sg01 and sg02 `config.yaml` (NOT inside
  the cameras list): `homography: null`, `calibration_date: null`,
  `calibration_distance_m: null`, `blend_alpha: 0.4`, `colormap: "INFERNO"`.

- **Config drawer** — "⊕ FUSION (experimental)" link added below the Save button.
  NOT in the main header nav.

**Known issues:**
- Alignment is accurate only near the calibration distance.  Parallax from the
  ~4 cm camera separation causes visible misalignment at other distances.
- Fusion is live-view only — never recorded.  The dashboard can reproduce it offline
  from `video_rgb.avi` + `video_thermal.avi` + the `fusion.homography` stored in
  `meta.json`.
- P2 Pro temperature decoding (raw temp-data half of the frame) is untested against
  hardware — this feature uses only the image half.

---

### 2026-08-29 — Config slide-over panel + sensor tile field-name fix (`refactor/fleet-structure`)

**Files:** `shared/server/web/control.html`

**Why:** The `[DRIVE][CONFIG]` nav toggle required full-page navigation to reach the
calibration/config panel, which interrupts a live drive session.  Embedding the config
as a slide-over drawer on the drive page lets the operator adjust settings, inspect
sensor status, and run servo test moves without leaving the joystick view.

**What changed:**

- **Nav toggle removed.**  Replaced with a single `⚙ CONFIG` button in the header.
  `GET /config` still serves `config.html` as a standalone fallback — nothing removed.

- **Config drawer** slides in from the right edge (~380 px wide, full width on narrow
  screens, 200 ms ease-out transition).  Closes on: ✕ button, backdrop click, Escape key.

- **Drawer contents** (all config.html functionality, now inline):
  - Drive speeds (forward/backward/spin sliders + deadzone number)
  - Servo angles (center/left/right sliders + CENTRE/LEFT/RIGHT/STOP test buttons)
  - Body physical values (radius, mass, pendulum offset) — collapsed by default
  - Camera enable checkboxes (rgb / thermal) — collapsed by default; restart note shown
  - Sample rate — collapsed by default; restart note shown
  - IMU calibration bars (sys/gyro/accel/mag, colour-coded 0=red…3=green) — collapsed
  - Detected sensors table (name, address, fixed/opt, online/offline) — collapsed
  - Save button → `POST /api/config`

- **Live-poll only while open.**  IMU cal bars and sensor table poll `/api/config?cal=1`
  every 1 s only when the drawer is open; interval is cleared on close.

- **Joystick fully functional with drawer open.**  Drawer captures scroll (`touch-action:
  pan-y`) but not joystick touch events — joystick is outside the drawer's DOM subtree.

- **Sensor tile field-name fix.**  `fetchSensors()` was referencing `d.temp` and
  `d.humidity` — the pre-refactor column names.  Updated to `d.bme_temp` and `d.bme_hum`
  to match the `SCHEMA_VERSION=1` names.  Tiles were showing `—` for BME280 since the
  schema rename.

- **Save syncs main-page sliders.**  After `POST /api/config` succeeds, the drive speed
  and servo sliders on the main page are updated to match the saved values via
  `syncSettingsFromServer()`, so live-apply and saved values stay in sync.

---

### 2026-08-29 — Dual camera simultaneous capture, recording, and streaming (`refactor/fleet-structure`)

**Files:** `shared/recording/sampler.py`, `shared/recording/session.py`,
`shared/server/routes.py`, `shared/server/web/control.html`,
`robots/sg01/config.yaml`, `robots/sg01/deploy/README.md`

**Why:** SG01 carries both an RGB camera and an InfiRay P2 Pro thermal camera.
Both must record to session files simultaneously, and the operator must be able
to view either or both feeds from the drive page.

**What changed:**

- **`sg01/config.yaml`** — thermal camera `enabled: false` → `enabled: true`.

- **`sampler.py`** — on-demand JPEG encoding:
  - Added `_stream_clients: dict[str, int]` (role → active MJPEG client count).
  - `inc_stream_client(role)` / `dec_stream_client(role)` called by `routes.py` on
    MJPEG handler connect/disconnect.
  - `_camera_loop` checks `_stream_clients.get(role, 0) > 0` before encoding; if no
    clients are watching a role, the frame is written to the session but never JPEG-encoded,
    saving CPU on the Pi 5.
  - JPEG encoding moved out of `cam.jpeg_frame()` (which re-called `read_frame()`, wasting
    a capture slot) into a module-level `_encode_jpeg(frame)` using the already-captured
    `numpy` array.

- **`session.py`** — cameras list in meta.json:
  - `_cam_manifest` built from active cameras at `start()`.
  - Partial meta: `cameras` list shows `{role, device, width, height, fps}`.
  - Complete meta: each camera entry gains `frames_written` from `_frame_rows`.

- **`routes.py`** — per-camera stream endpoints:
  - `GET /stream` and `GET /stream/rgb` → MJPEG for RGB camera.
  - `GET /stream/thermal` → MJPEG for thermal camera (image half only — sampler
    records only `cam.read_frame()` which `ThermalP2Pro` already returns as the
    top 256×192 image half).
  - `_serve_mjpeg(role)` calls `sampler.inc_stream_client(role)` on entry and
    `sampler.dec_stream_client(role)` in `finally` — client count drops to zero on
    browser tab close, stopping JPEG encoding for that role.
  - Config save handler (`_handle_config_save`) extended to merge camera-array updates
    by matching on `role` key.

- **`control.html`** — camera panel UI:
  - Added `[RGB][THERMAL][BOTH]` mode buttons.
  - `setCamMode(mode)` stops all feeds (sets `img.src = ""`, clearing the MJPEG
    connection so the server's client counter decrements), then starts the selected feed(s).
  - `BOTH` mode shows two side-by-side feeds; each `<img>` requests its own `/stream/{role}`.
  - `onCamError(role)` retries the appropriate feed after 3 s without affecting
    the other role's stream.

- **`robots/sg01/deploy/README.md`** — added `v4l2-ctl` instructions for finding the
  correct thermal camera device index (P2 Pro registers as 256×384 — top half is image,
  bottom is temperature data).

---

### 2026-08-29 — Fixed sensor column schema (`refactor/fleet-structure`)

**Files:** `shared/sensors/schema.py` (new), `shared/sensors/bno055.py`,
`shared/sensors/bme280.py`, `shared/sensors/sht45.py`, `shared/sensors/scd41.py`,
`shared/sensors/sdp810.py`, `shared/sensors/voc_ps1.py`, `shared/sensors/registry.py`,
`shared/recording/session.py`, `shared/recording/sampler.py`,
`docs/session_schema.md` (new)

**Why:** Dynamic sensor headers (built from whatever sensors are present at startup)
made cross-session CSV comparison impossible — a session without BME280 has a
completely different column layout from one with it.  Firebase dashboard and offline
analysis both need one consistent shape.  Also: mid-session sensor reconnection was
silently broken — if a sensor dropped and reconnected, the CSV header was already
written and couldn't gain new columns.

**What changed:**

- **`schema.py`** — `SCHEMA_VERSION = 1`, `COLUMNS` list (37 entries), `validate_driver_cols()`
  Absent sensor writes `""` (distinct from 0).  New sensors appended at end, version bumped.

- **Column renames** to canonical names (old → new):
  - BME280: `temp/humidity/pressure` → `bme_temp/bme_hum/bme_press`
  - SHT45: `sht45_temp/sht45_hum` → `sht_temp/sht_hum`
  - SCD41: `co2_ppm/scd41_temp/scd41_hum` → `co2/scd_temp/scd_hum`
  - SDP810: `dp_pa/dp_temp` → `diff_press` (`dp_temp` dropped — not in schema)
  - VOC PS1: `voc_ppm` → `voc_ppb`
  - INA226, PiInternal: unchanged (already matched schema)

- **BNO055** — added quaternion cols (`quat_w/x/y/z`) and calibration cols
  (`cal_sys/cal_gyro/cal_accel/cal_mag`) to both `cols()` and `read()`.
  Quaternions are gimbal-lock-free and preferred for analysis; Euler angles stay
  for human display.  `calibration_status()` still returns the cached tuple for
  the `/api/config` page.

- **`registry.py`** — calls `validate_driver_cols(name, cols())` on every driver
  at startup.  Raises `ValueError` immediately if a driver returns an unknown name.
  This catches schema drift at process start, not silently at first write.

- **`session.py`** — `sensors.csv` now uses `fieldnames=COLUMNS` with `restval=""`
  so missing columns write `""` automatically.  Added `schema_version` to meta.json.
  Added `sensor_events` list (offline/reconnected events during the session).
  Added `log_sensor_event(name, event, t_ms)` method (atomic meta rewrite after each event).
  Fixed `robot_id: None` bug in final meta.json (now stored as `self._robot_id`).
  Refactored meta building into `_build_meta(complete=…)` to avoid duplication.
  Added `status: "partial"` / `"complete"` field.

- **`sampler.py`** — offline sensors are now retried every `RETRY_TICKS = 60` ticks
  (~3 s at 20 Hz) rather than being permanently skipped.  A successful retry fires
  `session.log_sensor_event(name, "reconnected", t_ms)`.  Going offline fires
  `session.log_sensor_event(name, "offline", t_ms)`.  Import added: `info` from log.

- **`docs/session_schema.md`** — new file; documents every file, column, unit,
  meta.json field, Firestore document shape, and Storage layout as a contract for
  the future uploader and dashboard.

**Mid-session hot-plug behaviour:**  A sensor absent at session start has `""` in its
columns.  If it connects later (retry succeeds), its columns start filling in from
that row.  The `sensor_events` list in meta.json records the reconnection timestamp
so the dashboard can annotate the gap.

**Still unresolved:** `sensor_cache()` (used by `GET /sensors`) calls `s.read()` for
its own live snapshot; this does not update the `_fail_streak` counter.  A sensor
read that fails only via `sensor_cache()` (not the sampler loop) is not tracked.
Low priority: `sensor_cache()` is for display, not recording.

---

### 2026-08-29 — Clean shutdown fix (`refactor/fleet-structure`)

**Files:** `shared/run.py`, `shared/server/http_server.py`, `shared/recording/sampler.py`

**Symptom:** Ctrl+C printed "Shutting down…" but the process never exited — required
`kill -9`. Under systemd (`Restart=always`) this meant every stop left video files and
CSVs unflushed, producing corrupt partial sessions.

**Root causes (two independent):**

1. **MJPEG stream blocked shutdown.** `ThreadingHTTPServer` spawns a non-daemon thread
   per request. The `/stream` handler sits in `while True` writing frames. `server.shutdown()`
   waits for `serve_forever()` to exit, which waits for all handler threads — so one open
   browser tab with the stream held the process hostage forever.

2. **`server.shutdown()` called from the signal handler deadlocked.** `serve_forever()`
   was blocking the main thread. The signal handler interrupted it, then called
   `shutdown()` which blocks on `__is_shut_down.wait()` — but `serve_forever()` is the
   one that sets that event, and it can't run because the main thread is stuck in the
   signal handler. Classic self-deadlock.

**Fixes:**

- `http_server.py`: subclassed `ThreadingHTTPServer` with `daemon_threads = True` — handler
  threads become daemons and no longer block `shutdown()`. Added `server_close()` to release
  the listening socket.
- `run.py`: shutdown now runs in a background thread (`threading.Thread(target=_do_shutdown)`).
  The signal handler just starts that thread and returns — `serve_forever()` can then run
  to its next poll interval and exit cleanly.
- `run.py`: `_shutdown_started` Event makes the handler idempotent — a second Ctrl+C is
  silently ignored.
- `run.py`: 5-second hard fallback daemon thread calls `os._exit(1)` if shutdown hangs
  (e.g. broken sensor driver blocking `sensor.cleanup()`).
- `run.py`: SIGTERM handled identically to SIGINT (systemd sends SIGTERM on `stop`).
- Shutdown order: stop motors → stop watchdog → `sampler.stop(join_timeout=1.0)` →
  session flush → release cameras → `server.shutdown()` + `server_close()`.

**Also fixed — `VIDIOC_REQBUFS errno=19` on shutdown:**
- The camera loop thread (`_camera_loop`) was still calling `cam.read_frame()` while
  `cam.release()` ran concurrently, racing against `_cap = None` after `cap.release()`.
- `sampler.py`: `start()` now appends each camera thread to `self._cam_threads`.
  `stop()` joins all of them (1s timeout each) before returning. Cameras are only
  released after `sampler.stop()` returns.

**Still unresolved:** If a sensor's `cleanup()` method hangs (e.g. SCD41 laser stop
over a stuck I2C bus), the 5s `os._exit` fires without flushing the session. A per-sensor
timeout wrapper would fix this but is not yet implemented.

---

### 2026-08-29 — `/config` route collision fix (`refactor/fleet-structure`)

**Files:** `shared/server/routes.py`, `shared/server/web/config.html`,
`shared/server/web/control.html`

**Symptom:** Clicking the CONFIG nav button opened `/config` but the browser showed
raw JSON instead of the calibration page.

**Root cause:** `GET /config` was the API endpoint returning config JSON. The nav
button navigated there expecting HTML.

**Fix:** Split the route:
- `GET /config` → serves `config.html`
- `GET /api/config` (+ optional `?cal=1`) → returns config JSON
- `POST /api/config` → validates + writes config.yaml

Updated all three `fetch()` calls in `config.html` and the one in `control.html`
(robot-id label fetch on load) to use `/api/config`.

---

### 2026-08-29 — First hardware run on SG01 (`refactor/fleet-structure`)

**Outcome:** Server starts cleanly, control page loads and is functional. RGB camera
opens at 640×480@30. Pi internal sensor active (pi_temp, wifi_dbm, internet check).
I2C sensors not connected during this test — only `Pi` detected. Confirms that
graceful degradation works: FIXED sensors (BNO055, INA226) log a warning and the
server continues rather than crashing.

**Follow-up:** Full sensor integration test pending (BNO055, INA226, BME280).

---

## Current Architecture

Entry point (run from `robots/`):
```
python -m shared.run --config sg01/config.yaml   # or sg02/config.yaml
```

### Package structure

```
robots/shared/
├── config/      loader.py (YAML + .env + validation), writer.py (atomic write-back)
├── server/      http_server.py, routes.py, web/control.html, web/config.html
├── drive/       drive_servo.py, steering_servo.py, mixer.py (pure), watchdog.py
├── sensors/     base.py, registry.py, bno055.py, bme280.py, ina226.py,
│                pi_internal.py, sht45.py, scd41.py, sdp810.py, voc_ps1.py
├── cameras/     base.py, rgb_uvc.py, thermal_p2pro.py
├── recording/   session.py, sampler.py, video_writer.py
├── control/     (empty — future PID)
├── uploader/    (empty — future cloud upload)
└── util/        clock.py (MYT timestamps), log.py
```

### HTTP endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/` | `control.html` |
| GET | `/config` | `config.html` (standalone calibration page — fallback) |
| GET | `/api/config` | config JSON (`?cal=1` adds BNO055 calibration tuple) |
| POST | `/api/config` | validate + write config.yaml; merges cameras array by role |
| GET | `/settings` | current drive/servo/deadzone values |
| GET | `/sensors` | latest sensor cache + robot_id/name |
| GET | `/record` | `{recording, session_id}` |
| POST | `/record` | `{action: start\|stop}` |
| GET | `/stream` | MJPEG rgb (alias for `/stream/rgb`) |
| GET | `/stream/rgb` | MJPEG rgb camera |
| GET | `/stream/thermal` | MJPEG thermal camera (image half only, 256×192) |
| POST | `/joystick` | `{x, y}` → drive + steer + watchdog heartbeat |
| POST | `/command` | `{action}` → named command + watchdog heartbeat |
| OPTIONS | `*` | CORS 204 |

### Shutdown sequence

```
SIGINT / SIGTERM
  → signal handler (idempotent, sets _shutdown_started)
  → spawns background thread _do_shutdown()
      1. motors stop + steering center
      2. watchdog.stop()
      3. sampler.stop(join_timeout=1.0)   ← camera threads join before camera release
      4. session.stop() if active          ← flushes CSVs, closes VideoWriters
      5. cam.release() for each camera
      6. server.shutdown() + server_close()
  → serve_forever() unblocks → main() returns
  → hard fallback: os._exit(1) after 5 s if anything hangs
```

### Known issues

1. **P2 Pro thermal temperature decoding is UNVERIFIED**
   `thermal_p2pro.py::read_temp_at()` assumes uint16 big-endian, 0.01 K units per the
   P2 Pro documentation. This has NOT been tested against hardware. The method logs a
   one-time `WARN` on first call. Do not use temperature values for safety-critical
   decisions until verified with a known-temperature target.

2. **serviceAccountKey.json in git history**
   `robots/sg01/serviceAccountKey.json` was committed and may still be in git history.
   It is now covered by `**/serviceAccountKey.json` in `.gitignore`. Treat the key as
   compromised and rotate it if that service account is still active.

3. **sg02 values are UNTUNED**
   All servo angles, speeds, and body dimensions in `sg02/config.yaml` are marked
   `# UNTUNED placeholder`. Do not drive SG02 without calibrating via the `/config` page.

4. **Sensor cleanup hang could defeat the 5s fallback exit**
   If a sensor's cleanup blocks on a stuck I2C bus, `sampler.stop()` will wait for
   `join_timeout` per camera thread (safe), but sensor cleanup paths are not yet
   individually time-bounded. The 5s `os._exit` is the last line of defence.

---

## Fleet refactor — August 2026 (`refactor/fleet-structure`)

Extracted `robots/sg01/src/robot_server/robot_server.py` (~700-line monolith) into
`robots/shared/`. Both SG01 and SG02 now run identical code, differing only by
`config.yaml`. See "Current Architecture" above for the present state.

### Design decisions made during this refactor

#### Sensor architecture
- Old: BNO055 and BME280 initialised inline in `robot_server.py`
- New: `Sensor` ABC + I2C auto-detection registry; no sensor list in config.yaml
- Dynamic CSV header from `[col for s in active_sensors for col in s.cols()]`
- Meta.json records active sensor manifest for offline analysis

#### INA219 → INA226
- Replaced `adafruit-circuitpython-ina219` with `smbus2` + raw INA226 registers
  (Adafruit INA226 library package name is ambiguous on Pi OS)
- Calibration: `current_lsb = 10 A / 32768`, `CAL = floor(0.00512 / (current_lsb * shunt_ohms))`
- Address in config (`ina226.address: 0x41`; A0 bridged; 0x40 is PCA9685)

#### BNO055 — IMUPLUS mode
- Raw constant `_IMUPLUS_MODE = 0x08` — no magnetometer; metal duct housing corrupts mag
- Calibration status exposed via `calibration_status()`; displayed on `/config` page

#### VideoWriter fps bug — fixed during refactor
- Old: hardcoded 20 fps; camera delivers ~30 fps → slow-motion playback
- Evidence: session_2026-07-03_16-20-27 — 754 frames / 25.24 s ≈ 29.9 fps
- Fix: fps from `cfg.cameras[i].fps`; `frames_{role}.csv` is the authoritative timeline

#### Deadzone sync
- Old: hardcoded `DEADZONE = 0.12` in Python and JS
- New: `/settings` includes `deadzone`; `control.html` fetches on load

#### sg01/src/ removal
- Explicitly `rm -rf` after all contents moved/archived — deliberate, not accidental
- All moves via `git mv` so history is preserved

### Files archived (not deleted)

| File | Archive destination | Reason |
|---|---|---|
| `sg01/src/robot_server/robot_server.py` | `sg01/archive/robot_server.py` | replaced by shared/ |
| `sg01/src/sensors/ina219_sensor.py` | `sg01/archive/ina219_sensor.py` | replaced by INA226 |
| `sg01/src/sensors/imu_mpu6050.py` | `sg01/archive/imu_mpu6050.py` | never used on SG01 |
| `sg01/src/sensors/camera.py` | `sg01/archive/camera.py` | stub, replaced by cameras/ |
| `robots/shared/data_models.py` | `archive/root_shared/data_models.py` | shared-level stub |
| `robots/shared/firebase_utils.py` | `archive/root_shared/firebase_utils.py` | shared-level stub |
| `sg02/src/` (whole tree) | `sg02/archive/src/` | RTDB-era code |
| `sg02/test_file/` | `sg02/archive/test_file/` | sg02 test scripts |
| `thermal_test/` (repo root) | `experiments/thermal_test/` | test images/scripts |

---

## Restructure — July 2026 (`restructure`)

- Moved all sg01 runtime source into `robots/sg01/src/robot_server/`
- Added `robots/sg01/data/` for session folders and background sensor CSVs
- Added `robots/sg01/deploy/` with systemd service file and README
- Added `robots/sg01/archive/` for RTDB-era code no longer in use
- Added internet connectivity status field to sensor stream
- Added wifi speed field to sensor stream

---

## Earlier history

See `git log` for full commit history. Key milestones:

- 20 Hz IMU sampling thread with `time.monotonic()` drift-free scheduling
- Dead-man watchdog (500 ms timeout, 100 ms check interval)
- MJPEG stream via `multipart/x-mixed-replace`
- Session folder logging: `meta.json`, `sensors.csv`, `commands.csv`, `frames.csv`, `video.avi`
- Live charts in control.html (Chart.js)
- BNO055 replacing MPU-6050 (metal duct housing, no magnetometer)
