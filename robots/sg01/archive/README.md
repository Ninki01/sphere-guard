# Archive

Moved here July 2026 when sg01 was restructured. Active server is now `src/robot_server/`.

- `main.py` — old RTDB-based main controller, replaced by src/robot_server/robot_server.py
- `local_storage.py` — early local CSV logging module, superseded by session-based logging in robot_server.py
- `control/` — servo control abstraction; logic now inlined into robot_server.py
- `firebase_client/` — Firebase RTDB/Storage client; not used by current server
- `local_test/` — first-generation local HTTP joystick server (pre-joystick refactor)
- `test_file/` — one-off sensor and integration test scripts
- `test_servo/` — servo calibration scripts from the local_test_joystick era
- `SERVO Robot test.py` — quick manual servo test
- `test_robot.py` — manual integration test for full robot stack (local_test_joystick era)
- `robot_server_noHat_noSensors.py` — stripped server variant for testing without HAT or sensors

---

## Fleet refactor — August 2026

Added when all sg01 logic was extracted into `robots/shared/` (fleet refactor branch).
Active server is now `robots/shared/` started via `python -m shared.run --config sg01/config.yaml`.

- `robot_server.py` — original ~700-line monolith; logic split across shared/ subpackages
- `ina219_sensor.py` — INA219 current sensor driver; replaced by `shared/sensors/ina226.py`
- `imu_mpu6050.py` — MPU-6050 IMU driver; never used on SG01 (BNO055 is fitted)
- `camera.py` — camera stub with TODO comment; replaced by `shared/cameras/`
