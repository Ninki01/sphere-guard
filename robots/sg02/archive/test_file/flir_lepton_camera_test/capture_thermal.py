import spidev
import time
import numpy as np
import cv2

def capture_lepton_sweep():
    print("--- FLIR Lepton 3.5 (Pi 5 RP1 Blind Sweep) ---")
    
    spi = spidev.SpiDev()
    spi.open(0, 0)
    spi.max_speed_hz = 16000000 
    spi.mode = 0b11

    # 24 packets * 164 bytes = 3936 bytes (Perfectly fits under Pi 5's 4096 limit)
    CHUNK_SIZE = 3936 
    
    print("⏳ Rebooting Lepton (200ms)...")
    time.sleep(0.2)
    
    print("📸 Sweeping high-speed data directly to RAM...")
    
    # 1. THE BLIND SWEEP (Fast as possible, zero math)
    raw_buffer = bytearray()
    
    try:
        # Sweep 150 chunks (about 3.5 frames worth of raw data)
        for _ in range(150):
            raw_buffer.extend(spi.readbytes(CHUNK_SIZE))
            
        print(f"✅ Captured {len(raw_buffer)} bytes. Parsing offline...")
        
    except Exception as e:
        print(f"❌ SPI Error: {e}")
        return
    finally:
        spi.close() # Close port immediately, we don't need it for the math!

    # 2. THE OFFLINE PARSER
    # Reshape the massive bytearray into 164-byte packets
    total_packets = len(raw_buffer) // 164
    data = np.array(raw_buffer, dtype=np.uint8).reshape((total_packets, 164))
    
    frame_buffer = np.zeros((120, 160), dtype=np.uint16)
    segments_captured = [False, False, False, False]
    
    print("🔍 Hunting for Segments in the data...")
    
    # Hunt for the segments
    for i in range(total_packets):
        packet = data[i]
        
        is_discard = (packet[0] & 0x0F) == 0x0F
        if is_discard:
            continue
            
        packet_num = ((packet[0] & 0x0F) << 8) | packet[1]
        
        # Did we find the start of a segment?
        if packet_num == 0:
            # Check if we have enough packets left in the buffer to make a full segment
            if i + 60 <= total_packets:
                # Grab the next 60 packets
                segment_data = data[i:i+60]
                
                # Check segment ID in packet 20
                seg_id = (segment_data[20][0] >> 4) & 0x0F
                
                if 1 <= seg_id <= 4:
                    seg_idx = seg_id - 1
                    
                    if not segments_captured[seg_idx]:
                        # Verify the segment is perfectly sequential with no drops
                        is_valid = True
                        for row in range(60):
                            p_num = ((segment_data[row][0] & 0x0F) << 8) | segment_data[row][1]
                            if p_num != row:
                                is_valid = False
                                break
                                
                        if is_valid:
                            print(f"   ↳ Found valid Segment {seg_id}!")
                            
                            for row in range(60):
                                pixel_bytes = segment_data[row][4:]
                                pixels = (pixel_bytes[0::2] << 8) | pixel_bytes[1::2]
                                
                                actual_row = seg_idx * 30 + (row // 2)
                                col_offset = (row % 2) * 80
                                frame_buffer[actual_row, col_offset:col_offset+80] = pixels
                                
                            segments_captured[seg_idx] = True

    # 3. BUILD THE IMAGE
    if all(segments_captured):
        print("\n✅ Full 160x120 thermal frame constructed!")
        valid_pixels = frame_buffer[frame_buffer > 0]
        
        if len(valid_pixels) > 0:
            temp_max = (np.max(valid_pixels) / 100.0) - 273.15
            temp_min = (np.min(valid_pixels) / 100.0) - 273.15
            temp_avg = (np.mean(valid_pixels) / 100.0) - 273.15
            
            print(f"🌡️ Max: {temp_max:.2f}°C | Min: {temp_min:.2f}°C | Avg: {temp_avg:.2f}°C")
            
            frame_8bit = cv2.normalize(frame_buffer, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
            heatmap = cv2.applyColorMap(frame_8bit, cv2.COLORMAP_INFERNO)
            cv2.imwrite("thermal_test.jpg", heatmap)
            print("📸 Saved 'thermal_test.jpg'!")
    else:
        missing = [i+1 for i, found in enumerate(segments_captured) if not found]
        print(f"\n❌ Parse complete, but missing Segments: {missing}")
        print("The camera is likely doing a background calibration. Just run it again!")

if __name__ == "__main__":
    capture_lepton_sweep()