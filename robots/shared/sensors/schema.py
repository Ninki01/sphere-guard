"""
Canonical sensor CSV column schema for the SphereGuard fleet.

Rules:
  - sensors.csv always writes this full header in this order, regardless of which
    sensors are present.  Absent sensor → "".  Failed read → "".
  - Each driver's cols() must return names from COLUMNS only.  detect() validates
    this at startup and raises ValueError for any unknown name.
  - Adding a new sensor type: append columns to the END of the list and bump
    SCHEMA_VERSION.  Never reorder or rename existing columns — that would break
    every existing CSV the dashboard already holds.
  - schema_version is written into meta.json so the dashboard can detect
    schema migrations without parsing column headers.
"""

SCHEMA_VERSION: int = 3

COLUMNS: list[str] = [
    "t_ms",

    # ── BNO055 ────────────────────────────────────────────────────────────
    # Euler (degrees, display only — use quaternion for analysis)
    "pitch", "roll", "heading",
    # Quaternion — gimbal-lock-free, preferred for analysis
    "quat_w", "quat_x", "quat_y", "quat_z",
    # Linear acceleration (m/s²) and angular velocity (rad/s)
    "lin_acc_x", "lin_acc_y", "lin_acc_z",
    "gyro_x", "gyro_y", "gyro_z",
    # Calibration status 0–3 (cached from last read, updated every read cycle)
    "cal_sys", "cal_gyro", "cal_accel", "cal_mag",

    # ── BME280 ────────────────────────────────────────────────────────────
    "bme_temp",   # °C
    "bme_hum",    # % RH
    "bme_press",  # hPa

    # ── INA226 ────────────────────────────────────────────────────────────
    "bus_v",      # V
    "current_a",  # A
    "power_w",    # W

    # ── Pi internal ───────────────────────────────────────────────────────
    "pi_temp",    # °C (SoC thermal zone 0)
    "wifi_dbm",   # dBm signal of active wifi interface; "" when not on wifi
    "internet",   # 1 = reachable, 0 = unreachable (TCP 1.1.1.1:443)

    # ── SHT45 ─────────────────────────────────────────────────────────────
    "sht_temp",   # °C
    "sht_hum",    # % RH

    # ── SCD41 ─────────────────────────────────────────────────────────────
    "co2",        # ppm
    "scd_temp",   # °C
    "scd_hum",    # % RH

    # ── SDP810 ────────────────────────────────────────────────────────────
    "diff_press", # Pa (differential pressure)

    # ── VOC PS1 ───────────────────────────────────────────────────────────
    "voc_ppb",    # ppb (volatile organic compounds)

    # ── Pi internal (network identity — added schema v2) ─────────────────
    # Strings, not numerics — do not parse as float in numeric-only paths.
    "net_type",   # "wifi" | "ethernet" | "none"
    "net_name",   # SSID (wifi) | "Ethernet" | "" when down
    "ip_address", # IPv4 of active interface | ""
    # net_iface is excluded: live-only via /sensors, not written to CSV

    # ── Pi internal (network metrics — added schema v3) ───────────────────
    "latency_ms",      # ms round-trip TCP connect to 1.1.1.1:443; "" if unreachable
    "link_speed_mbps", # negotiated link rate (Mbps); "" if unavailable
    "wifi_quality",    # link quality % (0–100, normalised from /proc/net/wireless)
                       # "" when not on wifi
]

# Lookup set for O(1) validation
_COLUMN_SET: set[str] = set(COLUMNS)


def validate_driver_cols(driver_name: str, cols: list[str]) -> None:
    """
    Raise ValueError if any column returned by a driver is not in COLUMNS.
    Called by detect() at startup before the sensor goes into the active list.
    """
    unknown = [c for c in cols if c not in _COLUMN_SET]
    if unknown:
        raise ValueError(
            f"Driver '{driver_name}' returned unknown column(s) {unknown}. "
            f"Add them to shared/sensors/schema.py COLUMNS (end of list) and "
            f"bump SCHEMA_VERSION."
        )
