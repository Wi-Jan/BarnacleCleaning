"""
Laptop-side Xbox controller -> serial bridge to ESP32_1 (topside).

Requirements:
    pip install pygame pyserial

Mapping (tank drive):
    LT (analog 0..1)  -> left side forward 0..100%
    LB (button)       -> left side backward 100%   (overrides LT if both held)
    RT (analog 0..1)  -> right side forward 0..100%
    RB (button)       -> right side backward 100%
    A button          -> toggle drum on/off
    Back/Select       -> emergency stop (zeroes everything until released)

Frame format (matches protocol.h on the ESP32 side):
    0xAA 0x55 CMD LEN PAYLOAD... CRC8(poly=0x07, init=0x00, over CMD+LEN+PAYLOAD)

Run:
    python xbox_control.py COM5          # Windows
    python xbox_control.py /dev/ttyUSB0  # Linux
"""

import sys
import time
import struct
import pygame
import serial
import serial.tools.list_ports

# ----- Constants (match protocol.h) -----
FRAME_H1  = 0xAA
FRAME_H2  = 0x55
CMD_DRIVE = 0x01
CMD_DRUM  = 0x02

SEND_HZ = 50

# ----- Xbox axis/button indices (pygame on Windows; check with --probe if odd) -----
AXIS_LT = 4
AXIS_RT = 5
BTN_A   = 0
BTN_LB  = 4
BTN_RB  = 5
BTN_ESTOP = 1     # B button — emergency stop

# ----- Helpers -----
def crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc

def build_frame(cmd: int, payload: bytes) -> bytes:
    body = bytes([cmd, len(payload)]) + payload
    return bytes([FRAME_H1, FRAME_H2]) + body + bytes([crc8(body)])

def auto_pick_port():
    """Find a likely ESP32 USB-serial port. Returns COMx string or None."""
    ports = list(serial.tools.list_ports.comports())
    # Keywords seen in ESP32 dev boards' VID/PID descriptions.
    keywords = ("CP210", "CH340", "CH343", "Silicon Labs", "USB-SERIAL", "USB-Enhanced-SERIAL")
    matches = [p.device for p in ports
               if any(k.lower() in (p.description or "").lower() for k in keywords)
               or any(k.lower() in (p.manufacturer or "").lower() for k in keywords)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print("Multiple ESP32-like ports found:")
        for i, m in enumerate(matches):
            print(f"  [{i}] {m}")
        print("Pass one explicitly: python xbox_control.py COMx")
        return None
    return None

def trigger_to_pct(v: float) -> int:
    # pygame triggers usually report -1 (released) .. +1 (full). Normalize to 0..1.
    x = (v + 1.0) * 0.5
    if x < 0.05:
        return 0
    return int(round(x * 100))

# ----- Probe mode for figuring out axis/button indices on your specific setup -----
def probe(joy):
    print("Press buttons / move triggers. Ctrl+C to exit.")
    pygame.event.pump()
    while True:
        pygame.event.pump()
        axes = [round(joy.get_axis(i), 2) for i in range(joy.get_numaxes())]
        btns = [joy.get_button(i) for i in range(joy.get_numbuttons())]
        print(f"axes={axes}  btns={btns}", end="\r")
        time.sleep(0.05)

# ----- Main loop -----
def main():
    probe_mode = "--probe" in sys.argv

    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("No joystick detected. Plug in the Xbox controller and try again.")
        sys.exit(1)
    joy = pygame.joystick.Joystick(0)
    joy.init()
    print(f"Connected: {joy.get_name()}  axes={joy.get_numaxes()}  btns={joy.get_numbuttons()}")

    if probe_mode:
        probe(joy)
        return

    if len(sys.argv) >= 2 and not sys.argv[1].startswith("--"):
        port_name = sys.argv[1]
    else:
        port_name = auto_pick_port()
        if port_name is None:
            print("No ESP32-like serial port found. Plug ESP32_1 in, or pass the COM port explicitly:")
            print("    python xbox_control.py COM5")
            sys.exit(1)
        print(f"Auto-selected port: {port_name}")

    ser = serial.Serial(port_name, 115200, timeout=0)
    time.sleep(2.0)   # let ESP32 reset after opening port
    print(f"Sending to {port_name} at 115200 baud.")

    last_a = False
    drum = False
    period = 1.0 / SEND_HZ

    try:
        while True:
            t0 = time.time()
            pygame.event.pump()

            estop = bool(joy.get_button(BTN_ESTOP))

            lt = trigger_to_pct(joy.get_axis(AXIS_LT))
            rt = trigger_to_pct(joy.get_axis(AXIS_RT))
            lb = joy.get_button(BTN_LB)
            rb = joy.get_button(BTN_RB)

            left  = lt - (100 if lb else 0)
            right = rt - (100 if rb else 0)
            left  = max(-100, min(100, left))
            right = max(-100, min(100, right))

            if estop:
                left = right = 0
                drum = False

            a_now = bool(joy.get_button(BTN_A))
            if a_now and not last_a and not estop:
                drum = not drum
            last_a = a_now

            # DRIVE: two signed 8-bit values
            ser.write(build_frame(CMD_DRIVE, struct.pack("bb", left, right)))
            # DRUM: one byte
            ser.write(build_frame(CMD_DRUM, bytes([1 if drum else 0])))

            # Drain any text echoed back from ESP32_2 (debugBack lines).
            incoming = ser.read(256)
            if incoming:
                try:
                    sys.stdout.write(incoming.decode("utf-8", errors="replace"))
                    sys.stdout.flush()
                except Exception:
                    pass

            print(f"L={left:+4d}  R={right:+4d}  drum={'ON ' if drum else 'off'}  estop={estop}", end="\r")

            # Pace to SEND_HZ.
            dt = time.time() - t0
            if dt < period:
                time.sleep(period - dt)
    except KeyboardInterrupt:
        print("\nStopping. Sending zero...")
        ser.write(build_frame(CMD_DRIVE, struct.pack("bb", 0, 0)))
        ser.write(build_frame(CMD_DRUM, bytes([0])))
        ser.close()

if __name__ == "__main__":
    main()
