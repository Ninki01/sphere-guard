"""
Load and validate robots/{sg01,sg02}/config.yaml.

Usage:
    cfg = load_config("robots/sg01/config.yaml")

All paths in the returned Config are absolute.
Validation fails fast with a clear message rather than a traceback.
"""

import os
from pathlib import Path
from types import SimpleNamespace

try:
    import yaml
except ImportError:
    yaml = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def _ns(d: dict) -> SimpleNamespace:
    """Recursively convert dict to SimpleNamespace for attribute access."""
    ns = SimpleNamespace()
    for k, v in d.items():
        setattr(ns, k, _ns(v) if isinstance(v, dict) else v)
    return ns


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(f"Config error: {msg}")


def load_config(path: str):
    """
    Load, validate, and return a Config SimpleNamespace from the given YAML path.
    Also loads a .env file from the same directory if present.
    """
    if yaml is None:
        raise ImportError("PyYAML is required: pip install pyyaml")

    config_path = Path(path).resolve()
    _assert(config_path.exists(), f"config file not found: {config_path}")

    config_dir = config_path.parent

    # Load optional .env from same directory
    env_path = config_dir / ".env"
    if load_dotenv and env_path.exists():
        load_dotenv(env_path)

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    _assert(isinstance(raw, dict), "config file must be a YAML mapping")

    cfg = _ns(raw)

    # ── robot ──────────────────────────────────────────────────────────────
    _assert(hasattr(cfg, "robot"), "missing section: robot")
    _assert(hasattr(cfg.robot, "id"), "missing: robot.id")
    _assert(hasattr(cfg.robot, "name"), "missing: robot.name")

    # ── server ─────────────────────────────────────────────────────────────
    _assert(hasattr(cfg, "server"), "missing section: server")
    _assert(hasattr(cfg.server, "port"), "missing: server.port")
    _assert(1 <= cfg.server.port <= 65535, "server.port must be 1-65535")

    # ── drive ──────────────────────────────────────────────────────────────
    _assert(hasattr(cfg, "drive"), "missing section: drive")
    for key in ("drive_channel", "steering_channel", "forward_speed",
                "backward_speed", "spin_speed", "deadzone"):
        _assert(hasattr(cfg.drive, key), f"missing: drive.{key}")
    _assert(0 < cfg.drive.forward_speed  <= 1.0, "drive.forward_speed must be in (0, 1]")
    _assert(0 < cfg.drive.backward_speed <= 1.0, "drive.backward_speed must be in (0, 1]")
    _assert(0 < cfg.drive.spin_speed     <= 1.0, "drive.spin_speed must be in (0, 1]")
    _assert(0 <= cfg.drive.deadzone < 1.0, "drive.deadzone must be in [0, 1)")

    # ── steering ───────────────────────────────────────────────────────────
    _assert(hasattr(cfg, "steering"), "missing section: steering")
    for key in ("servo_center", "servo_left", "servo_right"):
        _assert(hasattr(cfg.steering, key), f"missing: steering.{key}")
        val = getattr(cfg.steering, key)
        _assert(0 <= val <= 180, f"steering.{key} must be 0-180, got {val}")

    # ── body ───────────────────────────────────────────────────────────────
    _assert(hasattr(cfg, "body"), "missing section: body")
    _assert(cfg.body.sphere_radius_m > 0, "body.sphere_radius_m must be > 0")
    _assert(cfg.body.total_mass_kg   > 0, "body.total_mass_kg must be > 0")
    _assert(cfg.body.pendulum_offset_m >= 0,
            "body.pendulum_offset_m must be >= 0 (0.0 = unmeasured)")

    # ── ina226 ─────────────────────────────────────────────────────────────
    if hasattr(cfg, "ina226"):
        _assert(cfg.ina226.shunt_ohms > 0, "ina226.shunt_ohms must be > 0")

    # ── logging ────────────────────────────────────────────────────────────
    _assert(hasattr(cfg, "logging"), "missing section: logging")
    _assert(cfg.logging.sample_hz > 0, "logging.sample_hz must be > 0")
    _assert(cfg.logging.env_every_n > 0, "logging.env_every_n must be > 0")
    _assert(cfg.logging.flush_every > 0, "logging.flush_every must be > 0")

    # ── cameras ────────────────────────────────────────────────────────────
    if hasattr(cfg, "cameras") and cfg.cameras:
        for i, cam in enumerate(cfg.cameras):
            if isinstance(cam, dict):
                cfg.cameras[i] = _ns(cam)

    # ── paths ──────────────────────────────────────────────────────────────
    _assert(hasattr(cfg, "paths"), "missing section: paths")
    _assert(hasattr(cfg.paths, "data_dir"), "missing: paths.data_dir")
    # Resolve data_dir against the DIRECTORY CONTAINING THE CONFIG FILE.
    # Never resolve against os.getcwd() — the process may be started from any
    # directory (e.g. repo root, robots/, or sg01/).
    # "data/sensor_log" in sg01/config.yaml → /abs/path/to/robots/sg01/data/sensor_log
    # "../data/sensor_log" would resolve to /abs/path/to/robots/data/sensor_log — wrong.
    _config_dir = config_path.parent
    raw_data_dir = Path(cfg.paths.data_dir)
    if raw_data_dir.is_absolute():
        resolved_data_dir = raw_data_dir
    else:
        resolved_data_dir = (_config_dir / raw_data_dir).resolve()
    cfg.paths.data_dir     = str(resolved_data_dir)
    cfg.paths._config_dir  = str(_config_dir)
    cfg.paths._config_path = str(config_path)

    return cfg
