// ESP32_3 (onboard) — I2C slave. Receives 1 byte from ESP32_2:
//   0 = drum OFF, 1 = drum ON.
//
// ═══════════════════════════════════════════════════════════════════════════
//  PHYSICAL WIRING — what to connect to what
// ═══════════════════════════════════════════════════════════════════════════
//
// H-bridge module (the small 2-input one labelled IN1, IN2, GND):
//
//   ESP32 dev-board pin (silkscreen) → H-bridge pin (printed label)
//   ──────────────────────────────────────────────────────────────────
//   D25  (= GPIO25)                  →  "IN1"
//   D26  (= GPIO26)                  →  "IN2"
//   GND                              →  "GND"
//
//   On the motor side of the H-bridge:
//     V_MOT (or VCC) ◄── 24V motor supply (from tether)
//     GND            ◄── motor supply ground
//     OUT1 (or M+)   ──► drum motor terminal 1
//     OUT2 (or M-)   ──► drum motor terminal 2
//   (motor-power wiring is hardware-only, no code involvement)
//
// I²C bus (to ESP32_2, the stepper board):
//
//   This ESP32_3 pin (silkscreen) ◄──► That ESP32_2 pin (silkscreen)
//   ──────────────────────────────────────────────────────────────────
//   D21  (= GPIO21)               ◄──► D21  (= GPIO21)    [SDA — data]
//   D22  (= GPIO22)               ◄──► D22  (= GPIO22)    [SCL — clock]
//   GND                           ──── GND                [shared ground]
//
// H-bridge truth table (2-input type — DRV8871 / MX1508 / L9110 / etc):
//   IN1=0,   IN2=0   → motor stop (coast)
//   IN1=PWM, IN2=0   → spin one direction at the PWM duty cycle
//   IN1=0,   IN2=PWM → spin the OTHER direction at the PWM duty cycle
//   IN1=1,   IN2=1   → brake
//
// We only need one direction for cleaning, so we PWM one input and hold the
// other LOW. If the drum spins the wrong way, flip DRUM_DIR_FORWARD below.
//
// ═══════════════════════════════════════════════════════════════════════════

#include <Wire.h>

// ─── H-bridge input GPIOs ──────────────────────────────────────────────────
static const int PIN_IN1 = 25;   // dev-board "D25"  → H-bridge "IN1"
static const int PIN_IN2 = 26;   // dev-board "D26"  → H-bridge "IN2"

// Direction selector: true = PWM on IN1 (one way), false = PWM on IN2 (other way).
// Flip this if the drum spins the wrong direction.
static const bool DRUM_DIR_FORWARD = true;

// ─── I²C bus GPIOs (to ESP32_2) ────────────────────────────────────────────
static const int PIN_I2C_SDA = 21;       // dev-board "D21" → ESP32_2 "D21" (SDA — data)
static const int PIN_I2C_SCL = 22;       // dev-board "D22" → ESP32_2 "D22" (SCL — clock)
static const uint8_t I2C_ADDR = 0x10;    // this board's I²C slave address

// LEDC PWM (ESP32 Arduino core 3.x API — attach to pin directly, no channel id)
static const uint32_t PWM_FREQ = 20000;
static const uint8_t  PWM_BITS = 8;
static const uint32_t PWM_FULL = 255;

// Resolved at compile time — which pin is the PWM driver and which is held LOW.
static const int PIN_PWM = DRUM_DIR_FORWARD ? PIN_IN1 : PIN_IN2;
static const int PIN_LOW = DRUM_DIR_FORWARD ? PIN_IN2 : PIN_IN1;

volatile bool drumOn = false;
bool lastApplied = false;

// Failsafe: if no I2C traffic from ESP32_2 in this window, kill the drum.
// ESP32_2 now sends a real drum-state byte every 200 ms, so 1000 ms covers
// four missed heartbeats — comfortable margin without nuisance trips.
static const uint32_t I2C_TIMEOUT_MS = 1000;
volatile uint32_t lastI2CMs = 0;

void onI2CReceive(int n) {
  lastI2CMs = millis();
  while (Wire.available()) {
    uint8_t b = (uint8_t)Wire.read();
    drumOn = (b != 0);
  }
}

void applyDrum(bool on) {
  if (on == lastApplied) return;
  ledcWrite(PIN_PWM, on ? PWM_FULL : 0);
  digitalWrite(PIN_LOW, LOW);
  lastApplied = on;
}

void setup() {
  pinMode(PIN_LOW, OUTPUT);
  digitalWrite(PIN_LOW, LOW);

  ledcAttach(PIN_PWM, PWM_FREQ, PWM_BITS);
  ledcWrite(PIN_PWM, 0);

  Wire.begin(I2C_ADDR, PIN_I2C_SDA, PIN_I2C_SCL, 100000);
  Wire.onReceive(onI2CReceive);
}

void loop() {
  // Watchdog: if ESP32_2 has gone silent, force the drum off regardless of the
  // last commanded state. Reading drumOn is safe — it's a single byte volatile.
  if (lastI2CMs != 0 && (millis() - lastI2CMs) > I2C_TIMEOUT_MS) {
    drumOn = false;
  }
  applyDrum(drumOn);
  delay(10);
}
