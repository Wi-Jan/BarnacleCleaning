// ESP32_2 (onboard) — receives RS485 drive commands, drives 4x TB6600 steppers,
// forwards drum on/off to ESP32_3 over I2C.
//
// ═══════════════════════════════════════════════════════════════════════════
//  PHYSICAL WIRING — what to connect to what
// ═══════════════════════════════════════════════════════════════════════════
//
// MAX485 transceiver (onboard one, inside the ROV):
//
//   ESP32 dev-board pin (silkscreen) → MAX485 module pin (printed label)
//   ──────────────────────────────────────────────────────────────────────
//   TX2  (= GPIO17)                  →  "DI"   (data into transceiver)
//   RX2  (= GPIO16)                  ←  "RO"   (THROUGH voltage divider!)
//   D4   (= GPIO4)                   →  "DE"  AND  "RE"  (tie together)
//   5V                               →  "VCC"
//   GND                              →  "GND"
//
//   MAX485 "A" ──► tether conductor up to topside MAX485 "A"
//   MAX485 "B" ──► tether conductor up to topside MAX485 "B"
//
//   ⚠ Voltage divider on RO line (3x 4.7kΩ resistors):
//      MAX485 "RO" ──[4.7k]──┬── ESP32 GPIO16
//                            │
//                          [4.7k]
//                            │
//                          [4.7k]
//                            │
//                           GND
//      Output at the junction = 3.33V (safe for ESP32 GPIO).
//
// I²C bus (to ESP32_3, the drum board):
//
//   This ESP32_2 pin (silkscreen) ◄──► That ESP32_3 pin (silkscreen)
//   ──────────────────────────────────────────────────────────────────
//   D21  (= GPIO21)               ◄──► D21  (= GPIO21)    [SDA — data]
//   D22  (= GPIO22)               ◄──► D22  (= GPIO22)    [SCL — clock]
//   GND                           ──── GND                [shared ground]
//
// Stepper drivers (TB6600 — one per wheel, four total):
//   Each TB6600 module has signal-side terminals labelled:
//     PUL+, PUL-, DIR+, DIR-, ENA+, ENA-
//   We drive the "+" terminals from ESP32 GPIOs and tie the "-" terminals to
//   ESP32 GND (common-cathode wiring). ENA is left unconnected (driver defaults
//   to enabled).
//
//   Dev-board silkscreen pin → TB6600 terminal       Wheel position
//   ──────────────────────────────────────────────────────────────────
//   D25 (= GPIO25)  →  TB6600 #1 PUL+                 \
//   D26 (= GPIO26)  →  TB6600 #1 DIR+                 / Front-Left
//
//   D27 (= GPIO27)  →  TB6600 #2 PUL+                 \
//   D14 (= GPIO14)  →  TB6600 #2 DIR+                 / Rear-Left
//
//   D19 (= GPIO19)  →  TB6600 #3 PUL+                 \
//   D18 (= GPIO18)  →  TB6600 #3 DIR+                 / Front-Right
//
//   D5  (= GPIO5)   →  TB6600 #4 PUL+                 \
//   D33 (= GPIO33)  →  TB6600 #4 DIR+                 / Rear-Right
//
//   ALL TB6600 PUL- and DIR-  ──► ESP32 GND
//
//   Motor-side terminals on each TB6600 (A+ A- B+ B-, plus VCC/GND) go to the
//   stepper coils and the 24V motor supply — that's hardware wiring, not code.
//
// ═══════════════════════════════════════════════════════════════════════════

#include <Wire.h>
#include "protocol.h"

// ─── Stepper driver GPIOs ──────────────────────────────────────────────────
// Format below: GPIO number (= dev-board silkscreen label) → TB6600 terminal
static const int PIN_TB1_PUL = 25, PIN_TB1_DIR = 26;   // D25→#1 PUL+,  D26→#1 DIR+  (Front-Left)
static const int PIN_TB2_PUL = 27, PIN_TB2_DIR = 14;   // D27→#2 PUL+,  D14→#2 DIR+  (Rear-Left)
static const int PIN_TB3_PUL = 19, PIN_TB3_DIR = 18;   // D19→#3 PUL+,  D18→#3 DIR+  (Front-Right)
static const int PIN_TB4_PUL = 5,  PIN_TB4_DIR = 33;   // D5 →#4 PUL+,  D33→#4 DIR+  (Rear-Right)
// All PUL- and DIR- terminals tie to ESP32 GND.

// ─── MAX485 transceiver GPIOs ──────────────────────────────────────────────
static const int PIN_RS485_RX    = 16;   // dev-board "RX2"  → MAX485 "RO" (through voltage divider!)
static const int PIN_RS485_TX    = 17;   // dev-board "TX2"  → MAX485 "DI"
static const int PIN_RS485_DE_RE = 4;    // dev-board "D4"   → MAX485 "DE" AND "RE" (tied together)
static const uint32_t RS485_BAUD = 115200;

