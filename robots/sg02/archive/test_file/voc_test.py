import serial
import time

def debug_voc():
    print("--- VOC Sensor Raw Data Debugger ---")
    try:
        ser = serial.Serial('/dev/serial0', baudrate=9600, timeout=2)
        print("Serial port opened successfully.")
        
        # 1. Test for Active Streaming
        print("\n⏳ Listening for active data stream for 5 seconds...")
        end_time = time.time() + 15
        found_stream = False
        
        while time.time() < end_time:
            if ser.in_waiting > 0:
                found_stream = True
                time.sleep(0.2) # Let the buffer fill up a bit
                raw_bytes = ser.read(ser.in_waiting)
                hex_data = " ".join([f"{b:02X}" for b in raw_bytes])
                print(f"📥 RAW STREAM RECEIVED: {hex_data}")
        
        # 2. Test for "Question & Answer" Polling Mode
        if not found_stream:
            print("\n🔇 Silence... The sensor is not streaming data on its own.")
            print("Trying to wake it up using Q&A Polling Mode...")
            
            # This is the industry-standard "Read Gas Concentration" command
            # Format: Start Byte (FF), Sensor ID (01), Command (86), padding..., Checksum (79)
            poll_cmd = bytearray([0xFF, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79])
            
            ser.reset_input_buffer()
            ser.write(poll_cmd)
            print("📤 SENT COMMAND: FF 01 86 00 00 00 00 00 79")
            
            time.sleep(0.5) # Wait for the sensor to think and reply
            
            if ser.in_waiting > 0:
                raw_bytes = ser.read(ser.in_waiting)
                hex_data = " ".join([f"{b:02X}" for b in raw_bytes])
                print(f"📥 RECEIVED REPLY: {hex_data}")
            else:
                print("\n❌ Still no response.")
                print("Checklist:")
                print("1. Ensure Sensor TX is wired to Pi RX (Pin 10)")
                print("2. Ensure Sensor RX is wired to Pi TX (Pin 8)")
                print("3. Ensure the sensor has 5V or 3.3V power (check your datasheet!)")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if 'ser' in locals():
            ser.close()
            print("\n✅ Port closed.")

if __name__ == "__main__":
    debug_voc()