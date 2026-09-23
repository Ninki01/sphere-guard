import serial
import time

class PS1VOCSensor:
    def __init__(self, port='/dev/ttyAMA0', baudrate=9600):
        """Initializes the PS1-VOC-200-MOD UART VOC sensor in Polling Mode."""
        self.connected = False
        self.port = port
        
        # The industry-standard SGX/Winsen "Read Gas Concentration" command
        self.poll_cmd = bytearray([0xFF, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79])
        
        try:
            # Open the hardware serial port
            self.ser = serial.Serial(
                port=self.port,
                baudrate=baudrate,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
                timeout=1 
            )
            self.connected = True
            print(f"✅ PS1-VOC-200-MOD connected successfully on {self.port}.")
        except Exception as e:
            print(f"⚠️ Warning: PS1-VOC-200-MOD not found on {self.port}. Error: {e}")

    def get_readings(self):
        """Asks the sensor for data and returns VOC concentration in ppm."""
        if not self.connected:
            return 0.0

        try:
            # 1. Clear out any junk in the buffer
            self.ser.reset_input_buffer()
            
            # 2. Ask the question (Send the Poll Command)
            self.ser.write(self.poll_cmd)
            
            # 3. Wait exactly 0.1 seconds for the sensor to think and reply
            time.sleep(0.1)
            
            # 4. Listen for the 9-byte answer
            if self.ser.in_waiting >= 9:
                # Read exactly 9 bytes
                data = self.ser.read(9)
                
                # Verify Start Byte (0xFF) and Command Byte (0x86)
                if data[0] == 0xFF and data[1] == 0x86:
                    
                    # 5. Calculate Checksum to ensure the data isn't corrupted
                    checksum = (sum(data[1:8]) & 0xFF)
                    checksum = (~checksum & 0xFF) + 1
                    
                    if checksum == data[8]:
                        # 6. Extract the Gas Concentration (High Byte and Low Byte)
                        voc_raw = (data[2] << 8) | data[3]
                        
                        # Return the value as a float
                        return float(voc_raw) / 10.0
                    else:
                        print("⚠️ VOC Sensor: Checksum failed!")
            
            # If no data came back, or it was incomplete
            return 0.0
            
        except Exception as e:
            print(f"⚠️ PS1-VOC-200-MOD reading error: {e}")
            return 0.0

    def cleanup(self):
        """Closes the serial port cleanly."""
        if self.connected:
            try:
                self.ser.close()
                print("🛑 PS1-VOC-200-MOD serial port closed cleanly.")
            except Exception:
                pass