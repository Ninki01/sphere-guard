import time
import board
import adafruit_scd4x

i2c = board.I2C()
scd4x = adafruit_scd4x.SCD4X(i2c)
print("Serial number:", [hex(i) for i in scd4x.serial_number])

scd4x.start_periodic_measurement()
print("Waiting for first measurement...")

try:
    while True:
        if scd4x.data_ready:
            print(f"CO2: {scd4x.CO2} ppm")
            print(f"Temperature: {scd4x.temperature:.1f} °C")
            print(f"Humidity: {scd4x.relative_humidity:.1f} %")
            print("-" * 20)
        time.sleep(1)
except KeyboardInterrupt:
    scd4x.stop_periodic_measurement()
    print("Stopped.")