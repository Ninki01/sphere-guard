"""
Atomic write-back of config.yaml.

Always writes to a .tmp sibling then os.replace() so a crash mid-write
never corrupts the live config file.
"""

import os
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


def write_config(cfg_path: str, data: dict) -> None:
    """
    Write `data` as YAML to `cfg_path` atomically.
    `data` must be a plain dict (not a SimpleNamespace).
    """
    if yaml is None:
        raise ImportError("PyYAML is required: pip install pyyaml")

    path = Path(cfg_path)
    tmp  = path.with_suffix(".yaml.tmp")

    with open(tmp, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    os.replace(tmp, path)


def apply_live(cfg, data: dict, drive, steering) -> list:
    """
    Apply whichever fields from `data` can be changed without a restart.
    Returns a list of field names that were applied live.

    Safe to apply live:
      - drive.forward_speed, backward_speed, spin_speed, deadzone
      - steering.servo_center, servo_left, servo_right
    Everything else needs a restart.
    """
    applied = []

    drive_data    = data.get("drive", {})
    steering_data = data.get("steering", {})

    for key in ("forward_speed", "backward_speed", "spin_speed", "deadzone"):
        if key in drive_data:
            val = float(drive_data[key])
            setattr(cfg.drive, key, val)
            applied.append(f"drive.{key}")

    for key in ("servo_center", "servo_left", "servo_right"):
        if key in steering_data:
            val = int(steering_data[key])
            setattr(cfg.steering, key, val)
            applied.append(f"steering.{key}")

    # Re-centre steering to new center angle
    if "servo_center" in steering_data:
        steering.center()

    return applied
