# SphereGuard Session Schema

This document is the contract between the robot server, the future Firebase uploader
(`robots/shared/uploader/`), and the web dashboard.  Do not change file formats or
column names without bumping `SCHEMA_VERSION` in `shared/sensors/schema.py` and
updating this document.

---

## Session folder layout

```
data/sensor_log/
└── session_YYYY-MM-DD_HH-MM-SS/
    ├── meta.json
    ├── sensors.csv
    ├── commands.csv
    ├── frames_rgb.csv          (if RGB camera active)
    ├── video_rgb.avi           (if RGB camera active)
    ├── frames_thermal.csv      (if thermal camera active)
    └── video_thermal.avi       (if thermal camera active)
```

Timestamps in folder names are in MYT (UTC+8) for human readability.
All `t_ms` values inside files are epoch milliseconds UTC.

### Legacy filename mapping (pre-dual-camera sessions)

Sessions recorded before the dual-camera refactor use different filenames.
The uploader transparently maps these to the current canonical names; the
dashboard always sees the canonical paths in Cloud Storage.

| Legacy filename | Canonical name | Notes |
|---|---|---|
| `video.avi` | `video_rgb.avi` | Single-camera era; converted and uploaded as `video_rgb.mp4` |
| `frames.csv` | `frames_rgb.csv` | Matching legacy frame index CSV |

When a legacy filename is used, the Firestore document gains a `legacy_filenames`
field recording the mapping:

```json
"legacy_filenames": {
  "video_rgb.avi": "video.avi"
}
```

Do **not** rename legacy files on disk — the uploader reads the original filename
and writes to the canonical storage path.

---

## meta.json

Written at session start (`status: "partial"`) and rewritten at stop (`status: "complete"`).
Also rewritten after every `sensor_event` so a crash mid-session still preserves the event list.

### Fields

| Field | Type | Description |
|---|---|---|
| `session_id` | string | Folder name (e.g. `session_2026-08-29_14-30-00`) |
| `robot_id` | string | From config: `"sg01"` or `"sg02"` |
| `schema_version` | int | `SCHEMA_VERSION` from `schema.py` (currently `3`) |
| `status` | string | `"partial"` while recording, `"complete"` after stop |
| `start_time_ms` | int | Epoch ms UTC |
| `start_time_local` | string | ISO-8601 MYT (human display only) |
| `end_time_ms` | int | Epoch ms UTC — omitted if partial |
| `end_time_local` | string | ISO-8601 MYT — omitted if partial |
| `duration_s` | float | Seconds — omitted if partial |
| `settings` | object | Drive/servo snapshot at session start (see below) |
| `sensors` | array | Sensor manifest: sensors present at session start |
| `sensor_events` | array | Lifecycle events during session (offline/reconnected) |
| `cameras` | array | Camera manifest (see below); `frames_written` added on complete |
| `rows` | object | Row counts per file — omitted if partial |
| `fusion` | object | Fusion config snapshot at session start — present only when `fusion:` key exists in config.yaml |
| `network_test` | object | Latest speed test result at session start — present only when a successful test has been run (status `"ok"` or `"error"`) |

### `settings` object

```json
{
  "forward_speed": 0.40,
  "backward_speed": 0.40,
  "spin_speed": 0.25,
  "deadzone": 0.12,
  "servo_center": 90,
  "servo_left": 135,
  "servo_right": 45
}
```

### `sensors` array (manifest — present at session start)

```json
[
  {"name": "BNO055", "address": "0x28", "driver": "BNO055", "fixed": true},
  {"name": "Pi",     "address": "n/a",  "driver": "PiInternal", "fixed": true}
]
```

### `cameras` array (active cameras at session start)

```json
[
  {"role": "rgb",     "device": 0, "width": 640, "height": 480, "fps": 30, "frames_written": 754},
  {"role": "thermal", "device": 2, "width": 256, "height": 384, "fps": 25, "frames_written": 0}
]
```

