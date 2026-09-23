"""
FLIR Lepton 3.5 – Real-Time Thermal Viewer  v5
Hardware : Lepton 3.5 + PureThermal Breakout Board V2
Platform : Raspberry Pi 5
"""

import os, sys, time, argparse
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
os.environ.setdefault("DISPLAY", ":0")
os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.qpa.*=false"

import cv2

try:
    import spidev
    import RPi.GPIO as GPIO
    ON_PI = True
except ImportError:
    ON_PI = False
    print("[WARN] spidev/RPi.GPIO missing – DEMO mode")

# ── Config (edit here) ─────────────────────────────────────────────────────────
SPI_BUS      = 0
SPI_DEVICE   = 0
SPI_SPEED_HZ = 16_000_000
SPI_MODE     = 0b11   # mode 3: CPOL=1, CPHA=1

RST_PIN      = 23     # BCM GPIO → /RESET on Breakout V2

DISPLAY_SCALE = 4
WINDOW_TITLE  = "FLIR Lepton 3.5"

COLORMAPS = [
    ("INFERNO", cv2.COLORMAP_INFERNO),
    ("JET",     cv2.COLORMAP_JET),
    ("HOT",     cv2.COLORMAP_HOT),
    ("PLASMA",  cv2.COLORMAP_PLASMA),
    ("BONE",    cv2.COLORMAP_BONE),
    ("RAINBOW", cv2.COLORMAP_RAINBOW),
]

# ── VOSPI geometry (Lepton 3.5 datasheet) ─────────────────────────────────────
# 4 segments × 60 packets × 164 bytes
# Each packet: 4 header bytes + 160 payload bytes = 80 uint16 pixels (half-row)
# Segment → frame mapping:
#   seg 1 → rows  0-59,  cols   0-79
#   seg 2 → rows  0-59,  cols  80-159
#   seg 3 → rows 60-119, cols   0-79
#   seg 4 → rows 60-119, cols  80-159
PACKET_SIZE  = 164
PKTS_PER_SEG = 60
HALF_COLS    = 80
FRAME_ROWS   = 120
FRAME_COLS   = 160

SEG_ROW = {1: 0,  2: 0,  3: 60, 4: 60}
SEG_COL = {1: 0,  2: 80, 3: 0,  4: 80}


# ── SPI / GPIO ─────────────────────────────────────────────────────────────────

def init_gpio():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(RST_PIN, GPIO.OUT, initial=GPIO.HIGH)


def open_spi():
    spi = spidev.SpiDev()
    spi.open(SPI_BUS, SPI_DEVICE)
    spi.max_speed_hz  = SPI_SPEED_HZ
    spi.mode          = SPI_MODE
    spi.bits_per_word = 8
    return spi


def cs_deassert(spi):
    """Close/reopen SPI to release CS for ≥185 ms (VOSPI resync)."""
    spi.close()
    time.sleep(0.200)
    spi.open(SPI_BUS, SPI_DEVICE)
    spi.max_speed_hz  = SPI_SPEED_HZ
    spi.mode          = SPI_MODE
    spi.bits_per_word = 8


def hard_reset(spi):
    print("[INFO] Hard reset …")
    GPIO.output(RST_PIN, GPIO.LOW)
    time.sleep(0.1)
    GPIO.output(RST_PIN, GPIO.HIGH)
    time.sleep(0.3)
    cs_deassert(spi)
    time.sleep(0.3)


# ── Packet helpers ─────────────────────────────────────────────────────────────

def read_packet(spi):
    data = spi.readbytes(PACKET_SIZE)
    return data if len(data) == PACKET_SIZE else None


def pkt_num(pkt):
    return ((pkt[0] & 0x0F) << 8) | pkt[1]


def is_discard(pkt):
    return (pkt[0] & 0xF0) == 0xF0


def pkt_segment(pkt):
    """TTT field in byte 0 bits[6:4], valid only on packet 20."""
    if pkt_num(pkt) != 20:
        return 0
    seg = (pkt[0] >> 4) & 0x07
    return seg if 1 <= seg <= 4 else 0


def decode_pixels(pkt):
    return np.frombuffer(bytes(pkt[4:4 + HALF_COLS * 2]), dtype=">u2").astype(np.uint16)


# ── VOSPI frame reader ─────────────────────────────────────────────────────────

