# SG02 Archive

Files moved here when SG02 was migrated to the shared `robots/shared/` package
(fleet refactor, August 2026). Active server: `python -m shared.run --config sg02/config.yaml`.

## Contents

- `src/` — Firebase RTDB telemetry hub (the original SG02 codebase).
  SG02 was originally a sensor telemetry node, not a drive robot. This code
  reads sensors and pushes data to Firebase; it has no drive, servo, or HTTP
  server logic.
  - `src/sensors/` — sensor drivers: bme280, sht45, scd41, sdp810, bno055, ps1_voc
  - `src/firebase_client/` — Firebase RTDB + Storage client
  - `src/main-sensors.py` — main loop (RTDB push, no HTTP)

- `test_file/` — one-off test scripts from the SG02 bring-up phase
  - `flir_lepton_camera_test/` — FLIR Lepton thermal camera test scripts
  - `voc_test.py`, `raspi_camera_v2_test.py`, `video_thermal_test.py`, etc.
  - `troubleshoot_raspi_cam/` — camera debugging scripts
  - `luxonis_test.py` — OAK-D Lite (DepthAI) camera test

Note: sensor drivers from `src/sensors/` that were also in sg01 have been moved
to `robots/shared/sensors/` (via `git mv` from sg01). The copies here are the
SG02-era originals kept for reference.