// ─── I²C bus GPIOs (to ESP32_3) ────────────────────────────────────────────
static const int PIN_I2C_SDA = 21;       // dev-board "D21"  → ESP32_3 "D21" (SDA — data)
static const int PIN_I2C_SCL = 22;       // dev-board "D22"  → ESP32_3 "D22" (SCL — clock)
static const uint8_t I2C_ADDR_DC = 0x10; // ESP32_3 listens at this I²C address

// --- Motion ---
// Capped at 1600 SPS because at 2000 SPS the motors lose torque under load and
// stall for ~0.5 s before catching up. 1600 SPS = the highest rate that ran
// smoothly on bench tests (matches what 80% on the GUI used to feel like).
// If you ever upgrade to higher-torque motors or add acceleration ramping,
// raise this back toward 2000.
static const uint32_t MAX_SPS = 1600;

// --- State ---
struct Side {
  int pulPin;
  int dirPin;
  bool invertDir;
  volatile int32_t stepInterval_us;
  volatile bool dirHigh;
  uint32_t lastEdgeUs;
  bool pulHigh;
};
// Set invertDir=true on any motor whose wiring/mounting spins the wrong way
// relative to its side mate. Flip the flag, reflash, retest.
// Flipped AGAIN — different replacement ESP32 / different DIP positions made
// the previous convention go backward. Relative inversion between L1↔L2 and
// L↔R is still preserved (each pair still differs), so per-motor compensation
// still holds.
Side L1{PIN_TB1_PUL, PIN_TB1_DIR, false, 0, false, 0, false};   // Front-Left
Side L2{PIN_TB2_PUL, PIN_TB2_DIR, true,  0, false, 0, false};   // Rear-Left   (motor flipped on mount)
Side R1{PIN_TB3_PUL, PIN_TB3_DIR, true,  0, false, 0, false};   // Front-Right (side mirrors left)
Side R2{PIN_TB4_PUL, PIN_TB4_DIR, true,  0, false, 0, false};   // Rear-Right  (side mirrors left)

bool drumOn = false;
bool lastDrumSent = false;
uint32_t lastRxMs = 0;

// Failsafe: motors stop if no valid frame in this window.
// At SEND_HZ=50 the GUI sends every 20 ms; 250 ms tolerates ~12 missed frames
// (bursty USB hiccup, brief topside-bridge stall) before braking.
static const uint32_t RX_TIMEOUT_MS = 250;

// ---------- RS485 RX ----------
enum RxState : uint8_t { WAIT_H1, WAIT_H2, READ_CMD, READ_LEN, READ_PAYLOAD, READ_CRC };
RxState rxState = WAIT_H1;
uint8_t rxCmd = 0, rxLen = 0, rxIdx = 0;
uint8_t rxPayload[32];

// Send a short debug line back up the tether (over Serial2 / RS485).
// Topside ESP32_1 bridges these bytes to laptop USB.
void debugBack(const char* s) {
  digitalWrite(PIN_RS485_DE_RE, HIGH);
  Serial2.print(s);
  Serial2.flush();
  delayMicroseconds(50);
  digitalWrite(PIN_RS485_DE_RE, LOW);
}

void handleFrame(uint8_t cmd, const uint8_t* p, uint8_t len) {
  lastRxMs = millis();
  switch (cmd) {
    case CMD_DRIVE:
      // No debugBack here — would block ~1.7 ms every 20 ms (50 Hz GUI rate)
      // and starve the step-pulse generator, causing asymmetric motor speeds.
      if (len == 2) setDrive((int8_t)p[0], (int8_t)p[1]);
      break;
    case CMD_DRUM:
      // GUI sends CMD_DRUM every frame at 50 Hz, not just on button press.
      // Only debug-print when the state ACTUALLY changes, otherwise the log
      // gets spammed and the RS485 bus stays busy with redundant traffic.
      if (len == 1) {
        bool newDrum = (p[0] != 0);
        if (newDrum != drumOn) {
          drumOn = newDrum;
          debugBack(drumOn ? "DRUM ON\n" : "DRUM OFF\n");
        }
      }
      break;
  }
}

void rs485Poll() {
  while (Serial2.available()) {
    uint8_t b = (uint8_t)Serial2.read();
    switch (rxState) {
      case WAIT_H1:       rxState = (b == FRAME_H1) ? WAIT_H2 : WAIT_H1; break;
      case WAIT_H2:       rxState = (b == FRAME_H2) ? READ_CMD : WAIT_H1; break;
      case READ_CMD:      rxCmd = b; rxState = READ_LEN; break;
      case READ_LEN:
        rxLen = b;
        rxIdx = 0;
        rxState = (rxLen == 0) ? READ_CRC : READ_PAYLOAD;
        if (rxLen > sizeof(rxPayload)) rxState = WAIT_H1;
        break;
      case READ_PAYLOAD:
        rxPayload[rxIdx++] = b;
        if (rxIdx >= rxLen) rxState = READ_CRC;
        break;
      case READ_CRC: {
        uint8_t hdr[2 + 32];
        hdr[0] = rxCmd; hdr[1] = rxLen;
        for (uint8_t i = 0; i < rxLen; ++i) hdr[2 + i] = rxPayload[i];
        if (crc8(hdr, 2 + rxLen) == b) handleFrame(rxCmd, rxPayload, rxLen);
        rxState = WAIT_H1;
        break;
      }
    }
  }
}