`frames_written` is omitted in partial meta (during recording) and added on complete.

### `sensor_events` array

Events are appended when a sensor goes offline or reconnects during a session.
The dashboard uses this list to annotate gaps in a column.

```json
[
  {"t_ms": 1724904600123, "sensor": "BNO055", "event": "offline"},
  {"t_ms": 1724904660456, "sensor": "BNO055", "event": "reconnected"}
]
```

`event` values: `"offline"` | `"reconnected"`

### `rows` object (complete sessions only)

```json
{
  "sensors": 12400,
  "frames_rgb": 754
}
```

---

## sensors.csv

Fixed schema — always written with all columns in this exact order, regardless of
which sensors are present.  A sensor absent at session start writes `""` for its
columns.  A sensor that reconnects mid-session starts writing values from that row
onward.  Never reorder or rename columns — append new columns at the end only.

`schema_version: 3`

| Column | Unit | Sensor | Notes |
|---|---|---|---|
| `t_ms` | epoch ms UTC | — | Row timestamp |
| `pitch` | ° | BNO055 | Euler pitch — display only, use quaternion for analysis |
| `roll` | ° | BNO055 | Euler roll |
| `heading` | ° | BNO055 | Euler heading |
| `quat_w` | — | BNO055 | Quaternion W (real part) |
| `quat_x` | — | BNO055 | Quaternion X |
| `quat_y` | — | BNO055 | Quaternion Y |
| `quat_z` | — | BNO055 | Quaternion Z |
| `lin_acc_x` | m/s² | BNO055 | Linear acceleration X |
| `lin_acc_y` | m/s² | BNO055 | Linear acceleration Y |
| `lin_acc_z` | m/s² | BNO055 | Linear acceleration Z |
| `gyro_x` | rad/s | BNO055 | Angular velocity X |
| `gyro_y` | rad/s | BNO055 | Angular velocity Y |
| `gyro_z` | rad/s | BNO055 | Angular velocity Z |
| `cal_sys` | 0–3 | BNO055 | System calibration (cached from last read) |
| `cal_gyro` | 0–3 | BNO055 | Gyro calibration |
| `cal_accel` | 0–3 | BNO055 | Accelerometer calibration |
| `cal_mag` | 0–3 | BNO055 | Magnetometer cal — not required in IMUPLUS mode |
| `bme_temp` | °C | BME280 | Temperature |
| `bme_hum` | %RH | BME280 | Relative humidity |
| `bme_press` | hPa | BME280 | Barometric pressure |
| `bus_v` | V | INA226 | Bus voltage |
| `current_a` | A | INA226 | Current |
| `power_w` | W | INA226 | Power |
| `pi_temp` | °C | Pi internal | SoC thermal zone 0 |
| `wifi_dbm` | dBm | Pi internal | Signal level of active wifi interface; `""` when on ethernet |
| `internet` | 0 or 1 | Pi internal | 1 = reachable (TCP 8.8.8.8:53) |
| `net_type` | string | Pi internal | `"wifi"` \| `"ethernet"` \| `"none"` — active interface type |
| `net_name` | string | Pi internal | SSID when wifi; `"Ethernet"` when wired; `""` when down |
| `ip_address` | string | Pi internal | IPv4 of active interface; `""` when down |
| `latency_ms` | ms (int) | Pi internal | Round-trip TCP connect to 1.1.1.1:443; `""` if unreachable — **added schema v3** |
| `link_speed_mbps` | Mbps (float) | Pi internal | Negotiated link rate (`/sys/class/net/<iface>/speed` or `iw`); `""` if unavailable — **added schema v3** |
| `wifi_quality` | % (int 0–100) | Pi internal | Normalised link quality from `/proc/net/wireless`; `""` when not on wifi — **added schema v3** |
| `sht_temp` | °C | SHT45 | Temperature |
| `sht_hum` | %RH | SHT45 | Relative humidity |
| `co2` | ppm | SCD41 | CO₂ concentration |
| `scd_temp` | °C | SCD41 | Temperature |
| `scd_hum` | %RH | SCD41 | Relative humidity |
| `diff_press` | Pa | SDP810 | Differential pressure |
| `voc_ppb` | ppb | VOC PS1 | Volatile organic compounds |

