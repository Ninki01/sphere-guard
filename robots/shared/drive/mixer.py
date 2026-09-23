"""
Pure joystick-to-drive mapping. No hardware imports — unit-testable off-robot.

joystick_to_drive(x, y, cfg) -> (servo_angle_deg, throttle)

  x, y  : floats in [-1.0, 1.0]  (positive-x = right, positive-y = forward)
  cfg   : config object with drive.* and steering.* attributes

Rules (preserved from original robot_server.py):
  1. Both axes inside deadzone → stop (center, 0.0)
  2. Steering: angle = center - x * half_range
     where half_range = center - servo_right  (default 90 - 45 = 45)
  3. Throttle: y >= 0 → y * forward_speed; y < 0 → y * backward_speed
  4. Spin boost: |x| > deadzone and |y| < deadzone → throttle = spin_speed
"""


def joystick_to_drive(x: float, y: float, cfg) -> tuple:
    dz   = cfg.drive.deadzone
    fwd  = cfg.drive.forward_speed
    bwd  = cfg.drive.backward_speed
    spin = cfg.drive.spin_speed
    ctr  = cfg.steering.servo_center
    lft  = cfg.steering.servo_left
    rgt  = cfg.steering.servo_right

    if abs(x) < dz and abs(y) < dz:
        return float(ctr), 0.0

    half_range = ctr - rgt
    angle = ctr - x * half_range
    angle = max(0.0, min(180.0, angle))

    if abs(x) > dz and abs(y) < dz:
        throttle = spin
    elif y >= 0:
        throttle = y * fwd
    else:
        throttle = y * bwd

    return angle, throttle
