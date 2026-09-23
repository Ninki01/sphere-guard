# AGENTS.md

HVAC inspection robot fleet ("SphereGuard"): Python robot server on Raspberry Pi, React dashboard on Firebase Hosting, Firebase Cloud Functions. No CI, no monorepo tool, no automated test suite.

## Repo layout

- `robots/` — Python robot server + uploader. **All Python commands run from `robots/`** (the `shared` package is only importable from there).
  - `robots/shared/` — code shared by both robots (entry: `shared/run.py`, uploader: `shared/uploader/`)
  - `robots/sg01/`, `robots/sg02/` — per-robot `config.yaml`, `data/`, `deploy/`, `archive/`
- `dashboard/` — React 19 + Vite SPA (hosting source; builds to `dashboard/dist`)
- `firebase/` — Cloud Functions (`functions/`), Firestore/Storage/RTDB rules; wired by root `firebase.json`
- `docs/` — `session_schema.md` (data contract), `CHANGELOG.md` (append-only, newest first; bottom section = current architecture)
- `archive/`, `experiments/`, `testing/` — dead code and hardware test scripts; do not treat as active

## Commands

```bash
# Robot server (dev, from robots/; needs Pi hardware)
cd robots
pip install -r requirements.txt
python -m shared.run --config sg01/config.yaml

# Firebase uploader (from robots/)
python -m shared.uploader --config sg01/config.yaml --dry-run --once   # preview, no writes
python -m shared.uploader --config sg01/config.yaml --status           # queue state
python -m shared.uploader --config sg01/config.yaml --once             # one pass

# Dashboard (from dashboard/)
npm install
npm run dev       # Vite dev server
npm run lint      # eslint, --max-warnings 0 — must pass
npm run build     # output goes to dashboard/dist (Firebase Hosting serves this)

# Cloud Functions (from firebase/functions/; Node 22 per engines field)
npm run lint      # eslint 8 + eslint-config-google
npm run serve     # Firebase emulator for functions only
```

Verification order for dashboard changes: `npm run lint` → `npm run build`. There is no typecheck (plain JS/JSX) and no test runner in any package.

Deploy: `firebase deploy` from repo root — but Hosting serves `dashboard/dist`, so run `npm run build` in `dashboard/` first. `.firebaserc` is gitignored; each dev must link their own Firebase project before deploying.

## Hard rules (data contract)

`docs/session_schema.md` is the contract between robot, uploader, and dashboard. Enforced rules:

- `sensors.csv` columns: **append only, never reorder or rename**. Any schema change = append to `COLUMNS` in `robots/shared/sensors/schema.py`, bump `SCHEMA_VERSION` (currently 3), update `docs/session_schema.md`. Drivers are validated at startup via `validate_driver_cols()` — unknown column names crash the server.
- Absent/failed sensor reads write `""`, never `0`.
- Dashboard code must read column names from the CSV header, not positional offsets. `net_type`, `net_name`, `ip_address` are strings — do not cast to float.
- Timestamps: all `t_ms` are epoch ms UTC; folder names / `*_local` fields are MYT (UTC+8, no DST).
- Firestore doc is written **last** (after all Storage uploads) — a session "exists" only when its Firestore doc exists. Data model: Storage holds files, Firestore holds the index; never write per-sensor-row docs.
- Uploader credentials come only from `SG_FIREBASE_KEY` / `SG_STORAGE_BUCKET` (systemd EnvironmentFile `/etc/sphereguard/uploader.env`) — never commit keys. `serviceAccountKey.json` was in git history: treat as compromised.

## Non-obvious gotchas

- **Config relative paths** resolve against the config file's directory, not cwd (`paths.data_dir: "data/sensor_log"` → `robots/sg01/data/sensor_log`).
- **RTDB status is contradictory:** `docs/session_schema.md` says RTDB is retired (robot no longer writes it), but `dashboard/src/pages/Dashboard*.jsx` still reads RTDB and `firebase/functions/index.js` still triggers on RTDB `/robots/sg01`. The active ingestion path is the uploader → Cloud Storage + Firestore (`sessions` collection). Verify against code before relying on live RTDB telemetry; `variables_definition.md` documents the legacy RTDB shape.
- **Dashboard env:** `src/lib/firebase.js` requires `VITE_FIREBASE_*` vars (API_KEY, AUTH_DOMAIN, PROJECT_ID, STORAGE_BUCKET, MESSAGING_SENDER_ID, APP_ID, DATABASE_URL) in `dashboard/.env` — gitignored, no `.env.example` exists.
- **sg02 `config.yaml` is untuned** (servo angles/speeds marked `# UNTUNED placeholder`). sg01 is the calibrated robot.
- **Sensor schema changes also live in three places:** `schema.py`, `docs/session_schema.md`, and the dashboard's CSV parsing.
- Uploader needs `ffmpeg` (apt) + `firebase-admin` (pip), beyond `robots/requirements.txt`. Python deps include Pi-only hardware libs (Blinka, smbus2) — expect failures off-Pi.
- Session data lives in `robots/sg01/data/sensor_log/session_*/`; git status is often noisy with CSV changes — don't "fix" them.
- Firmware/hardware quirks are documented in `docs/CHANGELOG.md` "Known issues" (BNO055 IMUPLUS mode — no magnetometer in metal duct; P2 Pro thermal temp decoding unverified; clean-shutdown ordering matters — see `run.py` docstring).