**Note:** `net_type`, `net_name`, and `ip_address` are **string** columns, not numeric.
Dashboard code that casts all sensor columns to `float` must skip these (check
`schema_version >= 2` and treat them as categoricals).  `net_iface` (active interface
name, e.g. `"wlan0"`) is returned by `/sensors` for live display but is **not** written
to `sensors.csv` — it is live-only.

`latency_ms`, `link_speed_mbps`, and `wifi_quality` (schema v3) are **numeric** — safe
to cast to `float` like the other numeric columns.  `wifi_quality` is `""` when
`net_type != "wifi"`; `link_speed_mbps` is `""` on wifi if `iw` is unavailable.

### Adding a new sensor type

1. Append new column(s) to the END of `COLUMNS` in `shared/sensors/schema.py`
2. Bump `SCHEMA_VERSION`
3. Write a new driver implementing the `Sensor` ABC; `cols()` returns only the new names
4. Add the driver to `registry.py`; `validate_driver_cols()` is called automatically at startup
5. Update this document

---

## commands.csv

Fixed header — every row is one driver command event.

| Column | Type | Description |
|---|---|---|
| `t_ms` | epoch ms UTC | Event timestamp |
| `source` | string | `"joystick"` \| `"button"` \| `"watchdog"` |
| `action` | string | `"move"` \| `"forward"` \| `"backward"` \| `"left"` \| `"right"` \| `"stop"` \| `"auto_stop"` |
| `x` | float | Joystick X in \[-1, 1\] (0 for button commands) |
| `y` | float | Joystick Y in \[-1, 1\] (0 for button commands) |
| `servo_angle` | float | Steering angle applied (degrees) |
| `throttle` | float | Drive throttle applied \[-1, 1\] |
| `extra` | string | Additional context (e.g. set_speed values) |

---

## frames_{role}.csv

One row per video frame written, per camera role (`rgb` or `thermal`).

| Column | Type | Description |
|---|---|---|
| `frame_index` | int | Zero-based frame counter within this session |
| `t_ms` | epoch ms UTC | Timestamp when frame was written |

The video file (`video_{role}.avi`) and this CSV share the same frame ordering.
Use `t_ms` to align video frames with `sensors.csv` rows for data sync — do not
rely on the VideoWriter fps as the authoritative clock.

---

## Timestamp convention

- **All `t_ms` columns**: epoch milliseconds UTC.  Consistent across all files in a session.
- **Human display (meta.json `*_local` fields, session folder name)**: MYT, UTC+8, fixed offset.
  No DST — Malaysia does not observe daylight saving time.
- **Cross-session comparison**: always use `t_ms` (UTC), never the local strings.

---

## Firebase layout

Implemented by `robots/shared/uploader/` (`python -m shared.uploader`).

**RTDB is not used.** The old Realtime Database telemetry path
(`archive/main.py`, `archive/firebase_client/db_manager.py`) is retired.
Control is local-only; the online dashboard is read-only analysis.

**Data model: Storage holds data, Firestore holds the index.**  The uploader never
writes per-sensor-row documents to Firestore (at 20 Hz that would be ~72 000
writes/hour — wrong data model and costly).

---

### Cloud Storage layout

```
robots/
└── {robot_id}/
    └── sessions/
        └── {session_id}/
            ├── meta.json
            ├── sensors.csv
            ├── commands.csv
            ├── frames_rgb.csv         (if RGB camera active)
            ├── frames_thermal.csv     (if thermal camera active)
            ├── video_rgb.mp4          (H.264, converted from .avi by uploader)
            └── video_thermal.mp4      (H.264, if thermal camera active)
```

