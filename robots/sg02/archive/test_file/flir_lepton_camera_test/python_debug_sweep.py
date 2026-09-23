import spidev
import time

def debug_lepton_data():
    print("--- FLIR Lepton 3.5 Raw Hex Dumper ---")
    
    spi = spidev.SpiDev()
    spi.open(0, 0)
    spi.max_speed_hz = 10000000  # Sticking to 10MHz for stability
    spi.mode = 0b11

    print("⏳ Forcing Lepton Reset (200ms)...")
    time.sleep(0.2)
    
    print("📸 Sweeping high-speed data...")
    raw_buffer = bytearray()
    
    try:
        # Just grab 10 chunks to see what the camera is doing
        for _ in range(10):
            raw_buffer.extend(spi.readbytes(3936))
            
    except Exception as e:
        print(f"❌ SPI Error: {e}")
        return
    finally:
        spi.close()

    print(f"✅ Captured {len(raw_buffer)} bytes.")
    print("\n🔎 First 15 Packet Headers (Raw Hex):")
    
    # Print the first 4 bytes of the first 15 packets
    for i in range(15):
        idx = i * 164
        # We grab 4 bytes to see the ID, CRC, and the start of the payload
        header = raw_buffer[idx:idx+4]
        hex_str = " ".join([f"{b:02X}" for b in header])
        print(f"Chunk {i:02d} Start: {hex_str}")

if __name__ == "__main__":
    debug_lepton_data()