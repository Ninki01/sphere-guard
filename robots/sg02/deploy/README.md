# SG02 Robot Server — systemd deployment

## Overview

SG02 runs the same `shared` Python package as SG01, differing only in
`sg02/config.yaml`. Run from the `robots/` directory.

## Before installing

Edit `robot_server.service` and replace the paths with the actual clone location
on your Pi:

```ini
WorkingDirectory=/home/<user>/<clone-path>/robots
ExecStart=/usr/bin/python3 -m shared.run --config sg02/config.yaml
```

## Install and enable

```bash
sudo cp robot_server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable robot_server
sudo systemctl start robot_server
```

## View live logs

```bash
journalctl -u robot_server -f
```

## Manual run (development)

```bash
cd robots
python -m shared.run --config sg02/config.yaml
```

## Tuning note

`sg02/config.yaml` has placeholder `# UNTUNED` values for servo angles, speeds,
and body dimensions. Use the `/config` calibration page to adjust live values,
then save to persist them to disk. A restart is required for camera changes.

---

## Firebase uploader

See `robots/sg01/deploy/README.md` for full uploader setup instructions — the
procedure is identical for SG02. The only difference is the service file path and
config flag:

```bash
sudo cp uploader.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable uploader
sudo systemctl start uploader
```

The same `/etc/sphereguard/uploader.env` credentials file is shared between both
robots if they run on the same Pi. If they run on different Pis, each Pi needs its
own copy of the credentials.

```bash
# Manual status check for SG02
cd robots
python -m shared.uploader --config sg02/config.yaml --status
```