Videos are uploaded as `.mp4` (H.264, libx264 veryfast), not `.avi`.
Files are never made public — the dashboard fetches them via the Firebase SDK
with authentication.  The uploader stores the storage path for each file in the
Firestore document; the dashboard constructs signed URLs from those paths.

---

### Firestore — `sessions` collection

One document per session, doc id = `session_id`.  One collection serves the whole
fleet (`device_id` is a field, not a subcollection) so cross-fleet queries are simple.

The document is written **last**, after all files are uploaded.  The dashboard
treats a session as existing only when this document is present.

```json
{
  "session_id":       "session_2026-08-29_14-30-00",
  "device_id":        "sg01",
  "status":           "complete",
  "schema_version":   3,
  "start_time_ms":    1724904600000,
  "start_time_local": "2026-08-29 22:30:00 MYT",
  "end_time_ms":      1724905200000,
  "end_time_local":   "2026-08-29 22:40:00 MYT",
  "duration_s":       600.0,
  "rows": {
    "sensors":     12000,
    "frames_rgb":  754
  },
  "sensors_present":  ["BNO055", "INA226", "Pi", "BME280"],
  "sensor_events":    [],
  "camera_events":    [],
  "cameras": [
    {"role": "rgb", "fps": 30, "frames_written": 754, "video_status": "ok"}
  ],
  "settings": { "forward_speed": 0.40, "servo_center": 90, "..." : "..." },
  "network_test":     { "..." : "..." },
  "homography":       null,
  "storage_paths": {
    "meta.json":       "robots/sg01/sessions/session_.../meta.json",
    "sensors.csv":     "robots/sg01/sessions/session_.../sensors.csv",
    "video_rgb.mp4":   "robots/sg01/sessions/session_.../video_rgb.mp4"
  },
  "uploaded_at":      "<Firestore SERVER_TIMESTAMP>",
  "device_clock_ms":  1724905260000,
  "uploader_version": "1.0.0"
}
```

**`device_clock_ms` vs `uploaded_at`:** the Pi has no battery RTC and may
boot with a wrong clock before NTP syncs.  The gap between `device_clock_ms`
(Pi wall-clock at upload time) and `uploaded_at` (Firebase server time) lets the
dashboard detect and flag clock drift for sessions whose timestamps may be wrong.

**`status`** values:

| Value | Meaning |
|---|---|
| `"complete"` | Session stopped cleanly; all data present |
| `"partial"` | Recording crashed before `stop()`; CSVs valid up to crash; `end_time_ms` recovered from last `sensors.csv` row |
| `"empty"` | Recording was aborted before any sensor rows were written; only `meta.json` uploaded |
| `"video_only"` | Session folder has a video file but no `meta.json` or CSVs; `start_time_ms` derived from folder name |

**`video_status`** per camera: `"ok"` | `"unrecoverable"` (ffmpeg failed, e.g.
truncated avi from crash) | `"none"` (no video file was created).

---

### Dashboard queries

```js
// All sessions for one robot
db.collection("sessions").where("device_id", "==", "sg01")

// Recent sessions across fleet, newest first
db.collection("sessions").orderBy("start_time_ms", "desc").limit(50)

// Sessions with a specific sensor
db.collection("sessions").where("sensors_present", "array-contains", "BNO055")

// Sessions with complete video
db.collection("sessions").where("cameras", "array-contains",
  { role: "rgb", video_status: "ok" })  // not directly queryable — filter client-side
```

`schema_version` lets the dashboard apply the correct CSV column mapping — always
read column names from the CSV header row, never from assumed offsets.

---

### Upload state

Each session folder gains `upload_state.json` (written atomically) after the first
upload attempt.  The uploader uses this to resume interrupted uploads without
re-uploading already-completed files.

```json
{
  "uploaded_files":    ["meta.json", "sensors.csv"],
  "firestore_written": false,
  "video_status":      {"rgb": "ok", "thermal": "none"},
  "attempts":          1,
  "last_error":        "",
  "session_status":    "empty",
  "permanently_skipped": false
}
```
