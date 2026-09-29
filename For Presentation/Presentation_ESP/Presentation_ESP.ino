#include "protocol.h"

// --- Stepper pins ---
static const int PIN_L_PUL = 25, PIN_L_DIR = 26;
static const int PIN_R_PUL = 33, PIN_R_DIR = 32;   // moved off 27/14 — wire those if you prefer

// --- Motion ---
// Nema 23 1.8°/step = 200 steps/rev (without microstepping).
// MAX_SPS is the step rate at 100% throttle. Lower this if the motor stalls.
// 800 sps is a safe starting point; increase later once it's spinning reliably.
static const uint32_t MAX_SPS = 800;

static const uint32_t BAUD = 115200;

// --- Side state ---
struct Side {
  int pulPin;
  int dirPin;
  int32_t stepInterval_us;     // 0 = stopped; otherwise half-period between toggles
  bool dirHigh;
  uint32_t lastEdgeUs;
  bool pulHigh;
};
Side L{PIN_L_PUL, PIN_L_DIR, 0, false, 0, false};
Side R{PIN_R_PUL, PIN_R_DIR, 0, false, 0, false};

uint32_t lastRxMs = 0;

// ---------- USB-CDC RX frame parser ----------
enum RxState : uint8_t { WAIT_H1, WAIT_H2, READ_CMD, READ_LEN, READ_PAYLOAD, READ_CRC };
RxState rxState = WAIT_H1;
uint8_t rxCmd = 0, rxLen = 0, rxIdx = 0;
uint8_t rxPayload[32];

void setSideSpeed(Side& s, int8_t pct) {
  if (pct == 0) { s.stepInterval_us = 0; return; }
  bool reverse = (pct < 0);
  int mag = pct < 0 ? -pct : pct;
  uint32_t sps = (uint32_t)mag * MAX_SPS / 100;
  s.stepInterval_us = (int32_t)(1000000UL / (sps * 2));
  s.dirHigh = reverse;
  digitalWrite(s.dirPin, s.dirHigh ? HIGH : LOW);
}

void setDrive(int8_t leftPct, int8_t rightPct) {
  // Both motors act as a single side. Use whichever input has the larger
  // magnitude so any control (LT, RT, LB, RB, arrow keys, W/S) drives them.
  int al = leftPct  < 0 ? -leftPct  : leftPct;
  int ar = rightPct < 0 ? -rightPct : rightPct;
  int8_t v = (al >= ar) ? leftPct : rightPct;
  setSideSpeed(L, v);
  setSideSpeed(R, v);
}

void handleFrame(uint8_t cmd, const uint8_t* p, uint8_t len) {
  lastRxMs = millis();
  if (cmd == CMD_DRIVE && len == 2) {
    setDrive((int8_t)p[0], (int8_t)p[1]);
    // Echo back over USB so the GUI can confirm reception.
    Serial.print("DRIVE L="); Serial.print((int)(int8_t)p[0]);
    Serial.print(" R=");      Serial.println((int)(int8_t)p[1]);
  }
  // CMD_DRUM / CMD_PING ignored in this build.
}

void serialPoll() {
  while (Serial.available()) {
    uint8_t b = (uint8_t)Serial.read();
    switch (rxState) {
      case WAIT_H1:  rxState = (b == FRAME_H1) ? WAIT_H2 : WAIT_H1; break;
      case WAIT_H2:  rxState = (b == FRAME_H2) ? READ_CMD : WAIT_H1; break;
      case READ_CMD: rxCmd = b; rxState = READ_LEN; break;
      case READ_LEN:
        rxLen = b; rxIdx = 0;
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

// ---------- Step generator (non-blocking pulse toggling) ----------
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
  tickSide(L, now);
  tickSide(R, now);
}

// ---------- Arduino ----------
void setup() {
  int pins[] = {PIN_L_PUL, PIN_L_DIR, PIN_R_PUL, PIN_R_DIR};
  for (int p : pins) { pinMode(p, OUTPUT); digitalWrite(p, LOW); }

  Serial.begin(BAUD);
  delay(200);
  Serial.println("Presentation_ESP ready.");
}

void loop() {
  serialPoll();
  stepGenerator();

  // Failsafe: if no command for 500 ms, stop both motors.
  if (millis() - lastRxMs > 500) {
    setDrive(0, 0);
  }
}