// ---------- Motion ----------
void setSideSpeed(Side& s, int8_t pct) {
  bool reverse = (pct < 0);
  int mag = abs(pct);
  if (mag == 0) {
    s.stepInterval_us = 0;
    return;
  }
  uint32_t sps = (uint32_t)mag * MAX_SPS / 100;
  s.stepInterval_us = (int32_t)(1000000UL / (sps * 2));
  s.dirHigh = reverse ^ s.invertDir;
  digitalWrite(s.dirPin, s.dirHigh ? HIGH : LOW);
}

void setDrive(int8_t leftPct, int8_t rightPct) {
  setSideSpeed(L1, leftPct);
  setSideSpeed(L2, leftPct);
  setSideSpeed(R1, rightPct);
  setSideSpeed(R2, rightPct);
}

inline void tickSide(Side& s, uint32_t nowUs) {
  if (s.stepInterval_us == 0) return;
  if ((int32_t)(nowUs - s.lastEdgeUs) >= s.stepInterval_us) {
    s.lastEdgeUs = nowUs;
    s.pulHigh = !s.pulHigh;
    digitalWrite(s.pulPin, s.pulHigh ? HIGH : LOW);
  }
}

void stepGenerator() {
  uint32_t now = micros();
  tickSide(L1, now);
  tickSide(L2, now);
  tickSide(R1, now);
  tickSide(R2, now);
}

// ---------- I2C to ESP32_3 ----------
// Always send the current drum byte. ESP32_3 has a 1 s watchdog that disarms
// the drum if no I2C traffic arrives; the periodic heartbeat below keeps it
// alive, and a zero-byte ping would NOT (onReceive doesn't fire for n=0).
void sendDrumState() {
  Wire.beginTransmission(I2C_ADDR_DC);
  Wire.write(drumOn ? 1 : 0);
  if (Wire.endTransmission() == 0) lastDrumSent = drumOn;
}

// ---------- Arduino ----------
void setup() {
  // Stepper pins as outputs, all LOW.
  int pins[] = {PIN_TB1_PUL, PIN_TB1_DIR, PIN_TB2_PUL, PIN_TB2_DIR,
                PIN_TB3_PUL, PIN_TB3_DIR, PIN_TB4_PUL, PIN_TB4_DIR};
  for (int p : pins) { pinMode(p, OUTPUT); digitalWrite(p, LOW); }

  // RS485 direction pin: start in receive mode.
  pinMode(PIN_RS485_DE_RE, OUTPUT);
  digitalWrite(PIN_RS485_DE_RE, LOW);

  // USB serial: free for optional debug prints to laptop (Serial.print works normally).
  Serial.begin(115200);

  // RS485 on UART2 (D16 RX from MAX485 RO, D17 TX to MAX485 DI).
  Serial2.begin(115200, SERIAL_8N1, PIN_RS485_RX, PIN_RS485_TX);

  // I2C master.
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setClock(100000);

  Serial.println("ESP32_2 ready. RS485 on UART2 (D16/D17). Drum I2C addr 0x10.");
}

void loop() {
  rs485Poll();
  stepGenerator();

  // Failsafe: if no command in RX_TIMEOUT_MS, stop motors and turn drum off.
  if (millis() - lastRxMs > RX_TIMEOUT_MS) {
    setDrive(0, 0);
    drumOn = false;
  }

  // Heartbeat I2C to ESP32_3 every 200 ms — keeps its watchdog fed and
  // doubles as STATUS evidence (we forward the ack result up the tether
  // at a slower 2 Hz rate so the GUI's board-health dot still updates).
  static uint32_t lastDrumPoll = 0;
  static bool lastAckOk = true;
  if (millis() - lastDrumPoll > 200) {
    lastDrumPoll = millis();
    Wire.beginTransmission(I2C_ADDR_DC);
    Wire.write(drumOn ? 1 : 0);
    lastAckOk = (Wire.endTransmission() == 0);
    if (lastAckOk) lastDrumSent = drumOn;
  }

  // STATUS message at 2 Hz (was 1 Hz) — slow enough that the ~1.7 ms RS485
  // write doesn't disturb the step generator noticeably.
  static uint32_t lastStatusMs = 0;
  if (millis() - lastStatusMs > 500) {
    lastStatusMs = millis();
    debugBack(lastAckOk ? "STATUS i2c=OK\n" : "STATUS i2c=FAIL\n");
  }
}
