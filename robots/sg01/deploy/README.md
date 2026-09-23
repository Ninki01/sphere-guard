# SG01 Robot Server — systemd deployment

## Overview

The server runs as the `shared` Python package, so it must be started from the
`robots/` directory (not `sg01/`). The systemd service file sets this automatically.

## Before installing

Edit `robot_server.service` and replace the paths with the actual clone location
on your Pi, and replace `User=pi` with your Pi's username (e.g. `sguard`):

```ini
WorkingDirectory=/home/<user>/<clone-path>/robots
ExecStart=/usr/bin/python3 -m shared.run --config sg01/config.yaml
```

If your Python packages are in a conda/virtualenv, point `ExecStart` at the
correct interpreter:

```ini
ExecStart=/home/sguard/miniforge3/envs/robot-env/bin/python -m shared.run --config sg01/config.yaml
```

## Install and enable

```bash
# 1. Copy the unit file
sudo cp robot_server.service /etc/systemd/system/

# 2. Reload systemd
sudo systemctl daemon-reload

# 3. Enable on boot
sudo systemctl enable robot_server

# 4. Start immediately
sudo systemctl start robot_server
```

## View live logs

```bash
journalctl -u robot_server -f
```

## Other useful commands

```bash
sudo systemctl status robot_server   # check running state
sudo systemctl restart robot_server  # apply config/code changes
sudo systemctl stop robot_server     # stop until next boot
sudo systemctl disable robot_server  # remove from boot
```

## Manual run (development)

```bash
# From the repository root:
cd robots
python -m shared.run --config sg01/config.yaml
```

## Camera device indices

The RGB camera is usually `/dev/video0` (device index `0`). The thermal P2 Pro
is usually two indices higher (it registers two UVC endpoints).

To find the correct index before editing `sg01/config.yaml`:

```bash
# List all UVC devices
v4l2-ctl --list-devices

# Verify a device index delivers the expected resolution
v4l2-ctl -d /dev/video2 --get-fmt-video
```

The P2 Pro reports 256×384 — the top 256×192 half is the thermal image, the
bottom half is raw temperature data. Confirm `config.yaml` `cameras.thermal.device`
matches the `/dev/videoN` index where 256×384 appears.

## Sensor auto-detection

The server auto-detects sensors via I2C scan at startup. No sensor list in
`config.yaml` is needed. FIXED sensors (BNO055, INA226) print a warning if
absent; SWAPPABLE sensors (SHT45, SCD41, SDP810) are silently skipped.

---

## Firebase uploader

The uploader runs as a separate service (`uploader.service`). It scans the session
data directory after every recording, converts video to MP4, and uploads to Cloud
Storage + Firestore in FIFO order.

### Credentials setup (do this once on the Pi)

The service account key and bucket name are passed via an EnvironmentFile on the
Pi — they are **never stored in the repository**.

```bash
# 1. Create the credentials directory
sudo mkdir -p /etc/sphereguard
sudo chmod 700 /etc/sphereguard

# 2. Copy your Firebase service account JSON to the Pi (from your workstation):
#    scp firebase-key.json pi@<pi-ip>:/tmp/
#    Then on the Pi:
sudo cp /tmp/firebase-key.json /etc/sphereguard/firebase-key.json
sudo chmod 600 /etc/sphereguard/firebase-key.json
sudo chown root:root /etc/sphereguard/firebase-key.json

# 3. Create the EnvironmentFile
sudo tee /etc/sphereguard/uploader.env > /dev/null <<EOF
SG_FIREBASE_KEY=/etc/sphereguard/firebase-key.json
SG_STORAGE_BUCKET=sphere-guard-2025.firebasestorage.app
EOF
sudo chmod 600 /etc/sphereguard/uploader.env
```

> **Security note:** `robots/sg01/serviceAccountKey.json` was committed to git
> history in error. That file should be treated as compromised — rotate the service
> account key in the Firebase console if that account is still active. Never place
> keys inside the repository directory.

### Install and enable the uploader service

```bash
# Edit uploader.service first — replace paths and User= as for robot_server.service
sudo cp uploader.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable uploader
sudo systemctl start uploader
```

### View live uploader logs

```bash
journalctl -u uploader -f
```

### Manual / test runs

```bash
cd robots

# Show what would be uploaded (no files touched, no Firebase calls)
python -m shared.uploader --config sg01/config.yaml --dry-run --once

# Print queue status (sessions, upload state, attempt counts)
python -m shared.uploader --config sg01/config.yaml --status

# Process one pass then exit (useful for scripted testing)
python -m shared.uploader --config sg01/config.yaml --once
```

### Prerequisites

```bash
# Firebase Admin SDK
pip install firebase-admin

# ffmpeg for video conversion (apt, not pip)
sudo apt install ffmpeg
```
