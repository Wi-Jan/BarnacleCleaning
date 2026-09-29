"""
Unit tests for the wire protocol implemented in GUI/gui.py.

The same protocol is implemented in C++ at OnboardSteppers_ESP2/protocol.h. If
either side ever drifts, these tests will catch it before the next firmware
flash — far cheaper than chasing a "robot won't move" bug on the dock.

Run:
    cd Coding
    python -m unittest tests.test_protocol -v
"""

from __future__ import annotations

import os
import sys
import unittest

# Make Coding/GUI/ importable so we can pull the protocol primitives out of gui.py
# without triggering the rest of its module-level side effects (pygame.init etc).
# We import only the pure functions by parsing a small subset — easier to just
# add GUI/ to path and pay the import cost.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "GUI"))

from gui import (  # noqa: E402
    CMD_DRIVE,
    CMD_DRUM,
    FRAME_H1,
    FRAME_H2,
    build_frame,
    crc8,
    trigger_to_pct,
)


class TestCRC8(unittest.TestCase):
    """CRC-8/SMBUS — polynomial 0x07, init 0x00, no reflection, no xorout.

    Matches the C++ implementation at OnboardSteppers_ESP2/protocol.h:16.
    """

    def test_empty_input_is_zero(self):
        self.assertEqual(crc8(b""), 0x00)

    def test_smbus_check_vector(self):
        # Standard SMBUS check value for the ASCII string "123456789".
        # Documented at https://reveng.sourceforge.io/crc-catalogue/all.htm
        self.assertEqual(crc8(b"123456789"), 0xF4)

    def test_single_byte(self):
        # 0x01 with poly 0x07: after XOR with crc=0, msb cleared 7 times,
        # leaves 0x07 in the last shift — known answer.
        self.assertEqual(crc8(b"\x01"), 0x07)

    def test_two_byte_drive_payload_zero(self):
        # CMD_DRIVE, len=2, payload (0, 0) — the failsafe-stop frame the GUI
        # sends on shutdown. Locked-in expected value: if this changes, the
        # ESP32_2 firmware will reject every frame after the change.
        body = bytes([CMD_DRIVE, 2, 0, 0])
        self.assertEqual(crc8(body), 0xC0)

    def test_idempotent(self):
        # Calling twice should not mutate any internal state.
        data = b"\xAA\x55\x01\x02\x03"
        self.assertEqual(crc8(data), crc8(data))


class TestBuildFrame(unittest.TestCase):
    """build_frame layout: H1 H2 CMD LEN PAYLOAD... CRC8(over CMD+LEN+PAYLOAD)."""

    def test_drive_frame_layout(self):
        # GUI sends drive frames at SEND_HZ; this is the canonical shape.
        f = build_frame(CMD_DRIVE, bytes([0x32, 0xCE]))  # +50, -50 as int8
        self.assertEqual(f[0], FRAME_H1)
        self.assertEqual(f[1], FRAME_H2)
        self.assertEqual(f[2], CMD_DRIVE)
        self.assertEqual(f[3], 2)
        self.assertEqual(f[4:6], b"\x32\xCE")
        self.assertEqual(f[6], crc8(bytes([CMD_DRIVE, 2, 0x32, 0xCE])))
        self.assertEqual(len(f), 7)

    def test_drum_off_frame(self):
        # 1-byte payload, the smallest non-empty frame.
        f = build_frame(CMD_DRUM, b"\x00")
        self.assertEqual(f[:4], bytes([FRAME_H1, FRAME_H2, CMD_DRUM, 1]))
        self.assertEqual(f[4], 0x00)
        self.assertEqual(f[5], crc8(bytes([CMD_DRUM, 1, 0x00])))
        self.assertEqual(len(f), 6)

    def test_drum_on_frame_differs_from_off(self):
        # CRC must change with payload — guards against a future refactor that
        # accidentally drops the payload from the CRC input.
        off = build_frame(CMD_DRUM, b"\x00")
        on = build_frame(CMD_DRUM, b"\x01")
        self.assertNotEqual(off[-1], on[-1])

    def test_empty_payload(self):
        # Reserved for ping/heartbeat frames; len=0 is valid.
        f = build_frame(0x03, b"")
        self.assertEqual(f, bytes([FRAME_H1, FRAME_H2, 0x03, 0, crc8(bytes([0x03, 0]))]))


class TestTriggerToPct(unittest.TestCase):
    """Xbox trigger axis: raw -1.0 (released) to +1.0 (fully pulled) → 0..100."""

    def test_fully_released(self):
        self.assertEqual(trigger_to_pct(-1.0), 0)

    def test_fully_pressed(self):
        self.assertEqual(trigger_to_pct(1.0), 100)

    def test_centre_is_half(self):
        # An axis sitting at exactly 0 normalises to 0.5 → 50.
        self.assertEqual(trigger_to_pct(0.0), 50)

    def test_below_deadzone_is_zero(self):
        # Anything mapping to < 5% must read as 0 — prevents trigger drift from
        # creeping the motors on when the user isn't touching the controller.
        # x = (-0.91 + 1)/2 = 0.045  → below 0.05 deadzone → 0.
        self.assertEqual(trigger_to_pct(-0.91), 0)

    def test_just_above_deadzone(self):
        # Use values that the IEEE-754 round-trip preserves exactly so the test
        # doesn't depend on float-representation quirks. -0.8 → x = 0.1 → 10.
        self.assertEqual(trigger_to_pct(-0.8), 10)

    def test_monotonic(self):
        # The mapping must never decrease as the input grows.
        last = -1
        for i in range(-100, 101):
            v = trigger_to_pct(i / 100.0)
            self.assertGreaterEqual(v, last)
            last = v

    def test_output_bounded(self):
        for raw in (-1.0, -0.5, 0.0, 0.5, 1.0):
            v = trigger_to_pct(raw)
            self.assertGreaterEqual(v, 0)
            self.assertLessEqual(v, 100)


if __name__ == "__main__":
    unittest.main()