def read_frame(spi):
    frame    = np.zeros((FRAME_ROWS, FRAME_COLS), dtype=np.uint16)
    seg_done = [False] * 5   # 1-indexed

    current_seg  = 0
    in_seg       = False
    row_idx      = 0
    seg_fallback = 0

    for _ in range(PKTS_PER_SEG * 4 * 12):
        pkt = read_packet(spi)
        if pkt is None:
            continue
        if is_discard(pkt):
            in_seg = False
            continue

        num = pkt_num(pkt)

        if num == 0:
            seg_fallback += 1
            current_seg   = seg_fallback
            in_seg        = True
            row_idx       = 0

        if not in_seg:
            continue

        if num == 20:
            ttt = pkt_segment(pkt)
            if ttt != 0:
                current_seg  = ttt
                seg_fallback = ttt

        if num != row_idx:
            in_seg = False
            continue

        if 1 <= current_seg <= 4:
            r0 = SEG_ROW[current_seg]
            c0 = SEG_COL[current_seg]
            dr = r0 + row_idx
            if 0 <= dr < FRAME_ROWS:
                frame[dr, c0:c0 + HALF_COLS] = decode_pixels(pkt)

        row_idx += 1

        if row_idx == PKTS_PER_SEG:
            in_seg = False
            if 1 <= current_seg <= 4:
                seg_done[current_seg] = True
            if all(seg_done[1:5]):
                return frame

    return None


# ── Diagnostic ─────────────────────────────────────────────────────────────────

def run_diagnostic(spi, n=240):
    print(f"\n[DIAG] Reading {n} raw packets …\n")
    print(f"{'#':>5}  {'num':>5}  {'discard':>7}  {'seg(TTT)':>8}  {'px[0]':>7}  {'px[1]':>7}")
    print("-" * 58)
    for i in range(n):
        pkt = read_packet(spi)
        if pkt is None:
            print(f"{i:5d}  SHORT READ")
            continue
        num  = pkt_num(pkt)
        disc = is_discard(pkt)
        ttt  = pkt_segment(pkt)
        px   = decode_pixels(pkt)
        print(f"{i:5d}  {num:5d}  {str(disc):>7}  {ttt:>8}  {px[0]:>7}  {px[1]:>7}")
    print("\n[DIAG] Done – paste this output to diagnose sync issues.")


# ── Demo ───────────────────────────────────────────────────────────────────────

def demo_frame(tick):
    x  = np.linspace(0, np.pi*2, FRAME_COLS)
    y  = np.linspace(0, np.pi*2, FRAME_ROWS)
    xx, yy = np.meshgrid(x, y)
    d  = np.sin(xx + tick*0.05) + np.cos(yy*0.5 + tick*0.03)
    d  = (d - d.min()) / (d.max() - d.min() + 1e-9)
    return (d * 8000 + 7500).astype(np.uint16)


# ── Rendering ──────────────────────────────────────────────────────────────────

def to_display(raw, cmap_idx):
    lo, hi = raw.min(), raw.max()
    if hi == lo: hi = lo + 1
    norm     = ((raw.astype(np.float32) - lo) / (hi - lo) * 255).astype(np.uint8)
    coloured = cv2.applyColorMap(norm, COLORMAPS[cmap_idx][1])
    h, w     = coloured.shape[:2]
    return cv2.resize(coloured, (w * DISPLAY_SCALE, h * DISPLAY_SCALE),
                      interpolation=cv2.INTER_NEAREST)


