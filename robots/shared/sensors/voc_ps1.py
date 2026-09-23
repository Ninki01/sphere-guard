"""
PS1-VOC-200-MOD UART VOC sensor — SWAPPABLE sensor.

Uses serial polling (not I2C). Detection is attempted by opening the serial port
from config (cfg.voc.port). addr = 0 since it is not I2C.

Reconnect lifecycle: if serial I/O raises (USB disconnected, port gone),
Sensor.record_failure() counts it; at OFFLINE_AFTER failures Sensor.attempt_reconnect()
calls init() which closes the stale port and opens a fresh one.
"""

import time
import serial

from shared.sensors.base import Sensor

_POLL_CMD = bytearray([0xFF, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79])


class VOCPS1(Sensor):
    name     = "VOC_PS1"
    addr     = 0        # not I2C
    is_fixed = False

    def __init__(self):
        self._ser  = None
        self._port = None
        self._baud = 9600

    def probe(self, bus) -> bool:
        # bus is ignored (UART sensor); actual probe happens in probe_uart()
        return self._port is not None

    def probe_uart(self, cfg) -> bool:
        """Discover the serial port from config and do an initial open."""
        voc_cfg = getattr(cfg, "voc", None)
        port    = getattr(voc_cfg, "port", None)
        baud    = getattr(voc_cfg, "baud", 9600)
        if not port:
            return False
        self._port = port
        self._baud = baud
        try:
            self.init(cfg)
            return self._ser is not None
        except Exception:
            return False

    def init(self, cfg) -> None:
        """Open (or reopen) the serial port, closing any stale handle first."""
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
        # cfg still available for fresh opens; fall back to stored values
        voc_cfg = getattr(cfg, "voc", None)
        port = self._port or getattr(voc_cfg, "port", None)
        baud = self._baud or getattr(voc_cfg, "baud", 9600)
        if not port:
            raise RuntimeError("VOC port not configured")
        self._ser  = serial.Serial(
            port=port, baudrate=baud,
            parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS, timeout=1,
        )
        self._port = port
        self._baud = baud

    def cols(self) -> list:
        return ["voc_ppb"]

    def read(self) -> dict:
        if self._ser is None:
            return {"voc_ppb": None}
        # Serial I/O errors propagate: Sensor.record_failure() counts them and
        # Sensor.attempt_reconnect() calls init() to reopen the port.
        self._ser.reset_input_buffer()
        self._ser.write(_POLL_CMD)
        time.sleep(0.2)
        if self._ser.in_waiting >= 9:
            data = self._ser.read(9)
            if data[0] == 0xFF and data[1] == 0x86:
                chk = ((~sum(data[1:8]) & 0xFF) + 1) & 0xFF
                if chk == data[8]:
                    return {"voc_ppb": float((data[2] << 8) | data[3]) / 10.0}
        return {"voc_ppb": None}

    def cleanup(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
