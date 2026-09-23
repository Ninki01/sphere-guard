import board
import busio
from adafruit_pca9685 import PCA9685

# Create the I2C bus interface
i2c = busio.I2C(board.SCL, board.SDA)

try:
    # Create the PCA9685 instance
    pca = PCA9685(i2c)
    pca.frequency = 50
    print("✅ PCA9685 detected and initialized at 0x40!")
except Exception as e:
    print(f"❌ Failed to initialize PCA9685: {e}")