def draw_overlay(img, raw, cmap_name, fps, fails):
    h, w   = img.shape[:2]
    cy, cx = raw.shape[0]//2, raw.shape[1]//2
    cval   = int(raw[cy, cx])
    ch, cw2 = cy*DISPLAY_SCALE, cx*DISPLAY_SCALE

    cv2.line(img,   (cw2-14, ch),  (cw2+14, ch),  (255,255,255), 1)
    cv2.line(img,   (cw2, ch-14),  (cw2, ch+14),  (255,255,255), 1)
    cv2.circle(img, (cw2, ch), 6,  (255,255,255),  1)

    font  = cv2.FONT_HERSHEY_SIMPLEX
    lines = ["FLIR Lepton 3.5", f"Map:{cmap_name}", f"FPS:{fps:5.1f}",
             f"Min:{int(raw.min())}", f"Max:{int(raw.max())}", f"Ctr:{cval}"]
    if fails:
        lines.append(f"!! SYNC FAIL x{fails}")
    for i, txt in enumerate(lines):
        y = 22 + i*22
        cv2.putText(img, txt, (8,y), font, 0.52, (0,0,0),     2, cv2.LINE_AA)
        cv2.putText(img, txt, (8,y), font, 0.52, (255,255,255),1, cv2.LINE_AA)

    hint = "[C] colormap  [S] save  [Q/ESC] quit"
    cv2.putText(img, hint, (8,h-8), font, 0.42, (0,0,0),     2, cv2.LINE_AA)
    cv2.putText(img, hint, (8,h-8), font, 0.42, (180,180,180),1, cv2.LINE_AA)
    return img


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # global must appear before any reference to SPI_SPEED_HZ in this scope
    global SPI_SPEED_HZ

    parser = argparse.ArgumentParser()
    parser.add_argument("--diag",  action="store_true",
                        help="Dump raw packet metadata and exit")
    parser.add_argument("--speed", type=int, default=SPI_SPEED_HZ,
                        help=f"SPI speed Hz (default {SPI_SPEED_HZ})")
    args = parser.parse_args()

    SPI_SPEED_HZ = args.speed   # safe: global declared above

    print("=" * 55)
    print("  FLIR Lepton 3.5  v5 –", "Raspberry Pi 5" if ON_PI else "DEMO MODE")
    print(f"  SPI speed: {SPI_SPEED_HZ // 1_000_000} MHz")
    print("=" * 55)

    spi  = None
    fails = 0

    if ON_PI:
        init_gpio()
        spi = open_spi()
        hard_reset(spi)
        print(f"[OK] SPI bus={SPI_BUS} dev={SPI_DEVICE} "
              f"@ {SPI_SPEED_HZ//1_000_000} MHz | mode={SPI_MODE}")

        if args.diag:
            run_diagnostic(spi)
            spi.close()
            GPIO.cleanup()
            return
    else:
        if args.diag:
            print("[DIAG] Not on Pi – nothing to diagnose.")
            return
        print("[INFO] Demo mode")

    cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_AUTOSIZE)

    cmap_idx    = 0
    fps         = 0.0
    frame_count = 0
    t0          = time.time()
    tick        = 0
    shot_n      = 0

    print("\nControls: [C] colormap | [S] screenshot | [Q/ESC] quit")
    print("[INFO] Waiting for first frame …\n")

    try:
        while True:
            if ON_PI:
                raw = read_frame(spi)
                if raw is None:
                    fails += 1
                    print(f"[WARN] No frame (streak={fails})")
                    cs_deassert(spi)
                    if fails % 3 == 0:
                        hard_reset(spi)
                    if fails > 10:
                        print("\n[ERROR] Cannot sync after 10 attempts.")
                        print("  → Run:  python lepton_viewer.py --diag")
                        print("  → Try:  python lepton_viewer.py --speed 10000000")
                        break
                    continue
                fails = 0
            else:
                raw  = demo_frame(tick)
                tick += 1
                time.sleep(0.04)

            disp = to_display(raw, cmap_idx)
            disp = draw_overlay(disp, raw, COLORMAPS[cmap_idx][0], fps, fails)
            cv2.imshow(WINDOW_TITLE, disp)

            frame_count += 1
            elapsed = time.time() - t0
            if elapsed >= 1.0:
                fps = frame_count / elapsed
                frame_count = 0
                t0 = time.time()

            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                print("[INFO] Quit.")
                break
            elif key == ord('c'):
                cmap_idx = (cmap_idx + 1) % len(COLORMAPS)
                print(f"[INFO] Colormap → {COLORMAPS[cmap_idx][0]}")
            elif key == ord('s'):
                fname = f"thermal_{shot_n:04d}.png"
                cv2.imwrite(fname, disp)
                print(f"[INFO] Saved {fname}")
                shot_n += 1

    except KeyboardInterrupt:
        print("\n[INFO] Interrupted.")
    finally:
        cv2.destroyAllWindows()
        if spi:
            spi.close()
        if ON_PI:
            GPIO.cleanup()
        print("[INFO] Clean shutdown.")


if __name__ == "__main__":
    main()``