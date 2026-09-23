"""
Sensor auto-detection.

On startup, scans I2C bus 1 and instantiates a driver for each found address.
FIXED sensors that are absent log a loud warning but do not block startup.
SWAPPABLE sensors that are absent are silently skipped.
VOC (UART) is probed separately via probe_uart().
PiInternal is always added (probed via sysfs).

Usage:
    from shared.sensors.registry import detect
    sensors = detect(cfg)
"""

from shared.sensors.bno055      import BNO055
from shared.sensors.bme280      import BME280
from shared.sensors.ina226      import INA226
from shared.sensors.pi_internal import PiInternal
from shared.sensors.sht45       import SHT45
from shared.sensors.scd41       import SCD41
from shared.sensors.sdp810      import SDP810
from shared.sensors.voc_ps1     import VOCPS1
from shared.sensors.schema      import validate_driver_cols
from shared.util.log            import info, warn

try:
    import smbus2
    _SMBUS_OK = True
except ImportError:
    _SMBUS_OK = False

# Address → driver class mapping (I2C sensors only)
_REGISTRY = {
    BNO055.addr: BNO055,
    BME280.addr: BME280,
    # INA226 addr is config-driven; handled specially below
    SHT45.addr:  SHT45,
    SCD41.addr:  SCD41,
    SDP810.addr: SDP810,
}


def _scan_i2c(bus) -> set:
    """Return set of I2C addresses that respond on bus 1."""
    found = set()
    for addr in range(0x03, 0x78):
        try:
            #bus.read_byte(addr)
            bus.write_quick(addr)
            found.add(addr)
        except Exception:
            pass
    return found


def detect(cfg) -> list:
    """
    Scan I2C bus 1, match addresses to drivers, probe UART VOC, and add PiInternal.
    Returns a list of initialised Sensor instances ready for read().
    """
    bus = None
    found_addrs = set()

    if _SMBUS_OK:
        try:
            bus = smbus2.SMBus(1)
            found_addrs = _scan_i2c(bus)
            info(f"I2C scan found {len(found_addrs)} device(s): "
                 + ", ".join(hex(a) for a in sorted(found_addrs)))
        except Exception as e:
            warn(f"I2C bus unavailable: {e}")
    else:
        warn("smbus2 not installed — I2C sensors will be unavailable")

    active: list = []

    # ── I2C sensors from registry ──────────────────────────────────────────
    # Every known sensor is pre-registered with online=False — even when it is
    # not on the bus at boot or init() fails.  The sampler's attempt_reconnect()
    # loop then keeps re-calling init() (time-gated at 5 s) and brings the
    # sensor online as soon as the hardware appears: hot-plug recovery.
    for addr, cls in _REGISTRY.items():
        sensor = cls()
        validate_driver_cols(sensor.name, sensor.cols())  # fail fast if schema mismatch
        if addr in found_addrs:
            try:
                sensor.init(cfg)
                active.append(sensor)
                info(f"  FOUND    {sensor.name:<12} @ {hex(addr)}")
                continue
            except Exception as e:
                warn(f"  INIT ERR {sensor.name:<12} @ {hex(addr)}: {e}  — will keep retrying")
        else:
            tag = "MISSING" if sensor.is_fixed else "absent"
            info(f"  {tag:<7} {sensor.name:<12} @ {hex(addr)}  — will retry reconnect")
        sensor.online = False
        active.append(sensor)

    # ── INA226 (address from config, not hardcoded in registry) ───────────
    ina_addr = getattr(getattr(cfg, "ina226", None), "address", 0x41)
    ina = INA226()
    validate_driver_cols(ina.name, ina.cols())
    ina.addr = ina_addr
    if ina_addr in found_addrs:
        try:
            ina.init(cfg)
            active.append(ina)
            info(f"  FOUND    {ina.name:<12} @ {hex(ina_addr)}")
        except Exception as e:
            warn(f"  INIT ERR {ina.name:<12} @ {hex(ina_addr)}: {e}  — will keep retrying")
            ina.online = False
            active.append(ina)
    else:
        warn(f"  MISSING  INA226       @ {hex(ina_addr)}  ← FIXED sensor not found!  — will retry reconnect")
        ina.online = False
        active.append(ina)

    # ── VOC (UART) ─────────────────────────────────────────────────────────
    voc = VOCPS1()
    validate_driver_cols(voc.name, voc.cols())
    if voc.probe_uart(cfg):
        voc.init(cfg)
        active.append(voc)
        info(f"  FOUND    {voc.name:<12}  (UART {getattr(getattr(cfg, 'voc', None), 'port', '?')})")
    else:
        info(f"  absent   {voc.name:<12}  (UART, port unavailable or not configured)")

    # ── Pi internal (always present) ───────────────────────────────────────
    pi = PiInternal()
    validate_driver_cols(pi.name, pi.cols())
    if pi.probe(bus):
        pi.init(cfg)
        active.append(pi)
        info(f"  FOUND    {pi.name:<12}  (sysfs)")
    else:
        warn(f"  MISSING  {pi.name:<12}  (sysfs not accessible — not on Pi?)")

    if bus is not None:
        try:
            bus.close()
        except Exception:
            pass

    return active
