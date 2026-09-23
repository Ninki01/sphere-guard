import spidev
import time
import numpy as np

def test_lepton_spi():
    print("--- FLIR Lepton 3.5 SPI Diagnostic ---")
    
    # Initialize the SPI bus
    spi = spidev.SpiDev()
    
    try:
        # Open SPI Bus 0, Device 0 (Physical Pin 24 / CE0)
        spi.open(0, 0)
        
        # Lepton requires high speed (up to 20MHz). We will start at a safe 16MHz.
        spi.max_speed_hz = 16000000
        spi.mode = 0b11 # Lepton requires SPI Mode 3
        
        print("✅ SPI Port /dev/spidev0.0 opened successfully.")
        print("⏳ Listening for Lepton VoSPI sync packets...\n")
        
        # The Lepton sends data in 164-byte packets.
        # We will try to grab a chunk of packets and look for the sync pattern.
        packets_received = 0
        valid_packets = 0
        discard_packets = 0
        
        start_time = time.time()
        
        # Listen for 3 seconds
        while time.time() - start_time < 3.0:
            # Request 164 bytes from the SPI bus
            packet = spi.readbytes(164)
            packets_received += 1
            
            # The first two bytes of a packet are the ID header
            header = (packet[0] << 8) | packet[1]
            
            # If the header is x0Fxx, it's a "Discard Packet" (camera isn't ready)
            if (packet[0] & 0x0F) == 0x0F:
                discard_packets += 1
            else:
                valid_packets += 1

        print(f"📊 Diagnostic Results in 3 Seconds:")
        print(f"Total packets captured: {packets_received}")
        print(f"Valid video packets:    {valid_packets}")
        print(f"Discard (sync) packets: {discard_packets}")
        
        if valid_packets > 0:
            print("\n🚀 SUCCESS: The Raspberry Pi is successfully reading video frames from the Lepton!")
        elif discard_packets > 0:
            print("\n⚠️ WARNING: Connected, but camera is only sending discard packets. It might need a reboot or is lacking power.")
        else:
            print("\n❌ FAILED: Total silence. Check your MISO, CLK, and CS wiring.")

    except Exception as e:
        print(f"\n❌ Hardware Error: {e}")
    finally:
        spi.close()
        print("Port closed.")

if __name__ == "__main__":
    test_lepton_spi()