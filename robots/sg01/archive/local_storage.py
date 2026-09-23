import os
import csv
from datetime import datetime, timezone, timedelta

MYT = timezone(timedelta(hours=8))

# CSV headers for each sensor
_HEADERS = {
    'imu':     ['timestamp', 'pitch', 'roll', 'yaw'],
    'bme280':  ['timestamp', 'temp_c', 'hum_pct', 'press_hpa'],
    'scd41':   ['timestamp', 'co2_ppm', 'temp_c', 'hum_pct'],
    'sht45':   ['timestamp', 'temp_c', 'hum_pct'],
    'sdp810':  ['timestamp', 'diff_pressure_pa', 'temp_c'],
    'voc':     ['timestamp', 'gas_ppm'],
    'battery': ['timestamp', 'voltage_v', 'current_ma', 'power_mw', 'percentage'],
}

class LocalStorage:
    def __init__(self):
        base = os.path.dirname(os.path.abspath(__file__))
        self._data_dir = os.path.join(base, '..', 'data')
        self._active_session_id = None
        self._files = {}
        self._writers = {}
        self._open_writers()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_folder(self):
        if self._active_session_id:
            folder = os.path.join(self._data_dir, 'sessions', self._active_session_id)
        else:
            today = datetime.now(MYT).strftime('%Y-%m-%d')
            folder = os.path.join(self._data_dir, 'background', today)
        os.makedirs(folder, exist_ok=True)
        return folder

    def _open_writers(self):
        self._close_writers()
        folder = self._get_folder()
        for name, headers in _HEADERS.items():
            filepath = os.path.join(folder, f'{name}.csv')
            file_exists = os.path.exists(filepath)
            f = open(filepath, 'a', newline='')
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(headers)
            self._files[name] = f
            self._writers[name] = writer
        print(f"📁 Local Storage: writing to {folder}")

    def _close_writers(self):
        for f in self._files.values():
            try:
                f.flush()
                f.close()
            except Exception:
                pass
        self._files.clear()
        self._writers.clear()

    def _write(self, name, row):
        try:
            self._writers[name].writerow(row)
            self._files[name].flush()
        except Exception as e:
            print(f"❌ Local Storage write error [{name}]: {e}")

    def _now(self):
        return datetime.now(MYT).strftime('%Y-%m-%d %H:%M:%S')

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def set_active_session(self, session_id):
        self._active_session_id = session_id
        self._open_writers()
        if session_id:
            print(f"📁 Local Storage: session started → {session_id}")
        else:
            print("📁 Local Storage: session ended → back to background folder.")

    # ------------------------------------------------------------------
    # Sensor log methods
    # ------------------------------------------------------------------

    def log_imu(self, pitch, roll, yaw):
        self._write('imu', [self._now(), pitch, roll, yaw])

    def log_bme280(self, temp, hum, press):
        self._write('bme280', [self._now(), temp, hum, press])

    def log_scd41(self, co2, temp, hum):
        self._write('scd41', [self._now(), co2, temp, hum])

    def log_sht45(self, temp, hum):
        self._write('sht45', [self._now(), temp, hum])

    def log_sdp810(self, pressure, temp):
        self._write('sdp810', [self._now(), pressure, temp])

    def log_voc(self, voc):
        self._write('voc', [self._now(), voc])

    def log_battery(self, voltage, current, power, percentage):
        self._write('battery', [self._now(), voltage, current, power, percentage])

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self):
        self._close_writers()
        print("📁 Local Storage: all files closed cleanly.")
